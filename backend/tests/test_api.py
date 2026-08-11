"""API smoke tests against the FastAPI app (venues, scenarios, simulation)."""

from fastapi.testclient import TestClient

from app.main import app
from app.routers.simulation import SIMULATIONS

client = TestClient(app)


def _run_sim(scenario_id: str = "normal") -> str:
    r = client.post("/api/simulation/run", json={"scenario_id": scenario_id})
    assert r.status_code == 200
    state = r.json()
    assert state["sim_id"]
    assert state["metrics"]["in_venue"] > 0
    return state["sim_id"]


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["scenarios_loaded"] >= 6
    assert body["venues_loaded"] >= 1


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["system"] == "CROWD_FLOW_OPTIMISER"


def test_default_venue():
    r = client.get("/api/venue")
    assert r.status_code == 200
    assert r.json()["id"] == "unity_arena"


def test_venues_and_scenarios_listed():
    assert client.get("/api/venues").status_code == 200
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()}
    assert {"normal", "exit_surge", "gate_overload"} <= ids


def test_run_simulation():
    sim_id = _run_sim()
    assert client.get(f"/api/simulation/{sim_id}").status_code == 200


def test_step_and_state():
    sim_id = _run_sim()
    r = client.post(f"/api/simulation/{sim_id}/step", json={"steps": 30})
    assert r.status_code == 200
    state = r.json()
    assert state["metrics"]["t_min"] > 0
    assert client.get(f"/api/simulation/{sim_id}").status_code == 200
    assert client.get("/api/simulation/nope").status_code == 404


def test_emergency_endpoint():
    sim_id = _run_sim()
    r = client.post(f"/api/simulation/{sim_id}/emergency", json={"active": True})
    assert r.status_code == 200
    assert r.json()["emergency_active"] is True


def test_optimize_endpoint():
    sim_id = _run_sim()
    client.post(f"/api/simulation/{sim_id}/step", json={"steps": 120})
    r = client.post(f"/api/simulation/{sim_id}/optimize", json={})
    assert r.status_code == 200
    body = r.json()
    assert len(body["candidates"]) >= 1
    assert "intervention" in body["candidates"][0]
    assert body["candidates"][0]["intervention"]["id"]


def test_apply_intervention_endpoint():
    sim_id = _run_sim()
    r = client.post(f"/api/simulation/{sim_id}/apply", json={
        "id": "api_test",
        "type": "ADJUST_ROUTING",
        "description": "api smoke",
        "parameters": {"congestion_penalty_weight": 8.0},
    })
    assert r.status_code == 200


def test_recommend_and_emergency_route():
    sim_id = _run_sim()
    r = client.post(f"/api/simulation/{sim_id}/recommend-route", json={
        "source": "GATE_A", "destination": "SEAT_E",
    })
    assert r.status_code == 200
    assert r.json()["path"][-1] == "SEAT_E"
    r = client.post(f"/api/simulation/{sim_id}/emergency-route", json={
        "node_id": "CONCOURSE_E",
    })
    assert r.status_code == 200
    assert r.json()["path"][-1].startswith("EMERGENCY_")


def test_play_pause_reset_speed():
    sim_id = _run_sim()
    assert client.post(f"/api/simulation/{sim_id}/play").json()["status"] == "RUNNING"
    assert client.post(f"/api/simulation/{sim_id}/pause").json()["status"] == "PAUSED"
    assert client.post(f"/api/simulation/{sim_id}/speed", json={"speed": 10}).json()["speed"] == 10
    state = client.post(f"/api/simulation/{sim_id}/reset")
    assert state.status_code == 200
    assert state.json()["metrics"]["total_spawned"] == 0


def test_optimize_requires_ticks():
    r = client.post("/api/simulation/run", json={"scenario_id": "normal"})
    sim_id = r.json()["sim_id"]
    SIMULATIONS[sim_id].reset()
    r = client.post(f"/api/simulation/{sim_id}/optimize", json={})
    assert r.status_code == 422


def test_unknown_scenario_404():
    r = client.post("/api/simulation/run", json={"scenario_id": "missing"})
    assert r.status_code == 404
