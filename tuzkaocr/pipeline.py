from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import _models
from .config import Config
from .images import decode_gray_image_path, decode_image_path, dpi_from_page_width, read_image_dpi
from .layout.detector import LayoutDetector
from .layout.large_text import stretch_crop
from .lang import LanguageDetector
from .layout.role import RoleClassifier
from .ocr.recognizer import create_recognizer
from .alto import HYPHEN_CHARS, build_alto
from .pagexml import build_page_xml
from .orientation import CLASS_ANGLES, OrientationClassifier


@dataclass
class _LineInput:
    gray: np.ndarray
    M: np.ndarray
    region_idx: int
    baseline: Optional[list] = None

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


def _blocks_to_text(blocks: List[dict]) -> str:
    parts = []
    for block in blocks:
        for line in block["lines"]:
            parts.append(line["transcription"])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _rotate_rect_back(box: tuple, page_w: int, page_h: int,
                      angle: int) -> tuple[int, int, int, int]:
    x, y, width, height = (int(value) for value in box)
    if angle == 90:
        return page_w - y - height, x, height, width
    if angle == 180:
        return page_w - x - width, page_h - y - height, width, height
    if angle == 270:
        return y, page_h - x - width, height, width
    return x, y, width, height


def _rotate_point_back(point: tuple, page_w: int, page_h: int,
                       angle: int) -> tuple[float, float]:
    x, y = (float(value) for value in point)
    if angle == 90:
        return page_w - 1 - y, x
    if angle == 180:
        return page_w - 1 - x, page_h - 1 - y
    if angle == 270:
        return y, page_h - 1 - x
    return x, y


def _map_blocks_back(blocks: list, page_w: int, page_h: int, angle: int) -> list:
    if angle == 0:
        return blocks
    for block in blocks:
        if block.get("polygon"):
            block["polygon"] = [
                _rotate_point_back(point, page_w, page_h, angle)
                for point in block["polygon"]
            ]
        block["rotation"] = (-angle) % 360
        for line in block["lines"]:
            line["style_hpos"] = line["hpos"]
            line["style_vpos"] = line["vpos"]
            line["style_width"] = line["width"]
            line["style_height"] = line["height"]
            line["hpos"], line["vpos"], line["width"], line["height"] = (
                _rotate_rect_back(
                    (line["hpos"], line["vpos"], line["width"], line["height"]),
                    page_w, page_h, angle,
                )
            )
            for key in ("polygon", "baseline"):
                if line.get(key):
                    line[key] = [
                        _rotate_point_back(point, page_w, page_h, angle)
                        for point in line[key]
                    ]
            for word in line["words"]:
                word["hpos"], word["vpos"], word["width"], word["height"] = (
                    _rotate_rect_back(
                        (word["hpos"], word["vpos"], word["width"], word["height"]),
                        page_w, page_h, angle,
                    )
                )
                for key in ("stem_box", "hyp_box"):
                    if word.get(key):
                        word[key] = _rotate_rect_back(word[key], page_w, page_h, angle)
            if line.get("spaces"):
                mapped_spaces = []
                for space in line["spaces"]:
                    x, y, width, height = _rotate_rect_back(
                        (space["hpos"], space["vpos"], space["width"], space["height"]),
                        page_w, page_h, angle,
                    )
                    mapped_spaces.append({"hpos": x, "vpos": y, "width": width})
                line["spaces"] = mapped_spaces
    return blocks


def _add_space_boxes(blocks: list) -> None:
    for block in blocks:
        for line in block["lines"]:
            words = line["words"]
            if len(words) < 2:
                continue
            spaces = []
            for left, right in zip(words, words[1:]):
                x = left["hpos"] + left["width"]
                right_edge = max(x, right["hpos"])
                spaces.append({
                    "hpos": x,
                    "vpos": line["vpos"],
                    "width": right_edge - x,
                    "height": line["height"],
                })
            line["spaces"] = spaces


def _probe_score(chosen: dict) -> tuple[float, int]:
    weighted = 0.0
    char_count = 0
    for result in chosen["results"]:
        for word in result.words:
            count = len(word.text)
            if not count:
                continue
            confidence = (float(np.mean(word.char_conf)) if word.char_conf
                          else float(result.confidence))
            weighted += confidence * count
            char_count += count
    return (weighted / char_count if char_count else 0.0), char_count


