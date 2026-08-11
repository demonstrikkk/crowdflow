"""External environment + road-network congestion (brief section 20).

The digital twin does not stop at the venue walls. This module provides:

  * a deterministic *bundled* surrounding environment (ring road, arterial and
    feeder roads, junctions, a transit stop and a parking area) generated from
    the venue footprint, so the app works fully offline;
  * an optional *live* OSM fetch (Overpass API) enabled with OSM_LIVE=1 that
    replaces the bundled roads when reachable and falls back to bundled data
    with a note when offline / unconfigured / empty;
  * a deterministic external-congestion model: people leaving an exit flow onto
    the nearest road element, which drains at a fixed outflow. Congestion,
    queue and clearance time are derived from the backlog. It is an operational
    estimate, never a traffic microsimulation.

Coordinate frame: environment geometry lives in the *venue* coordinate space
(venue units are treated as metres), so the frontend overlay aligns with the
venue canvas with no extra transform.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Dict, List, Optional

from ..models import (
    ExternalElementState,
    ExternalEnvironment,
    ExternalState,
    JunctionModel,
    ParkingAreaModel,
    RiskLevel,
    RoadSegmentModel,
    TransitStopModel,
    VenueModel,
    WorldPosition,
)
from .predictor import risk_level_from_score

logger = logging.getLogger("crowdflow.environment")

PERSONS_PER_VEH = 1.7
LIVE_ENABLED = os.getenv("OSM_LIVE", "").strip().lower() in ("1", "true", "yes", "on")
LIVE_TIMEOUT_S = 6.0
LIVE_MIN_INTERVAL_S = 60.0

_ROAD_SPEED = {"ARTERIAL": 70.0, "MAJOR": 55.0, "LOCAL": 40.0, "ACCESS": 30.0, "RING": 55.0}
_ROAD_LANES = {"ARTERIAL": 4, "MAJOR": 2, "LOCAL": 2, "ACCESS": 1, "RING": 2}
_ROAD_CAP = {"ARTERIAL": 1800.0, "MAJOR": 1400.0, "LOCAL": 800.0, "ACCESS": 500.0, "RING": 1400.0}

# outflow (persons/min) per element kind; transit drains fast (boarding),
# parking slowly (people walking to/from cars)
_DRAIN_PERSONS_PER_MIN = {
    "ROAD": 1.0,
    "JUNCTION": 0.7,
    "TRANSIT": 120.0,
    "PARKING": 10.0,
}


# --------------------------------------------------------------------------- #
#  Bundled (offline) environment generator
# --------------------------------------------------------------------------- #
def build_bundled_environment(venue: VenueModel) -> ExternalEnvironment:
    """Deterministically lay out a road network around the venue footprint.

    The venue occupies [0..width, 0..height]; a square ring road wraps it with
    an approach junction per side and an arterial leading outward from each
    junction, so every gate group drains onto a nearby element.
    """
    W, H = venue.width, venue.height
    ring_gap = min(W, H) * 0.55
    out_gap = ring_gap + min(W, H) * 0.45

    # ring corners (world = venue coords)
    j_sw = WorldPosition(x=-ring_gap, y=-ring_gap)
    j_se = WorldPosition(x=W + ring_gap, y=-ring_gap)
    j_ne = WorldPosition(x=W + ring_gap, y=H + ring_gap)
    j_nw = WorldPosition(x=-ring_gap, y=H + ring_gap)

    # outer endpoints of the arterial approaches (the wider network)
    a_sw = WorldPosition(x=-out_gap, y=-out_gap)
    a_se = WorldPosition(x=W + out_gap, y=-out_gap)
    a_ne = WorldPosition(x=W + out_gap, y=H + out_gap)
    a_nw = WorldPosition(x=-out_gap, y=H + out_gap)

    junctions = [
        JunctionModel(id="J_SW", name="Southwest interchange", position=j_sw, kind="SIGNAL"),
        JunctionModel(id="J_SE", name="Southeast interchange", position=j_se, kind="ROUNDABOUT"),
        JunctionModel(id="J_NE", name="Northeast interchange", position=j_ne, kind="SIGNAL"),
        JunctionModel(id="J_NW", name="Northwest interchange", position=j_nw, kind="ROUNDABOUT"),
    ]

    def road(rid: str, name: str, kind: str, a, b) -> RoadSegmentModel:
        length = math.hypot(b.x - a.x, b.y - a.y)
        return RoadSegmentModel(
            id=rid,
            name=name,
            kind=kind,
            from_node="",
            to_node="",
            lanes=_ROAD_LANES[kind],
            speed_limit_kmh=_ROAD_SPEED[kind],
            capacity_veh_h=_ROAD_CAP[kind],
            length_m=round(length, 1),
            points=[WorldPosition(x=a.x, y=a.y), WorldPosition(x=b.x, y=b.y)],
        )

    roads = [
        # ring road
        road("R_SOUTH", "Ring Road South", "RING", j_sw, j_se),
        road("R_EAST", "Ring Road East", "RING", j_se, j_ne),
        road("R_NORTH", "Ring Road North", "RING", j_ne, j_nw),
        road("R_WEST", "Ring Road West", "RING", j_nw, j_sw),
        # arterials to the wider network
        road("A_SW", "Southwest Arterial", "ARTERIAL", a_sw, j_sw),
        road("A_SE", "Southeast Arterial", "ARTERIAL", a_se, j_se),
        road("A_NE", "Northeast Arterial", "ARTERIAL", a_ne, j_ne),
        road("A_NW", "Northwest Arterial", "ARTERIAL", a_nw, j_nw),
    ]
    ring_conns = {
        "R_SOUTH": ("J_SW", "J_SE"),
        "R_EAST": ("J_SE", "J_NE"),
        "R_NORTH": ("J_NE", "J_NW"),
        "R_WEST": ("J_NW", "J_SW"),
    }
    art_conns = {
        "A_SW": ("NODE_OSW", "J_SW"),
        "A_SE": ("NODE_OSE", "J_SE"),
        "A_NE": ("NODE_ONE", "J_NE"),
        "A_NW": ("NODE_ONW", "J_NW"),
    }
    for r in roads:
        if r.id in ring_conns:
            r.from_node, r.to_node = ring_conns[r.id]
        elif r.id in art_conns:
            r.from_node, r.to_node = art_conns[r.id]

    # feeder roads from the venue gates to the nearest ring corner
    feeder_no = 0
    for node in venue.nodes:
        if node.type.value not in ("ENTRY", "EXIT", "EMERGENCY_EXIT"):
            continue
        corner = min(
            junctions,
            key=lambda j: (j.position.x - node.position.x) ** 2
            + (j.position.y - node.position.y) ** 2,
        )
        midpoint = WorldPosition(
            x=(node.position.x + corner.position.x) / 2,
            y=(node.position.y + corner.position.y) / 2,
        )
        feeder_no += 1
        fid = f"F{feeder_no:02d}"
        feeder = road(fid, f"Venue access {fid}", "ACCESS", node.position, midpoint)
        roads.append(feeder)
        roads.append(
            RoadSegmentModel(
                id=f"{fid}B",
                name=f"Venue access {fid}",
                kind="ACCESS",
                from_node="",
                to_node="",
                lanes=1,
                speed_limit_kmh=30.0,
                capacity_veh_h=500.0,
                length_m=round(math.hypot(midpoint.x - corner.position.x, midpoint.y - corner.position.y), 1),
                points=[midpoint, corner.position],
            )
        )
        feeder.from_node, feeder.to_node = node.id, f"MID_{fid}"
        roads[-1].from_node, roads[-1].to_node = f"MID_{fid}", corner.id

    transit = TransitStopModel(
        id="TRAM_NE",
        name="North-east tram stop",
        position=WorldPosition(x=W + ring_gap * 0.7, y=H + ring_gap * 0.7),
        kind="TRAM",
    )
    parking = ParkingAreaModel(
        id="PK_SW",
        name="South-west car park",
        position=WorldPosition(x=-ring_gap * 0.7, y=-ring_gap * 0.7),
        capacity=1200,
    )

    return ExternalEnvironment(
        venue_id=venue.id,
        source="BUNDLED",
        origin=None,
        bbox={
            "min_x": -out_gap,
            "min_y": -out_gap,
            "max_x": W + out_gap,
            "max_y": H + out_gap,
        },
        roads=roads,
        junctions=junctions,
        transit=[transit],
        parking=[parking],
        notes=[
            "Bundled offline road network generated from the venue footprint "
            "(ring road + arterial approaches + gate feeder roads).",
            "Set OSM_LIVE=1 and provide a venue location to replace it with live "
            "OpenStreetMap data.",
        ],
    )


# --------------------------------------------------------------------------- #
#  External congestion model
# --------------------------------------------------------------------------- #
class ExternalCongestion:
    """Deterministic backlog/drain model over environment elements."""

    def __init__(self, env: ExternalEnvironment, venue: VenueModel):
        self.env = env
        self.venue = venue
        self.accumulated: Dict[str, float] = {}
        self._drain: Dict[str, float] = {}
        for road in env.roads:
            base = road.capacity_veh_h / 60.0 * PERSONS_PER_VEH
            self._drain[road.id] = max(4.0, base * _DRAIN_PERSONS_PER_MIN["ROAD"])
        for j in env.junctions:
            self._drain[j.id] = max(6.0, 1400.0 / 60.0 * PERSONS_PER_VEH * _DRAIN_PERSONS_PER_MIN["JUNCTION"])
        for t in env.transit:
            self._drain[t.id] = _DRAIN_PERSONS_PER_MIN["TRANSIT"]
        for p in env.parking:
            self._drain[p.id] = _DRAIN_PERSONS_PER_MIN["PARKING"]
        self._exit_map = self._map_nodes("EXIT", env)
        self._entry_map = self._map_nodes("ENTRY", env)

    # ------------------------------------------------------------------ #
    def _map_nodes(self, node_type: str, env: ExternalEnvironment) -> Dict[str, str]:
        """Nearest element (by type priority) for each gate node of `node_type`."""
        candidates: List[tuple] = [
            (e.id, e.position, "JUNCTION") for e in env.junctions
        ]
        candidates += [
            (r.id, r.points[0] if r.points else WorldPosition(x=0, y=0), "ROAD")
            for r in env.roads
            if r.kind in ("ARTERIAL", "RING")
        ]
        candidates += [(t.id, t.position, "TRANSIT") for t in env.transit]
        candidates += [(p.id, p.position, "PARKING") for p in env.parking]

        mapping: Dict[str, str] = {}
        for node in self.venue.nodes:
            if node.type.value != node_type:
                continue
            best = min(
                candidates,
                key=lambda c: (c[1].x - node.position.x) ** 2 + (c[1].y - node.position.y) ** 2,
            )
            mapping[node.id] = best[0]
        return mapping

    def record_exit(self, node_id: str, people: float) -> None:
        element = self._exit_map.get(node_id)
        if element is None:
            return
        self.accumulated[element] = self.accumulated.get(element, 0.0) + people

    def record_arrival(self, node_id: str, people: float) -> None:
        element = self._entry_map.get(node_id)
        if element is None:
            return
        self.accumulated[element] = self.accumulated.get(element, 0.0) + people

    def step(self, dt_min: float) -> None:
        if dt_min <= 0:
            return
        for element, backlog in self.accumulated.items():
            drain = self._drain.get(element, 0.0)
            if drain <= 0:
                continue
            drained = drain * dt_min
            self.accumulated[element] = max(0.0, backlog - drained)

    def reset(self) -> None:
        self.accumulated.clear()

    def copy(self) -> "ExternalCongestion":
        clone = ExternalCongestion(self.env, self.venue)
        clone.accumulated = dict(self.accumulated)
        return clone

    # ------------------------------------------------------------------ #
    def element_kind(self, element_id: str) -> str:
        for road in self.env.roads:
            if road.id == element_id:
                return "ROAD"
        for j in self.env.junctions:
            if j.id == element_id:
                return "JUNCTION"
        for t in self.env.transit:
            if t.id == element_id:
                return "TRANSIT"
        for p in self.env.parking:
            if p.id == element_id:
                return "PARKING"
        return "ROAD"

    def state(self) -> ExternalState:
        elements: Dict[str, ExternalElementState] = {}
        congested = 0
        worst = 0.0
        for element_id in sorted(set(list(self._drain.keys()) + list(self.accumulated.keys()))):
            backlog = self.accumulated.get(element_id, 0.0)
            drain = self._drain.get(element_id, 0.0) or 1.0
            congestion = min(1.0, backlog / max(1.0, drain * 20.0))
            clearance = round(backlog / drain, 1) if backlog > 0 else None
            if congestion > 0.35:
                congested += 1
            worst = max(worst, congestion)
            elements[element_id] = ExternalElementState(
                id=element_id,
                kind=self.element_kind(element_id),
                people_accumulated=int(round(backlog)),
                queue_veh=int(round(backlog / PERSONS_PER_VEH)),
                congestion=round(congestion, 3),
                clearance_min=clearance,
                risk=RiskLevel(risk_level_from_score(congestion)),
            )
        risk = RiskLevel(risk_level_from_score(worst))
        if congested:
            summary = (
                f"{congested} road element{'s' if congested != 1 else ''} congested "
                f"from exit flows ({risk.value} risk)"
            )
        else:
            summary = "No external road congestion"
        return ExternalState(
            venue_id=self.venue.id,
            source=self.env.source,
            elements=elements,
            congested_elements=congested,
            risk=risk,
            summary=summary,
        )


# --------------------------------------------------------------------------- #
#  Live OSM (Overpass) fetch - optional, graceful when absent
# --------------------------------------------------------------------------- #
def venue_location(venue: VenueModel) -> Optional[tuple]:
    """(lat, lon) for a venue: metadata > OSM_LAT/OSM_LON env."""
    meta = venue.model_dump().get("metadata") or {}
    if isinstance(meta.get("location"), dict):
        loc = meta["location"]
        if loc.get("lat") is not None and loc.get("lon") is not None:
            return float(loc["lat"]), float(loc["lon"])
    if os.getenv("OSM_LAT") and os.getenv("OSM_LON"):
        return float(os.getenv("OSM_LAT")), float(os.getenv("OSM_LON"))
    return None


def _project_to_venue(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Position:
    """Equirectangular metres around the reference point (venue coord frame)."""
    m_per_deg_lat = 110540.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(ref_lat))
    return WorldPosition(
        x=round((lon - ref_lon) * m_per_deg_lon, 1),
        y=round(-(lat - ref_lat) * m_per_deg_lat, 1),
    )


_KIND_BY_TAG = {
    "trunk": "ARTERIAL",
    "trunk_link": "ARTERIAL",
    "primary": "ARTERIAL",
    "primary_link": "ARTERIAL",
    "secondary": "MAJOR",
    "secondary_link": "MAJOR",
    "tertiary": "MAJOR",
    "tertiary_link": "MAJOR",
    "residential": "LOCAL",
    "service": "ACCESS",
    "living_street": "ACCESS",
}


def _http_get(url: str, params: dict, timeout_s: float):
    """Thin httpx wrapper so tests can monkeypatch a single seam."""
    import httpx

    return httpx.get(url, params=params, timeout=timeout_s)


def fetch_live_environment(
    venue: VenueModel,
    ref_lat: float,
    ref_lon: float,
    timeout_s: float = LIVE_TIMEOUT_S,
) -> Optional[ExternalEnvironment]:
    """Query Overpass for roads/transit/parking around the venue.

    Returns None on any failure so the caller can fall back to bundled data.
    Never blocks the simulation: bounded timeout, single request, no retries.
    """

    span_m = min(venue.width, venue.height) * 1.9 + 900.0
    dlat = span_m / 110540.0
    dlon = span_m / (111320.0 * math.cos(math.radians(ref_lat)))
    # the venue frame occupies [0..W, 0..H]; the projection places the reference
    # point (venue centre) at (0, 0), so shift back by half the frame to keep
    # live roads centred on the venue.
    off_x = venue.width / 2.0
    off_y = venue.height / 2.0
    query = f"""
    [out:json][timeout:{int(timeout_s)}];
    (
      way["highway"~"^(trunk|primary|secondary|tertiary|residential|service|living_street)"]
        ({ref_lat - dlat},{ref_lon - dlon},{ref_lat + dlat},{ref_lon + dlon});
      node["public_transport"~"^(station|stop_position)$"]
        ({ref_lat - dlat},{ref_lon - dlon},{ref_lat + dlat},{ref_lon + dlon});
      node["amenity"="parking"]
        ({ref_lat - dlat},{ref_lon - dlon},{ref_lat + dlat},{ref_lon + dlon});
    );
    out body;
    >;
    out skel qt;
    """
    try:
        resp = _http_get(
            "https://overpass-api.de/api/interpreter",
            {"data": query},
            timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - any failure falls back to bundled
        logger.warning("OSM fetch failed: %s", exc)
        return None

    elements = data.get("elements", [])
    ways = [e for e in elements if e.get("type") == "way"]
    nodes = {e["id"]: e for e in elements if e.get("type") == "node"}
    if not ways:
        logger.warning("OSM fetch returned no usable highway ways")
        return None

    # keep ways close enough to the venue to be relevant
    mid_lat = ref_lat
    mid_lon = ref_lon

    def way_positions(way: dict) -> Optional[List[Position]]:
        pts: List[Position] = []
        for nid in way.get("nodes", []):
            node = nodes.get(nid)
            if not node:
                continue
            p = _project_to_venue(node["lat"], node["lon"], mid_lat, mid_lon)
            pts.append(WorldPosition(x=p.x + off_x, y=p.y + off_y))
        return pts if len(pts) >= 2 else None

    roads: List[RoadSegmentModel] = []
    used: set = set()
    for way in ways[:120]:
        tags = way.get("tags", {})
        highway = tags.get("highway", "")
        kind = _KIND_BY_TAG.get(highway)
        if kind is None:
            continue
        pts = way_positions(way)
        if not pts:
            continue
        center = WorldPosition(
            x=sum(p.x for p in pts) / len(pts),
            y=sum(p.y for p in pts) / len(pts),
        )
        # skip ways more than ~1.2x the venue diagonal away
        if math.hypot(center.x - venue.width / 2, center.y - venue.height / 2) > span_m * 0.9:
            continue
        length = sum(
            math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(pts[:-1], pts[1:])
        )
        if length < 30:
            continue
        name = tags.get("name")
        rid = f"R_{way['id']}"
        roads.append(RoadSegmentModel(
            id=rid,
            name=name,
            kind=kind,
            from_node=f"N_{way['nodes'][0]}",
            to_node=f"N_{way['nodes'][-1]}",
            lanes=int(tags.get("lanes") or _ROAD_LANES[kind]),
            speed_limit_kmh=float(tags.get("maxspeed") or _ROAD_SPEED[kind]),
            capacity_veh_h=_ROAD_CAP[kind],
            length_m=round(length, 1),
            points=pts,
        ))

    if not roads:
        return None

    junctions: List[JunctionModel] = []
    transit: List[TransitStopModel] = []
    parking: List[ParkingAreaModel] = []
    seen_j: set = set()
    seen_t: set = set()
    seen_p: set = set()
    for e in elements:
        if e.get("type") != "node":
            continue
        tags = e.get("tags", {})
        p = _project_to_venue(e["lat"], e["lon"], mid_lat, mid_lon)
        pos = WorldPosition(x=p.x + off_x, y=p.y + off_y)
        pt_type = tags.get("public_transport")
        if pt_type and e["id"] not in seen_t:
            seen_t.add(e["id"])
            kind = "TRAM" if tags.get("tram") == "yes" else "BUS"
            if tags.get("railway") == "station":
                kind = "RAIL"
            transit.append(TransitStopModel(
                id=f"T_{e['id']}", name=tags.get("name") or "Transit stop",
                position=pos, kind=kind,
            ))
        if tags.get("amenity") == "parking" and e["id"] not in seen_p:
            seen_p.add(e["id"])
            parking.append(ParkingAreaModel(
                id=f"P_{e['id']}", name=tags.get("name") or "Car park",
                position=pos, capacity=int(tags.get("capacity") or 200),
            ))
        if e["id"] not in seen_j and (
            tags.get("highway") in ("traffic_signals", "stop")
            or tags.get("junction") == "roundabout"
        ):
            seen_j.add(e["id"])
            junctions.append(JunctionModel(
                id=f"J_{e['id']}", name=tags.get("name"),
                position=pos,
                kind="ROUNDABOUT" if tags.get("junction") == "roundabout" else "SIGNAL",
            ))

    bbox = {
        "min_x": min(p.x for r in roads for p in r.points),
        "min_y": min(p.y for r in roads for p in r.points),
        "max_x": max(p.x for r in roads for p in r.points),
        "max_y": max(p.y for r in roads for p in r.points),
    }
    return ExternalEnvironment(
        venue_id=venue.id,
        source="LIVE_OSM",
        origin=f"{ref_lat},{ref_lon}",
        bbox=bbox,
        roads=roads[:80],
        junctions=junctions[:40],
        transit=transit[:10],
        parking=parking[:10],
        notes=[
            "Roads from OpenStreetMap via the Overpass API, © OpenStreetMap "
            "contributors (ODbL). Geometry projected into the venue coordinate "
            "frame; capacities are heuristic defaults per highway class.",
            "Congestion below is an operational estimate from exit flows, not "
            "live traffic data.",
        ],
    )


def resolve_environment(
    venue: VenueModel,
    force_live: bool = False,
) -> ExternalEnvironment:
    """Bundled environment, upgraded to live OSM when enabled and reachable."""
    bundled = build_bundled_environment(venue)
    if not (LIVE_ENABLED or force_live):
        return bundled
    loc = venue_location(venue)
    if loc is None:
        bundled.notes.append("Live OSM requested but the venue has no lat/lon "
                             "(add venue metadata.location or set OSM_LAT/OSM_LON).")
        return bundled
    live = fetch_live_environment(venue, loc[0], loc[1])
    if live is None:
        bundled.notes.append("Live OSM fetch failed or returned nothing; fell back "
                             "to the bundled road network.")
        return bundled
    return live

