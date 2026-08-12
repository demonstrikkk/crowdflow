"""Stadium procedural builder (Phase 6).

Takes a StadiumProfile and produces a VenueSpatialModel.

Invocation chain:
  ArchitecturalScene
      → profile.build_profile()   (StadiumProfile)
      → stadium_builder.build()   (VenueSpatialModel)

This module orchestrates the sub-builders:
  bowl.py        → seating tier structures
  concourse.py   → concourse structures + paths
  openings.py    → gates + emergency exits
  facilities.py  → facility room structures
  vertical.py    → stair/ramp/elevator structures
  structures.py  → field, floor, walls

Design rules:
  * No generic template. Everything derives from StadiumProfile.
  * Every structure gets a provenance metadata entry.
  * Paths and openings are cross-referenced (geometry_id / spatial_ref).
  * All coordinates are LOCAL_METRIC.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ...models import (
    LevelModel,
    OpeningModel,
    PathGeometryModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueSpatialModel,
)
from .profile import StadiumProfile

from . import bowl as bowl_builder
from . import concourse as concourse_builder
from . import openings as opening_builder
from . import facilities as facility_builder
from . import vertical as vertical_builder
from . import structures as structure_builder


def build(profile: StadiumProfile, venue_id: Optional[str] = None) -> VenueSpatialModel:
    """Build VenueSpatialModel from StadiumProfile.

    This is the single authoritative entry point replacing the legacy
    ``reconstruct.build_spatial()`` rectangle-only path.
    """
    vid = venue_id or profile.venue_id

    # Levels
    levels = _build_levels(profile)
    level_id_set = {lv.id for lv in levels}
    primary_level = levels[0].id if levels else "L0"

    structures: List[StructureModel] = []
    openings: List[OpeningModel] = []
    paths: List[PathGeometryModel] = []

    # 1. Floor slab and perimeter walls
    structures.extend(structure_builder.build_floor(profile, primary_level))
    structures.extend(structure_builder.build_field(profile, primary_level))

    # 2. Seating bowls (stepped tier geometry)
    for bowl in profile.seating_bowls:
        structures.extend(bowl_builder.build_bowl(bowl, profile))

    # 3. Concourses (ring / partial ring / corridor)
    for concourse in profile.concourses:
        structures_c, paths_c = concourse_builder.build_concourse(concourse, profile)
        structures.extend(structures_c)
        paths.extend(paths_c)

    # 4. Gates and emergency exits
    gate_openings, gate_paths = opening_builder.build_gates(
        profile.gates + profile.emergency_exits,
        profile,
        primary_level,
    )
    openings.extend(gate_openings)
    paths.extend(gate_paths)

    # 5. Facilities
    fac_structures = facility_builder.build_facilities(profile.facilities, profile)
    structures.extend(fac_structures)

    # 6. Vertical connections (stairs, ramps, elevators)
    vert_structures, vert_paths = vertical_builder.build_verticals(
        profile.vertical_connections, profile
    )
    structures.extend(vert_structures)
    paths.extend(vert_paths)

    # 7. Roof (if profile says PROCEDURAL or FULL)
    structures.extend(structure_builder.build_roof(profile, levels))

    # Ensure all level IDs are valid
    structures, openings, paths = _clamp_level_refs(
        structures, openings, paths, level_id_set, primary_level
    )

    return VenueSpatialModel(
        venue_id=vid,
        levels=levels,
        structures=structures,
        openings=openings,
        paths=paths,
        metadata={
            "source": "PROCEDURAL_BUILDER",
            "stadium_type": profile.stadium_type,
            "structural_style": profile.structural_style.value,
            "roof_strategy": profile.roof_strategy.value,
            "seating_bowls": len(profile.seating_bowls),
            "concourses": len(profile.concourses),
            "gates": len(profile.gates),
            "emergency_exits": len(profile.emergency_exits),
            "facilities": len(profile.facilities),
        },
    )


def _build_levels(profile: StadiumProfile) -> List[LevelModel]:
    if not profile.level_ids:
        return [LevelModel(id="L0", name="Ground Level", elevation_m=0.0, height_m=5.0)]

    levels = []
    for i, lid in enumerate(profile.level_ids):
        elevation = i * 5.0
        # Try to find actual elevation from a seating tier
        for bowl in profile.seating_bowls:
            for tier in bowl.tiers:
                if tier.level_id == lid:
                    elevation = tier.floor_elevation_m
                    break
        levels.append(LevelModel(
            id=lid,
            name=f"Level {i}",
            elevation_m=round(elevation, 2),
            height_m=5.0,
        ))
    return levels


def _clamp_level_refs(
    structures, openings, paths, level_ids: set, fallback: str
) -> Tuple[List, List, List]:
    """Replace any invalid level_id references with the fallback level."""
    def fix(items):
        result = []
        for item in items:
            if item.level_id not in level_ids:
                data = item.model_dump()
                data["level_id"] = fallback
                result.append(type(item).model_validate(data))
            else:
                result.append(item)
        return result

    return fix(structures), fix(openings), fix(paths)
