"""AI natural-language interface (Groq <-> Gemini, interchangeable).

Pipeline:  USER QUERY -> AI PROVIDER -> STRUCTURED JSON -> VALIDATION ->
            SIMULATION ENGINE -> (frontend renders the real result)

The LLM never produces simulation numbers. Every displayed result comes from
the engine. All secrets live server-side.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..ai.apply import (
    apply_delta,
    bottlenecks_summary,
    metrics_summary,
    scenario_context,
    world_summary,
)
from ..ai.base import AIError, AIValidationError, ScenarioDelta
from ..ai.factory import get_provider, provider_status
from ..models import SimulationState
from ..routers.simulation import register_engine
from ..storage import storage

logger = logging.getLogger("crowdflow.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])


class InterpretRequest(BaseModel):
    query: str = Field(min_length=3)
    scenario_id: str


class InterpretResponse(BaseModel):
    delta: ScenarioDelta
    provider: str
    model: str
    confidence: float
    reasoning: str
    warnings: list = Field(default_factory=list)


class SimulateRequest(BaseModel):
    scenario_id: str
    query: Optional[str] = Field(default=None, description="NL query; optional if delta is supplied")
    delta: Optional[ScenarioDelta] = Field(default=None, description="pre-validated delta")


class ExplainRequest(BaseModel):
    sim_id: str


def _load(scenario_id: str):
    scenario = storage.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")
    venue = storage.get_venue(scenario.venue_id)
    if venue is None:
        raise HTTPException(
            status_code=422, detail=f"Scenario references unknown venue '{scenario.venue_id}'"
        )
    return scenario, venue


def _guard_ai() -> None:
    from ..ai.config import get_settings

    if not get_settings().configured:
        raise HTTPException(status_code=503, detail=get_settings().missing_key_message())


@router.get("/status")
def status():
    return provider_status()


@router.post("/interpret", response_model=InterpretResponse)
def interpret(request: InterpretRequest):
    """NL -> validated ScenarioDelta (no simulation runs)."""
    _guard_ai()
    scenario, venue = _load(request.scenario_id)
    provider = get_provider()
    try:
        parsed = provider.parseScenario(request.query, scenario_context(venue, scenario))
    except AIError as exc:
        logger.warning("ai.interpret failed scenario=%s provider=%s err=%s",
                       request.scenario_id, provider.name, type(exc).__name__)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return InterpretResponse(
        delta=parsed.scenario_delta,
        provider=provider.name,
        model=provider.settings.active_model if hasattr(provider, "settings") else provider.name,
        confidence=parsed.confidence,
        reasoning=parsed.reasoning,
    )


@router.post("/simulate", response_model=SimulationState)
def simulate(request: SimulateRequest):
    """Interpret (if needed) + validate + run a REAL simulation, registered for live feed."""
    scenario, venue = _load(request.scenario_id)

    if request.delta is not None:
        delta = request.delta
    else:
        if not request.query:
            raise HTTPException(status_code=422, detail="Provide a query or a delta")
        _guard_ai()
        provider = get_provider()
        try:
            delta = provider.parseScenario(request.query, scenario_context(venue, scenario)).scenario_delta
        except AIError as exc:
            logger.warning("ai.simulate interpret failed scenario=%s err=%s",
                           request.scenario_id, type(exc).__name__)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        derived_scenario, derived_venue = apply_delta(scenario, venue, delta)
    except AIValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    engine = register_engine(derived_scenario, derived_venue)
    engine.play()
    engine.tick()
    logger.info(
        "ai.simulate started scenario=%s sim=%s crowd=%s gates_closed=%s edges_closed=%s incident=%s weather=%s",
        request.scenario_id, engine.sim_id, derived_scenario.crowd_size,
        len(delta.close_gates), len(delta.close_edges),
        bool(delta.incident), bool(delta.weather),
    )
    return engine.state()


@router.post("/explain")
def explain(request: ExplainRequest):
    """Grounded explanation of a running simulation (uses real metrics only)."""
    _guard_ai()
    from ..routers.simulation import _get_engine

    engine = _get_engine(request.sim_id)
    state = engine.state(include_agents=False)
    provider = get_provider()
    try:
        explanation = provider.explainSimulation(
            metrics_summary(state), bottlenecks_summary(state), world_summary(state)
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "provider": provider.name,
        "summary": explanation.summary,
        "cause": explanation.cause,
        "try_actions": [t.model_dump() for t in explanation.try_actions],
    }


class SuggestRequest(BaseModel):
    scenario_id: str


@router.post("/suggest")
def suggest(request: SuggestRequest):
    """Suggest scenario variations to try."""
    _guard_ai()
    scenario, venue = _load(request.scenario_id)
    provider = get_provider()
    try:
        bundle = provider.generateScenarioSuggestions(scenario_context(venue, scenario))
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"provider": provider.name, "suggestions": [s.model_dump() for s in bundle.suggestions]}
