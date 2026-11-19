from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from .ocr.recognizer import LineResult

LINE_REL = 0.5
WORD_REL = 0.4
WORD_LOCAL = 0.6
WORD_PAD = 1
MIN_RUN_CHARS = 2


def ink_contrast(gray: np.ndarray) -> float:
    return float(np.percentile(gray, 90) - np.percentile(gray, 3))


def _has_alnum(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def _span(gray: np.ndarray, t_start: int, t_end: int, stride: int) -> np.ndarray:
    x0 = max(0, (t_start - WORD_PAD) * stride)
    return gray[:, x0:(t_end + 1 + WORD_PAD) * stride]


def _word_contrast(gray: np.ndarray, word, stride: int) -> Optional[float]:
    if not _has_alnum(word.text):
        return None
    crop = _span(gray, word.t_start, word.t_end, stride)
    return ink_contrast(crop) if crop.size else None


def _edge_run(gray: np.ndarray, words: Sequence, order: Sequence[int], limit: float,
              stride: int) -> tuple[List[int], Optional[float], Optional[int]]:
    faint = []
    for i in order:
        c = _word_contrast(gray, words[i], stride)
        if c is None:
            continue
        if c >= limit:
            return faint, c, i
        faint.append((i, c))
    return [], None, None


def _edge_runs(gray: np.ndarray, words: Sequence, limit: float, stride: int) -> List[List[int]]:
    n = len(words)
    left, left_anchor, lo = _edge_run(gray, words, range(n), limit, stride)
    if left_anchor is None:
        return []
    right, right_anchor, _ = _edge_run(gray, words, range(n - 1, lo - 1, -1), limit, stride)
    runs = []
    for run, anchor in ((left, left_anchor), (right, right_anchor)):
        idx = sorted(i for i, c in run if anchor is not None and c < WORD_LOCAL * anchor)
        if sum(sum(ch.isalnum() for ch in words[i].text) for i in idx) >= MIN_RUN_CHARS:
            runs.append(idx)
    return runs


def filter_lines(recognizer, grays: Sequence[np.ndarray], measure: Sequence[np.ndarray],
                 results: Sequence[LineResult], stride: int) -> List[LineResult]:
    out = list(results)
    contrast = [ink_contrast(g) if r.text.strip() else 0.0 for g, r in zip(measure, results)]
    live = [c for c, r in zip(contrast, results) if r.text.strip()]
    if not live:
        return out
    median = float(np.median(live))

    faint = [i for i, (c, r) in enumerate(zip(contrast, results))
             if _has_alnum(r.text) and c < LINE_REL * median]
    if faint:
        flipped = recognizer.run_lines([np.ascontiguousarray(grays[i][:, ::-1]) for i in faint],
                                       workers=1)
        for i, rev in zip(faint, flipped):
            if rev.confidence > results[i].confidence:
                out[i] = LineResult("", [], results[i].confidence)

    candidates = []
    for i, r in enumerate(out):
        if not r.text.strip():
            continue
        for idx in _edge_runs(measure[i], r.words, WORD_REL * median, stride):
            t0 = min(r.words[j].t_start for j in idx)
            t1 = max(r.words[j].t_end for j in idx)
            candidates.append((i, idx, _span(grays[i], t0, t1, stride)))
    if not candidates:
        return out
    segments = [seg for _, _, seg in candidates]
    reads = recognizer.run_lines(
        segments + [np.ascontiguousarray(seg[:, ::-1]) for seg in segments], workers=1)
    cut: dict[int, set] = {}
    for k, (i, idx, _) in enumerate(candidates):
        if reads[len(candidates) + k].confidence > reads[k].confidence:
            cut.setdefault(i, set()).update(idx)
    for i, idx in cut.items():
        kept = [w for j, w in enumerate(out[i].words) if j not in idx]
        out[i] = LineResult(" ".join(w.text for w in kept), kept, out[i].confidence)
    return out
