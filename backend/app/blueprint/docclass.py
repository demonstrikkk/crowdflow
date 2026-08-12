"""Source-document type classification (Phase 2C item 1).

The pipeline used to assume every upload is a clean top-down orthographic floor
plan. That assumption breaks on perspective architectural illustrations (e.g. a
stadium bowl render) whose pixel coordinates are NOT a floor plan. This module
classifies the projection deterministically (OpenCV heuristics, no model):

  * axis alignment of dominant line work  - plans are wall-dominated 0/90 deg
  * vanishing-point convergence           - perspective wireframes converge
  * filled / shaded ink area               - illustrations shade; plans are lines
  * stacked long horizontal separators    - multi-level sheets / elevations

The result is advisory + recorded: the reconstruction pipeline must not treat a
PERSPECTIVE / ELEVATION / UNKNOWN source as an orthographic plan.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from ..models import DocumentType

_IMG_BOX = 0.05  # convergence point must lie within [box, 1-box] of the frame


def _lines(edges: np.ndarray) -> np.ndarray:
    import cv2

    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0, threshold=70, minLineLength=40, maxLineGap=8
    )
    if lines is None or len(lines) == 0:
        return np.empty((0, 4), dtype=np.float64)
    segs = lines[:, 0].astype(np.float64)
    # keep the dominant, longer segments (perspective wireframes are noisy)
    lens = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    if len(segs) > 500:
        idx = np.argsort(lens)[::-1][:500]
        segs = segs[idx]
    return segs


def _axis_aligned_fraction(segs: np.ndarray) -> float:
    if len(segs) == 0:
        return 0.0
    ang = np.abs(np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0])))
    dev = np.minimum(ang % 90.0, 90.0 - (ang % 90.0))
    return float(np.mean(dev <= 6.0))


def _long_horizontal_fraction(segs: np.ndarray, width: float) -> float:
    """Share of segments that are near-horizontal and span > half the frame."""
    if len(segs) == 0:
        return 0.0
    dy = np.abs(segs[:, 3] - segs[:, 1])
    lens = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    mask = (dy <= 2.0) & (lens > width * 0.5)
    return float(np.mean(mask))


def _vanishing_point_score(segs: np.ndarray, w: int, h: int) -> float:
    """Fraction of large line-orientation clusters that converge inside the frame.

    Purely parallel sets (orthographic) give intersections far outside the image
    and are treated as non-converging.
    """
    if len(segs) < 40:
        return 0.0
    ang = np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0]))
    bucket = (np.round(ang / 10.0) * 10.0) % 180.0
    clusters: dict = {}
    for i, b in enumerate(bucket):
        clusters.setdefault(b, []).append(segs[i])

    def inter(a, b) -> Tuple[float, float]:
        x1, y1, x2, y2 = a
        x3, y3, x4, y4 = b
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-6:
            return (math.inf, math.inf)
        px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / d
        py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / d
        return px, py

    converging = 0
    large = 0
    diag = math.hypot(w, h)
    for b, segs_b in clusters.items():
        if len(segs_b) < 8:
            continue
        large += 1
        sample = segs_b[: min(24, len(segs_b))]
        pts = []
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                px, py = inter(sample[i], sample[j])
                if math.isfinite(px) and math.isfinite(py):
                    pts.append((px, py))
        if not pts:
            continue
        med = (np.median([p[0] for p in pts]), np.median([p[1] for p in pts]))
        # a genuine vanishing point sits inside/near the frame; parallel sets land
        # far outside (median beyond ~2 diagonals from the image centre)
        cx, cy = w / 2.0, h / 2.0
        if math.hypot(med[0] - cx, med[1] - cy) < 2.0 * diag:
            bx0, by0, bx1, by1 = w * _IMG_BOX, h * _IMG_BOX, w * (1 - _IMG_BOX), h * (1 - _IMG_BOX)
            if bx0 <= med[0] <= bx1 and by0 <= med[1] <= by1:
                converging += 1
    return converging / max(1, large)


def _filled_ink_fraction(ink: np.ndarray) -> float:
    """Area inside large solid ink blobs (shading/fill) vs thin line work."""
    import cv2

    n, labels, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), 8)
    total = float(ink.shape[0] * ink.shape[1])
    filled = 0.0
    for i in range(1, n):
        area = float(stats[i, cv2.CC_STAT_AREA])
        if area < total * 0.003:
            continue
        w = max(1, stats[i, cv2.CC_STAT_WIDTH])
        h = max(1, stats[i, cv2.CC_STAT_HEIGHT])
        if area / (w * h) > 0.55 and w > 20 and h > 20:
            filled += area
    return filled / total


def _ink_compactness(ink: np.ndarray) -> float:
    """Shape descriptor of the largest ink component's convex hull (0..1).

    4*pi*A/P^2 == 1 for a circle, ~0.785 for a square. Used to detect an oval
    vs rectangular source footprint for the correspondence check.
    """
    import cv2

    n, labels, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), 8)
    if n <= 1:
        return 0.0
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    comp = (labels == big).astype(np.uint8)
    pts = np.column_stack(np.where(comp > 0))[:, ::-1]
    hull = cv2.convexHull(pts)
    area = cv2.contourArea(hull)
    peri = cv2.arcLength(hull, True)
    if peri <= 0:
        return 0.0
    return float(min(1.0, (4.0 * math.pi * area) / (peri * peri)))


def classify(image) -> "DocumentTypeResult":
    """Classify the projection of a preprocessed blueprint raster."""
    import cv2

    gray = np.asarray(image.convert("L"))
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = (ink > 0)
    h, w = gray.shape
    edges = cv2.Canny(gray, 50, 150)
    segs = _lines(edges)

    reasons: List[str] = []
    if len(segs) < 8:
        reasons.append("insufficient line work to classify")
        return DocumentTypeResult(DocumentType.UNKNOWN, 0.2, reasons)

    axis = _axis_aligned_fraction(segs)
    vp = _vanishing_point_score(segs, w, h)
    filled = _filled_ink_fraction(ink)
    long_h = _long_horizontal_fraction(segs, w)
    ink_frac = float(ink.mean())
    aspect = h / w if h >= w else w / h

    reasons.append(f"axis-aligned line share {axis:.2f}")
    reasons.append(f"vanishing-point convergence {vp:.2f}")
    reasons.append(f"filled ink {filled:.3f} (total ink {ink_frac:.3f})")
    if long_h >= 0.15:
        reasons.append(f"stacked long horizontal separators {long_h:.2f}")

    # --- decision tree --------------------------------------------------- #
    if vp >= 0.35 and axis < 0.55 and filled >= 0.04:
        return DocumentTypeResult(
            DocumentType.PERSPECTIVE_ARCHITECTURAL_DRAWING, 0.75,
            reasons + ["line families converge inside the frame + shaded fill"],
        )
    if long_h >= 0.30 and axis >= 0.55 and len(segs) >= 40:
        # repeated wide horizontal separators + wall-aligned plan = multi-level sheet
        return DocumentTypeResult(
            DocumentType.MULTI_LEVEL_PLAN, 0.7,
            reasons + ["repeated floor separators over wall-aligned line work"],
        )
    if axis >= 0.62 and vp < 0.25:
        return DocumentTypeResult(
            DocumentType.ORTHOGRAPHIC_PLAN, 0.65,
            reasons + ["line work is wall-axis aligned with no in-frame convergence"],
        )
    if long_h >= 0.25 and aspect >= 1.25:
        return DocumentTypeResult(
            DocumentType.ELEVATION, 0.55,
            reasons + ["tall/asymmetric massing with horizontal separators"],
        )
    return DocumentTypeResult(
        DocumentType.UNKNOWN, 0.35,
        reasons + ["signals are mixed; do not treat as an orthographic plan"],
    )


class DocumentTypeResult:
    def __init__(self, document_type: DocumentType, confidence: float, reasons: List[str]):
        self.document_type = document_type
        self.confidence = confidence
        self.reasons = reasons
