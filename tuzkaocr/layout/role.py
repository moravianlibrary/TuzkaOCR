from __future__ import annotations

import re
from pathlib import Path
from typing import List

import numpy as np


_NUMERIC_RX = re.compile(r"^\s*[\-—.,()\[\]]*\s*\d{1,4}\s*[\-—.,()\[\]]*\s*$")

_CONF_THRESH = 0.60
_MARGIN_THRESH = 0.25
_LARGE_REL = 1.55


def _text_features(t: str) -> list[float]:
    s = t.strip()
    n = max(1, len(s))
    na = sum(1 for c in s if c.isalpha())
    nu = sum(1 for c in s if c.isupper())
    nd = sum(1 for c in s if c.isdigit())
    return [
        float(len(s)),
        float(max(1, len(s.split()))),
        nu / max(1, na),
        nd / n,
        1.0 if na > 1 and nu == na else 0.0,
        1.0 if n > 0 and nd == n else 0.0,
        1.0 if s and s[0].isupper() else 0.0,
        1.0 if s.endswith((".", "!", "?", ":", ";")) else 0.0,
        1.0 if s.endswith(".") else 0.0,
    ]


def _features_for(lines: list[dict], idx: int, H: int, W: int,
                  doc_med: float, page_med_h_local: float) -> np.ndarray:
    ln = lines[idx]
    h = max(1, ln["height"])
    rel = h / doc_med

    prev = None
    for j in range(idx - 1, -1, -1):
        if lines[j]["vpos"] + lines[j]["height"] <= ln["vpos"]:
            prev = lines[j]
            break
    gap_above = (ln["vpos"] - (prev["vpos"] + prev["height"])) if prev else ln["vpos"]
    gap_rel = gap_above / h

    nxt = None
    for j in range(idx + 1, len(lines)):
        if lines[j]["vpos"] >= ln["vpos"] + ln["height"]:
            nxt = lines[j]
            break
    gap_below = (nxt["vpos"] - (ln["vpos"] + ln["height"])) if nxt else max(0, H - (ln["vpos"] + ln["height"]))
    gap_below_rel = gap_below / h

    cy = ln["vpos"] + ln["height"] / 2
    sim_close = 0
    for o in lines:
        if o is ln:
            continue
        if abs((o["vpos"] + o["height"] / 2) - cy) <= 3 * ln["height"] \
                and abs(o["height"] - ln["height"]) <= 0.20 * ln["height"]:
            sim_close += 1
    isolated = 1.0 if sim_close <= 1 else 0.0
    in_top = 1.0 if ln["vpos"] < 0.15 * H else 0.0
    in_bot = 1.0 if (ln["vpos"] + ln["height"]) > 0.83 * H else 0.0

    txt = ln.get("transcription", "") or ""
    words = max(1, len(txt.split()))
    tf = _text_features(txt)

    prev_any = lines[idx - 1] if idx > 0 else None
    next_any = lines[idx + 1] if idx + 1 < len(lines) else None
    prev_rel = (prev_any["height"] / doc_med) if prev_any else 0.0
    next_rel = (next_any["height"] / doc_med) if next_any else 0.0
    prev_txt = (prev_any.get("transcription", "") or "") if prev_any else ""
    next_txt = (next_any.get("transcription", "") or "") if next_any else ""
    prev_words = max(1, len(prev_txt.split())) if prev_txt else 0
    next_words = 0
    prev_starts_cap = 1.0 if (prev_txt.strip() and prev_txt.strip()[0].isupper()) else 0.0

    return np.array([
        rel, gap_rel, gap_below_rel, float(words), float(len(txt)),
        ln["vpos"] / H, ln["hpos"] / W, ln["width"] / W,
        in_top, in_bot,
        isolated, float(sim_close),
        *tf,
        prev_rel, next_rel, float(prev_words), float(next_words),
        prev_starts_cap, float(len(lines)), float(page_med_h_local),
    ], dtype=np.float32)


