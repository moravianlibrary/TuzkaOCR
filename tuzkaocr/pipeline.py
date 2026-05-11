from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .config import Config
from .layout.detector import LayoutDetector
from .ocr.recognizer import OnnxRecognizer
from .alto import build_alto


@dataclass
class _LineInput:
    gray: np.ndarray
    M: np.ndarray
    region_idx: int

_TARGET_H      = 40
_BACKBONE_STRIDE = 2


def _extract_crop(img_bgr: np.ndarray, baseline: list, asc: float, desc: float,
                  ds: float = 3.0) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
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
    half_w = line_w / 2.0

    src = np.array([
        [cx - half_w * dx + asc_px  * px, cy - half_w * dy + asc_px  * py],
        [cx + half_w * dx + asc_px  * px, cy + half_w * dy + asc_px  * py],
        [cx + half_w * dx - desc_px * px, cy + half_w * dy - desc_px * py],
        [cx - half_w * dx - desc_px * px, cy - half_w * dy - desc_px * py],
    ], dtype=np.float32)

    dst_h, dst_w = int(round(total_h)), line_w
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


def ensure_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


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


class PageProcessor:
    def __init__(self, config: Config):
        self.config = config
        device_str = config.resolve_device()

        self.detector = LayoutDetector(
            config.layout_model,
            device=device_str,
            threads=config.ocr_threads,
        )
        self.recognizer = OnnxRecognizer(
            config.ocr_model,
            vocab_path=config.vocab,
            device=device_str,
            threads=config.ocr_threads,
            max_width=config.max_width,
        )

    def _run(self, img_bgr: np.ndarray,
             height_scale: Optional[float] = None) -> Tuple[int, int, List[dict]]:
        img_h, img_w = img_bgr.shape[:2]
        cfg = self.config
        hs = cfg.height_scale if height_scale is None else height_scale

        if cfg.h_dilate > 0:
            regions, img_scale = self.detector.detect(img_bgr, h_dilate_px=cfg.h_dilate)
        else:
            regions, img_scale = self.detector.detect(img_bgr)

        line_data: List[_LineInput] = []
        for ri, region in enumerate(regions):
            _pitch_calibrate(region.lines)
            for line in region.lines:
                asc  = line.heights[0] * hs
                desc = line.heights[1] * hs
                gray, M = _extract_crop(img_bgr, line.baseline, asc, desc, ds=img_scale)
                if gray is None:
                    continue
                line_data.append(_LineInput(gray=gray, M=M, region_idx=ri))

        if not line_data:
            return img_h, img_w, []

        crops = [d.gray for d in line_data]
        results = self.recognizer.run_lines(crops, workers=cfg.line_workers)

        region_blocks: dict[int, list] = defaultdict(list)
        for d, (transcription, word_spans) in zip(line_data, results):
            if not transcription.strip():
                continue

            crop_w = d.gray.shape[1]
            lh, lv, lw, lht = _bbox_from_quad(0, 0, crop_w, _TARGET_H, d.M)

            words = [
                (word, *_word_bbox(t0, t1, crop_w, d.M))
                for word, t0, t1 in word_spans
            ]

            region_blocks[d.region_idx].append({
                "transcription": transcription,
                "hpos": lh, "vpos": lv, "width": lw, "height": lht,
                "words": words,
            })

        blocks = [{"lines": region_blocks[ri]} for ri in sorted(region_blocks)]
        return img_h, img_w, blocks

    def process(self, img_bgr: np.ndarray, page_id: str = "page",
                fmt: str = "alto", height_scale: Optional[float] = None) -> str:
        img_h, img_w, blocks = self._run(img_bgr, height_scale=height_scale)
        if fmt == "txt":
            return _blocks_to_text(blocks)
        software_name = Path(self.config.ocr_model).stem
        return build_alto(page_id, img_h, img_w, blocks, software_name=software_name)

    def process_file(self, image_path: str | Path, out_path: str | Path | None = None,
                     fmt: str = "alto") -> str:
        img_path = Path(image_path)
        img = cv2.imread(str(img_path))
        if img is None:
            raise ValueError(f"Cannot read image: {img_path}")
        img = ensure_bgr(img)

        result = self.process(img, page_id=img_path.stem, fmt=fmt)

        if out_path is not None:
            Path(out_path).write_text(result, encoding="utf-8")

        return result
