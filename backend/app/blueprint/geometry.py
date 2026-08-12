"""Blueprint geometry extraction.

Two layers, both optional:

  * **OpenCV layer** (cv2): Canny edges + probabilistic Hough line detection for
    wall segments, gaps along the perimeter for gate openings.
  * **Heuristic layer** (numpy + Pillow, always available): dark-pixel
    projection to find the building footprint, perimeter walls and interior
    wall bands, plus opening candidates on each side.

The pipeline always runs the heuristic layer; OpenCV is used when installed
(see `requirements-optional.txt`). Every function here returns plain dicts so
the pipeline can degrade at each step without exceptions.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

_cv2_available: Optional[bool] = None


def _cv2() -> bool:
    global _cv2_available
    if _cv2_available is None:
        _cv2_available = importlib.util.find_spec("cv2") is not None
    return _cv2_available


@dataclass
class GeometryResult:
    width_px: int
    height_px: int
    footprint: Tuple[int, int, int, int]          # (x0, y0, x1, y1) in px
    perimeter: List[Tuple[Tuple[int, int], Tuple[int, int]]] = field(default_factory=list)
    interior_walls: List[Tuple[Tuple[int, int], Tuple[int, int]]] = field(default_factory=list)
    openings: List[Dict] = field(default_factory=list)  # {"position": (x,y), "side": "N|S|E|W"}
    opencv_used: bool = False


def _to_array(image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.float32)


def _detect_footprint(dark: np.ndarray) -> Tuple[int, int, int, int]:
    ys, xs = np.where(dark)
    if len(xs) == 0:
        return (0, 0, dark.shape[1] - 1, dark.shape[0] - 1)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _merge_bands(bands: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not bands:
        return []
    bands = sorted(bands)
    merged = [list(bands[0])]
    for a, b in bands[1:]:
        if a - merged[-1][1] <= 3:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _runs(mask: np.ndarray, min_len: int) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i in range(mask.shape[0]):
        if mask[i] and start is None:
            start = i
        elif not mask[i] and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    if start is not None and mask.shape[0] - start >= min_len:
        out.append((start, mask.shape[0] - 1))
    return out


def heuristic_geometry(image) -> GeometryResult:
    """numpy/Pillow-only structure detection (always available)."""
    arr = _to_array(image)
    H, W = arr.shape
    dark = arr < 165

    x0, y0, x1, y1 = _detect_footprint(dark)
    bbox = (x0, y0, x1, y1)
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)

    footprint_mask = np.zeros_like(dark)
    footprint_mask[y0:y1 + 1, x0:x1 + 1] = True

    # perimeter walls: the outermost dark band on each side
    perimeter: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    col_dark = dark[y0:y1 + 1, x0:x1 + 1].sum(axis=0) / bh
    row_dark = dark[y0:y1 + 1, x0:x1 + 1].sum(axis=1) / bw
    col_runs = _merge_bands(_runs(col_dark > 0.5, 4))
    row_runs = _merge_bands(_runs(row_dark > 0.5, 4))

    # east/west perimeter: the runs touching the bbox edges
    for a, b in col_runs:
        if a <= 2:
            perimeter.append(((x0 + a, y0), (x0 + b, y1)))
        if b >= bw - 3:
            perimeter.append(((x0 + a, y0), (x0 + b, y1)))
    for a, b in row_runs:
        if a <= 2:
            perimeter.append(((x0, y0 + a), (x1, y0 + b)))
        if b >= bh - 3:
            perimeter.append(((x0, y0 + a), (x1, y0 + b)))
    # de-duplicate
    perimeter = list(dict.fromkeys(perimeter))

    # interior walls: bands strictly inside the footprint (away from edges)
    interior_walls: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    for a, b in row_runs:
        center = (a + b) / 2
        if center > bh * 0.08 and center < bh * 0.92:
            # x-extent of the dark run in this band
            band = dark[y0 + a:y0 + b + 1, x0:x1 + 1].any(axis=0)
            run = _runs(band, 6)
            for c0, c1 in run:
                if c1 - c0 >= 10:
                    interior_walls.append(((x0 + c0, y0 + int(center)), (x0 + c1, y0 + int(center))))
    for a, b in col_runs:
        center = (a + b) / 2
        if center > bw * 0.08 and center < bw * 0.92:
            band = dark[y0:y1 + 1, x0 + a:x0 + b + 1].any(axis=1)
            run = _runs(band, 6)
            for c0, c1 in run:
                if c1 - c0 >= 10:
                    interior_walls.append(((x0 + int(center), y0 + c0), (x0 + int(center), y0 + c1)))

    # opening candidates: light gaps along the perimeter strip
    openings: List[Dict] = []
    strip = 3
    sides = [
        ("N", dark[y0:y0 + strip, x0:x1 + 1]),
        ("S", dark[y1 - strip + 1:y1 + 1, x0:x1 + 1]),
        ("W", dark[y0:y1 + 1, x0:x0 + strip]),
        ("E", dark[y0:y1 + 1, x1 - strip + 1:x1 + 1]),
    ]
    for side, seg in sides:
        density = seg.sum(axis=0 if side in ("N", "S") else 1)
        if side in ("N", "S"):
            denom = max(1, seg.shape[0])
            gap = density / denom < 0.5
            for a, b in _runs(gap, 6):
                cx = (a + b) / 2
                openings.append({
                    "position": (int(x0 + cx), y0 if side == "N" else y1),
                    "side": side,
                    "width_px": int(b - a + 1),
                })
        else:
            denom = max(1, seg.shape[1])
            gap = density / denom < 0.5
            for a, b in _runs(gap, 6):
                cy = (a + b) / 2
                openings.append({
                    "position": (x0 if side == "W" else x1, int(y0 + cy)),
                    "side": side,
                    "width_px": int(b - a + 1),
                })

    # deterministic defaults when the perimeter reads as a solid rectangle
    if not openings and len(perimeter) >= 3:
        mid = [
            {"position": (int((x0 + x1) / 2), y0), "side": "N", "width_px": max(20, bw // 8)},
            {"position": (int((x0 + x1) / 2), y1), "side": "S", "width_px": max(20, bw // 8)},
            {"position": (x0, int((y0 + y1) / 2)), "side": "W", "width_px": max(20, bh // 8)},
            {"position": (x1, int((y0 + y1) / 2)), "side": "E", "width_px": max(20, bh // 8)},
        ]
        openings = mid

    return GeometryResult(
        width_px=W,
        height_px=H,
        footprint=bbox,
        perimeter=perimeter,
        interior_walls=interior_walls,
        openings=openings,
        opencv_used=False,
    )


def opencv_geometry(image) -> Optional[GeometryResult]:
    """OpenCV refinement: Hough line detection + perimeter gap analysis."""
    if not _cv2():
        return None
    import cv2

    arr = _to_array(image)
    H, W = arr.shape
    img = np.ascontiguousarray(image.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60, minLineLength=20, maxLineGap=8)

    dark = _to_array(image) < 165
    x0, y0, x1, y1 = _detect_footprint(dark)

    # perimeter from the footprint bbox (heuristic) + Hough interior walls
    perimeter = [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ]
    interior_walls: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    if lines is not None:
        # numpy>=2.0 returns a 2-D (N,4) array; earlier versions (N,1,4)
        for xa, ya, xb, yb in np.asarray(lines).reshape(-1, 4):
            # keep axis-dominant long lines strictly inside the footprint
            if min(xa, xb) < x0 + 6 or max(xa, xb) > x1 - 6:
                continue
            if min(ya, yb) < y0 + 6 or max(ya, yb) > y1 - 6:
                continue
            if abs(xb - xa) > 12 or abs(yb - ya) > 12:
                interior_walls.append(((int(xa), int(ya)), (int(xb), int(yb))))

    # light gaps along the perimeter strips
    openings: List[Dict] = []
    strip = 3
    for side, (p0, p1) in zip("NESW", perimeter):
        if side in ("N", "S"):
            yp = y0 if side == "N" else y1
            seg = dark[max(0, yp - 1):yp + 2, x0:x1 + 1].any(axis=0)
        else:
            xp = x0 if side == "W" else x1
            seg = dark[y0:y1 + 1, max(0, xp - 1):xp + 2].any(axis=1)
        gap = ~seg
        for a, b in _runs(gap, 8):
            if side in ("N", "S"):
                cx = a + (b - a) / 2
                openings.append({"position": (int(x0 + cx), yp), "side": side, "width_px": int(b - a + 1)})
            else:
                cy = a + (b - a) / 2
                openings.append({"position": (xp, int(y0 + cy)), "side": side, "width_px": int(b - a + 1)})

    if not openings:
        return None  # let the heuristic layer supply defaults

    return GeometryResult(
        width_px=W,
        height_px=H,
        footprint=(x0, y0, x1, y1),
        perimeter=perimeter,
        interior_walls=interior_walls,
        openings=openings,
        opencv_used=True,
    )


def analyze_geometry(image) -> GeometryResult:
    """Best-effort geometry: OpenCV when available, heuristic otherwise."""
    if _cv2():
        result = opencv_geometry(image)
        if result is not None:
            return result
    return heuristic_geometry(image)


def estimate_dimensions_m(geometry: GeometryResult) -> Tuple[float, float]:
    """Map pixel geometry to venue metres.

    Default scale 0.6 m/px (a 10 m gate ≈ 16 px), clamped to sane venue sizes.
    """
    bw = max(1, geometry.footprint[2] - geometry.footprint[0])
    bh = max(1, geometry.footprint[3] - geometry.footprint[1])
    width_m = min(2000.0, max(300.0, bw * 0.6))
    height_m = min(2000.0, max(200.0, bh * 0.6))
    return round(width_m), round(height_m)
