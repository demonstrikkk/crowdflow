"""Derive a VenueSpatialModel from a navigation-only VenueModel.

Backward compatibility path: any legacy venue (seeded JSON, API payloads) can
gain a spatial model without hand-authoring geometry. The derivation is
deterministic:

  * one ground level;
  * a FLOOR covering the venue footprint;
  * a WALL structure along the four perimeter edges;
  * an ENTRY/EXIT/EMERGENCY opening for every gate node;
  * a straight centre-line PATH for every edge (linked via ``geometry_id``).

Node ``spatial_ref`` values are set to ``opening:<node id>`` so the two models
stay connected.
"""
from __future__ import annotations

from typing import List

from ..models import (
    LevelModel,
    NodeType,
    OpeningModel,
    PathGeometryModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueModel,
    VenueSpatialModel,
)

_WALL_THICKNESS = 6.0
_LEVEL_ID = "L1"


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon2D:
    return Polygon2D(points=[Point2D(x=x0, y=y0), Point2D(x=x1, y=y0), Point2D(x=x1, y=y1), Point2D(x=x0, y=y1)])


def derive_spatial_from_venue(venue: VenueModel) -> VenueSpatialModel:
    W, H = venue.width, venue.height
    t = _WALL_THICKNESS

    structures: List[StructureModel] = [
        StructureModel(
            id="FLR",
            level_id=_LEVEL_ID,
            type="FLOOR",
            polygon=_rect(0.0, 0.0, W, H),
            height_m=0.3,
            metadata={"source": "DERIVED"},
        ),
        StructureModel(
            id="WALL_N", level_id=_LEVEL_ID, type="WALL",
            polygon=_rect(0.0, 0.0, W, t), height_m=5.0, metadata={"source": "DERIVED"},
        ),
        StructureModel(
            id="WALL_S", level_id=_LEVEL_ID, type="WALL",
            polygon=_rect(0.0, H - t, W, H), height_m=5.0, metadata={"source": "DERIVED"},
        ),
        StructureModel(
            id="WALL_E", level_id=_LEVEL_ID, type="WALL",
            polygon=_rect(W - t, 0.0, W, H), height_m=5.0, metadata={"source": "DERIVED"},
        ),
        StructureModel(
            id="WALL_W", level_id=_LEVEL_ID, type="WALL",
            polygon=_rect(0.0, 0.0, t, H), height_m=5.0, metadata={"source": "DERIVED"},
        ),
    ]

    openings: List[OpeningModel] = []
    node_by_id = {n.id: n for n in venue.nodes}
    for node in venue.nodes:
        if node.type == NodeType.ENTRY:
            otype = "ENTRY_GATE"
        elif node.type == NodeType.EXIT:
            otype = "EXIT_GATE"
        elif node.type == NodeType.EMERGENCY_EXIT:
            otype = "EMERGENCY_EXIT"
        else:
            continue
        openings.append(
            OpeningModel(
                id=node.id,
                level_id=_LEVEL_ID,
                type=otype,
                position=Point2D(x=node.position.x, y=node.position.y),
                width_m=8.0,
                rotation_deg=0.0,
                metadata={"source": "DERIVED", "node": node.id},
            )
        )

    paths: List[PathGeometryModel] = []
    for edge in venue.edges:
        src = node_by_id.get(edge.source)
        dst = node_by_id.get(edge.destination)
        if src is None or dst is None:
            continue
        pid = f"PATH_{edge.id}"
        paths.append(
            PathGeometryModel(
                id=pid,
                level_id=_LEVEL_ID,
                centerline=[
                    Point2D(x=src.position.x, y=src.position.y),
                    Point2D(x=dst.position.x, y=dst.position.y),
                ],
                width_m=edge.width_m,
                metadata={"source": "DERIVED", "edge": edge.id},
            )
        )
        edge.geometry_id = pid

    for node in venue.nodes:
        if node.type in (NodeType.ENTRY, NodeType.EXIT, NodeType.EMERGENCY_EXIT):
            node.spatial_ref = f"opening:{node.id}"

    return VenueSpatialModel(
        venue_id=venue.id,
        levels=[LevelModel(id=_LEVEL_ID, name="Ground", elevation_m=0.0, height_m=5.0)],
        structures=structures,
        openings=openings,
        paths=paths,
        metadata={"source": "DERIVED_FROM_VENUE"},
    )
