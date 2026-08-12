from __future__ import annotations

import asyncio
import json
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..engine.routing import RoutingEngine
from ..engine.simulator import TICK_DT_MIN, SimulationEngine
from ..engine.venue import VenueGraph
from ..models import (
    Bottleneck,
    Intervention,
    OptimizationResult,
    ScenarioModel,
    SimulationState,
    SimulationStatus,
    VenueModel,
)
from ..storage import storage

router = APIRouter()

SIMULATIONS: Dict[str, SimulationEngine] = {}


class RunRequest(BaseModel):
    scenario_id: str


class StepRequest(BaseModel):
    steps: int = 1


class EmergencyRequest(BaseModel):
    active: bool


class RouteRequest(BaseModel):
    sim_id: Optional[str] = None
    source: str
    destination: str


class EvacuationRequest(BaseModel):
    sim_id: Optional[str] = None
    node_id: str


# --------------------------------------------------------------------------- #
def register_engine(
    scenario: ScenarioModel,
    venue: VenueModel,
    sim_id: Optional[str] = None,
    seed: int = 42,
) -> SimulationEngine:
    """Build an engine from in-memory models and register it for live use."""
    graph = VenueGraph(venue)
    routing = RoutingEngine(graph)
    engine = SimulationEngine(
        sim_id or f"sim_{uuid.uuid4().hex[:8]}", scenario, graph, routing, seed=seed
    )
    SIMULATIONS[engine.sim_id] = engine
    return engine


def create_engine(scenario_id: str, sim_id: Optional[str] = None) -> SimulationEngine:
    scenario = storage.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")
    venue = storage.get_venue(scenario.venue_id)
    if venue is None:
        raise HTTPException(
            status_code=422, detail=f"Scenario references unknown venue '{scenario.venue_id}'"
        )
    return register_engine(scenario, venue, sim_id)


