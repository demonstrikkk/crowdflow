"""Seating bowl builder (Phase 6).

Generates stepped tier structures from SeatingBowlProfile.
Each tier is a StructureModel with:
  - type="SEATING"
  - polygon = the outer boundary of that tier level
  - height_m = tier top elevation

The bowl is stepped: each tier polygon is slightly smaller than the previous,
and sits at a higher elevation.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ...models import Point2D, Polygon2D, StructureModel
from .profile import SeatingBowlProfile, SeatingTierProfile, StadiumProfile


def build_bowl(bowl: SeatingBowlProfile, profile: StadiumProfile) -> List[StructureModel]:
    """Build all tier structures for one seating bowl."""
    structures = []
    for tier in bowl.tiers:
        structures.extend(_build_tier(tier, bowl.id, profile))
    return structures


def _build_tier(
    tier: SeatingTierProfile,
    bowl_id: str,
    profile: StadiumProfile,
) -> List[StructureModel]:
    """Build the stepped tier polygons for a single tier."""
    results = []
    outer = tier.outer_boundary
    inner = tier.inner_boundary

    if len(outer) < 3 or len(inner) < 3:
        return results

    # The tier has row_count stepped rows from inner to outer
    # For geometry purposes, we emit a single solid tier polygon
    # (the frontend renders rows via instanced mesh, not individual geometry)
    tier_poly = _make_ring_polygon(inner, outer)
    if tier_poly:
        results.append(StructureModel(
            id=f"{bowl_id}_{tier.id}",
            level_id=tier.level_id,
            type="SEATING",
            polygon=tier_poly,
            height_m=round(tier.top_elevation_m - tier.floor_elevation_m, 2),
            metadata={
                "source": tier.provenance.source.value,
                "source_entity_id": tier.provenance.source_entity_id,
                "confidence": round(tier.provenance.confidence, 3),
                "floor_elevation_m": tier.floor_elevation_m,
                "top_elevation_m": tier.top_elevation_m,
                "row_count": tier.row_count,
                "seat_depth_m": tier.seat_depth_m,
                "aisle_spacing_rows": tier.aisle_spacing_rows,
                "curvature": tier.curvature,
                "tiers": tier.row_count,
                "kind": "SEATING",
                "label": tier.name,
            },
        ))
    return results


def _make_ring_polygon(
    inner: List[Tuple[float, float]],
    outer: List[Tuple[float, float]],
) -> Polygon2D | None:
    """Create a polygon representing the ring between inner and outer boundaries.

    Strategy: use the outer boundary directly as the seating area polygon.
    The inner boundary is stored in metadata for the 3D renderer.
    We return a simple outer polygon here; the renderer handles the stepped bowl.
    """
    if len(outer) < 3:
        return None
    try:
        return Polygon2D(points=[Point2D(x=round(p[0], 2), y=round(p[1], 2)) for p in outer])
    except Exception:
        return None


def generate_seat_rows(
    tier: SeatingTierProfile,
) -> List[dict]:
    """Generate row-level metadata for instanced rendering.

    Returns a list of row descriptors (not geometry), each containing:
      - row_index
      - elevation_m
      - inner_radius_m (approximate)
      - outer_radius_m (approximate)
      - polygon (simplified arc)

    This metadata is embedded in the StructureModel metadata and consumed
    by the 3D frontend's InstancedMesh renderer.
    """
    rows = []
    n = tier.row_count
    if n <= 0:
        return rows

    outer = tier.outer_boundary
    inner = tier.inner_boundary
    if not outer or not inner:
        return rows

    # Compute bounding-box radii from center
    center = (
        sum(p[0] for p in outer) / len(outer),
        sum(p[1] for p in outer) / len(outer),
    )
    outer_r = max(math.hypot(p[0] - center[0], p[1] - center[1]) for p in outer)
    inner_r = max(math.hypot(p[0] - center[0], p[1] - center[1]) for p in inner)

    row_depth = (outer_r - inner_r) / max(1, n)
    elev_step = (tier.top_elevation_m - tier.floor_elevation_m) / max(1, n)

    for i in range(n):
        r_inner = inner_r + i * row_depth
        r_outer = r_inner + row_depth
        elev = tier.floor_elevation_m + i * elev_step
        rows.append({
            "row_index": i,
            "elevation_m": round(elev, 2),
            "inner_radius_m": round(r_inner, 2),
            "outer_radius_m": round(r_outer, 2),
        })
    return rows
