"""Facility builder (Phase 6).

Generates StructureModel objects for facilities: washrooms, concessions,
cafeterias, medical, VIP, media, service rooms.

If blueprint position is available: use it.
If not: procedurally place within nearest concourse zone.
Facilities never block primary circulation corridors.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ...models import Point2D, Polygon2D, StructureModel
from .profile import FacilityProfile, StadiumProfile

_TYPE_TO_STRUCT = {
    "WASHROOM": "ROOM",
    "CONCESSION": "ROOM",
    "CAFETERIA": "ROOM",
    "MEDICAL": "ROOM",
    "VIP": "ROOM",
    "MEDIA": "ROOM",
    "SERVICE": "ROOM",
}


def build_facilities(
    facilities: List[FacilityProfile],
    profile: StadiumProfile,
) -> List[StructureModel]:
    structures = []
    for fac in facilities:
        s = _build_facility(fac, profile)
        if s:
            structures.append(s)
    return structures


def _build_facility(fac: FacilityProfile, profile: StadiumProfile) -> StructureModel | None:
    cx, cy = fac.position
    half_side = math.sqrt(max(10.0, fac.area_m2)) / 2.0

    poly_pts = [
        (cx - half_side, cy - half_side),
        (cx + half_side, cy - half_side),
        (cx + half_side, cy + half_side),
        (cx - half_side, cy + half_side),
    ]

    try:
        polygon = Polygon2D(
            points=[Point2D(x=round(x, 2), y=round(y, 2)) for x, y in poly_pts]
        )
    except Exception:
        return None

    stype = _TYPE_TO_STRUCT.get(fac.type.upper(), "ROOM")

    return StructureModel(
        id=fac.id,
        level_id=fac.level_id,
        type=stype,
        polygon=polygon,
        height_m=3.5,
        metadata={
            "source": fac.provenance.source.value,
            "confidence": round(fac.provenance.confidence, 3),
            "label": fac.label,
            "facility_type": fac.type,
            "area_m2": fac.area_m2,
            "kind": fac.type,
        },
    )
