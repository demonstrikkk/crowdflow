"""Gate and emergency exit builder (Phase 6).

Generates OpeningModel objects and connecting PathGeometryModel objects from
GateProfile. Every gate has:
  - an OpeningModel in the spatial model
  - a short entry path linking the gate to the nearest concourse/circulation

Emergency exits are marked with is_emergency=True in the navigation graph.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ...models import OpeningModel, PathGeometryModel, Point2D
from .profile import GateProfile, StadiumProfile


def build_gates(
    gates: List[GateProfile],
    profile: StadiumProfile,
    default_level_id: str = "L0",
) -> Tuple[List[OpeningModel], List[PathGeometryModel]]:
    """Build OpeningModel + entry path for every gate."""
    openings: List[OpeningModel] = []
    paths: List[PathGeometryModel] = []

    for gate in gates:
        opening = _build_opening(gate, default_level_id)
        openings.append(opening)
        path = _build_entry_path(gate, profile.footprint_center, default_level_id)
        if path:
            paths.append(path)

    return openings, paths


def _build_opening(gate: GateProfile, default_level_id: str) -> OpeningModel:
    level_id = gate.level_id if gate.level_id else default_level_id
    gtype = gate.type
    if gtype not in ("ENTRY_GATE", "EXIT_GATE", "EMERGENCY_EXIT", "DOOR", "SERVICE_ENTRY"):
        gtype = "ENTRY_GATE"

    return OpeningModel(
        id=gate.id,
        level_id=level_id,
        type=gtype,
        position=Point2D(x=round(gate.position[0], 2), y=round(gate.position[1], 2)),
        width_m=round(max(1.5, gate.width_m), 2),
        rotation_deg=round(gate.rotation_deg, 1),
        metadata={
            "source": gate.provenance.source.value,
            "source_entity_id": gate.provenance.source_entity_id,
            "confidence": round(gate.provenance.confidence, 3),
            "label": gate.label,
            "is_emergency": gate.is_emergency,
            "capacity_ppm": gate.capacity_ppm,
        },
    )


def _build_entry_path(
    gate: GateProfile,
    footprint_center: Tuple[float, float],
    default_level_id: str,
) -> PathGeometryModel | None:
    """Build a short entry path from gate position toward the venue interior."""
    gx, gy = gate.position
    cx, cy = footprint_center

    # Direction from gate toward center, capped at 12 m
    dx, dy = cx - gx, cy - gy
    dist = math.hypot(dx, dy)
    if dist < 0.1:
        return None

    path_len = min(12.0, dist * 0.3)
    end_x = gx + (dx / dist) * path_len
    end_y = gy + (dy / dist) * path_len

    level_id = gate.level_id if gate.level_id else default_level_id

    return PathGeometryModel(
        id=f"PATH_{gate.id}",
        level_id=level_id,
        centerline=[
            Point2D(x=round(gx, 2), y=round(gy, 2)),
            Point2D(x=round(end_x, 2), y=round(end_y, 2)),
        ],
        width_m=max(2.0, gate.width_m * 0.8),
        metadata={
            "source": "PROCEDURAL",
            "gate_id": gate.id,
            "is_emergency": gate.is_emergency,
            "kind": "GATE_ENTRY",
        },
    )
