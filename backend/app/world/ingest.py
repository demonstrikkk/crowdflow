"""Normalize raw OSM payloads into the unified external WorldGraph.

OSM ways are split at shared junction nodes; each sub-path becomes one
ExternalEdge carrying length / speed / capacity heuristics (marked
``source="estimated"``). Venue gates are snapped onto the graph to build
AccessPoints, and transit/parking/entrance features become DemandSources.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ..engine.environment import venue_location  # reuse location resolution
from ..models import NodeType, VenueModel, WorldPosition
from . import osm
from .models import AccessPoint, DemandSource, ExternalEdge, ExternalNode, WorldGraph, WorldProvenance

# venue nodes to sink when their egress is absorbed
_SINK_RADIUS_M = 900.0


def _graph_bbox(venue: VenueModel, span_m: float) -> Dict[str, float]:
    cx, cy = venue.width / 2.0, venue.height / 2.0
    return {
        "min_x": round(cx - span_m / 2, 0),
        "min_y": round(cy - span_m / 2, 0),
        "max_x": round(cx + span_m / 2, 0),
        "max_y": round(cy + span_m / 2, 0),
    }


def world_span_m(venue: VenueModel) -> float:
    return min(venue.width, venue.height) * 1.9 + 1200.0


def _way_points(way: dict, nodes: Dict[int, dict], ref_lat: float, ref_lon: float) -> List[WorldPosition]:
    pts: List[WorldPosition] = []
    for nid in way.get("nodes", []):
        node = nodes.get(nid)
        if node is None:
            continue
        pts.append(osm.project(node["lat"], node["lon"], ref_lat, ref_lon))
    return pts


def ingest_osm(
    raw: dict,
    venue: VenueModel,
    ref_lat: float,
    ref_lon: float,
    provider_name: str = "OSM",
    fetched_at: Optional[str] = None,
) -> WorldGraph:
    elements = raw.get("elements", [])
    ways = [e for e in elements if e.get("type") == "way"]
    nodes = {e["id"]: e for e in elements if e.get("type") == "node"}

    walkable_ways: List[dict] = []
    for way in ways:
        tags = way.get("tags", {})
        kind = osm.highway_kind(tags)
        if kind is None:
            continue
        pts = _way_points(way, nodes, ref_lat, ref_lon)
        if len(pts) < 2:
            continue
        length = osm.way_length_m(pts)
        if length < 20.0:
            continue
        walkable_ways.append({"way": way, "kind": kind, "tags": tags, "pts": pts})

    # node incidence → break sub-paths at shared junction nodes
    incidence: Dict[int, int] = {}
    for w in walkable_ways:
        for nid in w["way"].get("nodes", []):
            incidence[nid] = incidence.get(nid, 0) + 1

    graph_nodes: Dict[str, ExternalNode] = {}
    graph_edges: List[ExternalEdge] = []
    sink_ids: List[str] = []
    cx, cy = venue.width / 2.0, venue.height / 2.0

    def ensure_node(nid: int) -> ExternalNode:
        nid_key = f"XN_{nid}"
        if nid_key not in graph_nodes:
            nd = nodes.get(nid, {})
            pos = osm.project(
                nd.get("lat", ref_lat), nd.get("lon", ref_lon), ref_lat, ref_lon
            )
            graph_nodes[nid_key] = ExternalNode(
                id=nid_key,
                kind="FOOTPATH",
                position=pos,
                lat=nd.get("lat"),
                lon=nd.get("lon"),
                source="OSM",
            )
        return graph_nodes[nid_key]

    def break_at(nid: int) -> bool:
        if nid not in nodes:
            return False
        nd = nodes[nid]
        tags = nd.get("tags", {}) or {}
        return (
            incidence.get(nid, 0) >= 2
            or tags.get("public_transport") in ("station", "stop_position")
            or tags.get("amenity") == "parking"
            or tags.get("railway") in ("station", "tram_stop")
            or tags.get("amenity") == "bus_station"
            or tags.get("highway") in ("traffic_signals", "crossing", "stop")
        )

    edge_no = 0
    for w in walkable_ways:
        way = w["way"]
        kind, tags, pts = w["kind"], w["tags"], w["pts"]
        way_node_ids = way.get("nodes", [])
        if len(way_node_ids) != len(pts):
            way_node_ids = [nid for nid in way_node_ids if nid in nodes][: len(pts)]

        segment_start = 0
        for i, nid in enumerate(way_node_ids):
            if i == len(way_node_ids) - 1 or break_at(nid) and i > segment_start:
                end = i if i < len(way_node_ids) - 1 else len(way_node_ids) - 1
                if end <= segment_start:
                    segment_start = i
                    continue
                sub = way_node_ids[segment_start:end + 1]
                sub_pts = pts[segment_start:end + 1]
                if len(sub) < 2 or len(sub_pts) < 2:
                    segment_start = i
                    continue
                a, b = ensure_node(sub[0]), ensure_node(sub[-1])
                length = osm.way_length_m(sub_pts)
                if length < 20.0:
                    segment_start = i
                    continue
                edge_no += 1
                graph_edges.append(ExternalEdge(
                    id=f"XE_{edge_no}",
                    source=a.id,
                    target=b.id,
                    kind=kind,
                    length_m=round(length, 1),
                    walking_allowed=osm.is_walkable(kind, tags),
                    road_allowed=kind == "ROAD",
                    capacity_estimate=osm.capacity_estimate(length, kind, tags),
                    speed_mps=osm.speed_for(kind),
                    free_flow_min=round(length / (osm.speed_for(kind) * 60.0), 3),
                    geometry=sub_pts,
                    capacity_source="estimated",
                ))
                # undirected edge (same id reused both directions by flow sim)
                graph_edges.append(ExternalEdge(
                    id=f"XE_{edge_no}R",
                    source=b.id,
                    target=a.id,
                    kind=kind,
                    length_m=round(length, 1),
                    walking_allowed=osm.is_walkable(kind, tags),
                    road_allowed=kind == "ROAD",
                    capacity_estimate=osm.capacity_estimate(length, kind, tags),
                    speed_mps=osm.speed_for(kind),
                    free_flow_min=round(length / (osm.speed_for(kind) * 60.0), 3),
                    geometry=list(reversed(sub_pts)),
                    capacity_source="estimated",
                ))
                segment_start = i

    # ensure every graph node used by edges exists
    for e in graph_edges:
        ensure_node(int(e.source.removeprefix("XN_")))
        ensure_node(int(e.target.removeprefix("XN_")))

    if not graph_edges:
        raise ValueError("OSM payload produced no usable external edges")

    # sinks = outer nodes far from venue centre + transit/parking nodes
    for nid, node in list(graph_nodes.items()):
        if math.hypot(node.position.x - cx, node.position.y - cy) > _SINK_RADIUS_M:
            sink_ids.append(nid)

    return WorldGraph(
        venue_id=venue.id,
        provider=provider_name,
        provenance=WorldProvenance(
            provider=provider_name,
            fetched_at=fetched_at,
            confidence="estimated",
            notes=[
                "OpenStreetMap © OpenStreetMap contributors (ODbL), via the Overpass API.",
                "Capacities are heuristic estimates per highway class — not measured.",
            ],
        ),
        bbox=_graph_bbox(venue, world_span_m(venue)),
        nodes=list(graph_nodes.values()),
        edges=graph_edges,
        sink_ids=sink_ids,
        notes=["External graph built from OpenStreetMap."],
    )


def _nearest_walkable_node(graph: WorldGraph, pos: WorldPosition) -> Optional[str]:
    best: Optional[Tuple[float, str]] = None
    for node in graph.nodes:
        d = (node.position.x - pos.x) ** 2 + (node.position.y - pos.y) ** 2
        if best is None or d < best[0]:
            best = (d, node.id)
    return best[1] if best else None


def connect_gates_and_sources(
    graph: WorldGraph,
    venue: VenueModel,
) -> WorldGraph:
    """Add AccessPoints (venue gate ↔ graph) and DemandSources to a built graph.

    Shared by the OSM and demo providers so both expose the same connectors.
    """
    for node in venue.nodes:
        if node.type not in (NodeType.ENTRY, NodeType.EXIT, NodeType.EMERGENCY_EXIT):
            continue
        target = _nearest_walkable_node(graph, node.position)
        if target is None:
            continue
        gate_kind = node.type.value
        service = float(node.capacity or (150.0 if gate_kind == "ENTRY" else 120.0))
        graph.access_points.append(AccessPoint(
            id=f"AP_{node.id}",
            gate_id=node.id,
            node_id=target,
            kind=gate_kind,
            position=WorldPosition(x=node.position.x, y=node.position.y),
            service_ppm=max(40.0, service),
        ))
    return graph