def _choose_probe_angle(scores: dict[int, tuple[float, int]]) -> int:
    candidates = sorted(scores)
    best_angle = max(
        candidates,
        key=lambda candidate: scores[candidate][0] if scores[candidate][1] >= 30 else 0.0,
    )
    upright_score = scores[0][0] if scores[0][1] >= 30 else 0.0
    best_score = scores[best_angle][0] if scores[best_angle][1] >= 30 else 0.0
    if best_angle != 0 and best_score - upright_score < 0.05 - 1e-12:
        return 0
    return best_angle


def _probe_candidates(run_angle, candidate_angles: tuple[int, ...] | list[int],
                      candidates: Optional[dict[int, tuple]] = None):
    runs = {} if candidates is None else dict(candidates)
    for candidate in candidate_angles:
        if candidate not in runs:
            runs[candidate] = run_angle(candidate)
    scores = {candidate: _probe_score(runs[candidate][1]) for candidate in runs}
    return runs, scores


def _contrast_stats(gray: np.ndarray, downsample: bool = False) -> tuple[float, float]:
    sample = gray
    if downsample and sample.size > 65536:
        step = int(np.ceil(np.sqrt(sample.size / 65536)))
        sample = sample[::step, ::step]
    low, median = np.percentile(sample, (0.5, 50.0))
    return float(low), float(median)