def _walk_tree(nodes: np.ndarray, X: np.ndarray) -> np.ndarray:
    n = X.shape[0]
    out = np.empty(n, dtype=np.float64)
    feature_idx = nodes["feature_idx"]
    threshold   = nodes["num_threshold"]
    miss_left   = nodes["missing_go_to_left"]
    left        = nodes["left"]
    right       = nodes["right"]
    is_leaf     = nodes["is_leaf"]
    value       = nodes["value"]
    for i in range(n):
        node = 0
        while not is_leaf[node]:
            fv = X[i, feature_idx[node]]
            if np.isnan(fv):
                node = left[node] if miss_left[node] else right[node]
            elif fv <= threshold[node]:
                node = left[node]
            else:
                node = right[node]
        out[i] = value[node]
    return out


def _softmax(x: np.ndarray) -> np.ndarray:
    m = x.max(axis=1, keepdims=True)
    e = np.exp(x - m)
    return e / e.sum(axis=1, keepdims=True)


class RoleClassifier:
    def __init__(self, npz_path: str | Path):
        d = np.load(str(npz_path))
        self.classes: List[str] = [str(c) for c in d["classes"]]
        self.feature_names: List[str] = [str(n) for n in d["feature_names"]]
        self.doc_med: float = float(d["doc_med"])
        self.n_iter: int = int(d["n_iter"])
        self.n_classes: int = int(d["n_classes"])
        self.init_pred: np.ndarray = d["init_pred"].astype(np.float64).reshape(self.n_classes)
        self.learning_rate: float = float(d["learning_rate"])
        self.trees: list[list[np.ndarray]] = [
            [d[f"nodes_{i}_{k}"] for k in range(self.n_classes)]
            for i in range(self.n_iter)
        ]
        self._idx = {c: i for i, c in enumerate(self.classes)}

    def _predict_proba(self, X: np.ndarray) -> np.ndarray:
        n = X.shape[0]
        raw = np.tile(self.init_pred, (n, 1))
        for it in range(self.n_iter):
            for k in range(self.n_classes):
                raw[:, k] += _walk_tree(self.trees[it][k], X)
        return _softmax(raw)

    def classify_blocks(self, blocks: list[dict], img_h: int, img_w: int) -> None:
        lines: list[dict] = []
        for b in blocks:
            for ln in b.get("lines", []):
                lines.append(ln)
        if not lines:
            return
        lines.sort(key=lambda l: l["vpos"])

        heights = np.array([max(1, l["height"]) for l in lines], dtype=np.float32)
        page_med_h_local = float(np.median(heights))

        X = np.stack([
            _features_for(lines, i, img_h, img_w, self.doc_med, page_med_h_local)
            for i in range(len(lines))
        ])
        probs = self._predict_proba(X)

        body_i = self._idx.get("body", 0)
        pagenum_i = self._idx.get("pagenum", 2)
        prominent_i = self._idx.get("prominent", 1)

        for i, ln in enumerate(lines):
            txt = (ln.get("transcription", "") or "").strip()
            rel = X[i, 0]
            in_top = X[i, 8] > 0.5
            in_bot = X[i, 9] > 0.5
            isolated = X[i, 10] > 0.5
            words = X[i, 3]
            starts_cap = X[i, 18] > 0.5

            if _NUMERIC_RX.match(txt) and words <= 2 and isolated and (in_top or in_bot):
                ln["role"] = self.classes[pagenum_i]
                continue
            if rel >= _LARGE_REL and isolated and starts_cap and words >= 1:
                ln["role"] = self.classes[prominent_i]
                continue

            p = probs[i]
            top = int(p.argmax())
            order = np.sort(p)[::-1]
            if top != body_i and order[0] >= _CONF_THRESH and (order[0] - order[1]) >= _MARGIN_THRESH:
                ln["role"] = self.classes[top]
            else:
                ln["role"] = self.classes[body_i]
