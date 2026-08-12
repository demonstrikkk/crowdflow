"""Reconstruct a VenueSpatialModel from detected blueprint geometry.

Deterministic reconstruction (no AI): boundary walls become WALL structures,
the footprint becomes a FLOOR, gate openings become OpeningModel entries and
interior wall segments become WALL structures. Opening ids reuse the gate
node ids (``B1..Bn``) so NodeModel ``spatial_ref`` can link to them.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..models import (
    LevelModel,
    OpeningModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueSpatialModel,
)
from ..spatial.coordinates import px_to_venue

_LEVEL_ID = "L1"
_GATE_TYPE = {"ENTRY": "ENTRY_GATE", "EXIT": "EXIT_GATE", "EMERGENCY_EXIT": "EMERGENCY_EXIT"}
_WALL_THICKNESS_M = 2.5


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon2D:
    return Polygon2D(points=[Point2D(x=round(x0, 2), y=round(y0, 2)),
                             Point2D(x=round(x1, 2), y=round(y0, 2)),
                             Point2D(x=round(x1, 2), y=round(y1, 2)),
                             Point2D(x=round(x0, 2), y=round(y1, 2))])


def _thick_segment(p0: Tuple[float, float], p1: Tuple[float, float], thickness: float) -> Polygon2D:
    """Turn an axis-aligned wall line into a rectangle polygon."""
    dx = abs(p1[0] - p0[0])
    dy = abs(p1[1] - p0[1])
    if dx >= dy:  # horizontal wall
        y = (p0[1] + p1[1]) / 2.0
        return _rect(min(p0[0], p1[0]), y - thickness / 2.0, max(p0[0], p1[0]), y + thickness / 2.0)
    x = (p0[0] + p1[0]) / 2.0
    return _rect(x - thickness / 2.0, min(p0[1], p1[1]), x + thickness / 2.0, max(p0[1], p1[1]))


def build_spatial(
    perimeter: List[Tuple[Tuple[int, int], Tuple[int, int]]],
    interior_walls: List[Tuple[Tuple[int, int], Tuple[int, int]]],
    gates: List[Dict],
    width_m: float,
    height_m: float,
    px_w: int,
    px_h: int,
) -> VenueSpatialModel:
    """Reconstruct a spatial model from geometry stage output + classified gates."""
    scale = min(width_m / max(1, px_w), height_m / max(1, px_h))

    structures: List[StructureModel] = []
    # footprint floor
    structures.append(
        StructureModel(
            id="FLR",
            level_id=_LEVEL_ID,
            type="FLOOR",
            polygon=_rect(0.0, 0.0, width_m, height_m),
            height_m=0.3,
            metadata={"source": "BLUEPRINT"},
        )
    )
    # boundary walls
    for i, (p0, p1) in enumerate(perimeter):
        structures.append(
            StructureModel(
                id=f"WALL_PERIM_{i + 1}",
                level_id=_LEVEL_ID,
                type="WALL",
                polygon=_thick_segment(px_to_venue(p0[0], p0[1], width_m, height_m, px_w, px_h),
                                       px_to_venue(p1[0], p1[1], width_m, height_m, px_w, px_h),
                                       _WALL_THICKNESS_M),
                height_m=5.0,
                metadata={"source": "BLUEPRINT"},
            )
        )
    # interior walls
    for i, (p0, p1) in enumerate(interior_walls):
        structures.append(
            StructureModel(
                id=f"WALL_INT_{i + 1}",
                level_id=_LEVEL_ID,
                type="WALL",
                polygon=_thick_segment(px_to_venue(p0[0], p0[1], width_m, height_m, px_w, px_h),
                                       px_to_venue(p1[0], p1[1], width_m, height_m, px_w, px_h),
                                       _WALL_THICKNESS_M),
                height_m=5.0,
                metadata={"source": "BLUEPRINT"},
            )
        )

    openings: List[OpeningModel] = []
    for i, gate in enumerate(gates):
        gid = gate.get("id") or f"B{i + 1}"
        kind = gate.get("kind", "ENTRY")
        px = gate["position"]
        x_m, y_m = px_to_venue(px[0], px[1], width_m, height_m, px_w, px_h)
        width_m_gate = gate.get("width_px", 16) * scale
        openings.append(
            OpeningModel(
                id=gid,
                level_id=_LEVEL_ID,
                type=_GATE_TYPE.get(kind, "ENTRY_GATE"),
                position=Point2D(x=round(x_m, 2), y=round(y_m, 2)),
                width_m=round(max(1.0, width_m_gate), 2),
                rotation_deg=_gate_rotation(gate.get("side")),
                metadata={
                    "source": "BLUEPRINT",
                    "confidence": gate.get("confidence", 0.4),
                    "label": gate.get("label"),
                },
            )
        )

    return VenueSpatialModel(
        venue_id="BLUEPRINT_VENUE",
        levels=[LevelModel(id=_LEVEL_ID, name="Ground", elevation_m=0.0, height_m=5.0)],
        structures=structures,
        openings=openings,
        paths=[],
        metadata={"source": "BLUEPRINT_IMPORT"},
    )


def _gate_rotation(side) -> float:
    return {"N": 0.0, "S": 180.0, "E": 90.0, "W": 270.0}.get(side, 0.0)
