"""Deterministic computer-vision perception provider.

Extracts blueprint structure with OpenCV + numpy (no model involved):

  * BOUNDARY    - outermost building footprint polygon
  * WALL        - merged long interior wall segments (Hough + collinear merge)
  * REGION      - enclosed spaces (holes in the wall topology); semantic stage
                  refines these into ROOM / ZONE / FIELD / SEATING / CONCOURSE
  * GATE/DOOR   - light gaps along the footprint perimeter / wall segments
  * STAIR       - compact parallel-line hatching clusters
  * CORRIDOR    - polylines through open walkable space (skeleton thinning)

Confidence is deliberately conservative: every detection records how strongly
the evidence supported it so the report can flag objects for human review.
"""
from __future__ import annotations

import importlib.util
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from ...models import Detection, DetectionGeometry, DetectionKind, GeometryType, Point2D
from .base import BlueprintPerceptionProvider

_MERGE_ANGLE_DEG = 3.0
_MERGE_RHO_PX = 6.0


def _cv2():
    return importlib.util.find_spec("cv2")


def _pt(p: np.ndarray) -> Point2D:
    return Point2D(x=round(float(p[0]), 2), y=round(float(p[1]), 2))


class CVPerceptionProvider(BlueprintPerceptionProvider):
    id = "cv"
    name = "OpenCV deterministic geometry"

    def __init__(self):
        self._failures: List[str] = []

    def available(self) -> bool:
        return _cv2() is not None

    def detect(self, image: Image.Image) -> List[Detection]:
        import cv2

        rgb = np.asarray(image.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        H, W = gray.shape
        long_edge = max(W, H)

        ink = _binarize(gray)

        detections: List[Detection] = []
        seq = [0]

        footprint = _footprint_bbox(ink)
        if footprint is not None:
            x0, y0, x1, y1 = footprint
            boundaries = _boundary_regions(ink, footprint)
            for i, poly in enumerate(boundaries):
                detections.append(
                    _det(
                        f"BND{i + 1}", DetectionKind.BOUNDARY,
                        DetectionGeometry(type=GeometryType.POLYGON, polygon=poly,
                                          bbox=(x0, y0, x1, y1)),
                        conf=0.7, source="CV", metadata={"role": "footprint"},
                    )
                )

            regions = _region_holes(ink, footprint)
            for i, r in enumerate(regions):
                seq[0] += 1
                detections.append(
                    _det(
                        f"RGN{seq[0]}", DetectionKind.REGION,
                        DetectionGeometry(type=GeometryType.POLYGON, polygon=r["polygon"],
                                          bbox=r["bbox"]),
                        conf=r["confidence"], source="CV",
                        metadata={"area_px": r["area"]},
                    )
                )

        # walls (Hough + merge) — strictly interior segments
        walls = _wall_segments(gray, ink, footprint, long_edge)
        for i, (p0, p1, conf) in enumerate(walls):
            seq[0] += 1
            xa, ya, xb, yb = p0[0], p0[1], p1[0], p1[1]
            detections.append(
                _det(
                    f"WALL{seq[0]}", DetectionKind.WALL,
                    DetectionGeometry(type=GeometryType.SEGMENT, p0=_pt(p0), p1=_pt(p1),
                                      bbox=(min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))),
                    conf=conf, source="CV",
                )
            )

        # openings along the perimeter
        if footprint is not None:
            for side, (cx, cy), width, conf in _perimeter_gaps(ink, footprint):
                seq[0] += 1
                detections.append(
                    _det(
                        f"GATE{seq[0]}", DetectionKind.GATE,
                        DetectionGeometry(type=GeometryType.POINT, point=_pt((cx, cy)),
                                          bbox=(cx - width / 2, cy - width / 2, cx + width / 2, cy + width / 2)),
                        conf=conf, source="CV", metadata={"side": side, "width_px": width},
                    )
                )

        # doors inside near-axis-aligned wall segments
        for i, (p0, p1, conf) in enumerate(walls):
            ang = abs(float(np.degrees(np.arctan2(abs(p1[1] - p0[1]), abs(p1[0] - p0[0])))))
            if min(ang, 90.0 - ang) > 8.0:
                continue
            gap = _wall_gap(ink, p0, p1, min_len=10)
            if gap is not None:
                (gx, gy), gw = gap
                seq[0] += 1
                detections.append(
                    _det(
                        f"DOOR{seq[0]}", DetectionKind.DOOR,
                        DetectionGeometry(type=GeometryType.POINT, point=_pt((gx, gy)),
                                          bbox=(gx - gw / 2, gy - gw / 2, gx + gw / 2, gy + gw / 2)),
                        conf=min(0.6, 0.4 + 0.2 * conf), source="CV",
                        metadata={"width_px": gw},
                    )
                )

        # stairs / hatching
        for i, (poly, bbox, conf) in enumerate(_hatching_regions(gray, ink, footprint, long_edge)):
            seq[0] += 1
            detections.append(
                _det(
                    f"STAIR{seq[0]}", DetectionKind.STAIR,
                    DetectionGeometry(type=GeometryType.POLYGON, polygon=poly, bbox=bbox),
                    conf=conf, source="CV", metadata={"hatch_lines": True},
                )
            )

        # corridors from the walkable skeleton
        if footprint is not None:
            for i, (polyline, conf) in enumerate(_corridor_polylines(ink, footprint, long_edge)):
                seq[0] += 1
                detections.append(
                    _det(
                        f"CORR{seq[0]}", DetectionKind.CORRIDOR,
                        DetectionGeometry(type=GeometryType.POLYLINE, polyline=polyline,
                                          bbox=_polyline_bbox(polyline)),
                        conf=conf, source="CV",
                    )
                )

        return detections


