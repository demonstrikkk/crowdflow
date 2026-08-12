"""Reconstruction validation + confidence reporting.

Three layers, matching the phase's validation requirements:

  * geometry  - valid polygons, sane dimensions, in-bounds, no duplicate ids;
  * spatial   - openings align with the venue frame, paths stay in bounds,
                levels exist, stairs reference valid levels;
  * navigation- gate confidence flags (connectivity itself is enforced by the
                VenueModel validator / graph engine).

Validation never silently produces a broken venue: findings are returned as
warnings in the ``ReconstructionReport`` so the UI can surface uncertainty.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

from ..models import (
    BlueprintElement,
    BlueprintImageMeta,
    Canonical2DModel,
    Detection,
    DocumentType,
    ElementReport,
    PLAN_DOCUMENT_TYPES,
    ReconstructionQuality,
    ReconstructionReport,
    VenueModel,
    VenueSpatialModel,
)

_REVIEW_CONFIDENCE = 0.55


def _polygon_area(points: List[Tuple[float, float]]) -> float:
    n = len(points)
    area = sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
               for i in range(n))
    return abs(area) / 2.0


def _polygon_self_intersects(points: List[Tuple[float, float]]) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    def seg_intersect(a, b, c, d):
        return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)

    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            if seg_intersect(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                return True
    return False


def validate_spatial(spatial: VenueSpatialModel, width_m: float, height_m: float) -> List[str]:
    warnings: List[str] = []
    seen_ids: set = set()

    def dup_check(id_: str) -> None:
        if id_ in seen_ids:
            warnings.append(f"duplicate id '{id_}' in spatial model")
        seen_ids.add(id_)

    def in_bounds(x: float, y: float, what: str) -> None:
        tol = 2.0
        if x < -tol or x > width_m + tol or y < -tol or y > height_m + tol:
            warnings.append(f"{what} point ({x:.1f}, {y:.1f}) is outside the venue frame")

    for s in spatial.structures:
        dup_check(s.id)
        pts = [(p.x, p.y) for p in s.polygon.points]
        if len(pts) < 3:
            warnings.append(f"structure '{s.id}' has fewer than 3 polygon points")
            continue
        area = _polygon_area(pts)
        if area < 0.5:
            warnings.append(f"structure '{s.id}' has implausible area {area:.1f} m2")
        if _polygon_self_intersects(pts):
            warnings.append(f"structure '{s.id}' polygon self-intersects")
        for p in pts:
            in_bounds(p[0], p[1], f"structure '{s.id}'")

    for o in spatial.openings:
        dup_check(o.id)
        in_bounds(o.position.x, o.position.y, f"opening '{o.id}'")
        if o.width_m < 0.5:
            warnings.append(f"opening '{o.id}' width {o.width_m:.1f} m is implausible")

    for p in spatial.paths:
        dup_check(p.id)
        if len(p.centerline) < 2:
            warnings.append(f"path '{p.id}' has fewer than 2 centre-line points")
        for pt in p.centerline:
            in_bounds(pt.x, pt.y, f"path '{p.id}'")

    level_ids = {l.id for l in spatial.levels}
    for s in spatial.structures:
        if s.level_id not in level_ids:
            warnings.append(f"structure '{s.id}' references unknown level '{s.level_id}'")
    for o in spatial.openings:
        if o.level_id not in level_ids:
            warnings.append(f"opening '{o.id}' references unknown level '{o.level_id}'")

    # stairs: level relationship is retained when a to-level hint exists
    for s in spatial.structures:
        if s.type == "STAIR":
            to_level = (s.metadata or {}).get("to_level")
            if to_level and to_level not in level_ids:
                warnings.append(f"stair '{s.id}' points to undefined level '{to_level}'")
    return warnings


def validate_navigation(venue: VenueModel) -> List[str]:
    warnings: List[str] = []
    if not venue.nodes:
        warnings.append("venue has no nodes")
        return warnings
    gates = [n for n in venue.nodes if n.type in ("ENTRY", "EXIT", "EMERGENCY_EXIT")]
    if not gates:
        warnings.append("venue has no entry/exit nodes")
    return warnings


def _element_reports(spatial: VenueSpatialModel) -> List[ElementReport]:
    reports: List[ElementReport] = []
    for s in spatial.structures:
        conf = float((s.metadata or {}).get("confidence", 0.8))
        reports.append(_report(s.id, f"structure:{s.type}", conf, s.metadata, s.type))
    for o in spatial.openings:
        conf = float((o.metadata or {}).get("confidence", 0.8))
        reports.append(_report(o.id, f"opening:{o.type}", conf, o.metadata, o.type))
    for p in spatial.paths:
        conf = float((p.metadata or {}).get("confidence", 0.6))
        reports.append(_report(p.id, f"path", conf, p.metadata, "PATH"))
    return reports


def _report(id_: str, kind: str, conf: float, metadata: Dict, label_kind: str) -> ElementReport:
    warning = None
    if conf < 0.35:
        status = "REJECTED"
        warning = "confidence below acceptance floor"
    elif conf < _REVIEW_CONFIDENCE:
        status = "REVIEW"
        warning = "low confidence - verify this detection"
    else:
        status = "ACCEPTED"
    return ElementReport(
        id=id_, kind=f"{kind}:{label_kind}", confidence=round(conf, 2),
        source=str((metadata or {}).get("source", "GEOMETRY")), status=status, warning=warning,
    )


def build_report(
    spatial: Optional[VenueSpatialModel],
    venue: VenueModel,
    width_m: float,
    height_m: float,
    warnings: List[str],
    unresolved: List[str],
    detections: List[Detection],
    quality: Optional[ReconstructionQuality] = None,
) -> ReconstructionReport:
    all_warnings = list(warnings)
    if spatial is not None:
        all_warnings.extend(validate_spatial(spatial, width_m, height_m))
    all_warnings.extend(validate_navigation(venue))
    all_warnings = list(dict.fromkeys(all_warnings))

    elements: List[ElementReport] = []
    if spatial is not None:
        elements = _element_reports(spatial)

    confs = [e.confidence for e in elements]
    overall = round(sum(confs) / len(confs), 3) if confs else venue.id == "BLUEPRINT_VENUE" and 0.3 or 0.2
    if overall > 1.0:
        overall = 1.0

    # unresolved: text detections that never attached to a gate/region
    unresolved_ids = [u for u in unresolved if u]

    summary = (
        f"Reconstruction produced {len(spatial.structures) if spatial else 0} structures, "
        f"{len(spatial.openings) if spatial else 0} openings and "
        f"{len(spatial.paths) if spatial else 0} paths "
        f"with {len(all_warnings)} warning(s) and {len(unresolved_ids)} unresolved item(s)."
    )
    return ReconstructionReport(
        summary=summary,
        overall_confidence=overall,
        elements=elements,
        warnings=all_warnings,
        unresolved=unresolved_ids,
        quality=quality,
    )


def _rect_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _compactness(points: List[Tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    n = len(points)
    area = abs(sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
                   for i in range(n))) / 2.0
    peri = sum(((points[i][0] - points[(i + 1) % n][0]) ** 2 + (points[i][1] - points[(i + 1) % n][1]) ** 2) ** 0.5
               for i in range(n))
    return min(1.0, 4.0 * math.pi * area / (peri * peri)) if peri > 0 else 0.0


def _polygon_area_px(points: List[Tuple[float, float]]) -> float:
    return _polygon_area(points)


def build_quality(
    canonical2d: Canonical2DModel,
    sem_structures: List[dict],
    sem_gates: List[dict],
    sem_corridors: List[List[Tuple[float, float]]],
    sem_rejected: List[str],
    footprint_bbox: Optional[Tuple[float, float, float, float]],
    image_meta: BlueprintImageMeta,
    detections: List[Detection],
) -> ReconstructionQuality:
    """Compute the reconstruction quality gates (Phase 2C items 1 + 5).

    ``passed`` is the single bit the pipeline, UI and commit path must respect
    before a reconstruction may become the active venue or open a 3D Twin. A
    source that is not an orthographic floor plan fails hard; so do reconstructions
    with no credible openings or no footprint correspondence.
    """
    frame = (0.0, 0.0, float(image_meta.width_px), float(image_meta.height_px))
    frame_area = frame[2] * frame[3]

    reasons: List[str] = []
    doc_type = image_meta.document_type
    doc_conf = image_meta.document_type_confidence

    # --- correspondence metrics ---------------------------------------- #
    if footprint_bbox is not None:
        footprint_similarity = _rect_iou(footprint_bbox, frame)
        src_comp = _compactness([(footprint_bbox[0], footprint_bbox[1]),
                                 (footprint_bbox[2], footprint_bbox[1]),
                                 (footprint_bbox[2], footprint_bbox[3]),
                                 (footprint_bbox[0], footprint_bbox[3])])
        compactness_mismatch = abs(src_comp - canonical2d.footprint_compactness)
    else:
        footprint_similarity = 1.0  # preprocess already cropped to the source ink
        compactness_mismatch = 0.0

    region_area = sum(_polygon_area_px(s["polygon_px"]) for s in sem_structures
                      if len(s.get("polygon_px") or []) >= 3)
    region_coverage = min(1.0, region_area / max(1.0, frame_area))
    field_present = any(s.get("kind") in ("FIELD", "SEATING", "CONCOURSE", "ZONE")
                        for s in sem_structures)

    confirmed = len(sem_gates)
    rejected_gates = sum(1 for r in sem_rejected if r.startswith("GATE/"))
    total = confirmed + rejected_gates
    gate_recall = confirmed / total if total else 0.0
    on_perimeter = 0
    if footprint_bbox is not None:
        fx0, fy0, fx1, fy1 = footprint_bbox
        for g in sem_gates:
            x, y = g["position"]
            if min(abs(x - fx0), abs(fx1 - x), abs(y - fy0), abs(fy1 - y)) <= 12:
                on_perimeter += 1
    else:
        for g in sem_gates:
            x, y = g["position"]
            if min(x, frame[2] - x, y, frame[3] - y) <= 8:
                on_perimeter += 1
    gate_precision = (on_perimeter / confirmed) if confirmed else 0.0
    path_coverage = 1.0 if sem_corridors else 0.0

    scale_text = " ".join(d.text for d in detections if getattr(d, "text", None))
    scale_confidence = 1.0 if re.search(r"(?i)\b(scale|metre|meter)\b|1\s*[:/]\s*\d", scale_text) else 0.5
    uncertain_count = len(sem_rejected)

    # --- hard gates ---------------------------------------------------- #
    passed = True
    plan_known = doc_type in PLAN_DOCUMENT_TYPES
    unclassified = doc_type == DocumentType.UNKNOWN and doc_conf == 0.0
    if not plan_known and not unclassified:
        passed = False
        reasons.append(
            f"source is {doc_type.value}, not an orthographic floor plan; "
            f"a {doc_type.value.lower().replace('_', ' ')} cannot be reconstructed as a top-down venue"
        )
    elif unclassified:
        reasons.append("source projection not classified; treating as a floor plan")

    if passed and confirmed == 0:
        passed = False
        reasons.append("no credible openings - every gate candidate was rejected")
    elif passed and gate_recall < 0.5:
        passed = False
        reasons.append(f"gate recall {gate_recall:.0%} - too few openings are credible")
    if passed and footprint_similarity < 0.5:
        passed = False
        reasons.append("reconstructed footprint does not correspond to the source drawing")
    if passed and uncertain_count > 8:
        passed = False
        reasons.append(f"{uncertain_count} uncertain elements above the review threshold")
    if not passed:
        reasons.append("reconstruction blocked from becoming the active venue")

    return ReconstructionQuality(
        document_type=doc_type.value,
        footprint_similarity=round(max(0.0, min(1.0, footprint_similarity)), 3),
        compactness_mismatch=round(max(0.0, min(1.0, compactness_mismatch)), 3),
        field_present=field_present,
        region_coverage=round(region_coverage, 3),
        gate_precision=round(gate_precision, 3),
        gate_recall=round(gate_recall, 3),
        path_coverage=round(path_coverage, 3),
        scale_confidence=round(scale_confidence, 3),
        uncertain_count=uncertain_count,
        passed=passed,
        reasons=reasons,
    )