def _contrast_stretch(gray: np.ndarray, low: float, median: float) -> np.ndarray:
    if median - low <= 8.0:
        return gray
    return np.clip((gray.astype(np.float32) - low) * (255.0 / (median - low)),
                   0, 255).astype(np.uint8)


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
            reading_order=getattr(config, "reading_order", "basic"),
            large_text=getattr(config, "large_text", False),
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
        self._orientation: Optional[OrientationClassifier] = None
        self._orientation_lock = threading.Lock()

    def _layout_pass(self, img_bgr: np.ndarray) -> dict:
        if self.config.adaptive_downsample and self.config.layout_line_height > 0:
            regions, img_scale = self.detector.detect(
                img_bgr, None, line_height=self.config.layout_line_height)
        else:
            regions, img_scale = self.detector.detect(img_bgr, None)
        return {"regions": regions, "img_scale": img_scale}

    def _recognize_pass(self, img_bgr: np.ndarray, hs: float, lp: dict) -> dict:
        img_scale = lp["img_scale"]
        contrast_mode = lp.get("contrast_mode", self.config.contrast)
        line_data: List[_LineInput] = []
        for ri, region in enumerate(lp["regions"]):
            _pitch_calibrate(region.lines)
            for line in region.lines:
                gray, M = _extract_crop(img_bgr, line.baseline,
                                        line.heights[0] * hs, line.heights[1] * hs, ds=img_scale,
                                        endpoint_ext=self.config.crop_endpoint_ext)
                if gray is None:
                    continue
                if line.large:
                    gray, M = stretch_crop(gray, M)
                if contrast_mode == "line":
                    low, median = _contrast_stats(gray)
                    gray = _contrast_stretch(gray, low, median)
                line_data.append(_LineInput(
                    gray=gray, M=M, region_idx=ri,
                    baseline=[(x * img_scale, y * img_scale) for x, y in line.baseline]))
        results = (self.recognizer.run_lines([d.gray for d in line_data],
                                             workers=self.config.line_workers)
                   if line_data else [])
        confs = [c for (t, _, c) in results if t.strip()]
        mean_conf = float(np.mean(confs)) if confs else 0.0
        return {"line_data": line_data, "results": results, "mean_conf": mean_conf,
                "regions": lp["regions"], "img_scale": img_scale}

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
            quad = cv2.perspectiveTransform(
                np.array([[0, 0], [crop_w, 0], [crop_w, _TARGET_H], [0, _TARGET_H]],
                         dtype=np.float64).reshape(-1, 1, 2), d.M).reshape(-1, 2)

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
                "polygon": [(float(x), float(y)) for x, y in quad],
                "baseline": d.baseline,
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
             role_classifier: Optional[bool] = None,
             orientation: Optional[str] = None,
             orientation_threshold: Optional[float] = None,
             orientation_probe: Optional[str] = None,
             contrast: Optional[str] = None,
             orientation_image: Optional[np.ndarray] = None):
        img_h, img_w = img_bgr.shape[:2]
        cfg = self.config
        hs = cfg.height_scale if height_scale is None else height_scale

        mode = cfg.orientation if orientation is None else orientation
        threshold = (cfg.orientation_threshold if orientation_threshold is None
                     else float(orientation_threshold))
        probe_mode = cfg.orientation_probe if orientation_probe is None else orientation_probe
        contrast_mode = cfg.contrast if contrast is None else contrast
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("orientation threshold must be in [0, 1]")
        if probe_mode not in ("on", "off"):
            raise ValueError("orientation probe must be 'on' or 'off'")
        if contrast_mode not in ("off", "on", "auto", "line"):
            raise ValueError("contrast must be 'off', 'on', 'auto' or 'line'")

        page_contrast_stats = None
        use_page_contrast = contrast_mode in ("on", "auto")
        if use_page_contrast:
            page_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            page_contrast_stats = _contrast_stats(page_gray, downsample=True)
            if contrast_mode == "auto" and page_contrast_stats[0] <= cfg.contrast_ink:
                use_page_contrast = False

        def run_angle(angle: int):
            upright = (np.rot90(img_bgr, k=angle // 90).copy() if angle else img_bgr)
            if use_page_contrast:
                gray = cv2.cvtColor(upright, cv2.COLOR_BGR2GRAY)
                gray = _contrast_stretch(gray, *page_contrast_stats)
                upright = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            lp = self._layout_pass(upright)
            lp["contrast_mode"] = contrast_mode
            chosen = self._recognize_pass(upright, hs, lp)
            blocks = self._assemble_blocks(
                chosen["line_data"], chosen["results"], chosen.get("regions"),
                chosen.get("img_scale") or 1.0,
            )
            return upright, chosen, blocks

        candidates: dict[int, tuple] = {}
        fully_probed = False
        if mode == "off":
            angle = 0
            upright, chosen, blocks = run_angle(angle)
            orientation_meta = {
                "orientation_angle": 0,
                "orientation_confidence": None,
                "orientation_classifier_confidence": None,
                "orientation_method": "off",
            }
        elif mode == "auto":
            with self._orientation_lock:
                if self._orientation is None:
                    self._orientation = OrientationClassifier(cfg.orientation_model)
                orientation_model = self._orientation
            predicted_angle, classifier_confidence, _ = orientation_model.predict(
                orientation_image if orientation_image is not None else img_bgr
            )
            if probe_mode == "on" and (classifier_confidence < threshold or predicted_angle != 0):
                if classifier_confidence < threshold:
                    candidate_angles = list(CLASS_ANGLES)
                else:
                    candidate_angles = [0, predicted_angle]
                candidates, scores = _probe_candidates(run_angle, candidate_angles)
                fully_probed = len(candidate_angles) == len(CLASS_ANGLES)
                best_angle = _choose_probe_angle(scores)
                angle = best_angle
                upright, chosen, blocks = candidates[angle]
                orientation_meta = {
                    "orientation_angle": angle,
                    "orientation_confidence": scores[angle][0],
                    "orientation_classifier_confidence": classifier_confidence,
                    "orientation_method": "probe",
                }
            else:
                angle = predicted_angle
                upright, chosen, blocks = run_angle(angle)
                candidates = {angle: (upright, chosen, blocks)}
                orientation_meta = {
                    "orientation_angle": angle,
                    "orientation_confidence": classifier_confidence,
                    "orientation_classifier_confidence": classifier_confidence,
                    "orientation_method": "classifier",
                }
        else:
            raise ValueError("orientation must be 'off' or 'auto'")

        recheck_performed = False
        if (mode == "auto" and cfg.orientation_recheck == "on"
                and not fully_probed):
            initial_char_conf, initial_chars = _probe_score(chosen)
            if (initial_char_conf < cfg.orientation_recheck_conf
                    and initial_chars >= cfg.orientation_recheck_chars):
                candidates, scores = _probe_candidates(run_angle, CLASS_ANGLES, candidates)
                angle = _choose_probe_angle(scores)
                upright, chosen, blocks = candidates[angle]
                orientation_meta = {
                    "orientation_angle": angle,
                    "orientation_confidence": scores[angle][0],
                    "orientation_classifier_confidence": classifier_confidence,
                    "orientation_method": "recheck",
                }
                recheck_performed = True
        orientation_meta["orientation_recheck"] = recheck_performed

        use_role = cfg.role_classifier if role_classifier is None else role_classifier
        if use_role:
            if self._role is None:
                self._role = RoleClassifier(str(_models.resolve(cfg.role_model)),
                                            device=self._device, threads=cfg.ocr_threads,
                                            cpu_mem_arena=cfg.cpu_mem_arena)
            self._role.classify_blocks(blocks, upright)

        if angle:
            _add_space_boxes(blocks)
            blocks = _map_blocks_back(blocks, img_w, img_h, angle)

        return (img_h, img_w, blocks, float(chosen["mean_conf"]),
                chosen.get("img_scale"), orientation_meta)

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
                physical_img_nr: Optional[int] = None,
                orientation: Optional[str] = None,
                orientation_threshold: Optional[float] = None,
                orientation_probe: Optional[str] = None,
                contrast: Optional[str] = None,
                _orientation_image: Optional[np.ndarray] = None):
        img_h, img_w, blocks, mean_conf, img_scale, orientation_meta = self._run(
            img_bgr, height_scale=height_scale, role_classifier=role_classifier,
            orientation=orientation,
            orientation_threshold=orientation_threshold,
            orientation_probe=orientation_probe,
            contrast=contrast,
            orientation_image=_orientation_image,
        )
        cfg = self.config
        text = _blocks_to_text(blocks)
        profile = profile or cfg.alto_profile
        language = None
        if fmt == "page" or (fmt != "txt" and profile == "ndk"):
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
        page_kwargs = dict(
            software_name=alto_kwargs["software_name"],
            layout_name=alto_kwargs["layout_name"],
            source_file=alto_kwargs["source_file"],
            language=language,
        )
        if fmt == "multi":
            content = {
                "alto": build_alto(page_id, img_h, img_w, blocks, **alto_kwargs),
                "txt":  text,
            }
        elif fmt == "txt":
            content = text
        elif fmt == "page":
            content = build_page_xml(page_id, img_h, img_w, blocks, **page_kwargs)
        else:
            content = build_alto(page_id, img_h, img_w, blocks, **alto_kwargs)
        if with_meta:
            n_lines = sum(len(b["lines"]) for b in blocks)
            return content, {
                "mean_conf": round(mean_conf, 4),
                "n_lines": n_lines,
                **orientation_meta,
            }
        return content

    def process_file(self, image_path: str | Path, out_path: str | Path | None = None,
                     fmt: str = "alto", source_identifier: str | None = None,
                     physical_img_nr: int | None = None,
                     with_meta: bool = False,
                     orientation: Optional[str] = None,
                     orientation_threshold: Optional[float] = None,
                     orientation_probe: Optional[str] = None,
                     contrast: Optional[str] = None):
        img_path = Path(image_path)
        img = decode_image_path(img_path)
        orientation_mode = orientation if orientation is not None else self.config.orientation
        orientation_image = (decode_gray_image_path(img_path)
                             if orientation_mode == "auto" else None)

        result = self.process(img, page_id=img_path.stem, fmt=fmt,
                              with_meta=with_meta,
                              source_file=img_path.name,
                              source_identifier=source_identifier,
                              dpi=read_image_dpi(img_path),
                              physical_img_nr=physical_img_nr,
                              orientation=orientation,
                              orientation_threshold=orientation_threshold,
                              orientation_probe=orientation_probe,
                              contrast=contrast,
                              _orientation_image=orientation_image)

        metadata = None
        if with_meta:
            result, metadata = result

        if out_path is not None:
            if isinstance(result, dict):
                stem = _strip_multi_suffix(Path(out_path))
                _MULTI_SUFFIX = {"alto": ".alto.xml", "txt": ".txt"}
                for key, content in result.items():
                    Path(f"{stem}{_MULTI_SUFFIX[key]}").write_text(content, encoding="utf-8")
            else:
                Path(out_path).write_text(result, encoding="utf-8")

        return (result, metadata) if with_meta else result


def _strip_multi_suffix(p: Path) -> str:
    name = p.name
    for suf in (".alto.xml", ".xml", ".txt"):
        if name.endswith(suf):
            return str(p.parent / name[:-len(suf)])
    return str(p)
