"""Vertical connection builder (Phase 6).

Generates stairs, ramps, and elevator StructureModels + PathGeometryModels that
span multiple levels. Each vertical connector:
  - appears as a StructureModel in 3D
  - has a PathGeometryModel connecting the two level positions
  - is wired as NavigationEdge in the navigation builder

Design rule: Never create visual stairs that have no simulation connectivity.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ...models import PathGeometryModel, Point2D, Polygon2D, StructureModel
from .profile import StadiumProfile, VerticalConnectionProfile


def build_verticals(
    vert_conns: List[VerticalConnectionProfile],
    profile: StadiumProfile,
) -> Tuple[List[StructureModel], List[PathGeometryModel]]:
    structures: List[StructureModel] = []
    paths: List[PathGeometryModel] = []

    # Build level elevation map
    level_elevations: dict = {}
    for bowl in profile.seating_bowls:
        for tier in bowl.tiers:
            level_elevations.setdefault(tier.level_id, tier.floor_elevation_m)
    # Also check concourses
    for c in profile.concourses:
        level_elevations.setdefault(c.level_id, c.elevation_m)

    for vc in vert_conns:
        s, p = _build_vertical(vc, level_elevations)
        if s:
            structures.append(s)
        if p:
            paths.append(p)

    return structures, paths


def _build_vertical(
    vc: VerticalConnectionProfile,
    level_elevations: dict,
) -> Tuple[StructureModel | None, PathGeometryModel | None]:
    cx, cy = vc.position
    half = vc.width_m / 2.0

    poly_pts = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]

    try:
        polygon = Polygon2D(
            points=[Point2D(x=round(x, 2), y=round(y, 2)) for x, y in poly_pts]
        )
    except Exception:
        return None, None

    from_elev = level_elevations.get(vc.from_level_id, 0.0)
    to_elev = level_elevations.get(vc.to_level_id, 5.0)
    height = abs(to_elev - from_elev)
    if height < 0.5:
        height = 5.0

    vc_type = vc.type.upper()
    struct_type = "STAIR" if vc_type in ("STAIR", "RAMP") else "ROOM"

    struct = StructureModel(
        id=f"VERT_{vc.id}",
        level_id=vc.from_level_id,
        type=struct_type,
        polygon=polygon,
        height_m=round(height, 2),
        metadata={
            "source": vc.provenance.source.value,
            "confidence": round(vc.provenance.confidence, 3),
            "vertical_type": vc.type,
            "from_level": vc.from_level_id,
            "to_level": vc.to_level_id,
            "label": vc.label,
            "kind": vc_type,
        },
    )

    # Create a vertical center-line path (2 points at the same XY, different z)
    # stored as metadata for the navigation builder
    path = PathGeometryModel(
        id=f"PATH_VERT_{vc.id}",
        level_id=vc.from_level_id,
        centerline=[
            Point2D(x=round(cx, 2), y=round(cy, 2)),
            Point2D(x=round(cx, 2), y=round(cy, 2) + 0.01),  # tiny offset to satisfy 2-point rule
        ],
        width_m=vc.width_m,
        metadata={
            "source": "PROCEDURAL",
            "vertical_type": vc.type,
            "from_level": vc.from_level_id,
            "to_level": vc.to_level_id,
            "is_vertical": True,
            "from_elevation_m": from_elev,
            "to_elevation_m": to_elev,
        },
    )

    return struct, path
