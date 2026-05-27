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

def _extract_baseline_points(mask: np.ndarray, step: int=4) -> List[Tuple[int, int]]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return []
    x_min, x_max = (int(xs.min()), int(xs.max()))
    points = []
    for x in range(x_min, x_max + 1, step):
        col_ys = ys[xs == x]
        if len(col_ys) == 0:
            continue
        points.append((x, int(np.median(col_ys))))
    if points and points[0][0] != x_min:
        col_ys = ys[xs == x_min]
        if len(col_ys):
            points.insert(0, (x_min, int(np.median(col_ys))))
    if points and points[-1][0] != x_max:
        col_ys = ys[xs == x_max]
        if len(col_ys):
            points.append((x_max, int(np.median(col_ys))))
    return sorted(points, key=lambda p: p[0])

def _sample_component_heights(mask: np.ndarray, asc_map: np.ndarray, desc_map: np.ndarray, percentile: float=70.0) -> Tuple[float, float]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
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
    num, labels = cv2.connectedComponents(dilated, connectivity=8)
    labels = labels * binary.astype(labels.dtype)
    asc_h = ndi.grey_dilation(maps[:, :, 0], size=(5, 1))
    desc_h = ndi.grey_dilation(maps[:, :, 1], size=(5, 1))
    extend = max(1, int(median_asc * 0.25))
    min_asc_poly = max(1.0, median_asc * 0.5)
    min_desc_poly = max(1.0, median_asc * 0.4)
    H_map, W_map = binary.shape
    lines: List[TextLine] = []
    for lid in range(1, num):
        comp_mask = (labels == lid).astype(np.uint8)
        if comp_mask.sum() < min_pixels:
            continue
        pts = _extract_baseline_points(comp_mask, step=4)
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
        asc, desc = _sample_component_heights(comp_mask, asc_h, desc_h, percentile=70.0)
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
    centers_x = [(bx[0] + bx[2]) / 2.0 for bx in bboxes]
    widths = [max(1, bx[2] - bx[0]) for bx in bboxes]
    median_w = float(np.median(widths))
    order = sorted(range(len(regions)), key=lambda i: centers_x[i])
    sorted_cx = [centers_x[i] for i in order]
    buckets: List[List[int]] = []
    threshold = 0.5 * median_w
    for k, idx in enumerate(order):
        if not buckets or sorted_cx[k] - sorted_cx[k - 1] > threshold:
            buckets.append([idx])
        else:
            buckets[-1].append(idx)
    out = []
    for bucket in buckets:
        bucket.sort(key=lambda i: bboxes[i][1])
        for i in bucket:
            out.append(regions[i])
    return out

def maps_to_regions(maps: np.ndarray) -> List[Region]:
    binary_initial, median_asc = _binarize(maps)
    lines = _extract_lines(maps, binary_initial, median_asc)
    if not lines:
        return []
    reg_map = np.maximum(maps[:, :, 4], 0)
    line_groups = _cluster_regions(lines, reg_map)
    regions = _assemble_regions(line_groups)
    return _order_regions(regions)