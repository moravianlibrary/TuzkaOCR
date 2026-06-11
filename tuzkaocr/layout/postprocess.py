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

def _nms_baseline(prob: np.ndarray, half_win: int=2, threshold: float=0.35) -> np.ndarray:
    kernel = np.ones((2 * half_win + 1, 1), dtype=np.float32)
    local_max = ndi.maximum_filter(prob, footprint=kernel, mode='constant')
    return ((prob >= local_max - 1e-06) & (prob > threshold)).astype(np.uint8)

def _nms_baseline_subtract_endpoints(prob: np.ndarray, endpoint_prob: np.ndarray, half_win: int=2, threshold: float=0.35, endpoint_weight: float=0.5) -> np.ndarray:
    kernel = np.ones((2 * half_win + 1, 1), dtype=np.float32)
    local_max = ndi.maximum_filter(prob, footprint=kernel, mode='constant')
    nms = prob * (prob >= local_max - 1e-06)
    return (nms - endpoint_weight * endpoint_prob > threshold).astype(np.uint8)

def _baseline_points_from_xy(ys: np.ndarray, xs: np.ndarray, step: int=4) -> List[Tuple[int, int]]:
    if xs.size == 0:
        return []
    x_min = int(xs.min())
    x_max = int(xs.max())
    order = np.argsort(xs, kind="stable")
    xs_s = xs[order]
    ys_s = ys[order]
    starts = np.concatenate(([0], np.flatnonzero(np.diff(xs_s)) + 1))
    ends = np.concatenate((starts[1:], [xs_s.size]))
    uniq_x = xs_s[starts]
    targets = np.arange(x_min, x_max + 1, step, dtype=xs.dtype)
    idx = np.searchsorted(uniq_x, targets)
    safe_idx = np.clip(idx, 0, uniq_x.size - 1)
    hit = (idx < uniq_x.size) & (uniq_x[safe_idx] == targets)
    pts: List[Tuple[int, int]] = []
    for t, h, i in zip(targets.tolist(), hit.tolist(), idx.tolist()):
        if not h:
            continue
        seg = ys_s[starts[i]:ends[i]]
        pts.append((int(t), int(np.median(seg))))
    if pts and pts[-1][0] != x_max:
        i = uniq_x.size - 1
        seg = ys_s[starts[i]:ends[i]]
        pts.append((int(x_max), int(np.median(seg))))
    return pts


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

def _line_center_x(ln: TextLine) -> float:
    xs = [p[0] for p in ln.baseline]
    return float(np.mean(xs)) if xs else 0.0

def _line_center_y(ln: TextLine) -> float:
    ys = [p[1] for p in ln.baseline]
    return float(np.mean(ys)) if ys else 0.0

def _line_x_range(ln: TextLine) -> Tuple[int, int]:
    xs = [p[0] for p in ln.baseline]
    return (min(xs), max(xs)) if xs else (0, 0)

def _binarize(maps: np.ndarray, half_win: int=1, threshold: float=0.35, endpoint_weight: float=0.5) -> Tuple[np.ndarray, float]:
    base_map = maps[:, :, 2]
    ep_map = maps[:, :, 3]
    binary = _nms_baseline_subtract_endpoints(base_map, ep_map, half_win=half_win, threshold=threshold, endpoint_weight=endpoint_weight)
    ys, xs = np.where(binary)
    if len(xs) == 0:
        return (binary, 10.0)
    asc_samples = np.maximum(maps[ys, xs, 0], 0)
    median_asc = float(np.median(asc_samples))
    return (binary, median_asc)

