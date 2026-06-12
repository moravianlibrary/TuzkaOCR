from __future__ import annotations

import numpy as np

DS_LEVELS = (3, 2, 1)
PITCH_RATIO_THRESH = 0.85
OCR_CONF_THRESH = 0.90
SELECT_MARGIN = 0.02
LINE_INFLATE_FACTOR = 1.4
MIN_REGION_LINES = 5
MIN_REGION_WIDTH = 400
WIDE_FRAC_THRESH = 0.08
WIDE_IMPROVE_MARGIN = 0.04
UNREADABLE_CONF = 0.60


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


def wide_line_frac(regions, img_scale, page_w) -> float:
    ws = []
    for r in regions:
        for ln in r.lines:
            xs = [x for x, _ in ln.baseline]
            if xs:
                ws.append((max(xs) - min(xs)) * img_scale)
    if len(ws) < 20:
        return 0.0
    med = float(np.median(ws))
    return float(np.mean([(w > 1.8 * med and w > 0.45 * page_w) for w in ws]))


def starved(pitch, conf, wide=0.0) -> bool:
    return pitch < PITCH_RATIO_THRESH or conf < OCR_CONF_THRESH or wide > WIDE_FRAC_THRESH


def choose(visited):
    base = visited[0]
    if base.get("wide", 0.0) > WIDE_FRAC_THRESH:
        cand = min(visited, key=lambda v: (v.get("wide", 0.0), -v["conf"]))
        if (cand["ds"] != base["ds"]
                and cand.get("wide", 0.0) < base["wide"] - WIDE_IMPROVE_MARGIN
                and cand["conf"] >= base["conf"] - 0.01):
            return cand
    base_starved = base["pitch"] < PITCH_RATIO_THRESH or base["conf"] < UNREADABLE_CONF
    cand = max(visited, key=lambda v: v["conf"])
    accept = (cand["ds"] != base["ds"]
              and cand["conf"] > base["conf"] + SELECT_MARGIN
              and (base_starved
                   or cand["n_lines"] <= LINE_INFLATE_FACTOR * max(1, base["n_lines"])))
    return cand if accept else base
