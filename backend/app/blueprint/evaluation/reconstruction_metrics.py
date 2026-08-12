"""Reconstruction quality metrics (Phase 10).

Calculates metrics comparing the reconstructed spatial model against
what can be inferred from the source architectural scene.
If ground truth is unavailable, reports 'not_available'.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple

from ...models import VenueSpatialModel


NA = "not_available"


def _polygon_area(pts: List[Tuple[float, float]]) -> float:
    """Shoelace formula."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


def _centroid(pts: List[Tuple[float, float]]) -> Tuple[float, float]:
    if not pts:
        return (0.0, 0.0)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def compute_metrics(
    spatial: "VenueSpatialModel",
    profile: Optional[Any] = None,
    ground_truth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute all available reconstruction quality metrics.

    Args:
        spatial: The reconstructed VenueSpatialModel.
        profile: The StadiumProfile used for generation (optional).
        ground_truth: Ground truth dict (optional). If None, structural metrics only.

    Returns:
        Dict with metric names and values (or NA string if unavailable).
    """
    metrics: Dict[str, Any] = {}

    # Structural metrics (always available)
    metrics["structure_count"] = len(spatial.structures)
    metrics["opening_count"] = len(spatial.openings)
    metrics["path_count"] = len(spatial.paths)
    metrics["level_count"] = len(spatial.levels)

    has_field = any(s.type == "FIELD" for s in spatial.structures)
    has_seating = any(s.type == "SEATING" for s in spatial.structures)
    has_concourse = any(s.type == "CONCOURSE" for s in spatial.structures)
    has_emergency = any(o.opening_type == "EMERGENCY_EXIT" for o in spatial.openings)

    metrics["has_field"] = has_field
    metrics["has_seating"] = has_seating
    metrics["has_concourse"] = has_concourse
    metrics["has_emergency_exits"] = has_emergency
    metrics["gate_count"] = len([o for o in spatial.openings if o.opening_type in ("ENTRY_GATE", "EXIT_GATE")])

    # Path connectivity
    if spatial.paths:
        path_ids = {p.id for p in spatial.paths}
        edge_ids = set()  # Would need VenueModel for edges; structural check only
        metrics["path_connectivity"] = "structural_only"
    else:
        metrics["path_connectivity"] = NA

    # Level consistency
    level_ids = {lv.id for lv in spatial.levels}
    struct_levels = {s.level_id for s in spatial.structures}
    orphan_level_refs = struct_levels - level_ids
    metrics["level_consistency"] = len(orphan_level_refs) == 0
    if orphan_level_refs:
        metrics["orphan_level_refs"] = list(orphan_level_refs)

    # Profile-derived metrics
    if profile is not None:
        metrics["footprint_shape"] = profile.footprint_shape.value
        metrics["seating_bowl_count"] = len(profile.seating_bowls)
        metrics["concourse_count"] = len(profile.concourses)
        metrics["facility_count"] = len(profile.facilities)
        metrics["vertical_connection_count"] = len(profile.vertical_connections)

    # Ground truth comparison (optional)
    if ground_truth is not None:
        gt_field = ground_truth.get("field_polygon")
        if gt_field and has_field:
            metrics["field_alignment"] = "present"
        elif gt_field:
            metrics["field_alignment"] = "missing_in_reconstruction"
        else:
            metrics["field_alignment"] = NA

        gt_gates = ground_truth.get("gate_count")
        if gt_gates is not None:
            diff = abs(metrics["gate_count"] - gt_gates)
            metrics["gate_count_delta"] = diff
            metrics["gate_accuracy"] = max(0.0, 1.0 - diff / max(1, gt_gates))
        else:
            metrics["gate_count_delta"] = NA
            metrics["gate_accuracy"] = NA
    else:
        metrics["field_alignment"] = NA
        metrics["footprint_overlap"] = NA
        metrics["seating_overlap"] = NA
        metrics["gate_count_delta"] = NA
        metrics["gate_accuracy"] = NA

    # Overall score
    checks = [has_field, has_seating, has_concourse, has_emergency, len(spatial.openings) > 0]
    metrics["structural_score"] = round(sum(checks) / len(checks), 2)

    return metrics
