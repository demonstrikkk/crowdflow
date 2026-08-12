"""Field, floor slab, and roof structure builders (Phase 6)."""
from __future__ import annotations
import math
from typing import List
from ...models import LevelModel, Point2D, Polygon2D, StructureModel
from .profile import StadiumProfile, RoofStrategy


def _polygon_from_tuples(pts: list) -> Polygon2D:
    return Polygon2D(points=[Point2D(x=round(x, 2), y=round(y, 2)) for x, y in pts])


def _ellipse_polygon(cx: float, cy: float, rx: float, ry: float, n: int = 32) -> list:
    """Generate an ellipse polygon in local metric."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


def build_floor(profile: StadiumProfile, level_id: str) -> List[StructureModel]:
    """Ground-level floor slab covering the stadium footprint."""
    poly = _polygon_from_tuples(profile.footprint_polygon)
    return [
        StructureModel(
            id="FLOOR_SLAB",
            type="FLOOR",
            level_id=level_id,
            polygon=poly,
            height_m=0.3,
            metadata={"source": "PROCEDURAL", "description": "Stadium floor slab"},
        )
    ]


def build_field(profile: StadiumProfile, level_id: str) -> List[StructureModel]:
    """Playing field structure."""
    if not profile.field_polygon:
        # fallback: 60% of footprint centered
        cx, cy = profile.footprint_center
        rx = profile.footprint_width_m * 0.30
        ry = profile.footprint_depth_m * 0.25
        pts = _ellipse_polygon(cx, cy, rx, ry, 24)
    else:
        pts = profile.field_polygon
    poly = _polygon_from_tuples(pts)
    return [
        StructureModel(
            id="FIELD",
            type="FIELD",
            level_id=level_id,
            polygon=poly,
            height_m=0.1,
            metadata={"source": profile.provenance.source.value, "confidence": profile.provenance.confidence},
        )
    ]


def build_roof(profile: StadiumProfile, levels: List[LevelModel]) -> List[StructureModel]:
    """Roof structure (cantilever ring or none)."""
    if profile.roof_strategy == RoofStrategy.NONE:
        return []
    if not profile.footprint_polygon:
        return []
    top_level = max(levels, key=lambda l: l.elevation_m)
    roof_elevation = top_level.elevation_m + top_level.height_m
    cx, cy = profile.footprint_center
    rx = profile.footprint_width_m * 0.55
    ry = profile.footprint_depth_m * 0.55
    inner_rx = profile.footprint_width_m * 0.42
    inner_ry = profile.footprint_depth_m * 0.42
    outer_pts = _ellipse_polygon(cx, cy, rx, ry, 32)
    inner_pts = _ellipse_polygon(cx, cy, inner_rx, inner_ry, 32)
    # Build a ring polygon (outer + reversed inner)
    ring_pts = outer_pts + list(reversed(inner_pts))
    return [
        StructureModel(
            id="ROOF_CANOPY",
            type="ROOF",
            level_id=top_level.id,
            polygon=_polygon_from_tuples(outer_pts),
            height_m=2.0,
            metadata={
                "source": "PROCEDURAL",
                "elevation_m": roof_elevation,
                "strategy": profile.roof_strategy.value,
            },
        )
    ]