def _get_engine(sim_id: str) -> SimulationEngine:
    engine = SIMULATIONS.get(sim_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return engine


# --------------------------------------------------------------------------- #
@router.post("/run", response_model=SimulationState)
def run_simulation(request: RunRequest):
    engine = create_engine(request.scenario_id)
    engine.play()
    engine.tick()
    return engine.state()


class ScrubRequest(BaseModel):
    sim_id: str
    target_t_min: float = 0.0


@router.post("/scrub", response_model=SimulationState)
def scrub_to(req: ScrubRequest):
    """Fast-forward a paused simulation to a target simulation time deterministically.

    Resets the engine to t=0 keeping the same scenario/seed, then ticks
    forward to target_t_min. The engine is left in PAUSED state so the
    caller can inspect the result before resuming live playback.
    """
    engine = _get_engine(req.sim_id)
    target_ticks = max(0, int(req.target_t_min / TICK_DT_MIN))
    engine.reset()
    engine.play()
    for _ in range(target_ticks):
        engine.tick()
    engine.pause()
    return engine.state()




@router.get("/{sim_id}", response_model=SimulationState)
def get_simulation_state(sim_id: str):
    return _get_engine(sim_id).state()


@router.get("/{sim_id}/bottlenecks", response_model=List[Bottleneck])
def get_bottlenecks(sim_id: str):
    return _get_engine(sim_id).bottlenecks()


@router.post("/{sim_id}/step", response_model=SimulationState)
def step_simulation(sim_id: str, request: StepRequest):
    engine = _get_engine(sim_id)
    engine.status = SimulationStatus.RUNNING
    for _ in range(max(0, min(request.steps, 600))):
        engine.tick()
    return engine.state()


@router.post("/{sim_id}/play")
def play_simulation(sim_id: str):
    engine = _get_engine(sim_id)
    engine.play()
    return {"status": engine.status.value}


@router.post("/{sim_id}/pause")
def pause_simulation(sim_id: str):
    engine = _get_engine(sim_id)
    engine.pause()
    return {"status": engine.status.value}


@router.post("/{sim_id}/reset", response_model=SimulationState)
def reset_simulation(sim_id: str):
    engine = _get_engine(sim_id)
    engine.reset()
    return engine.state()


@router.post("/{sim_id}/speed")
def set_speed(sim_id: str, request: dict):
    engine = _get_engine(sim_id)
    engine.set_speed(float(request.get("speed", 30)))
    return {"speed": engine.speed}


@router.post("/{sim_id}/emergency", response_model=SimulationState)
def emergency_mode(sim_id: str, request: EmergencyRequest):
    engine = _get_engine(sim_id)
    engine.set_emergency(request.active)
    return engine.state()


@router.post("/{sim_id}/optimize", response_model=OptimizationResult)
def optimize_simulation(sim_id: str):
    engine = _get_engine(sim_id)
    if engine.tick_count == 0:
        raise HTTPException(status_code=422, detail="Run the simulation before optimising")
    result = engine.optimize()
    return OptimizationResult.model_validate(result)


@router.post("/{sim_id}/apply", response_model=SimulationState)
def apply_intervention(sim_id: str, intervention: Intervention):
    engine = _get_engine(sim_id)
    engine.apply_intervention(intervention)
    return engine.state()


@router.post("/{sim_id}/counterfactual", response_model=SimulationState)
def counterfactual_simulation(sim_id: str, intervention: Intervention):
    """Fork the current simulation into a full-fidelity counterfactual that has the
    intervention applied, register it as a live simulation, and return its initial
    state so the frontend can open a second WebSocket and animate it side-by-side.
    The main simulation is left untouched - the two engines diverge from here.
    """
    engine = _get_engine(sim_id)
    if engine.tick_count == 0:
        raise HTTPException(status_code=422, detail="Run the simulation before forking")
    clone = engine.clone(fast=False)
    clone.sim_id = f"sim_{uuid.uuid4().hex[:8]}"
    clone.apply_intervention(intervention)
    clone.status = engine.status
    clone.speed = engine.speed
    SIMULATIONS[clone.sim_id] = clone
    return clone.state()


@router.post("/{sim_id}/recommend-route")
def recommend_route(sim_id: str, request: RouteRequest):
    """Congestion-aware path between two nodes inside a running simulation."""
    engine = _get_engine(sim_id)
    path = engine.routing.find_path(request.source, request.destination)
    if not path:
        raise HTTPException(status_code=422, detail="No route exists between those nodes")
    return {"path": path, "sim_id": sim_id}


@router.post("/{sim_id}/emergency-route")
def emergency_route(sim_id: str, request: EvacuationRequest):
    """Evacuation path from a node to the nearest emergency exit."""
    engine = _get_engine(sim_id)
    path = engine.routing.evacuation_path(request.node_id)
    if not path:
        raise HTTPException(status_code=422, detail="No evacuation route from that node")
    return {"path": path, "emergency_exit": path[-1], "sim_id": sim_id}


# --------------------------------------------------------------------------- #
#  WebSocket live channel:  /api/simulation/{sim_id}/live
# --------------------------------------------------------------------------- #
@router.websocket("/{sim_id}/live")
async def live_simulation(websocket: WebSocket, sim_id: str):
    await websocket.accept()
    engine = SIMULATIONS.get(sim_id)
    if engine is None:
        await websocket.send_json({"error": "Simulation not found"})
        await websocket.close()
        return

    async def send_state():
        await websocket.send_json(engine.state().model_dump(mode="json"))

    await send_state()
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
            except asyncio.TimeoutError:
                raw = None
            except WebSocketDisconnect:
                break
            if raw:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = None
                if isinstance(msg, dict):
                    action = msg.get("action")
                    if action == "play":
                        engine.play()
                    elif action == "pause":
                        engine.pause()
                    elif action == "reset":
                        engine.reset()
                    elif action == "step":
                        engine.status = SimulationStatus.RUNNING
                        engine.tick()
                        await send_state()
                        continue
                    elif action == "set_speed":
                        engine.set_speed(float(msg.get("value", 30)))
                    elif action == "emergency":
                        engine.set_emergency(bool(msg.get("active", True)))
                    elif action == "apply_intervention":
                        try:
                            intervention = Intervention.model_validate(msg.get("intervention"))
                            engine.apply_intervention(intervention)
                        except Exception:
                            pass
                # always reflect control changes back to the client so the
                # play/pause button and status stay in sync (e.g. PAUSED or
                # IDLE after reset). When RUNNING, the tick below emits state.
                if engine.status != SimulationStatus.RUNNING:
                    await send_state()
                    continue
            if engine.status == SimulationStatus.RUNNING:
                engine.tick()
                await send_state()
                await asyncio.sleep(1.0 / max(1.0, engine.speed / (TICK_DT_MIN * 60.0)))
            else:
                await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
