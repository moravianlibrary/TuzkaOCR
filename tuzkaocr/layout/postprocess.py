from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi

BASELINE_THRESH    = 0.35
ENDPOINT_THRESH    = 0.40
MIN_LINE_PX        = 30
NMS_HALF_WIN       = 3
H_DILATE_PX        = 12
V_DILATE_PX        = 0
REGION_GAP_FACTOR  = 2.5
MIN_REGION_LINES   = 1
COL_GAP_MIN_WIDTH  = 8


@dataclass
class TextLine:
    baseline: List[Tuple[int, int]]
    polygon:  List[Tuple[int, int]]
    heights:  Tuple[float, float]


@dataclass
class Region:
    lines:   List[TextLine] = field(default_factory=list)
    polygon: List[Tuple[int, int]] = field(default_factory=list)


def _nms_baseline(prob: np.ndarray,
                  half_win: int = NMS_HALF_WIN,
                  threshold: float = BASELINE_THRESH) -> np.ndarray:
    kernel = np.ones((2 * half_win + 1, 1), dtype=np.float32)
    local_max = ndi.maximum_filter(prob, footprint=kernel, mode="constant")
    return ((prob >= local_max - 1e-6) & (prob > threshold)).astype(np.uint8)


def _split_at_endpoints(binary: np.ndarray,
                         endpoint_prob: np.ndarray,
                         threshold: float = ENDPOINT_THRESH) -> np.ndarray:
    ep_mask = (endpoint_prob > threshold).astype(np.uint8)
    ep_dilated = cv2.dilate(ep_mask, np.ones((3, 3), np.uint8), iterations=1)
    return binary & (~ep_dilated).astype(np.uint8)


def _nms_baseline_subtract_endpoints(prob: np.ndarray,
                                     endpoint_prob: np.ndarray,
                                     half_win: int = 2,
                                     threshold: float = BASELINE_THRESH,
                                     endpoint_weight: float = 1.0) -> np.ndarray:
    kernel = np.ones((2 * half_win + 1, 1), dtype=np.float32)
    local_max = ndi.maximum_filter(prob, footprint=kernel, mode="constant")
    nms = prob * (prob >= local_max - 1e-6)
    return ((nms - endpoint_weight * endpoint_prob) > threshold).astype(np.uint8)


def _label_components(binary: np.ndarray,
                       h_dilate: int = H_DILATE_PX,
                       v_dilate: int = V_DILATE_PX) -> Tuple[np.ndarray, int]:
    if h_dilate > 0 or v_dilate > 0:
        kh = v_dilate * 2 + 1 if v_dilate > 0 else 1
        kw = h_dilate * 2 + 1 if h_dilate > 0 else 1
        kernel  = np.ones((kh, kw), np.uint8)
        dilated = cv2.dilate(binary, kernel, iterations=1)
    else:
        dilated = binary
    num, labels = cv2.connectedComponents(dilated, connectivity=8)
    return labels, num - 1


