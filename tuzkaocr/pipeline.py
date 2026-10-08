from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import _models
from .config import Config
from .images import decode_image_path, dpi_from_page_width, read_image_dpi
from .layout.detector import LayoutDetector
from .layout import adaptive
from .lang import LanguageDetector
from .layout.role import RoleClassifier
from .ocr.recognizer import create_recognizer
from .alto import HYPHEN_CHARS, build_alto


@dataclass
class _LineInput:
    gray: np.ndarray
    M: np.ndarray
    region_idx: int

_TARGET_H      = 40
_BACKBONE_STRIDE = 2


def _extract_crop(img_bgr: np.ndarray, baseline: list, asc: float, desc: float,
                  ds: float = 3.0, endpoint_ext: float = 0.0) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    if baseline is None or len(baseline) < 1:
        return None, None

    pts = np.array([(x * ds, y * ds) for x, y in baseline], dtype=np.float64)
    asc_px  = max(3.0, asc)  * ds
    desc_px = max(2.0, desc) * ds
    total_h = asc_px + desc_px

    if len(pts) >= 2:
        lp = cv2.fitLine(pts.reshape(-1, 1, 2).astype(np.float32),
                         cv2.DIST_L2, 0, 0.01, 0.01).flatten()
        vx, vy, cx, cy = float(lp[0]), float(lp[1]), float(lp[2]), float(lp[3])
    else:
        vx, vy = 1.0, 0.0
        cx, cy = float(pts[0][0]), float(pts[0][1])
    if vx < 0:
        vx, vy = -vx, -vy

    x0, y0 = pts[0]; x1, y1 = pts[-1]
    line_w = max(1, int(np.hypot(x1 - x0, y1 - y0)))
    norm   = max(1e-9, np.hypot(vx, vy))
    dx, dy = vx / norm, vy / norm
    px, py = dy, -dx
    half_w = line_w / 2.0 + endpoint_ext * total_h

    src = np.array([
        [cx - half_w * dx + asc_px  * px, cy - half_w * dy + asc_px  * py],
        [cx + half_w * dx + asc_px  * px, cy + half_w * dy + asc_px  * py],
        [cx + half_w * dx - desc_px * px, cy + half_w * dy - desc_px * py],
        [cx - half_w * dx - desc_px * px, cy - half_w * dy - desc_px * py],
    ], dtype=np.float32)

    dst_h, dst_w = int(round(total_h)), int(round(line_w + 2 * endpoint_ext * total_h))
    dst = np.array([[0, 0], [dst_w, 0], [dst_w, dst_h], [0, dst_h]], dtype=np.float32)

    M = cv2.getPerspectiveTransform(dst, src)

    M_fwd = cv2.getPerspectiveTransform(src, dst)
    crop  = cv2.warpPerspective(img_bgr, M_fwd, (dst_w, dst_h),
                                flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_REPLICATE)
    if crop.shape[0] < 2 or crop.shape[1] < 2:
        return None, None

    scale  = _TARGET_H / crop.shape[0]
    new_w  = max(1, int(crop.shape[1] * scale))
    crop   = cv2.resize(crop, (new_w, _TARGET_H), interpolation=cv2.INTER_AREA)
    gray   = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    S = np.array([[1 / scale, 0, 0], [0, 1 / scale, 0], [0, 0, 1]], dtype=np.float64)
    M_scaled = M @ S

    return gray, M_scaled


