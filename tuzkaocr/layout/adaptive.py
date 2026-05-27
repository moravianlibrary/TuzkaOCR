from __future__ import annotations

import numpy as np

DS_LEVELS = (3, 2, 1)
PITCH_RATIO_THRESH = 0.85
OCR_CONF_THRESH = 0.90
SELECT_MARGIN = 0.02
LINE_INFLATE_FACTOR = 1.4
MIN_REGION_LINES = 5
MIN_REGION_WIDTH = 400


def min_pitch_ratio(regions, img_scale) -> float:
    ratios = []
    for r in regions:
        if len(r.lines) < MIN_REGION_LINES:
            continue
        xs = [x for ln in r.lines for x, _ in ln.baseline]
        if not xs:
            continue
        if (max(xs) - min(xs)) * img_scale < MIN_REGION_WIDTH:
            continue
        cys = sorted(float(np.mean([y for _, y in ln.baseline])) for ln in r.lines)
        if len(cys) < 3:
            continue
        pitch = float(np.median(np.diff(cys)))
        line_h = float(np.median([ln.heights[0] + ln.heights[1] for ln in r.lines]))
        ratios.append(pitch / max(1.0, line_h))
    return min(ratios) if ratios else 1.0


def starved(pitch, conf) -> bool:
    return pitch < PITCH_RATIO_THRESH or conf < OCR_CONF_THRESH


def choose(visited):
    base = visited[0]
    base_starved = base["pitch"] < PITCH_RATIO_THRESH
    cand = max(visited, key=lambda v: v["conf"])
    accept = (cand["ds"] != base["ds"]
              and cand["conf"] > base["conf"] + SELECT_MARGIN
              and (base_starved
                   or cand["n_lines"] <= LINE_INFLATE_FACTOR * max(1, base["n_lines"])))
    return cand if accept else base