def _detect_column_splits(binary: np.ndarray,
                           min_gap_width: int = COL_GAP_MIN_WIDTH) -> List[int]:
    H, W = binary.shape

    x_density = binary.sum(axis=0).astype(float)

    nonzero = x_density[x_density > 0]
    if len(nonzero) == 0:
        return []
    gap_thresh = float(np.percentile(nonzero, 50)) * 0.06

    splits = []
    in_gap = False
    gap_start = 0

    for x in range(W):
        if x_density[x] <= gap_thresh:
            if not in_gap:
                in_gap = True
                gap_start = x
        else:
            if in_gap:
                in_gap = False
                gap_end = x
                gap_w = gap_end - gap_start
                if gap_w < min_gap_width:
                    continue
                min_px = max(10, int(H * 0.025))
                left_col  = binary[:, max(0, gap_start - 10):gap_start]
                right_col = binary[:, gap_end:min(W, gap_end + 10)]
                if int(left_col.sum()) >= min_px and int(right_col.sum()) >= min_px:
                    splits.append((gap_start + gap_end) // 2)

    return splits


def _mask_column_gaps(binary: np.ndarray,
                      h_dilate_px: int,
                      col_gap_min_width: int = COL_GAP_MIN_WIDTH) -> np.ndarray:
    effective_min_width = max(col_gap_min_width, h_dilate_px)
    col_splits = _detect_column_splits(binary, min_gap_width=effective_min_width)
    if not col_splits:
        return binary

    _, W_b = binary.shape
    x_dens = binary.sum(axis=0).astype(float)
    nonzero = x_dens[x_dens > 0]
    gap_thresh = float(np.percentile(nonzero, 50)) * 0.06 if len(nonzero) else 0
    masked = binary.copy()
    for xs in col_splits:
        lo, hi = xs, xs
        while lo > 0 and x_dens[lo - 1] <= max(gap_thresh, 5):
            lo -= 1
        while hi < W_b - 1 and x_dens[hi + 1] <= max(gap_thresh, 5):
            hi += 1
        lo = max(0, lo - h_dilate_px)
        hi = min(W_b - 1, hi + h_dilate_px)
        masked[:, lo:hi + 1] = 0
    return masked


def _extract_baseline_points(mask: np.ndarray,
                               step: int = 4) -> List[Tuple[int, int]]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return []
    x_min, x_max = int(xs.min()), int(xs.max())
    if x_max - x_min < MIN_LINE_PX:
        return []
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


def _sample_heights(points, asc_map, desc_map):
    if not points:
        return (10.0, 5.0)
    H, W = asc_map.shape
    ascs, descs = [], []
    for x, y in points:
        xc, yc = min(x, W - 1), min(y, H - 1)
        ascs.append(float(asc_map[yc, xc]))
        descs.append(float(desc_map[yc, xc]))
    return (float(np.median(ascs)), float(np.median(descs)))


def _sample_component_heights(mask: np.ndarray,
                              asc_map: np.ndarray,
                              desc_map: np.ndarray,
                              percentile: float = 50.0) -> Tuple[float, float]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return (10.0, 5.0)
    ascs = np.maximum(asc_map[ys, xs], 0)
    descs = np.maximum(desc_map[ys, xs], 0)
    return (float(np.percentile(ascs, percentile)),
            float(np.percentile(descs, percentile)))


def _baseline_to_polygon(points, asc, desc, min_asc=3.0, min_desc=2.0):
    asc  = max(asc,  min_asc)
    desc = max(desc, min_desc)
    top    = [(x, y - int(round(asc)))  for x, y in points]
    bottom = [(x, y + int(round(desc))) for x, y in reversed(points)]
    return top + bottom


def _baseline_to_polygon_normal(points, asc, desc, min_asc=3.0, min_desc=2.0):
    asc = max(float(asc), min_asc)
    desc = max(float(desc), min_desc)
    if len(points) < 2:
        return _baseline_to_polygon(points, asc, desc, min_asc, min_desc)

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


def _sort_regions_by_column(regions: List[Region], width: int) -> None:
    col_width = max(1, width // 4)
    regions.sort(key=lambda r: (
        int(_line_center_x(r.lines[0]) / col_width),
        _line_center_y(r.lines[0]),
    ))


def _cluster_lines(lines: List[TextLine],
                    region_map: np.ndarray,
                    gap_factor: float = REGION_GAP_FACTOR,
                    x_overlap_min: int = 5,
                    region_boundary_thresh: float = 0.65) -> List[Region]:
    if not lines:
        return []

    sorted_lines = sorted(lines, key=_line_center_y)
    n = len(sorted_lines)

    heights = [h for h in (ln.heights[0] + ln.heights[1] for ln in sorted_lines) if h > 0]
    median_h = float(np.median(heights)) if heights else 20.0
    H, W = region_map.shape

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    max_gap = gap_factor * median_h * 1.1

    for i in range(n):
        xi0, xi1 = _line_x_range(sorted_lines[i])
        cy_i = _line_center_y(sorted_lines[i])

        for j in range(i + 1, n):
            cy_j = _line_center_y(sorted_lines[j])
            if cy_j - cy_i > max_gap:
                break

            xj0, xj1 = _line_x_range(sorted_lines[j])
            x_overlap = max(0, min(xi1, xj1) - max(xi0, xj0))
            if x_overlap < x_overlap_min:
                continue

            if cy_j - cy_i > gap_factor * median_h:
                continue

            mid_y = int((cy_i + cy_j) / 2)
            mid_x = int((max(xi0, xj0) + min(xi1, xj1)) / 2)
            mid_y = min(mid_y, H - 1)
            mid_x = min(mid_x, W - 1)
            if region_map[mid_y, mid_x] > region_boundary_thresh:
                continue

            union(i, j)

    groups: dict = defaultdict(list)
    for i, ln in enumerate(sorted_lines):
        groups[find(i)].append(ln)

    regions = []
    for group_lines in groups.values():
        if len(group_lines) < MIN_REGION_LINES:
            continue
        group_sorted = sorted(group_lines, key=_line_center_y)
        regions.append(Region(lines=group_sorted, polygon=_region_hull(group_lines)))

    _sort_regions_by_column(regions, W)
    return regions


def _interpolate_baseline_y(points: List[Tuple[int, int]], xs: np.ndarray) -> np.ndarray:
    arr = np.asarray(points, dtype=np.float32)
    if len(arr) == 1:
        return np.full_like(xs, arr[0, 1], dtype=np.float32)
    return np.interp(xs, arr[:, 0], arr[:, 1]).astype(np.float32)


def _separator_score_between(a: TextLine, b: TextLine,
                             region_map: np.ndarray,
                             sample_count: int = 32) -> float:
    ax0, ax1 = _line_x_range(a)
    bx0, bx1 = _line_x_range(b)
    x0, x1 = max(ax0, bx0), min(ax1, bx1)
    if x1 - x0 < 5:
        return 1.0

    H, W = region_map.shape
    xs = np.linspace(x0, x1, max(4, min(sample_count, x1 - x0 + 1)), dtype=np.float32)
    ya = _interpolate_baseline_y(a.baseline, xs)
    yb = _interpolate_baseline_y(b.baseline, xs)
    mid = (ya + yb) / 2.0

    x_idx = np.clip(np.round(xs).astype(np.int32), 0, W - 1)
    y_idx = np.clip(np.round(mid).astype(np.int32), 0, H - 1)
    return float(np.mean(region_map[y_idx, x_idx]))


def _cluster_lines_structured(lines: List[TextLine],
                              region_map: np.ndarray,
                              separator_thresh: float = 0.15,
                              gap_factor: float = REGION_GAP_FACTOR,
                              x_overlap_min: int = 5) -> List[Region]:
    if not lines:
        return []

    sorted_lines = sorted(lines, key=_line_center_y)
    n = len(sorted_lines)
    heights = [
        max(1.0, float(h))
        for h in (ln.heights[0] + ln.heights[1] for ln in sorted_lines)
        if h > 0
    ]
    median_h = float(np.median(heights)) if heights else 20.0

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    max_gap = gap_factor * median_h
    for i in range(n):
        xi0, xi1 = _line_x_range(sorted_lines[i])
        cy_i = _line_center_y(sorted_lines[i])

        for j in range(i + 1, n):
            cy_j = _line_center_y(sorted_lines[j])
            if cy_j - cy_i > max_gap:
                break

            xj0, xj1 = _line_x_range(sorted_lines[j])
            x_overlap = max(0, min(xi1, xj1) - max(xi0, xj0))
            if x_overlap < x_overlap_min:
                continue

            if _separator_score_between(sorted_lines[i], sorted_lines[j], region_map) < separator_thresh:
                union(i, j)

    groups: dict = defaultdict(list)
    for i, ln in enumerate(sorted_lines):
        groups[find(i)].append(ln)

    regions = []
    for group_lines in groups.values():
        group_sorted = sorted(group_lines, key=_line_center_y)
        regions.append(Region(lines=group_sorted, polygon=_region_hull(group_sorted)))

    _sort_regions_by_column(regions, region_map.shape[1])
    return regions


def _maps_to_regions_legacy(maps: np.ndarray,
                     baseline_step: int = 4,
                     baseline_thresh: float = BASELINE_THRESH,
                     endpoint_thresh: float = ENDPOINT_THRESH,
                     h_dilate_px: int = H_DILATE_PX,
                     v_dilate_px: int = V_DILATE_PX,
                     region_gap_factor: float = REGION_GAP_FACTOR,
                     region_boundary_thresh: float = 0.65,
                     nms_half_win: int = NMS_HALF_WIN,
                     col_gap_min_width: int = COL_GAP_MIN_WIDTH) -> List[Region]:
    asc_map  = maps[:, :, 0]
    desc_map = maps[:, :, 1]
    base_map = maps[:, :, 2]
    ep_map   = maps[:, :, 3]
    reg_map  = maps[:, :, 4]

    binary = _nms_baseline(base_map, half_win=nms_half_win,
                           threshold=baseline_thresh)
    binary = _split_at_endpoints(binary, ep_map, threshold=endpoint_thresh)

    binary_for_cc = _mask_column_gaps(
        binary, h_dilate_px=h_dilate_px,
        col_gap_min_width=col_gap_min_width)

    labels, n_comp = _label_components(binary_for_cc, h_dilate=h_dilate_px,
                                       v_dilate=v_dilate_px)

    lines: List[TextLine] = []
    for label_id in range(1, n_comp + 1):
        comp_mask = (labels == label_id).astype(np.uint8)
        raw_mask = (comp_mask & binary_for_cc).astype(np.uint8)
        pts = _extract_baseline_points(raw_mask, step=baseline_step)
        if not pts:
            pts = _extract_baseline_points(comp_mask, step=baseline_step)
        if not pts:
            continue
        asc, desc = _sample_heights(pts, asc_map, desc_map)
        poly = _baseline_to_polygon(pts, asc, desc)
        lines.append(TextLine(baseline=pts, polygon=poly, heights=(asc, desc)))

    return _cluster_lines(lines, reg_map, gap_factor=region_gap_factor,
                          region_boundary_thresh=region_boundary_thresh)


def _line_count(regions: List[Region]) -> int:
    return sum(len(region.lines) for region in regions)


def _line_width_percentile(regions: List[Region], width: int,
                           percentile: float = 90.0) -> float:
    line_widths = []
    for region in regions:
        for line in region.lines:
            x0, x1 = _line_x_range(line)
            line_widths.append(max(0, x1 - x0))
    if not line_widths or width <= 0:
        return 0.0
    return float(np.percentile(line_widths, percentile)) / float(width)


def _maps_to_regions_structured_once(maps: np.ndarray,
                                     baseline_step: int,
                                     baseline_thresh: float,
                                     endpoint_weight: float,
                                     h_dilate_px: int,
                                     vertical_connection_range: int,
                                     height_percentile: float,
                                     separator_thresh: float,
                                     nms_half_win: int,
                                     col_gap_min_width: int) -> List[Region]:
    asc_map = maps[:, :, 0]
    desc_map = maps[:, :, 1]
    base_map = maps[:, :, 2]
    ep_map = maps[:, :, 3]
    reg_map = np.maximum(maps[:, :, 4], 0)

    height_maps = ndi.grey_dilation(maps[:, :, :2], size=(5, 1, 1))
    asc_h = height_maps[:, :, 0]
    desc_h = height_maps[:, :, 1]

    binary = _nms_baseline_subtract_endpoints(
        base_map, ep_map, half_win=nms_half_win,
        threshold=baseline_thresh, endpoint_weight=endpoint_weight,
    )

    binary_for_cc = _mask_column_gaps(
        binary, h_dilate_px=h_dilate_px,
        col_gap_min_width=col_gap_min_width)

    labels, n_comp = _label_components(
        binary_for_cc,
        h_dilate=h_dilate_px,
        v_dilate=max(0, vertical_connection_range // 2),
    )

    lines: List[TextLine] = []
    for label_id in range(1, n_comp + 1):
        comp_mask = (labels == label_id).astype(np.uint8)
        raw_mask = (comp_mask & binary_for_cc).astype(np.uint8)
        if raw_mask.sum() == 0:
            raw_mask = comp_mask
        pts = _extract_baseline_points(raw_mask, step=baseline_step)
        if not pts:
            continue
        asc, desc = _sample_component_heights(
            raw_mask, asc_h, desc_h, percentile=height_percentile)
        poly = _baseline_to_polygon_normal(pts, asc, desc)
        lines.append(TextLine(baseline=pts, polygon=poly, heights=(asc, desc)))

    return _cluster_lines_structured(lines, reg_map, separator_thresh=separator_thresh)


def maps_to_regions_structured(maps: np.ndarray,
                               baseline_step: int = 4,
                               baseline_thresh: float = 0.20,
                               endpoint_weight: float = 0.0,
                               h_dilate_px: int = 32,
                               vertical_connection_range: int = 3,
                               height_percentile: float = 50.0,
                               separator_thresh: float = 0.15,
                               nms_half_win: int = 2,
                               col_gap_min_width: int = COL_GAP_MIN_WIDTH,
                               legacy_fallback: bool = True) -> List[Region]:
    structured = _maps_to_regions_structured_once(
        maps,
        baseline_step=baseline_step,
        baseline_thresh=baseline_thresh,
        endpoint_weight=endpoint_weight,
        h_dilate_px=h_dilate_px,
        vertical_connection_range=vertical_connection_range,
        height_percentile=height_percentile,
        separator_thresh=separator_thresh,
        nms_half_win=nms_half_win,
        col_gap_min_width=col_gap_min_width,
    )
    if not legacy_fallback:
        return structured

    structured_n = _line_count(structured)
    if structured_n < 20:
        return structured

    legacy = _maps_to_regions_legacy(
        maps,
        baseline_step=baseline_step,
        baseline_thresh=0.35,
        h_dilate_px=12,
        col_gap_min_width=col_gap_min_width,
    )
    legacy_n = _line_count(legacy)
    primary_width_p90 = _line_width_percentile(structured, maps.shape[1])

    if (structured_n <= 95 and
            primary_width_p90 < 0.62 and
            1.25 * structured_n <= legacy_n <= 2.75 * structured_n and
            legacy_n <= 140):
        return legacy
    return structured