def _bbox_from_quad(x1: float, y1: float, x2: float, y2: float,
                    M: np.ndarray) -> Tuple[int, int, int, int]:
    corners = np.array(
        [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        dtype=np.float64,
    ).reshape(-1, 1, 2)
    orig = cv2.perspectiveTransform(corners, M).reshape(-1, 2)
    x_min = int(np.floor(orig[:, 0].min()))
    y_min = int(np.floor(orig[:, 1].min()))
    x_max = int(np.ceil(orig[:, 0].max()))
    y_max = int(np.ceil(orig[:, 1].max()))
    return x_min, y_min, x_max - x_min, y_max - y_min


def _word_bbox(t_start: int, t_end: int, crop_w: int,
               M_scaled: np.ndarray) -> Tuple[int, int, int, int]:
    x1 = t_start * _BACKBONE_STRIDE
    x2 = min((t_end + 1) * _BACKBONE_STRIDE, crop_w)
    return _bbox_from_quad(x1, 0, x2, _TARGET_H, M_scaled)


def _hyphen_split_bboxes(span, crop_w: int, M_scaled: np.ndarray):
    x0 = span.t_start * _BACKBONE_STRIDE
    x2 = min((span.t_end + 1) * _BACKBONE_STRIDE, crop_w)
    xh = min(span.char_ts[-1] * _BACKBONE_STRIDE, crop_w)
    xh = min(max(xh, x0 + 1), max(x0 + 1, x2 - 1))
    stem = _bbox_from_quad(x0, 0, xh, _TARGET_H, M_scaled)
    hyp = _bbox_from_quad(xh, 0, max(xh + 1, x2), _TARGET_H, M_scaled)
    return stem, hyp


def _pitch_calibrate(lines) -> None:
    if len(lines) < 3:
        return
    ys = sorted(float(np.mean([pt[1] for pt in ln.baseline])) for ln in lines
                if ln.baseline)
    if len(ys) < 2:
        return
    pitches = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    median_pitch = float(np.median(pitches))
    for ln in lines:
        asc = ln.heights[0]
        if asc > 0 and asc < 0.70 * median_pitch:
            scale = 0.70 * median_pitch / asc
            ln.heights = (asc * scale, ln.heights[1] * scale)


def _layout_starved(lp: dict) -> bool:
    return (lp["lineh"] < adaptive.MIN_LINE_HEIGHT_PX
            or lp["pitch"] < adaptive.PITCH_RATIO_THRESH
            or lp["wide"] > adaptive.WIDE_FRAC_THRESH)


def _choose_recognized(recognized: List[dict], base_lp: dict) -> dict:
    if len(recognized) == 1:
        return recognized[0]
    base = recognized[0]
    base_starved = (base["pitch"] < adaptive.PITCH_RATIO_THRESH
                    or base["mean_conf"] < adaptive.UNREADABLE_CONF
                    or base["lineh"] < adaptive.MIN_LINE_HEIGHT_PX)
    cand = max(recognized, key=lambda v: v["mean_conf"])
    accept = (cand["ds"] != base["ds"]
              and cand["mean_conf"] > base["mean_conf"] + adaptive.SELECT_MARGIN
              and (base_starved
                   or cand["n_lines"] <= adaptive.LINE_INFLATE_FACTOR * max(1, base_lp["n_lines"])))
    return cand if accept else base


def _blocks_to_text(blocks: List[dict]) -> str:
    parts = []
    for block in blocks:
        for line in block["lines"]:
            parts.append(line["transcription"])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


class PageProcessor:
    def __init__(self, config: Config):
        self.config = config
        device_str = config.resolve_device()
        self._device = device_str

        layout_path = _models.resolve(config.layout_model)
        ocr_path    = _models.resolve(config.ocr_model)
        vocab_path  = _models.resolve(config.vocab)

        self.detector = LayoutDetector(
            str(layout_path),
            device=device_str,
            threads=config.ocr_threads,
            cpu_mem_arena=config.cpu_mem_arena,
            column_split=getattr(config, "column_split", False),
        )
        self.recognizer = create_recognizer(
            str(ocr_path),
            vocab_path=str(vocab_path),
            device=device_str,
            threads=config.ocr_threads,
            max_width=config.max_width,
            cpu_mem_arena=config.cpu_mem_arena,
        )
        self._ocr_model_path = ocr_path
        self._layout_model_path = layout_path
        self._role: Optional[RoleClassifier] = None
        self._lang: Optional[LanguageDetector] = None

    def _layout_pass(self, img_bgr: np.ndarray, downsample: Optional[int]) -> dict:
        regions, img_scale = self.detector.detect(img_bgr, downsample)
        return {"regions": regions, "img_scale": img_scale,
                "n_lines": sum(len(r.lines) for r in regions),
                "pitch": adaptive.min_pitch_ratio(regions, img_scale),
                "wide": adaptive.wide_line_frac(regions, img_scale, img_bgr.shape[1]),
                "lineh": adaptive.median_line_height(regions)}

    def _recognize_pass(self, img_bgr: np.ndarray, hs: float, lp: dict) -> dict:
        img_scale = lp["img_scale"]
        line_data: List[_LineInput] = []
        for ri, region in enumerate(lp["regions"]):
            _pitch_calibrate(region.lines)
            for line in region.lines:
                gray, M = _extract_crop(img_bgr, line.baseline,
                                        line.heights[0] * hs, line.heights[1] * hs, ds=img_scale,
                                        endpoint_ext=self.config.crop_endpoint_ext)
                if gray is None:
                    continue
                line_data.append(_LineInput(gray=gray, M=M, region_idx=ri))
        results = (self.recognizer.run_lines([d.gray for d in line_data],
                                             workers=self.config.line_workers)
                   if line_data else [])
        confs = [c for (t, _, c) in results if t.strip()]
        mean_conf = float(np.mean(confs)) if confs else 0.0
        return {"line_data": line_data, "results": results, "mean_conf": mean_conf,
                "regions": lp["regions"], "img_scale": img_scale,
                "pitch": lp["pitch"], "n_lines": lp["n_lines"],
                "wide": lp["wide"], "lineh": lp["lineh"]}

    @staticmethod
    def _assemble_blocks(line_data: List[_LineInput], results: list,
                         regions: Optional[list] = None,
                         img_scale: float = 1.0) -> List[dict]:
        region_blocks: dict[int, list] = defaultdict(list)
        for d, (transcription, word_spans, conf) in zip(line_data, results):
            if not transcription.strip():
                continue

            crop_w = d.gray.shape[1]
            lh, lv, lw, lht = _bbox_from_quad(0, 0, crop_w, _TARGET_H, d.M)

            words = []
            for span in word_spans:
                wh, wv, ww, wht = _word_bbox(span.t_start, span.t_end, crop_w, d.M)
                word = {"text": span.text, "hpos": wh, "vpos": wv,
                        "width": ww, "height": wht}
                if span.char_conf and len(span.char_conf) == len(span.text):
                    word["conf"] = float(np.mean(span.char_conf))
                    word["char_conf"] = list(span.char_conf)
                if (len(span.text) > 1 and span.text[-1] in HYPHEN_CHARS
                        and len(span.char_ts) == len(span.text)):
                    word["stem_box"], word["hyp_box"] = _hyphen_split_bboxes(
                        span, crop_w, d.M)
                words.append(word)

            region_blocks[d.region_idx].append({
                "transcription": transcription,
                "hpos": lh, "vpos": lv, "width": lw, "height": lht,
                "conf": float(conf),
                "words": words,
            })

        blocks = []
        for ri in sorted(region_blocks):
            block = {"lines": region_blocks[ri]}
            polygon = getattr(regions[ri], "polygon", None) if regions and ri < len(regions) else None
            if polygon:
                block["polygon"] = [(int(round(x * img_scale)), int(round(y * img_scale)))
                                    for x, y in polygon]
            blocks.append(block)
        return blocks

    def _run(self, img_bgr: np.ndarray,
             height_scale: Optional[float] = None,
             role_classifier: Optional[bool] = None):
        img_h, img_w = img_bgr.shape[:2]
        cfg = self.config
        hs = cfg.height_scale if height_scale is None else height_scale

        if not cfg.adaptive_downsample:
            lp = self._layout_pass(img_bgr, None)
            chosen = self._recognize_pass(img_bgr, hs, lp)
        else:
            levels = adaptive.DS_LEVELS
            base_lp = None
            recognized = []
            for k, ds in enumerate(levels):
                lp = self._layout_pass(img_bgr, ds)
                if base_lp is None:
                    base_lp = lp
                is_last = k == len(levels) - 1
                if _layout_starved(lp) and not is_last:
                    continue
                r = self._recognize_pass(img_bgr, hs, lp)
                r["ds"] = ds
                recognized.append(r)
                if is_last or r["mean_conf"] >= adaptive.OCR_CONF_THRESH:
                    break
            chosen = _choose_recognized(recognized, base_lp)

        blocks = self._assemble_blocks(chosen["line_data"], chosen["results"],
                                       chosen.get("regions"), chosen.get("img_scale") or 1.0)

        use_role = cfg.role_classifier if role_classifier is None else role_classifier
        if use_role:
            if self._role is None:
                self._role = RoleClassifier(str(_models.resolve(cfg.role_model)),
                                            device=self._device, threads=cfg.ocr_threads,
                                            cpu_mem_arena=cfg.cpu_mem_arena)
            self._role.classify_blocks(blocks, img_bgr)

        return (img_h, img_w, blocks, float(chosen["mean_conf"]),
                chosen.get("img_scale"))

    def _detect_language(self, text: str) -> Optional[str]:
        if self._lang is None:
            self._lang = LanguageDetector(_models.resolve(self.config.lang_model))
        return self._lang.detect(text)

    def process(self, img_bgr: np.ndarray, page_id: str = "page",
                fmt: str = "alto", height_scale: Optional[float] = None,
                role_classifier: Optional[bool] = None, with_meta: bool = False,
                source_file: Optional[str] = None,
                source_identifier: Optional[str] = None,
                profile: Optional[str] = None,
                dpi: Optional[int] = None,
                physical_img_nr: Optional[int] = None):
        img_h, img_w, blocks, mean_conf, img_scale = self._run(
            img_bgr, height_scale=height_scale, role_classifier=role_classifier)
        cfg = self.config
        text = _blocks_to_text(blocks)
        profile = profile or cfg.alto_profile
        language = None
        if fmt != "txt" and profile == "ndk":
            language = (cfg.alto_lang or "").strip() or self._detect_language(text)
        alto_kwargs = dict(
            software_name=_models.display_name(self._ocr_model_path),
            layout_name=_models.display_name(self._layout_model_path),
            profile=profile,
            source_file=source_file if source_file is not None else page_id,
            source_identifier=source_identifier,
            page_confidence=mean_conf,
            physical_img_nr=physical_img_nr,
            layout_downsample=img_scale,
            language=language,
            dpi=((cfg.alto_dpi or None) or dpi
                 or dpi_from_page_width(img_w, cfg.alto_page_width_mm)),
            agency=(cfg.alto_agency or "").strip() or None,
            font_family=(cfg.alto_fontfamily or "").strip() or None,
        )
        if fmt == "multi":
            content = {
                "alto": build_alto(page_id, img_h, img_w, blocks, **alto_kwargs),
                "txt":  text,
            }
        elif fmt == "txt":
            content = text
        else:
            content = build_alto(page_id, img_h, img_w, blocks, **alto_kwargs)
        if with_meta:
            n_lines = sum(len(b["lines"]) for b in blocks)
            return content, {"mean_conf": round(mean_conf, 4), "n_lines": n_lines}
        return content

    def process_file(self, image_path: str | Path, out_path: str | Path | None = None,
                     fmt: str = "alto", source_identifier: str | None = None,
                     physical_img_nr: int | None = None):
        img_path = Path(image_path)
        img = decode_image_path(img_path)

        result = self.process(img, page_id=img_path.stem, fmt=fmt,
                              source_file=img_path.name,
                              source_identifier=source_identifier,
                              dpi=read_image_dpi(img_path),
                              physical_img_nr=physical_img_nr)

        if out_path is not None:
            if isinstance(result, dict):
                stem = _strip_multi_suffix(Path(out_path))
                _MULTI_SUFFIX = {"alto": ".alto.xml", "txt": ".txt"}
                for key, content in result.items():
                    Path(f"{stem}{_MULTI_SUFFIX[key]}").write_text(content, encoding="utf-8")
            else:
                Path(out_path).write_text(result, encoding="utf-8")

        return result


def _strip_multi_suffix(p: Path) -> str:
    name = p.name
    for suf in (".alto.xml", ".xml", ".txt"):
        if name.endswith(suf):
            return str(p.parent / name[:-len(suf)])
    return str(p)
