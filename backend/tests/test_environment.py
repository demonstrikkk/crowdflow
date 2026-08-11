"""External environment + road-network congestion tests (no network needed)."""

import pytest

from app.engine.environment import (
    ExternalCongestion,
    build_bundled_environment,
    fetch_live_environment,
    resolve_environment,
    venue_location,
)
from app.engine.simulator import SimulationEngine
from app.engine.venue import VenueGraph
from app.models import VenueModel


@pytest.fixture
def venue():
    from app.storage import storage
    return storage.get_venue("unity_arena")


@pytest.fixture
def env(venue):
    return build_bundled_environment(venue)


def test_bundled_environment_shape(env):
    assert env.source == "BUNDLED"
    assert len(env.roads) >= 12          # ring + arterials + feeders
    assert len(env.junctions) == 4
    assert len(env.transit) == 1
    assert len(env.parking) == 1
    b = env.bbox
    assert b["max_x"] > b["min_x"] and b["max_y"] > b["min_y"]


def test_bundled_ring_closed(env):
    ring = {r.id: r for r in env.roads if r.kind == "RING"}
    assert set(ring) == {"R_SOUTH", "R_EAST", "R_NORTH", "R_WEST"}
    chain = {}
    for r in ring.values():
        chain[r.from_node] = r.to_node
    node = ring["R_SOUTH"].from_node
    visited = []
    for _ in range(4):
        visited.append(node)
        node = chain[node]
    assert len(set(visited)) == 4 and node == visited[0]


def test_bundled_feeder_roads_touch_every_gate(env, venue):
    gates = {n.id for n in venue.nodes if n.type.value in ("ENTRY", "EXIT", "EMERGENCY_EXIT")}
    touched = set()
    for r in env.roads:
        if r.from_node in gates:
            touched.add(r.from_node)
    assert gates == touched


def test_exit_mapping_known(env, venue):
    ext = ExternalCongestion(env, venue)
    known = {e.id for e in env.junctions} | {r.id for r in env.roads} | {
        t.id for t in env.transit
    } | {p.id for p in env.parking}
    exits = [n.id for n in venue.nodes if n.type.value == "EXIT"]
    assert exits, "expected demo exits"
    for x in exits:
        assert ext._exit_map[x] in known


def test_congestion_grows_and_drains(env, venue):
    ext = ExternalCongestion(env, venue)
    some_exit = next(n.id for n in venue.nodes if n.type.value == "EXIT")
    element = ext._exit_map[some_exit]
    for _ in range(60):
        ext.record_exit(some_exit, 10)
    st = ext.state()
    assert st.elements[element].people_accumulated > 0
    assert st.elements[element].congestion > 0
    assert st.summary
    backlog_before = ext.accumulated[element]
    for _ in range(60):
        ext.step(1.0)
    assert ext.accumulated[element] < backlog_before


def test_unknown_exit_ignored(env, venue):
    ext = ExternalCongestion(env, venue)
    ext.record_exit("NOT_A_NODE", 999)
    assert not ext.accumulated


def test_venue_location_from_metadata():
    from app.storage import storage

    v = storage.get_venue("unity_arena").model_copy(
        update={"metadata": {"location": {"lat": 48.85, "lon": 2.35}}}
    )
    assert venue_location(v) == (48.85, 2.35)


def test_fetch_live_returns_none_on_failure(venue, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr("app.engine.environment._http_get", boom)
    assert fetch_live_environment(venue, 48.85, 2.35, timeout_s=1) is None


def test_fetch_live_parses_osm(venue, monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"elements": [
                {
                    "type": "way", "id": 101,
                    "nodes": [1, 2, 3],
                    "tags": {"highway": "secondary", "name": "Rue Test", "lanes": "2"},
                },
                {"type": "node", "id": 1, "lat": 48.85, "lon": 2.350},
                {"type": "node", "id": 2, "lat": 48.851, "lon": 2.352},
                {"type": "node", "id": 3, "lat": 48.852, "lon": 2.354},
                {"type": "node", "id": 50, "lat": 48.8505, "lon": 2.351,
                 "tags": {"public_transport": "stop_position", "name": "Test Stop"}},
                {"type": "node", "id": 60, "lat": 48.849, "lon": 2.349,
                 "tags": {"amenity": "parking", "capacity": "300"}},
            ]}

    monkeypatch.setattr("app.engine.environment._http_get", lambda *a, **k: FakeResp())
    live = fetch_live_environment(venue, 48.85, 2.35, timeout_s=1)
    assert live is not None
    assert live.source == "LIVE_OSM"
    assert any(r.id == "R_101" for r in live.roads)
    assert live.roads[0].kind == "MAJOR"
    assert len(live.transit) == 1 and live.transit[0].kind == "BUS"
    assert len(live.parking) == 1 and live.parking[0].capacity == 300


def test_resolve_environment_falls_back_when_offline(venue):
    env = resolve_environment(venue, force_live=False)
    assert env.source == "BUNDLED"
    assert any("Bundled" in n for n in env.notes)


def test_environment_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/environment", params={"venue_id": "unity_arena"})
    assert r.status_code == 200
    body = r.json()
    assert body["venue_id"] == "unity_arena"
    assert body["source"] == "BUNDLED"
    assert len(body["roads"]) > 0

    r404 = client.get("/api/environment", params={"venue_id": "missing"})
    assert r404.status_code == 404


def test_refresh_falls_back_without_location(venue):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/environment/refresh", params={"venue_id": "unity_arena"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "BUNDLED"
    assert any("lat/lon" in n for n in body["notes"])


def test_simulation_state_includes_external():
    from app.storage import storage
    from app.engine.routing import RoutingEngine

    scenario = storage.get_scenario("exit_surge")
    venue = storage.get_venue(scenario.venue_id)
    graph = VenueGraph(venue)
    engine = SimulationEngine(
        "sim_test_ext", scenario, graph, RoutingEngine(graph)
    )
    engine.play()
    for _ in range(30):
        engine.tick()
    st = engine.state()
    assert st.external is not None
    assert st.external.venue_id == venue.id
    assert st.external.elements
    assert all(st.external.elements[k].id == k for k in st.external.elements)
    # total accumulation is monotonic per element (drain may keep some at 0)
    assert st.external.risk.value in ("NORMAL", "ELEVATED", "HIGH", "CRITICAL")
