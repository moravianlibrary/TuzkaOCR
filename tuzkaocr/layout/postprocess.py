from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple
import cv2
import numpy as np
from scipy import ndimage as ndi


@dataclass
class TextLine:
    baseline: List[Tuple[int, int]]
    polygon: List[Tuple[int, int]]
    heights: Tuple[float, float]


@dataclass
class Region:
    lines: List[TextLine] = field(default_factory=list)
    polygon: List[Tuple[int, int]] = field(default_factory=list)


def _resample_baseline(xs: np.ndarray, ys: np.ndarray, max_pts: int = 10):
    if xs.size == 0:
        return None
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], ys[order]
    bounds = np.concatenate(([0], np.flatnonzero(np.diff(xs)) + 1, [xs.size]))
    ux = xs[bounds[:-1]]
    uy = np.array([np.median(ys[bounds[i]:bounds[i + 1]]) for i in range(len(ux))])
    n = ux.size
    if n < 2:
        return None
    k = max(2, min(max_pts, n // 10))
    sel = np.linspace(0, n - 1, k).astype(int)
    return [(int(ux[s]), int(round(uy[s]))) for s in sel]


def _sample_heights_from_xy(ys: np.ndarray, xs: np.ndarray, asc_map: np.ndarray, desc_map: np.ndarray, percentile: float=70.0) -> Tuple[float, float]:
    if xs.size == 0:
        return (10.0, 5.0)
    ascs = np.maximum(asc_map[ys, xs], 0)
    descs = np.maximum(desc_map[ys, xs], 0)
    return (float(np.percentile(ascs, percentile)), float(np.percentile(descs, percentile)))


def _baseline_to_polygon_normal(points, asc, desc, min_asc=1.0, min_desc=1.0):
    asc = max(float(asc), min_asc)
    desc = max(float(desc), min_desc)
    if len(points) < 2:
        x, y = points[0]
        return [(x - 2, y - int(asc)), (x + 2, y - int(asc)), (x + 2, y + int(desc)), (x - 2, y + int(desc))]
    pts = np.asarray(points, dtype=np.float32)
    diffs = np.diff(pts, axis=0)
    diffs = np.vstack([diffs, diffs[-1:]])
    angles = np.pi / 2 + np.arctan2(diffs[:, 1], diffs[:, 0])
    up = pts.copy()
    up[:, 0] -= np.cos(angles) * asc
    up[:, 1] -= np.sin(angles) * asc
    down = pts.copy()
    down[:, 0] += np.cos(angles) * desc
    down[:, 1] += np.sin(angles) * desc
    poly = np.vstack([up, down[::-1]])
    return [(int(round(x)), int(round(y))) for x, y in poly]


def _region_hull(lines):
    pts = []
    for ln in lines:
        pts.extend(ln.polygon)
    if len(pts) < 3:
        return pts
    arr = np.array(pts, dtype=np.float32)
    hull = cv2.convexHull(arr)
    return [(int(p[0][0]), int(p[0][1])) for p in hull]


def _line_center_y(ln: TextLine) -> float:
    ys = [p[1] for p in ln.baseline]
    return float(np.mean(ys)) if ys else 0.0


def _line_x_range(ln: TextLine) -> Tuple[int, int]:
    xs = [p[0] for p in ln.baseline]
    return (min(xs), max(xs)) if xs else (0, 0)


def _extract_lines(maps: np.ndarray, threshold: float = 0.25,
                   endpoint_weight: float = 1.0,
                   vertical_connection_range: int = 3) -> List[TextLine]:
    H, W = maps.shape[:2]
    asc_map = ndi.grey_dilation(maps[:, :, 0], size=(5, 1))
    desc_map = ndi.grey_dilation(maps[:, :, 1], size=(5, 1))

    base = ndi.convolve(maps[:, :, 2].astype(np.float32), np.ones((3, 3), np.float32) / 9.0)
    dil = ndi.grey_dilation(base, size=(5, 1))
    nms = base * (base >= dil - 1e-6)
    binary = ((nms - endpoint_weight * maps[:, :, 3]) > threshold).astype(np.uint8)
    if int(binary.sum()) == 0:
        return []

    structure = np.ones((vertical_connection_range, 3), np.uint8)
    dilated = cv2.dilate(binary, structure, iterations=1)
    num, labels = cv2.connectedComponents(dilated, connectivity=8)
    labels = labels * binary

    lines: List[TextLine] = []
    for lab in range(1, num):
        ys, xs = np.where(labels == lab)
        if xs.size <= 5:
            continue
        baseline = _resample_baseline(xs, ys)
        if baseline is None or (baseline[-1][0] - baseline[0][0]) < 5:
            continue
        baseline[0] = (max(0, baseline[0][0] - 2), baseline[0][1])
        baseline[-1] = (min(W - 1, baseline[-1][0] + 2), baseline[-1][1])
        asc, desc = _sample_heights_from_xy(ys, xs, asc_map, desc_map, percentile=50.0)
        polygon = _baseline_to_polygon_normal(baseline, asc, desc, min_asc=1.0, min_desc=1.0)
        lines.append(TextLine(
            baseline=[(int(x), int(y)) for x, y in baseline],
            polygon=[(int(x), int(y)) for x, y in polygon],
            heights=(float(asc), float(desc)),
        ))
    return lines


def _merge_line_fragments(lines: List[TextLine], sep_map: np.ndarray,
                          gap_factor: float = 1.5, sep_gate: float = 0.2) -> List[TextLine]:
    n = len(lines)
    if n < 2:
        return lines
    H, W = sep_map.shape
    it = []
    for ln in lines:
        xs = [p[0] for p in ln.baseline]
        ys = [p[1] for p in ln.baseline]
        it.append({"ln": ln, "x0": min(xs), "x1": max(xs), "cy": float(np.mean(ys)),
                   "h": max(1.0, ln.heights[0] + ln.heights[1])})

    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    order = sorted(range(n), key=lambda i: (it[i]["cy"], it[i]["x0"]))
    for ii in range(n):
        i = order[ii]
        for jj in range(ii + 1, n):
            j = order[jj]
            a, b = it[i], it[j]
            if b["cy"] - a["cy"] > max(a["h"], b["h"]):
                break
            h = 0.5 * (a["h"] + b["h"])
            if abs(a["cy"] - b["cy"]) > 0.6 * h:
                continue
            lo, hi = (a, b) if a["x0"] <= b["x0"] else (b, a)
            gap = hi["x0"] - lo["x1"]
            if gap < -0.5 * h or gap > gap_factor * h:
                continue
            gx0, gx1 = int(min(lo["x1"], hi["x0"])), int(max(lo["x1"], hi["x0"]) + 1)
            cy = int(0.5 * (a["cy"] + b["cy"]))
            ry0, ry1 = max(0, cy - int(0.5 * h)), min(H, cy + int(0.5 * h) + 1)
            gx0, gx1 = max(0, gx0), min(W, gx1)
            if gx1 > gx0 and ry1 > ry0 and float(sep_map[ry0:ry1, gx0:gx1].max()) > sep_gate:
                continue
            parent[find(i)] = find(j)

    groups: dict = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(it[i])

    out: List[TextLine] = []
    for grp in groups.values():
        if len(grp) == 1:
            out.append(grp[0]["ln"])
            continue
        pts = [p for g in grp for p in g["ln"].baseline]
        xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
        bl = _resample_baseline(xs, ys)
        if bl is None:
            out.append(max(grp, key=lambda g: g["x1"] - g["x0"])["ln"])
            continue
        asc = float(np.mean([g["ln"].heights[0] for g in grp]))
        desc = float(np.mean([g["ln"].heights[1] for g in grp]))
        poly = _baseline_to_polygon_normal(bl, asc, desc, min_asc=1.0, min_desc=1.0)
        out.append(TextLine(baseline=[(int(x), int(y)) for x, y in bl],
                            polygon=[(int(x), int(y)) for x, y in poly],
                            heights=(asc, desc)))
    return out


def _separator_penalty(baseline: List[Tuple[int, int]], shift: float,
                       x1: int, x2: int, sep_map: np.ndarray) -> float:
    H, W = sep_map.shape
    pts = np.array(baseline, dtype=np.int32).copy()
    pts[:, 1] = np.clip(pts[:, 1] + int(round(shift)), 0, H - 1)
    x_min = max(0, min(int(pts[:, 0].min()), int(x1)) - 2)
    x_max = min(W, max(int(pts[:, 0].max()), int(x2)) + 2)
    y_min = max(0, int(pts[:, 1].min()) - 1)
    y_max = min(H, int(pts[:, 1].max()) + 2)
    if x_max - x_min < 2 or y_max - y_min < 2:
        return 0.0
    crop = sep_map[y_min:y_max, x_min:x_max]
    mask = np.zeros_like(crop, dtype=np.uint8)
    local = pts.copy()
    local[:, 0] -= x_min
    local[:, 1] -= y_min
    for k in range(len(local) - 1):
        cv2.line(mask, (int(local[k][0]), int(local[k][1])),
                 (int(local[k + 1][0]), int(local[k + 1][1])), color=1, thickness=3)
    xs0 = max(0, int(x1) - x_min)
    xs1 = min(mask.shape[1], int(x2) - x_min)
    if xs1 <= xs0:
        return 0.0
    val = float((mask[:, xs0:xs1] * crop[:, xs0:xs1]).sum())
    return val / max(1.0, float(x2 - x1))


def _pair_penalty(li: TextLine, lj: TextLine, sep_map: np.ndarray) -> float:
    bi = np.asarray(li.baseline, dtype=float)
    bj = np.asarray(lj.baseline, dtype=float)
    x1 = max(bi[:, 0].min(), bj[:, 0].min())
    x2 = min(bi[:, 0].max(), bj[:, 0].max())
    if x2 - x1 <= 5:
        return 1.0
    if bi[:, 1].mean() < bj[:, 1].mean():
        p1 = _separator_penalty(li.baseline, +li.heights[1], x1, x2, sep_map)
        p2 = _separator_penalty(lj.baseline, -lj.heights[0], x1, x2, sep_map)
    else:
        p1 = _separator_penalty(li.baseline, -li.heights[0], x1, x2, sep_map)
        p2 = _separator_penalty(lj.baseline, +lj.heights[1], x1, x2, sep_map)
    return max(p1, p2)


def _cluster_regions(lines: List[TextLine], sep_map: np.ndarray,
                     paragraph_threshold: float = 0.25) -> List[List[TextLine]]:
    n = len(lines)
    if n == 0:
        return []
    if n == 1:
        return [list(lines)]
    sorted_lines = sorted(lines, key=_line_center_y)
    cys = [_line_center_y(ln) for ln in sorted_lines]
    xr = [_line_x_range(ln) for ln in sorted_lines]
    tot_h = [max(1.0, ln.heights[0] + ln.heights[1]) for ln in sorted_lines]
    median_h = float(np.median(tot_h))
    max_vgap = 3.0 * median_h

    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        xi0, xi1 = xr[i]
        cyi = cys[i]
        for j in range(i + 1, n):
            if cys[j] - cyi > max_vgap:
                break
            xj0, xj1 = xr[j]
            if min(xi1, xj1) - max(xi0, xj0) <= 5:
                continue
            if _pair_penalty(sorted_lines[i], sorted_lines[j], sep_map) < paragraph_threshold:
                union(i, j)

    groups: dict = defaultdict(list)
    for i, ln in enumerate(sorted_lines):
        groups[find(i)].append(ln)
    return list(groups.values())


def _assemble_regions(line_groups: List[List[TextLine]]) -> List[Region]:
    regions = []
    for group in line_groups:
        if not group:
            continue
        ordered = sorted(group, key=_line_center_y)
        regions.append(Region(lines=ordered, polygon=_region_hull(ordered)))
    return regions


def _split_bridged_columns(region: Region, sep_map: np.ndarray,
                           min_side_lines: int = 3,
                           max_bridge_frac: float = 0.25) -> List[Region]:
    lines = region.lines
    H, W = sep_map.shape
    if len(lines) < 2 * min_side_lines:
        return [region]
    x0s = [min(x for x, _ in ln.baseline) for ln in lines]
    x1s = [max(x for x, _ in ln.baseline) for ln in lines]
    ys = [y for ln in lines for _, y in ln.baseline]
    xmin, xmax = min(x0s), max(x1s)
    ymin, ymax = min(ys), max(ys)
    width = xmax - xmin
    if width < 0.55 * W or width < 2:
        return [region]

    y0, y1 = max(0, ymin), min(H, ymax + 1)
    cx0, cx1 = max(0, xmin), min(W, xmax + 1)
    if y1 - y0 < 2 or cx1 - cx0 < 4:
        return [region]
    prof = sep_map[y0:y1, cx0:cx1].sum(axis=0)
    lo, hi = int(0.25 * prof.size), int(0.75 * prof.size)
    if hi - lo < 2:
        return [region]
    gi = lo + int(np.argmax(prof[lo:hi]))
    peak = float(prof[gi])
    med = float(np.median(prof)) + 1e-6
    col_h = y1 - y0
    if peak < 0.12 * col_h or peak < 4.0 * med:
        return [region]
    g = cx0 + gi

    margin = 0.02 * width
    left, right, bridge = [], [], []
    for ln, a, b in zip(lines, x0s, x1s):
        if b <= g + margin:
            left.append(ln)
        elif a >= g - margin:
            right.append(ln)
        else:
            bridge.append(ln)
    if (len(left) < min_side_lines or len(right) < min_side_lines
            or len(bridge) > max_bridge_frac * len(lines)):
        return [region]

    out = []
    for grp in (left, right, bridge):
        if grp:
            ordered = sorted(grp, key=_line_center_y)
            out.append(Region(lines=ordered, polygon=_region_hull(ordered)))
    return out


def _region_bbox(r: Region) -> Tuple[int, int, int, int]:
    pts = r.polygon if r.polygon else [p for ln in r.lines for p in ln.polygon]
    if not pts:
        return (0, 0, 0, 0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _order_regions(regions: List[Region]) -> List[Region]:
    if not regions:
        return []
    bboxes = [_region_bbox(r) for r in regions]
    order = sorted(range(len(regions)), key=lambda i: bboxes[i][1])
    bands: List[List[int]] = []
    for i in order:
        y0, y1 = bboxes[i][1], bboxes[i][3]
        placed = False
        for band in bands:
            by0 = min(bboxes[k][1] for k in band)
            by1 = max(bboxes[k][3] for k in band)
            ov = min(y1, by1) - max(y0, by0)
            if ov > 0.5 * max(1, min(y1 - y0, by1 - by0)):
                band.append(i)
                placed = True
                break
        if not placed:
            bands.append([i])
    out = []
    for band in bands:
        widths = sorted(bboxes[i][2] - bboxes[i][0] for i in band)
        med_w = max(1.0, widths[len(widths) // 2])
        col_of = {}
        col = 0
        prev = None
        for i in sorted(band, key=lambda i: (bboxes[i][0] + bboxes[i][2]) / 2.0):
            c = (bboxes[i][0] + bboxes[i][2]) / 2.0
            if prev is not None and c - prev > 0.5 * med_w:
                col += 1
            col_of[i] = col
            prev = c
        band.sort(key=lambda i: (col_of[i], bboxes[i][1]))
        for i in band:
            out.append(regions[i])
    return out


def maps_to_regions(maps: np.ndarray, page_gray: np.ndarray = None) -> List[Region]:
    lines = _extract_lines(maps)
    if not lines:
        return []
    sep_map = np.maximum(maps[:, :, 4], 0)
    lines = _merge_line_fragments(lines, sep_map)
    groups = _cluster_regions(lines, sep_map)
    regions = _assemble_regions(groups)
    regions = [r2 for r in regions for r2 in _split_bridged_columns(r, sep_map)]
    return _order_regions(regions)