# --------------------------------------------------------------------------- #
#  binarisation + footprint
# --------------------------------------------------------------------------- #
def _binarize(gray: np.ndarray) -> np.ndarray:
    import cv2

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    ink = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15
    )
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return ink


def _footprint_bbox(ink: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box of the largest connected ink component (the building).

    Text labels and hatching are usually separate components; using only the
    largest keeps the perimeter strips free of label noise.
    """
    import cv2

    nlabels, _, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), connectivity=8)
    if nlabels < 2:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    idx = int(np.argmax(areas)) + 1
    if areas[idx - 1] < 100:
        return None
    x = int(stats[idx, cv2.CC_STAT_LEFT])
    y = int(stats[idx, cv2.CC_STAT_TOP])
    w = int(stats[idx, cv2.CC_STAT_WIDTH])
    h = int(stats[idx, cv2.CC_STAT_HEIGHT])
    return (x, y, x + w - 1, y + h - 1)


# --------------------------------------------------------------------------- #
#  boundaries + enclosed regions (contour topology)
# --------------------------------------------------------------------------- #
def _boundary_regions(ink: np.ndarray, footprint: Tuple[int, int, int, int]) -> List[List[Point2D]]:
    """Outermost external contours -> BOUNDARY polygons (building outlines)."""
    import cv2

    x0, y0, x1, y1 = footprint
    bw, bh = x1 - x0, y1 - y0
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]
    polys: List[List[Point2D]] = []
    for i, cnt in enumerate(contours):
        if hierarchy[i][3] != -1:  # parent exists -> hole or island, not outer boundary
            continue
        area = abs(cv2.contourArea(cnt))
        if area < 0.02 * bw * bh:
            continue
        poly = _approx_polygon(cnt)
        if len(poly) >= 3:
            polys.append(poly)
    polys.sort(key=lambda p: _polygon_area_px(p), reverse=True)
    return polys


def _region_holes(ink: np.ndarray, footprint: Tuple[int, int, int, int]) -> List[dict]:
    """Enclosed spaces = holes in the wall topology (children of external contours)."""
    import cv2

    x0, y0, x1, y1 = footprint
    bw, bh = x1 - x0, y1 - y0
    min_area = 0.003 * bw * bh
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]
    regions: List[dict] = []
    for i, cnt in enumerate(contours):
        if hierarchy[i][2] != -1:  # has children -> outer contour, not a hole
            continue
        if hierarchy[i][3] == -1:  # no parent -> outer boundary, not enclosed
            continue
        area = abs(cv2.contourArea(cnt))
        if area < min_area:
            continue
        poly = _approx_polygon(cnt)
        if len(poly) < 3:
            continue
        bbox = (int(cnt[:, 0, 0].min()), int(cnt[:, 0, 1].min()),
                int(cnt[:, 0, 0].max()), int(cnt[:, 0, 1].max()))
        fill = _region_fill(ink, cnt, bbox)
        regions.append({
            "polygon": poly,
            "bbox": bbox,
            "area": round(area, 1),
            "confidence": round(0.45 + 0.35 * min(1.0, area / (0.12 * bw * bh)) + 0.1 * fill, 2),
        })
    regions.sort(key=lambda r: r["area"], reverse=True)
    return regions


def _region_fill(ink: np.ndarray, contour, bbox: Tuple[int, int, int, int]) -> float:
    """Fraction of the region bbox that is dark ink (walls/hatching inside)."""
    import cv2

    x0, y0, x1, y1 = bbox
    crop = ink[y0:y1 + 1, x0:x1 + 1]
    if crop.size == 0:
        return 0.0
    return float((crop > 0).mean())


def _approx_polygon(contour) -> List[Point2D]:
    import cv2

    peri = cv2.arcLength(contour, True)
    eps = max(2.0, 0.02 * peri)
    approx = cv2.approxPolyDP(contour, eps, True)
    return [_pt(p[0]) for p in approx]


# --------------------------------------------------------------------------- #
#  walls (Hough + collinear merge)
# --------------------------------------------------------------------------- #
def _wall_segments(
    gray: np.ndarray,
    ink: np.ndarray,
    footprint: Optional[Tuple[int, int, int, int]],
    long_edge: int,
) -> List[Tuple[Tuple[float, float], Tuple[float, float], float]]:
    import cv2

    if footprint is None:
        return []
    x0, y0, x1, y1 = footprint
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    min_len = max(20, int(0.04 * long_edge))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50, minLineLength=min_len, maxLineGap=8)
    raw: List[Tuple[np.ndarray, np.ndarray]] = []
    if lines is not None:
        for seg in lines.reshape(-1, 4):
            xa, ya, xb, yb = [int(v) for v in seg]
            a = np.array([float(xa), float(ya)])
            b = np.array([float(xb), float(yb)])
            # strictly interior walls only (skip segments touching the footprint edge)
            if min(xa, xb) <= x0 + 8 or max(xa, xb) >= x1 - 8:
                continue
            if min(ya, yb) <= y0 + 8 or max(ya, yb) >= y1 - 8:
                continue
            length = float(np.hypot(b[0] - a[0], b[1] - a[1]))
            if length < min_len:
                continue
            # keep near-axis-aligned walls; diagonal walls only when dominant
            ang = abs(float(np.degrees(np.arctan2(abs(b[1] - a[1]), abs(b[0] - a[0])))))
            axis = min(ang, 90.0 - ang)
            if axis > 12.0 and length < 0.12 * long_edge:
                continue
            raw.append((a, b))

    merged = _merge_collinear(raw, long_edge)
    out: List[Tuple[Tuple[float, float], Tuple[float, float], float]] = []
    for a, b, strength in merged:
        length = np.hypot(b[0] - a[0], b[1] - a[1])
        if length < min_len:
            continue
        confidence = round(min(0.9, 0.45 + 0.4 * strength), 2)
        out.append(((float(a[0]), float(a[1])), (float(b[0]), float(b[1])), confidence))
    return out


def _merge_collinear(
    segs: List[Tuple[np.ndarray, np.ndarray]], long_edge: int
) -> List[Tuple[np.ndarray, np.ndarray, float]]:
    """Cluster near-parallel segments and join overlapping collinear ones."""
    clusters: List[Tuple[float, float, List[Tuple[np.ndarray, np.ndarray]]]] = []

    def line_rho_theta(a: np.ndarray, b: np.ndarray) -> Tuple[float, float]:
        dx, dy = b[0] - a[0], b[1] - a[1]
        theta = float(np.arctan2(dy, dx) * 180 / np.pi) % 180.0
        theta = min(theta, 180.0 - theta) if theta > 90.0 else theta
        # scalar z of the 2D cross product (v = a - b, rho = cross(v, a) / |v|)
        vx, vy = a[0] - b[0], a[1] - b[1]
        rho = float(vx * a[1] - vy * a[0]) / (np.hypot(dx, dy) or 1.0)
        return rho, theta

    for a, b in segs:
        rho, theta = line_rho_theta(a, b)
        placed = False
        for cl in clusters:
            if abs(cl[0] - rho) <= _MERGE_RHO_PX and abs(cl[1] - theta) <= _MERGE_ANGLE_DEG:
                cl[2].append((a, b))
                placed = True
                break
        if not placed:
            clusters.append([rho, theta, [(a, b)]])

    results: List[Tuple[np.ndarray, np.ndarray, float]] = []
    for rho, theta, members in clusters:
        if not members:
            continue
        theta_rad = theta * np.pi / 180.0
        u = np.array([np.cos(theta_rad), np.sin(theta_rad)])  # along line
        n = np.array([-np.sin(theta_rad), np.cos(theta_rad)])  # perpendicular
        projs = []
        for a, b in members:
            for p in (a, b):
                projs.append(float(np.dot(p, u)))
            projs.append(float(np.dot(a, u)))
            projs.append(float(np.dot(b, u)))
        p0 = min(projs)
        p1 = max(projs)
        anchor = members[0][0]
        origin = anchor + u * (p0 - float(np.dot(anchor, u)))
        end = anchor + u * (p1 - float(np.dot(anchor, u)))
        strength = min(1.0, len(members) / 6.0)
        results.append((origin, end, strength))
    return results


# --------------------------------------------------------------------------- #
#  openings: perimeter gaps + door gaps in walls
# --------------------------------------------------------------------------- #
def _perimeter_gaps(
    ink: np.ndarray, footprint: Tuple[int, int, int, int]
) -> List[Tuple[str, Tuple[float, float], int, float]]:
    """Light gaps along the four footprint sides -> (side, center, width_px, conf)."""
    x0, y0, x1, y1 = footprint
    strip = 3
    out: List[Tuple[str, Tuple[float, float], int, float]] = []
    sides = [
        ("N", ink[y0:y0 + strip, x0:x1 + 1]),
        ("S", ink[y1 - strip + 1:y1 + 1, x0:x1 + 1]),
        ("W", ink[y0:y1 + 1, x0:x0 + strip]),
        ("E", ink[y0:y1 + 1, x1 - strip + 1:x1 + 1]),
    ]
    for side, seg in sides:
        if side in ("N", "S"):
            density = (seg > 0).sum(axis=0)
            denom = max(1, seg.shape[0])
            gap = density / denom < 0.5
            runs = _light_runs(gap, 6)
            for a, b in runs:
                cx = (a + b) / 2
                w = b - a + 1
                conf = min(0.85, 0.5 + 0.02 * w)
                out.append((side, (x0 + cx, y0 if side == "N" else y1), int(w), round(conf, 2)))
        else:
            density = (seg > 0).sum(axis=1)
            denom = max(1, seg.shape[1])
            gap = density / denom < 0.5
            runs = _light_runs(gap, 6)
            for a, b in runs:
                cy = (a + b) / 2
                w = b - a + 1
                conf = min(0.85, 0.5 + 0.02 * w)
                out.append((side, (x0 if side == "W" else x1, y0 + cy), int(w), round(conf, 2)))

    if not out:
        # solid wall with no readable gaps: default to the mid-point of each
        # side so downstream semantic typing still produces a valid entry/exit
        # set (mirrors the legacy heuristic defaults)
        mid_x = (x0 + x1) / 2
        mid_y = (y0 + y1) / 2
        return [
            ("N", (mid_x, y0), 18, 0.45),
            ("S", (mid_x, y1), 18, 0.45),
            ("W", (x0, mid_y), 18, 0.45),
            ("E", (x1, mid_y), 18, 0.45),
        ]
    return out


def _light_runs(mask: np.ndarray, min_len: int) -> List[Tuple[int, int]]:
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


def _wall_gap(
    ink: np.ndarray, p0: Tuple[float, float], p1: Tuple[float, float], min_len: int = 10
) -> Optional[Tuple[Tuple[float, float], int]]:
    """Find a light gap along a wall segment; None when the wall is solid."""
    import cv2

    p0a = np.array(p0, dtype=np.float32)
    p1a = np.array(p1, dtype=np.float32)
    length = float(np.hypot(p1a[0] - p0a[0], p1a[1] - p0a[1]))
    if length < min_len * 3:
        return None
    n = max(2, int(length))
    ts = np.linspace(0.0, 1.0, n)
    pts = (p0a[None, :] + ts[:, None] * (p1a - p0a)).astype(np.int32)
    h, w = ink.shape
    pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
    pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)
    profile = ink[pts[:, 1], pts[:, 0]] > 0
    dark = np.flatnonzero(profile)
    if len(dark) < max(2, n // 4):
        return None
    # gap = a light run bounded by dark on both sides
    start: Optional[int] = None
    for i in range(n):
        dark_pix = profile[i]
        if not dark_pix and start is None:
            start = i
        elif dark_pix and start is not None:
            if i - start >= min_len:
                prev_dark = start > 0
                next_dark = i < n
                if prev_dark and next_dark:
                    mid = pts[(start + i) // 2]
                    return ((float(mid[0]), float(mid[1])), i - start)
            start = None
    return None


# --------------------------------------------------------------------------- #
#  stairs: parallel-line hatching clusters
# --------------------------------------------------------------------------- #
def _hatching_regions(
    gray: np.ndarray,
    ink: np.ndarray,
    footprint: Optional[Tuple[int, int, int, int]],
    long_edge: int,
) -> List[Tuple[List[Point2D], Tuple[float, float, float, float], float]]:
    import cv2

    if footprint is None:
        return []
    x0, y0, x1, y1 = footprint
    bw, bh = x1 - x0, y1 - y0
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 40, 130)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=30, minLineLength=8, maxLineGap=3)

    angles: List[Tuple[float, Tuple[int, int, int, int]]] = []
    if lines is not None:
        for seg in lines.reshape(-1, 4):
            xa, ya, xb, yb = [int(v) for v in seg]
            dx, dy = xb - xa, yb - ya
            if dx == 0 and dy == 0:
                continue
            ang = float(np.degrees(np.arctan2(dy, dx)) % 180.0)
            if abs(dx) < 2 or abs(dy) < 2:
                continue  # skip axis-perfect pixels; keep diagonal hatch
            angles.append((ang, (int(min(xa, xb)), int(min(ya, yb)), int(max(xa, xb)), int(max(ya, yb)))))

    # group by quantised orientation
    buckets: dict[float, List[Tuple[int, int, int, int]]] = {}
    for ang, box in angles:
        key = round(ang / 10.0) * 10.0
        buckets.setdefault(key, []).append(box)

    out: List[Tuple[List[Point2D], Tuple[float, float, float, float], float]] = []
    seen: List[Tuple[int, int, int, int]] = []
    for key, boxes in buckets.items():
        if len(boxes) < 4:
            continue
        xs0 = [b[0] for b in boxes] + [b[2] for b in boxes]
        ys0 = [b[1] for b in boxes] + [b[3] for b in boxes]
        bbox = (min(xs0), min(ys0), max(xs0), max(ys0))
        bx0, by0, bx1, by1 = bbox
        bw_box, bh_box = bx1 - bx0, by1 - by0
        if bw_box < 12 and bh_box < 12:
            continue
        if bw_box > 0.8 * bw or bh_box > 0.8 * bh:
            continue  # too spread out to be a single stair
        if any(abs(bx0 - s[0]) < 8 and abs(by0 - s[1]) < 8 and abs(bx1 - s[2]) < 8 and abs(by1 - s[3]) < 8 for s in seen):
            continue
        seen.append(bbox)
        poly = [
            _pt(np.array([bx0, by0])), _pt(np.array([bx1, by0])),
            _pt(np.array([bx1, by1])), _pt(np.array([bx0, by1])),
        ]
        conf = round(min(0.8, 0.42 + 0.05 * min(8, len(boxes))), 2)
        out.append((poly, bbox, conf))
    return out


# --------------------------------------------------------------------------- #
#  corridors: skeleton thinning of the walkable space
# --------------------------------------------------------------------------- #
def _corridor_polylines(
    ink: np.ndarray, footprint: Tuple[int, int, int, int], long_edge: int
) -> List[Tuple[List[Point2D], float]]:
    """Long open-space paths (walkable = not ink), extracted from the skeleton."""
    try:
        import cv2

        x0, y0, x1, y1 = footprint
        walkable = (ink <= 0).astype(np.uint8)
        # remove specks / text in the open area
        walkable = cv2.morphologyEx(walkable, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        skeleton = _thin(walkable)
        paths = _walk_skeleton(skeleton, x0, y0, x1, y1)
        out: List[Tuple[List[Point2D], float]] = []
        min_len = int(0.06 * long_edge)
        for pts in paths:
            if len(pts) < min_len:
                continue
            arr = np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2)
            approx = cv2.approxPolyDP(arr, 6.0, False)
            if approx is None or len(approx) < 2:
                continue
            polyline = [_pt(p[0]) for p in approx]
            if _polyline_len(polyline) < min_len * 0.6:
                continue
            out.append((polyline, 0.45))
        return out
    except Exception:
        return []


def _thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen skeletonisation (numpy), mask: 1 = foreground."""
    img = (mask > 0).astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for step in (1, 2):
            padded = np.pad(img, 1, mode="constant", constant_values=0)
            # neighbourhood: P9 P2 P3 / P8 P1 P4 / P7 P6 P5
            p2 = padded[1:-1, :-2]; p3 = padded[:-2, :-2]; p4 = padded[:-2, 1:-1]
            p5 = padded[:-2, 2:]; p6 = padded[1:-1, 2:]; p7 = padded[2:, 2:]
            p8 = padded[2:, 1:-1]; p9 = padded[2:, :-2]
            stacked = np.stack([p2, p3, p4, p5, p6, p7, p8, p9], axis=0).astype(np.uint8)
            b = stacked.sum(axis=0)
            a = ((stacked == 0) & (np.roll(stacked, -1, axis=0) == 1)).sum(axis=0)
            c = (img == 1)
            if step == 1:
                cond_c = (p2 * p4 * p6) == 0
                cond_d = (p4 * p6 * p8) == 0
            else:
                cond_c = (p2 * p4 * p8) == 0
                cond_d = (p2 * p6 * p8) == 0
            remove = c & (b >= 2) & (b <= 6) & (a == 1) & cond_c & cond_d
            if remove.any():
                img[remove] = 0
                changed = True
    return img


def _walk_skeleton(
    skeleton: np.ndarray, x0: int, y0: int, x1: int, y1: int
) -> List[List[Tuple[int, int]]]:
    """Trace skeleton pixel paths between endpoints / junction points."""
    from collections import deque

    kernel = np.ones((3, 3), np.uint8)
    ncount = cv2.filter2D(skeleton.astype(np.uint8), -1, kernel) - skeleton
    ys, xs = np.where(skeleton > 0)
    visited = set()
    paths: List[List[Tuple[int, int]]] = []

    def neighbors(px: int, py: int):
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = px + dx, py + dy
                if 0 <= nx < skeleton.shape[1] and 0 <= ny < skeleton.shape[0] and skeleton[ny, nx] > 0:
                    out.append((nx, ny))
        return out

    def trace(start: Tuple[int, int]) -> Optional[List[Tuple[int, int]]]:
        if start in visited:
            return None
        path = [start]
        visited.add(start)
        queue = deque([(start, [start])])
        # follow until we hit a junction / endpoint / visited
        while queue:
            (px, py), trail = queue.popleft()
            nb = [p for p in neighbors(px, py) if p not in visited]
            if not nb:
                # endpoint reached
                return _dedupe_trail(trail)
            if len(nb) > 1:
                # junction reached; keep trail but don't expand further here
                return _dedupe_trail(trail)
            (nx, ny) = nb[0]
            visited.add((nx, ny))
            queue.append(((nx, ny), trail + [(nx, ny)]))
        return None

    # start from endpoints
    ends = [(x, y) for (y, x) in zip(ys, xs) if ncount[y, x] == 1]
    for end in ends:
        p = trace(end)
        if p and len(p) >= 8:
            paths.append(p)
    # also capture loops between junctions (no free endpoints)
    for (y, x) in zip(ys, xs):
        if skeleton[y, x] > 0 and ncount[y, x] >= 3:
            for nb in neighbors(x, y):
                p = trace(nb)
                if p and len(p) >= 8:
                    paths.append(p)
    return paths


def _dedupe_trail(trail: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for pt in trail:
        if out and abs(pt[0] - out[-1][0]) <= 1 and abs(pt[1] - out[-1][1]) <= 1:
            continue
        out.append(pt)
    return out


# --------------------------------------------------------------------------- #
#  small geometry helpers
# --------------------------------------------------------------------------- #
def _det(
    det_id: str, kind: DetectionKind, geometry: DetectionGeometry, conf: float,
    source: str = "CV", metadata: Optional[dict] = None,
) -> Detection:
    return Detection(
        id=det_id, kind=kind, geometry=geometry, confidence=max(0.05, min(1.0, conf)),
        source=source, metadata=metadata or {},
    )


def _polygon_area_px(poly: List[Point2D]) -> float:
    n = len(poly)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += poly[i].x * poly[j].y - poly[j].x * poly[i].y
    return abs(area) / 2.0


def _polyline_len(polyline: List[Point2D]) -> float:
    return sum(np.hypot(polyline[i].x - polyline[i - 1].x, polyline[i].y - polyline[i - 1].y)
               for i in range(1, len(polyline)))


def _polyline_bbox(polyline: List[Point2D]) -> Tuple[float, float, float, float]:
    xs = [p.x for p in polyline]
    ys = [p.y for p in polyline]
    return (min(xs), min(ys), max(xs), max(ys))
