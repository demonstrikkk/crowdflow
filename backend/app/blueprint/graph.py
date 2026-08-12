"""Build a validated VenueModel from recovered blueprint elements.

The builder is deterministic and never raises on structurally poor geometry:
if the constructed graph fails VenueModel validation it degrades to a minimal
connected template (documented in the result notes) so an import always yields
a usable, simulation-ready venue.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ..models import EdgeModel, NodeModel, NodeType, Position, VenueModel

_GATE_TYPES = {"ENTRY": NodeType.ENTRY, "EXIT": NodeType.EXIT, "EMERGENCY_EXIT": NodeType.EMERGENCY_EXIT}


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _meters_per_px(width_m: float, height_m: float, geom_width_px: int, geom_height_px: int) -> float:
    scale = min(width_m / max(1, geom_width_px), height_m / max(1, geom_height_px))
    return max(0.05, min(2.0, scale))


def _id(prefix: str, index: int) -> str:
    return f"{prefix}{index}"


def _node(node_id: str, position: Tuple[float, float], ntype: NodeType, confidence: float) -> NodeModel:
    area_default = {
        NodeType.ENTRY: 60.0,
        NodeType.EXIT: 60.0,
        NodeType.EMERGENCY_EXIT: 80.0,
        NodeType.INTERSECTION: 40.0,
        NodeType.CONCESSION: 90.0,
        NodeType.CHECKPOINT: 30.0,
        NodeType.ZONE: 2000.0,
    }
    return NodeModel(
        id=node_id,
        position=Position(x=round(position[0], 2), y=round(position[1], 2)),
        type=ntype,
        capacity=None,
        area_m2=area_default.get(ntype),
    )


def build_venue(
    gates: List[dict],
    interior: List[dict],
    width_m: float,
    height_m: float,
    geom_width_px: int,
    geom_height_px: int,
) -> Tuple[VenueModel, List[str]]:
    """Construct a venue, returning (venue, notes). Raises nothing."""
    notes: List[str] = []
    scale = _meters_per_px(width_m, height_m, geom_width_px, geom_height_px)

    nodes: List[NodeModel] = []
    edges: List[EdgeModel] = []

    gate_positions: List[Tuple[str, Tuple[float, float]]] = []

    for i, gate in enumerate(gates):
        nid = gate.get("id") or _id("B", i + 1)
        pos_px = gate["position"]
        pos_m = (pos_px[0] * scale, pos_px[1] * scale)
        ntype = _GATE_TYPES.get(gate.get("kind", "ENTRY"), NodeType.ENTRY)
        nodes.append(_node(nid, pos_m, ntype, gate.get("confidence", 0.4)))
        gate_positions.append((nid, pos_m))

    interior_positions: List[Tuple[str, Tuple[float, float]]] = []
    for i, node in enumerate(interior):
        nid = node.get("id") or _id("I", i + 1)
        pos_px = node["position"]
        pos_m = (pos_px[0] * scale, pos_px[1] * scale)
        ntype = NodeType.INTERSECTION
        if node.get("kind") in ("CONCESSION", "CHECKPOINT", "ZONE"):
            ntype = {
                "CONCESSION": NodeType.CONCESSION,
                "CHECKPOINT": NodeType.CHECKPOINT,
                "ZONE": NodeType.ZONE,
            }[node["kind"]]
        nodes.append(_node(nid, pos_m, ntype, node.get("confidence", 0.5)))
        interior_positions.append((nid, pos_m))

    hub_m = (width_m / 2, height_m / 2)
    if interior_positions:
        hub_m = tuple(sum(p[i] for _, p in interior_positions) / len(interior_positions) for i in range(2))
    hub_id = _id("H", 1)
    nodes.append(_node(hub_id, hub_m, NodeType.INTERSECTION, 0.7))

    edge_seq = 0

    def add_edge(src: str, dst: str) -> None:
        nonlocal edge_seq
        edge_seq += 1
        src_pos = dict((nid, pos) for nid, pos in gate_positions + interior_positions + [(hub_id, hub_m)])[src]
        dst_pos = dict((nid, pos) for nid, pos in gate_positions + interior_positions + [(hub_id, hub_m)])[dst]
        length = max(2.0, _dist(src_pos, dst_pos))
        edges.append(
            EdgeModel(
                id=_id("E", edge_seq),
                source=src,
                destination=dst,
                length_m=round(length, 2),
                width_m=3.0,
                capacity=120.0,
            )
        )

    # hub connects every gate and every interior node -> guaranteed connectivity
    for nid, _ in gate_positions:
        add_edge(nid, hub_id)
    for nid, _ in interior_positions:
        add_edge(nid, hub_id)

    # snake chain through interior nodes for more realistic corridors
    ordered = sorted(interior_positions, key=lambda p: (p[1][1], p[1][0]))
    for prev, cur in zip(ordered, ordered[1:]):
        add_edge(prev[0], cur[0])

    if not interior_positions:
        notes.append("no interior walls detected; venue built as boundary-gate star topology")

    try:
        venue = VenueModel(
            id="BLUEPRINT_VENUE",
            name="Blueprint Venue",
            width=width_m,
            height=height_m,
            nodes=nodes,
            edges=edges,
            metadata={"source": "BLUEPRINT_IMPORT"},
        )
        return venue, notes
    except ValueError as exc:
        notes.append(f"constructed graph failed validation ({exc}); falling back to template venue")
        return _template_venue(width_m, height_m), notes


def _template_venue(width_m: float, height_m: float) -> VenueModel:
    w, h = width_m, height_m
    nodes = [
        NodeModel(id="ENTRY", position=Position(x=round(w * 0.15, 2), y=round(h * 0.5, 2)), type=NodeType.ENTRY, area_m2=60.0),
        NodeModel(id="EXIT", position=Position(x=round(w * 0.85, 2), y=round(h * 0.5, 2)), type=NodeType.EXIT, area_m2=60.0),
        NodeModel(id="EMERGENCY_EXIT", position=Position(x=round(w * 0.5, 2), y=round(h * 0.9, 2)), type=NodeType.EMERGENCY_EXIT, area_m2=80.0),
        NodeModel(id="HUB", position=Position(x=round(w * 0.5, 2), y=round(h * 0.5, 2)), type=NodeType.INTERSECTION, area_m2=40.0),
    ]
    edges = [
        EdgeModel(id="E1", source="ENTRY", destination="HUB", length_m=round(w * 0.35, 2), width_m=3.0, capacity=120.0),
        EdgeModel(id="E2", source="HUB", destination="EXIT", length_m=round(w * 0.35, 2), width_m=3.0, capacity=120.0),
        EdgeModel(id="E3", source="HUB", destination="EMERGENCY_EXIT", length_m=round(h * 0.4, 2), width_m=3.0, capacity=120.0),
    ]
    return VenueModel(
        id="BLUEPRINT_TEMPLATE",
        name="Blueprint Venue (template)",
        width=w,
        height=h,
        nodes=nodes,
        edges=edges,
        metadata={"source": "BLUEPRINT_TEMPLATE"},
    )
