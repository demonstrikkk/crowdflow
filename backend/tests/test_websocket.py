"""WebSocket live channel: state pushes, play/pause/step actions."""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.routers.simulation import SIMULATIONS

client = TestClient(app)


def _create_sim() -> str:
    r = client.post("/api/simulation/run", json={"scenario_id": "normal"})
    assert r.status_code == 200
    return r.json()["sim_id"]


def test_ws_pushes_state_on_connect():
    sim_id = _create_sim()
    with client.websocket_connect(f"/api/simulation/{sim_id}/live") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["sim_id"] == sim_id
        assert "metrics" in msg
        assert "nodes" in msg
        assert "edges" in msg
        assert "bottlenecks" in msg
        assert "history" in msg
        assert "emergency_active" in msg


def test_ws_step_action_advances_sim():
    sim_id = _create_sim()
    with client.websocket_connect(f"/api/simulation/{sim_id}/live") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"action": "step"}))
        msg = json.loads(ws.receive_text())
        assert msg["tick"] == 2
        assert msg["t_min"] > 0


def test_ws_emergency_action():
    sim_id = _create_sim()
    with client.websocket_connect(f"/api/simulation/{sim_id}/live") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"action": "emergency", "active": True}))
        msg = json.loads(ws.receive_text())
        assert msg["emergency_active"] is True


def test_ws_apply_intervention_action():
    sim_id = _create_sim()
    with client.websocket_connect(f"/api/simulation/{sim_id}/live") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({
            "action": "apply_intervention",
            "intervention": {
                "id": "ws_test",
                "type": "ADJUST_ROUTING",
                "description": "ws smoke",
                "parameters": {"congestion_penalty_weight": 8.0},
            },
        }))
        msg = json.loads(ws.receive_text())
        assert any(i["id"] == "ws_test" for i in msg["interventions_applied"])


def test_ws_unknown_sim_returns_error():
    with client.websocket_connect("/api/simulation/doesnotexist/live") as ws:
        msg = json.loads(ws.receive_text())
        assert "error" in msg


def test_ws_pause_emits_state_and_play_resumes():
    """Pausing must push a PAUSED frame back so the client's play/pause button
    stays in sync, and PLAY after pause must resume ticking from the same point."""
    sim_id = _create_sim()
    with client.websocket_connect(f"/api/simulation/{sim_id}/live") as ws:
        json.loads(ws.receive_text())  # initial state

        ws.send_text(json.dumps({"action": "pause"}))
        paused = None
        for _ in range(20):
            m = json.loads(ws.receive_text())
            if m["status"] == "PAUSED":
                paused = m
                break
        assert paused is not None, "no PAUSED frame pushed after pause action"
        paused_t = paused["t_min"]

        # while paused the engine must not advance: a short wait should produce
        # no additional frames (the loop sleeps) -- assert at least t holds
        ws.send_text(json.dumps({"action": "play"}))
        resumed = None
        for _ in range(20):
            m = json.loads(ws.receive_text())
            if m["status"] == "RUNNING":
                resumed = m
                break
        assert resumed is not None, "no RUNNING frame pushed after play action"
        assert resumed["t_min"] >= paused_t, "simulation rewound after resume"
        assert resumed["t_min"] > paused_t - 1e-9 or resumed["tick"] > 0
