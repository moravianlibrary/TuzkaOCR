from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from .postprocess import maps_to_regions_structured, Region

DOWNSAMPLE         = 3
MAX_ORIGINAL_WIDTH = 1500
MAX_SIDE           = 1536


def _sigmoid_inplace(x: np.ndarray) -> None:
    np.negative(x, out=x)
    np.exp(x, out=x)
    x += 1.0
    np.reciprocal(x, out=x)


class LayoutDetector:
    def __init__(self, model_path: str | Path, device: str = "cpu",
                 threads: int = 4, postprocess_kwargs: dict | None = None):
        self.postprocess_kwargs = postprocess_kwargs or {}

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = max(1, threads // 2)

        if device == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=providers
        )
        self._input_name = self.session.get_inputs()[0].name
        self._needs_sigmoid = self._probe_sigmoid()
        print(f"[layout] model={model_path} sigmoid_in_code={self._needs_sigmoid}", flush=True)

    def _probe_sigmoid(self) -> bool:
        dummy = np.zeros((1, 3, 64, 64), dtype=np.float32)
        out = self.session.run(None, {self._input_name: dummy})[0]
        ch = out[0, 2:5]
        return bool(ch.min() < -0.001 or ch.max() > 1.001)

    def get_maps(self, img_bgr: np.ndarray) -> tuple[np.ndarray, float]:
        orig_h, orig_w = img_bgr.shape[:2]
        h, w = orig_h, orig_w

        if w > MAX_ORIGINAL_WIDTH:
            pre_scale = MAX_ORIGINAL_WIDTH / w
            img_bgr = cv2.resize(img_bgr,
                                 (MAX_ORIGINAL_WIDTH, max(1, int(h * pre_scale))),
                                 interpolation=cv2.INTER_AREA)
            h, w = img_bgr.shape[:2]

        ds     = DOWNSAMPLE
        img_ds = cv2.resize(img_bgr, (w // ds, h // ds), interpolation=cv2.INTER_AREA)
        hd, wd = img_ds.shape[:2]

        if max(hd, wd) > MAX_SIDE:
            scale  = MAX_SIDE / max(hd, wd)
            img_ds = cv2.resize(img_ds,
                                (max(1, int(wd * scale)), max(1, int(hd * scale))),
                                interpolation=cv2.INTER_AREA)
            hd, wd = img_ds.shape[:2]

        img_scale = orig_h / hd

        ph = (32 - hd % 32) % 32
        pw = (32 - wd % 32) % 32
        img_pad = (np.pad(img_ds, ((0, ph), (0, pw), (0, 0)), mode="edge")
                   if ph or pw else img_ds)

        tensor = (img_pad.astype(np.float32).transpose(2, 0, 1)[None]) / 255.0

        out = self.session.run(None, {self._input_name: tensor})[0]
        if self._needs_sigmoid:
            _sigmoid_inplace(out[:, 2:5])

        maps = out[0, :, :hd, :wd].transpose(1, 2, 0)
        return np.ascontiguousarray(maps, dtype=np.float32), img_scale

    def detect(self, img_bgr: np.ndarray, **postprocess_kwargs) -> tuple[list[Region], float]:
        orig_h, orig_w = img_bgr.shape[:2]
        if orig_w > orig_h * 1.2:
            return self._detect_split(img_bgr, **postprocess_kwargs)

        maps, img_scale = self.get_maps(img_bgr)
        kwargs = dict(self.postprocess_kwargs)
        kwargs.update(postprocess_kwargs)
        return maps_to_regions_structured(maps, **kwargs), img_scale

    def _detect_split(self, img_bgr: np.ndarray, **postprocess_kwargs) -> tuple[list[Region], float]:
        h, w = img_bgr.shape[:2]
        mid = w // 2

        kwargs = dict(self.postprocess_kwargs)
        kwargs.update(postprocess_kwargs)

        left_maps, _  = self.get_maps(img_bgr[:, :mid])
        L_wd = left_maps.shape[1]
        left_regions = maps_to_regions_structured(left_maps, **kwargs)

        right_maps, _ = self.get_maps(img_bgr[:, mid:])
        R_wd = right_maps.shape[1]
        right_regions = maps_to_regions_structured(right_maps, **kwargs)

        pre_scale = MAX_ORIGINAL_WIDTH / w if w > MAX_ORIGINAL_WIDTH else 1.0
        F_w = int(w * pre_scale) if w > MAX_ORIGINAL_WIDTH else w
        F_h = max(1, int(h * pre_scale))
        F_wd = F_w // DOWNSAMPLE
        F_hd = F_h // DOWNSAMPLE
        if max(F_hd, F_wd) > MAX_SIDE:
            s = MAX_SIDE / max(F_hd, F_wd)
            F_hd = max(1, int(F_hd * s))
            F_wd = max(1, int(F_wd * s))

        img_scale = h / F_hd

        sx_L = (F_wd / 2) / L_wd;  sy_L = F_hd / left_maps.shape[0]
        sx_R = (F_wd / 2) / R_wd;  sy_R = F_hd / right_maps.shape[0]
        x_off_R = F_wd / 2

        def _transform(region, sx, sy, x_off=0.0):
            region.polygon = [(x * sx + x_off, y * sy) for x, y in region.polygon]
            for line in region.lines:
                line.baseline = [(x * sx + x_off, y * sy) for x, y in line.baseline]
                line.polygon  = [(x * sx + x_off, y * sy) for x, y in line.polygon]
                line.heights  = (line.heights[0] * sy, line.heights[1] * sy)

        for r in left_regions:
            _transform(r, sx_L, sy_L)
        for r in right_regions:
            _transform(r, sx_R, sy_R, x_off_R)

        return left_regions + right_regions, img_scale