def _gutter_columns(binary: np.ndarray) -> List[int]:
    col = binary.sum(axis=0).astype(np.float64)
    nz = np.where(col > 0)[0]
    if nz.size < 10:
        return []
    a, b = int(nz[0]), int(nz[-1])
    width = b - a
    if width < 60:
        return []
    k = max(3, width // 80)
    sm = np.convolve(col, np.ones(k) / k, mode="same")
    content = col[a:b + 1]
    ref = float(np.median(content[content > 0])) if np.any(content > 0) else 0.0
    if ref <= 0:
        return []
    lo = a + int(0.18 * width)
    hi = a + int(0.82 * width)
    if hi <= lo:
        return []
    flank = max(8, width // 6)
    gutters = []
    g = lo + int(np.argmin(sm[lo:hi]))
    if sm[g] < 0.45 * ref:
        left_peak = float(sm[max(a, g - flank):g].max()) if g > a else 0.0
        right_peak = float(sm[g + 1:min(b + 1, g + flank)].max()) if g < b else 0.0
        if left_peak > 2.0 * max(sm[g], 1e-6) and right_peak > 2.0 * max(sm[g], 1e-6):
            gutters.append(g)
    return gutters


def _extract_lines(maps: np.ndarray, binary_initial: np.ndarray, median_asc: float, threshold: float=0.35, endpoint_weight: float=0.5) -> List[TextLine]:
    base_map = maps[:, :, 2]
    ep_map = maps[:, :, 3]
    if median_asc > 10:
        nms_half_win = 2
        v_dilate = 5
        h_dilate = 2
        min_pixels = 8
    else:
        nms_half_win = 1
        v_dilate = 3
        h_dilate = 1
        min_pixels = max(5, int(median_asc))
    binary = _nms_baseline_subtract_endpoints(base_map, ep_map, half_win=nms_half_win, threshold=threshold, endpoint_weight=endpoint_weight)
    kernel = np.ones((v_dilate, 2 * h_dilate + 1), dtype=np.uint8)
    dilated = cv2.dilate(binary, kernel, iterations=1)
    for g in _gutter_columns(binary):
        dilated[:, max(0, g - h_dilate - 1):g + h_dilate + 2] = 0
    num, labels = cv2.connectedComponents(dilated, connectivity=8)
    labels = labels * binary.astype(labels.dtype)
    asc_h = ndi.grey_dilation(maps[:, :, 0], size=(5, 1))
    desc_h = ndi.grey_dilation(maps[:, :, 1], size=(5, 1))
    extend = max(1, int(median_asc * 0.25))
    min_asc_poly = max(1.0, median_asc * 0.5)
    min_desc_poly = max(1.0, median_asc * 0.4)
    H_map, W_map = binary.shape

    ys_all, xs_all = np.where(labels > 0)
    if ys_all.size == 0:
        return []
    lids_all = labels[ys_all, xs_all]
    order = np.argsort(lids_all, kind="stable")
    lids_sorted = lids_all[order]
    ys_sorted = ys_all[order]
    xs_sorted = xs_all[order]
    lab_starts = np.concatenate(([0], np.flatnonzero(np.diff(lids_sorted)) + 1))
    lab_ends = np.concatenate((lab_starts[1:], [lids_sorted.size]))

    lines: List[TextLine] = []
    for k in range(lab_starts.size):
        s, e = int(lab_starts[k]), int(lab_ends[k])
        if e - s < min_pixels:
            continue
        ys_lab = ys_sorted[s:e]
        xs_lab = xs_sorted[s:e]
        pts = _baseline_points_from_xy(ys_lab, xs_lab, step=4)
        if len(pts) < 2:
            continue
        (x0, y0), (x1, y1) = (pts[0], pts[1])
        dxs, dys = (x1 - x0, y1 - y0)
        n0 = max(1e-06, (dxs * dxs + dys * dys) ** 0.5)
        ex0 = max(0, int(x0 - dxs / n0 * extend))
        ey0 = int(y0 - dys / n0 * extend)
        (xa, ya), (xb, yb) = (pts[-2], pts[-1])
        dxe, dye = (xb - xa, yb - ya)
        ne = max(1e-06, (dxe * dxe + dye * dye) ** 0.5)
        ex1 = min(W_map - 1, int(xb + dxe / ne * extend))
        ey1 = int(yb + dye / ne * extend)
        pts = [(ex0, max(0, min(H_map - 1, ey0)))] + pts + [(ex1, max(0, min(H_map - 1, ey1)))]
        asc, desc = _sample_heights_from_xy(ys_lab, xs_lab, asc_h, desc_h, percentile=70.0)
        poly = _baseline_to_polygon_normal(pts, asc, desc, min_asc=min_asc_poly, min_desc=min_desc_poly)
        lines.append(TextLine(baseline=pts, polygon=poly, heights=(asc, desc)))
    return lines

def _path_penalty(b_top: np.ndarray, b_bot: np.ndarray, shift_top: float, shift_bot: float, x1: int, x2: int, region_map: np.ndarray) -> float:
    H, W = region_map.shape
    if x2 <= x1:
        return 0.0
    pts_top = b_top.astype(np.int32).copy()
    pts_top[:, 1] = np.clip(pts_top[:, 1] + int(round(shift_top)), 0, H - 1)
    pts_bot = b_bot.astype(np.int32).copy()
    pts_bot[:, 1] = np.clip(pts_bot[:, 1] + int(round(shift_bot)), 0, H - 1)
    y_min = max(0, min(pts_top[:, 1].min(), pts_bot[:, 1].min()) - 1)
    y_max = min(H, max(pts_top[:, 1].max(), pts_bot[:, 1].max()) + 2)
    if y_max - y_min < 2:
        return 0.0
    x_min = max(0, x1 - 2)
    x_max = min(W, x2 + 2)
    if x_max - x_min < 2:
        return 0.0
    crop = region_map[y_min:y_max, x_min:x_max]
    mask = np.zeros_like(crop, dtype=np.uint8)

    def _draw(pts, mask, x_off, y_off):
        local = pts.copy()
        local[:, 0] -= x_off
        local[:, 1] -= y_off
        for k in range(len(local) - 1):
            p0 = tuple(local[k])
            p1 = tuple(local[k + 1])
            cv2.line(mask, p0, p1, color=1, thickness=3)
    _draw(pts_top, mask, x_min, y_min)
    _draw(pts_bot, mask, x_min, y_min)
    xs_start = max(0, x1 - x_min)
    xs_end = min(mask.shape[1], x2 - x_min)
    if xs_end <= xs_start:
        return 0.0
    sub_mask = mask[:, xs_start:xs_end]
    sub_crop = crop[:, xs_start:xs_end]
    n = int(sub_mask.sum())
    if n == 0:
        return 0.0
    return float((sub_mask * sub_crop).sum() / n)

def _cluster_regions(lines: List[TextLine], region_map: np.ndarray, paragraph_threshold: float=0.15, x_overlap_min: int=5) -> List[List[TextLine]]:
    if not lines:
        return []
    sorted_lines = sorted(lines, key=_line_center_y)
    n = len(sorted_lines)
    heights = [max(1.0, ln.heights[0] + ln.heights[1]) for ln in sorted_lines if sum(ln.heights) > 0]
    median_h = float(np.median(heights)) if heights else 20.0
    max_vertical_gap = 3.0 * median_h
    x_ranges = [_line_x_range(ln) for ln in sorted_lines]
    cys = [_line_center_y(ln) for ln in sorted_lines]
    baselines_np = [np.asarray(ln.baseline, dtype=np.int32) for ln in sorted_lines]
    descs = [ln.heights[1] for ln in sorted_lines]
    ascs = [ln.heights[0] for ln in sorted_lines]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = (find(a), find(b))
        if ra != rb:
            parent[ra] = rb
    for i in range(n):
        xi0, xi1 = x_ranges[i]
        cy_i = cys[i]
        for j in range(i + 1, n):
            cy_j = cys[j]
            if cy_j - cy_i > max_vertical_gap:
                break
            xj0, xj1 = x_ranges[j]
            x_overlap = max(0, min(xi1, xj1) - max(xi0, xj0))
            if x_overlap < x_overlap_min:
                continue
            v_gap = abs(cy_j - cy_i)
            shorter_span = max(1, min(xi1 - xi0, xj1 - xj0))
            if v_gap < 0.5 * median_h and x_overlap > shorter_span * 0.5:
                union(i, j)
                continue
            penalty = _path_penalty(baselines_np[i], baselines_np[j], shift_top=descs[i], shift_bot=-ascs[j], x1=max(xi0, xj0), x2=min(xi1, xj1), region_map=region_map)
            if penalty < paragraph_threshold:
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

def _split_columns(group: List[TextLine], page_w: int) -> List[List[TextLine]]:
    if len(group) < 6:
        return [group]
    xr = [_line_x_range(ln) for ln in group]
    x0 = min(a for a, _ in xr)
    x1 = max(b for _, b in xr)
    span = x1 - x0
    widths = sorted(b - a for a, b in xr)
    med_w = max(1.0, widths[len(widths) // 2])
    if span < 1.6 * med_w:
        return [group]
    narrow = [(a, b) for a, b in xr if (b - a) < 0.6 * span]
    if len(narrow) < 4:
        return [group]
    occ = np.zeros(span + 2, dtype=np.int32)
    for a, b in narrow:
        occ[a - x0:b - x0 + 1] += 1
    lo = max(int(0.25 * span), 1)
    hi = int(0.75 * span)
    if hi <= lo:
        return [group]
    band = occ[lo:hi]
    gutter = x0 + lo + int(np.argmin(band))
    if int(occ[gutter - x0]) > max(1, int(0.15 * len(narrow))):
        return [group]
    left, right, wide = [], [], []
    for ln, (a, b) in zip(group, xr):
        if b <= gutter:
            left.append(ln)
        elif a >= gutter:
            right.append(ln)
        else:
            wide.append(ln)
    if len(left) < 2 or len(right) < 2:
        return [group]
    out = []
    if wide:
        out.append(wide)
    out.append(left)
    out.append(right)
    return out


def maps_to_regions(maps: np.ndarray) -> List[Region]:
    binary_initial, median_asc = _binarize(maps)
    lines = _extract_lines(maps, binary_initial, median_asc)
    if not lines:
        return []
    reg_map = np.maximum(maps[:, :, 4], 0)
    line_groups = _cluster_regions(lines, reg_map)
    page_w = maps.shape[1]
    split_groups = []
    for g in line_groups:
        split_groups.extend(_split_columns(g, page_w))
    regions = _assemble_regions(split_groups)
    return _order_regions(regions)