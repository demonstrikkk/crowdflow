"""Navigation extraction: VenueSpatialModel -> VenueModel.

The spatial model (structures + openings) is authoritative for architecture.
From it we keep the deterministic graph builder (which produces a validated,
simulation-ready VenueModel) and then wire the two models together:

  * every gate node gets ``spatial_ref`` -> ``opening:<node id>``;
  * every edge gets a straight centre-line PathGeometryModel and the edge's
    ``geometry_id`` is set to it.

Phase 7: when the architectural path is active (spatial.openings are already
populated with meaningful data), ``build_venue_from_spatial`` derives the graph
directly from spatial openings rather than from sem.gates / sem.interior, so
the navigation graph faithfully mirrors the 3D stadium geometry and every
emergency route is properly tagged ``is_emergency=True``.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ..models import (
    EdgeModel, NodeModel, NodeType, PathGeometryModel, Point2D,
    Position, VenueModel, VenueSpatialModel,
)
from . import graph


# --------------------------------------------------------------------------- #
#  Legacy path (sem.gates / sem.interior -> graph)
# --------------------------------------------------------------------------- #

def build_venue(
    spatial: VenueSpatialModel,
    gates: List[dict],
    interior: List[dict],
    width_m: float,
    height_m: float,
    px_w: int,
    px_h: int,
) -> Tuple[VenueModel, List[str]]:
    """Return (venue, notes). Fills path geometry + links into ``spatial``."""
    venue, notes = graph.build_venue(gates, interior, width_m, height_m, px_w, px_h)

    if venue.id != "BLUEPRINT_VENUE":
        return venue, notes

    spatial.venue_id = venue.id

    opening_ids = {o.id for o in spatial.openings}
    for node in venue.nodes:
        if node.id in opening_ids:
            node.spatial_ref = f"opening:{node.id}"

    pos: Dict[str, Point2D] = {n.id: n.position for n in venue.nodes}
    for edge in venue.edges:
        src = pos.get(edge.source)
        dst = pos.get(edge.destination)
        if src is None or dst is None:
            continue
        pid = f"PATH_{edge.id}"
        # avoid duplicate path IDs
        existing_ids = {p.id for p in spatial.paths}
        if pid in existing_ids:
            continue
        # Pick the level from source node's opening or fall back to primary level
        level_id = _node_level(edge.source, spatial) or _primary_level(spatial)
        spatial.paths.append(
            PathGeometryModel(
                id=pid,
                level_id=level_id,
                centerline=[Point2D(x=src.x, y=src.y), Point2D(x=dst.x, y=dst.y)],
                width_m=edge.width_m,
                metadata={"source": "BLUEPRINT", "edge": edge.id},
            )
        )
        edge.geometry_id = pid

    return venue, notes


# --------------------------------------------------------------------------- #
#  Architectural path (spatial.openings -> graph)  — Phase 7
# --------------------------------------------------------------------------- #

_OPENING_TO_NODE_TYPE = {
    "ENTRY_GATE": NodeType.ENTRY,
    "EXIT_GATE": NodeType.EXIT,
    "EMERGENCY_EXIT": NodeType.EMERGENCY_EXIT,
    "DOOR": NodeType.INTERSECTION,
    "SERVICE_ENTRY": NodeType.ENTRY,
}


def build_venue_from_spatial(
    spatial: VenueSpatialModel,
    width_m: float,
    height_m: float,
) -> Tuple[VenueModel, List[str]]:
    """Build VenueModel from a fully-populated VenueSpatialModel.

    Uses spatial.openings as gate/exit nodes and derives interior nodes from
    seating/concourse structure centroids. Every emergency-exit node gets all
    its edges tagged ``is_emergency=True``.

    This replaces the legacy sem.gates path when the architectural pipeline
    produces a spatial model with real openings.
    """
    notes: List[str] = []
    nodes: List[NodeModel] = []
    edges: List[EdgeModel] = []

    # ---- opening nodes -------------------------------------------------------
    opening_positions: Dict[str, Tuple[float, float]] = {}
    for opening in spatial.openings:
        ntype = _OPENING_TO_NODE_TYPE.get(opening.type, NodeType.ENTRY)
        pos_x = float(opening.position.x)
        pos_y = float(opening.position.y)
        # guard non-negative position requirement of Position validator
        px = max(0.0, pos_x)
        py = max(0.0, pos_y)
        capacity = float(opening.metadata.get("capacity_ppm", 120.0)) if opening.metadata else 120.0
        nodes.append(NodeModel(
            id=opening.id,
            position=Position(x=round(px, 2), y=round(py, 2)),
            type=ntype,
            capacity=capacity,
            area_m2=opening.width_m * 2.5 if opening.width_m else 5.0,
            spatial_ref=f"opening:{opening.id}",
            metadata={"level_id": opening.level_id},
        ))
        opening_positions[opening.id] = (px, py)

    # ---- interior hub per level from SEATING/CONCOURSE centroids -------------
    by_level: Dict[str, List[Tuple[float, float]]] = {}
    for struct in spatial.structures:
        if struct.type not in ("SEATING", "CONCOURSE", "ZONE", "FIELD"):
            continue
        pts = struct.polygon.points
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        by_level.setdefault(struct.level_id, []).append((cx, cy))

    hub_nodes: Dict[str, str] = {}  # level_id -> node_id
    for lvl_id, pts_list in by_level.items():
        hx = sum(p[0] for p in pts_list) / len(pts_list)
        hy = sum(p[1] for p in pts_list) / len(pts_list)
        hx = max(0.0, hx)
        hy = max(0.0, hy)
        hub_id = f"HUB_{lvl_id}"
        nodes.append(NodeModel(
            id=hub_id,
            position=Position(x=round(hx, 2), y=round(hy, 2)),
            type=NodeType.ZONE,
            area_m2=max(200.0, width_m * height_m * 0.05),
            metadata={"level_id": lvl_id, "source": "PROCEDURAL"},
        ))
        hub_nodes[lvl_id] = hub_id

    # fall back hub at venue centre if no structures found
    if not hub_nodes:
        hub_id = "HUB_L0"
        nodes.append(NodeModel(
            id=hub_id,
            position=Position(x=round(width_m / 2, 2), y=round(height_m / 2, 2)),
            type=NodeType.ZONE,
            area_m2=max(200.0, width_m * height_m * 0.05),
            metadata={"source": "PROCEDURAL"},
        ))
        hub_nodes["L0"] = hub_id
        notes.append("no structure centroids found; single hub at venue centre")

    # ---- edges: every opening -> nearest hub ---------------------------------
    edge_seq = 0
    primary_level = _primary_level(spatial)
    node_positions: Dict[str, Tuple[float, float]] = {
        **opening_positions,
        **{hid: (float(n.position.x), float(n.position.y))
           for n in nodes if n.id in hub_nodes.values()
           for hid in [n.id]},
    }

    # build fast lookup: node_id -> position
    npos: Dict[str, Tuple[float, float]] = {}
    for n in nodes:
        npos[n.id] = (float(n.position.x), float(n.position.y))

    def add_edge(src: str, dst: str, is_emg: bool = False) -> None:
        nonlocal edge_seq
        edge_seq += 1
        sp = npos[src]
        dp = npos[dst]
        length = max(1.0, math.hypot(dp[0] - sp[0], dp[1] - sp[1]))
        edges.append(EdgeModel(
            id=f"E{edge_seq}",
            source=src,
            destination=dst,
            length_m=round(length, 2),
            width_m=3.0,
            capacity=120.0,
            is_emergency=is_emg,
        ))

    # connect each opening to its level hub (or nearest hub)
    for opening in spatial.openings:
        oid = opening.id
        lvl = opening.level_id
        hub_id = hub_nodes.get(lvl) or next(iter(hub_nodes.values()))
        is_emg = opening.type == "EMERGENCY_EXIT"
        add_edge(oid, hub_id, is_emg)

    # connect level hubs via vertical connections in spatial paths
    hub_ids = list(hub_nodes.values())
    for i, a in enumerate(hub_ids):
        for b in hub_ids[i + 1:]:
            add_edge(a, b)

    # ---- validate and build --------------------------------------------------
    spatial.venue_id = "BLUEPRINT_VENUE"
    try:
        venue = VenueModel(
            id="BLUEPRINT_VENUE",
            name="Blueprint Venue",
            width=width_m,
            height=height_m,
            nodes=nodes,
            edges=edges,
            metadata={"source": "ARCHITECTURAL_SPATIAL"},
        )
    except ValueError as exc:
        notes.append(f"spatial-derived graph failed validation ({exc}); falling back to template")
        return graph._template_venue(width_m, height_m), notes

    # ---- add graph edges as PathGeometryModels in spatial --------------------
    existing_path_ids = {p.id for p in spatial.paths}
    for edge in venue.edges:
        src_node = next((n for n in nodes if n.id == edge.source), None)
        dst_node = next((n for n in nodes if n.id == edge.destination), None)
        if not src_node or not dst_node:
            continue
        pid = f"PATH_{edge.id}"
        if pid in existing_path_ids:
            continue
        # pick level from source opening if available
        level_id = (
            src_node.metadata.get("level_id")
            or dst_node.metadata.get("level_id")
            or primary_level
        )
        if level_id not in {lv.id for lv in spatial.levels}:
            level_id = primary_level
        spatial.paths.append(PathGeometryModel(
            id=pid,
            level_id=str(level_id),
            centerline=[
                Point2D(x=float(src_node.position.x), y=float(src_node.position.y)),
                Point2D(x=float(dst_node.position.x), y=float(dst_node.position.y)),
            ],
            width_m=edge.width_m,
            metadata={
                "source": "NAVIGATION",
                "edge": edge.id,
                "is_emergency": edge.is_emergency,
            },
        ))
        edge.geometry_id = pid

    notes.append(
        f"architectural nav: {len(venue.nodes)} nodes, {len(venue.edges)} edges "
        f"({sum(1 for e in venue.edges if e.is_emergency)} emergency)"
    )
    return venue, notes


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _primary_level(spatial: VenueSpatialModel) -> str:
    if not spatial.levels:
        return "L0"
    return min(spatial.levels, key=lambda lv: lv.elevation_m).id


def _node_level(node_id: str, spatial: VenueSpatialModel) -> Optional[str]:
    for opening in spatial.openings:
        if opening.id == node_id:
            return opening.level_id
    return None

