from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

CLASSES = ["body", "heading", "header", "footer", "page_number"]
TAU = {"heading": 0.6, "header": 0.6, "footer": 0.6, "page_number": 0.5}
_CROP_H, _CROP_W = 32, 256
_NUM_RX = re.compile(r"^[\dIVXLCDM.\-–—\s]+$", re.I)


def _text_features(t: str) -> list[float]:
    t = (t or "").strip()
    n = len(t)
    w = len(t.split())
    al = [c for c in t if c.isalpha()]
    dig = sum(c.isdigit() for c in t)
    up = sum(c.isupper() for c in al)
    return [min(n, 80) / 80.0, min(w, 20) / 20.0, dig / max(1, n), up / max(1, len(al)),
            1.0 if (t and _NUM_RX.match(t)) else 0.0, 1.0 if t[-1:] in ".:!?" else 0.0]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class RoleClassifier:

    def __init__(self, onnx_path: str | Path, device: str = "cpu", threads: int = 4):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=providers)
        self.classes = CLASSES
        self._body = CLASSES.index("body")

    def classify_blocks(self, blocks: list[dict], page_bgr: np.ndarray) -> None:
        gray = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY) if page_bgr.ndim == 3 else page_bgr
        H, W = gray.shape[:2]
        all_lines = [ln for b in blocks for ln in b.get("lines", [])]
        if not all_lines:
            return
        medh = float(np.median([max(1, ln["height"]) for ln in all_lines]))

        crops, feats, refs = [], [], []
        for b in blocks:
            L = b.get("lines", [])
            nl = len(L)
            for li, ln in enumerate(L):
                x, y, w, h = int(ln["hpos"]), int(ln["vpos"]), int(ln["width"]), int(ln["height"])
                cr = gray[max(0, y):y + h, max(0, x):x + w]
                if cr.size == 0:
                    ln["role"] = "body"
                    continue
                pv = L[li - 1] if li > 0 else None
                nx = L[li + 1] if li < nl - 1 else None
                ph = pv["height"] if pv else h
                nh = nx["height"] if nx else h
                pw = pv["width"] if pv else w
                ga = (y - (pv["vpos"] + pv["height"])) / medh if pv else 2.0
                gb = (nx["vpos"] - (y + h)) / medh if nx else 2.0
                ctx = [_clamp(h / max(1, ph), 0, 4) / 4.0, _clamp(h / max(1, nh), 0, 4) / 4.0,
                       _clamp(ga, 0, 5) / 5.0, _clamp(gb, 0, 5) / 5.0, _clamp(w / max(1, pw), 0, 3) / 3.0,
                       1.0 if li == 0 else 0.0, 1.0 if li == nl - 1 else 0.0]
                cx, cy = x + w / 2, y + h / 2
                geom = [cy / H, cx / W, w / W, h / medh / 4.0,
                        1.0 if cy < 0.12 * H else 0.0, 1.0 if cy > 0.88 * H else 0.0,
                        li / max(1, nl), 1.0 if nl == 1 else 0.0]
                crops.append(cv2.resize(cr, (_CROP_W, _CROP_H), interpolation=cv2.INTER_AREA))
                feats.append(_text_features(ln.get("transcription", "")) + geom + ctx)
                refs.append(ln)
        if not refs:
            return

        C = ((np.asarray(crops, np.float32) / 255.0 - 0.5) / 0.5)[:, None]
        F = np.asarray(feats, np.float32)
        logits = self.session.run(None, {"crop": C, "feats": F})[0]
        e = np.exp(logits - logits.max(1, keepdims=True))
        probs = e / e.sum(1, keepdims=True)
        pred = probs.argmax(1)
        for i, ln in enumerate(refs):
            role = CLASSES[pred[i]]
            if role != "body" and probs[i, pred[i]] < TAU[role]:
                role = "body"
            ln["role"] = role
