"""Map provider abstraction.

``MapProvider`` is the seam that lets CrowdFlow swap OSM / Mapbox / MapTiler /
Google / HERE without touching the spatial model. The world graph (nodes,
edges, access points, demand sources) is provider-agnostic — providers only
differ in *where the raw geography comes from*.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from ..engine.environment import build_bundled_environment, venue_location
from ..models import VenueModel, WorldPosition
from . import cache, osm
from .ingest import (
    _graph_bbox,
    _nearest_walkable_node,
    connect_gates_and_sources,
    ingest_osm,
    world_span_m,
)
from .models import DemandSource, ExternalEdge, ExternalNode, WorldGraph, WorldProvenance

logger = logging.getLogger("crowdflow.world")

LIVE_ENABLED = os.getenv("OSM_LIVE", "").strip().lower() in ("1", "true", "yes", "on")


class MapProvider(ABC):
    """Build a normalized WorldGraph for a venue from a raw geographic source."""

    name: str = "provider"

    @abstractmethod
    def build(self, venue: VenueModel) -> WorldGraph:
        ...


class DemoProvider(MapProvider):
    """Deterministic offline world graph derived from the bundled environment.

    Mirror of the bundled road network (ring + arterials + gate feeders) plus
    transit/parking/walking demand origins. Always available — the app never
    silently claims real geography when using this.
    """

    name = "DEMO"

    # Purposeful stadium-arrival walking pace for the demo world (real stadium
    # approaches are 1-2 km and take ~5-12 minutes; 1.3 m/s made every demo
    # route 15-35 minutes which starves the venue coupling). Still DEMO data.
    _DEMO_SPEED_MPS = 1.8

    _PERSON_CAP = {"ARTERIAL": 700, "MAJOR": 500, "LOCAL": 300, "ACCESS": 150, "RING": 500}

    def build(self, venue: VenueModel) -> WorldGraph:
        env = build_bundled_environment(venue)
        nodes: dict = {}
        edges: list = []

        def node(nid: str, kind: str, pos: WorldPosition, name: Optional[str] = None) -> ExternalNode:
            if nid not in nodes:
                nodes[nid] = ExternalNode(
                    id=nid, kind=kind, position=pos, name=name, source="DEMO"
                )
            return nodes[nid]

        for j in env.junctions:
            node(j.id, "ROAD", j.position, j.name)
        for t in env.transit:
            node(f"T_{t.id}", "TRANSIT", t.position, t.name)
        for p in env.parking:
            node(f"P_{p.id}", "PARKING", p.position, p.name)

        # materialise nodes referenced by roads (outer arterial endpoints, mids)
        for r in env.roads:
            if not r.points:
                continue
            if r.from_node:
                node(r.from_node, "ROAD", r.points[0])
            if r.to_node:
                node(r.to_node, "ROAD", r.points[-1])

        edge_no = 0
        road_nodes = [nid for nid, n in nodes.items() if n.kind == "ROAD"]

        def connector(a: str, b: str, geom: list) -> None:
            nonlocal edge_no
            length = 0.0
            for i in range(1, len(geom)):
                dx = geom[i].x - geom[i - 1].x
                dy = geom[i].y - geom[i - 1].y
                length += (dx * dx + dy * dy) ** 0.5
            length = max(length, 5.0)
            for source, target, g in ((a, b, geom), (b, a, list(reversed(geom)))):
                edge_no += 1
                edges.append(ExternalEdge(
                    id=f"XD_{edge_no}",
                    source=source,
                    target=target,
                    kind="GATE_LINK",
                    length_m=round(length, 1),
                    walking_allowed=True,
                    road_allowed=False,
                    capacity_estimate=150.0,
                    speed_mps=self._DEMO_SPEED_MPS,
                    free_flow_min=round(length / (self._DEMO_SPEED_MPS * 60.0), 3),
                    geometry=g,
                    capacity_source="estimated",
                ))

        # link transit / parking demand origins into the road network
        for t in env.transit:
            near = min(road_nodes, key=lambda nid: (nodes[nid].position.x - t.position.x) ** 2
                       + (nodes[nid].position.y - t.position.y) ** 2)
            connector(f"T_{t.id}", near, [t.position, nodes[near].position])
        for p in env.parking:
            near = min(road_nodes, key=lambda nid: (nodes[nid].position.x - p.position.x) ** 2
                       + (nodes[nid].position.y - p.position.y) ** 2)
            connector(f"P_{p.id}", near, [p.position, nodes[near].position])

        for r in env.roads:
            if not r.points or not r.from_node or not r.to_node:
                continue
            cap = self._PERSON_CAP.get(r.kind, 300)
            length = r.length_m
            for source, target, geom in (
                (r.from_node, r.to_node, r.points),
                (r.to_node, r.from_node, list(reversed(r.points))),
            ):
                edge_no += 1
                edges.append(ExternalEdge(
                    id=f"XD_{edge_no}",
                    source=source,
                    target=target,
                    kind="STREET",
                    length_m=round(length, 1),
                    walking_allowed=True,
                    road_allowed=r.kind in ("ARTERIAL", "MAJOR", "RING"),
                    capacity_estimate=float(cap),
                    speed_mps=self._DEMO_SPEED_MPS,
                    free_flow_min=round(length / (self._DEMO_SPEED_MPS * 60.0), 3),
                    geometry=geom,
                    capacity_source="estimated",
                ))

        graph = WorldGraph(
            venue_id=venue.id,
            provider=self.name,
            provenance=WorldProvenance(
                provider=self.name,
                confidence="demo",
                notes=[
                    "Demo world graph generated deterministically from the venue "
                    "footprint (ring road + arterial approaches + gate feeders). "
                    "Not real-world geography.",
                    "Approach pace set to 1.8 m/s (purposeful arrival) so stadium "
                    "routes are ~5-15 min rather than 15-35 min.",
                ],
            ),
            bbox=_graph_bbox(venue, world_span_m(venue)),
            nodes=list(nodes.values()),
            edges=edges,
            sink_ids=[
                nid for nid in nodes
                if nid.startswith("NODE_") or nid.startswith("T_") or nid.startswith("P_")
            ],
            notes=["Offline demo graph — set OSM_LIVE=1 and a venue location to use real OSM data."],
        )

        # structural demand origins
        for t in env.transit:
            graph.demand_sources.append(DemandSource(
                id=f"DS_{t.id}", kind="METRO", name=t.name,
                node_id=f"T_{t.id}", position=t.position, capacity=2000, share=0.4,
                data_source="SIMULATED",
            ))
        for p in env.parking:
            graph.demand_sources.append(DemandSource(
                id=f"DS_{p.id}", kind="PARKING", name=p.name,
                node_id=f"P_{p.id}", position=p.position, capacity=p.capacity, share=0.25,
                data_source="SIMULATED",
            ))
        # walking origin at the far outer node
        outer = next((nid for nid in nodes if nid.startswith("NODE_")), None)
        if outer:
            graph.demand_sources.append(DemandSource(
                id="DS_WALK_01", kind="WALKING", name="Walking catchment (drop-off)",
                node_id=outer, position=nodes[outer].position, capacity=1000, share=0.2,
                data_source="SIMULATED",
            ))

        connect_gates_and_sources(graph, venue)
        return graph


class OSMProvider(MapProvider):
    """Real external geography from OpenStreetMap via the Overpass API.

    Falls back to the demo graph when the venue has no location, Overpass is
    unreachable, or the area returns nothing usable — always with a provenance
    note. Raw payloads and normalized graphs are cached on disk (see cache.py).
    """

    name = "OSM"

    def build(self, venue: VenueModel) -> WorldGraph:
        loc = venue_location(venue)
        if loc is None:
            graph = DemoProvider().build(venue)
            graph.notes.append(
                "OSM requested but the venue has no lat/lon (venue metadata.location "
                "or OSM_LAT/OSM_LON) — using the demo world graph."
            )
            graph.provenance.notes.append("Fell back to demo: no venue location.")
            return graph

        ref_lat, ref_lon = loc
        span = world_span_m(venue)
        bbox = _graph_bbox(venue, span)

        raw = cache.get_raw_osm(venue.id, self.name, bbox)
        if raw is None:
            raw = osm.overpass_query(ref_lat, ref_lon, span)
            if raw is not None:
                cache.put_raw_osm(venue.id, self.name, bbox, raw)
        if raw is None:
            graph = DemoProvider().build(venue)
            graph.notes.append(
                "OSM fetch failed or returned nothing usable — using the demo "
                "world graph."
            )
            graph.provenance.notes.append("Fell back to demo: Overpass unreachable/empty.")
            return graph

        cached_graph = cache.get_graph(venue.id, self.name, bbox)
        if cached_graph is not None:
            try:
                graph = WorldGraph.model_validate(cached_graph)
                connect_gates_and_sources(graph, venue)
                graph.provenance.notes.insert(0, "Cached (24h TTL) — not re-fetched.")
                return graph
            except Exception:  # noqa: BLE001 - stale/invalid cache, rebuild
                logger.warning("world graph cache invalid; rebuilding")

        try:
            graph = ingest_osm(
                raw, venue, ref_lat, ref_lon,
                provider_name=self.name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - never block on ingest
            logger.warning("OSM ingest failed: %s", exc)
            graph = DemoProvider().build(venue)
            graph.notes.append(f"OSM ingest failed ({exc}) — using the demo world graph.")
            graph.provenance.notes.append(f"Fell back to demo: ingest error {exc!r}.")
            return graph

        connect_gates_and_sources(graph, venue)
        cache.put_graph(venue.id, self.name, bbox, graph.model_dump(mode="json"))
        return graph


def resolve_world_graph(venue: VenueModel, force_live: bool = False) -> WorldGraph:
    """Best-available world graph: OSM when enabled/reachable, else demo.

    ``force_live`` is used by the refresh endpoint so a user can explicitly
    request real data regardless of the OSM_LIVE default.
    """
    provider: MapProvider
    if LIVE_ENABLED or force_live:
        provider = OSMProvider()
    else:
        provider = DemoProvider()
    graph = provider.build(venue)
    return graph
