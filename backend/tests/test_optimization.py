"""Counterfactual optimisation: candidate generation, ranking, isolation."""

from app.engine.simulator import SimulationEngine
from app.models import Intervention, InterventionType


def _run_to(e, t_target):
    e.play()
    while e.t_min < t_target:
        e.tick()


def test_optimize_returns_ranked_candidates(make_engine):
    e = make_engine("exit_surge", seed=7)
    _run_to(e, 118)
    assert e.metrics.risk_level.value == "CRITICAL"
    result = e.optimize(horizon_min=6.0)
    assert len(result["candidates"]) >= 1
    scores = [c["score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)
    ids = [c["intervention"].id for c in result["candidates"]]
    assert len(ids) == len(set(ids)), "duplicate candidate ids"
    for c in result["candidates"]:
        assert "max_queue" in c["improvement"]
        assert c["baseline_metrics"] is not None
        assert c["candidate_metrics"] is not None


def test_emergency_candidate_suggested_when_critical(make_engine):
    e = make_engine("exit_surge", seed=7)
    _run_to(e, 118)
    result = e.optimize(horizon_min=4.0)
    types = [c["intervention"].type for c in result["candidates"]]
    assert InterventionType.EMERGENCY_RESPONSE in types


def test_optimize_does_not_mutate_original(make_engine):
    e = make_engine("exit_surge", seed=7)
    _run_to(e, 118)
    gate_dist = dict(e.gate_distribution())
    exit_dist = dict(e.exit_distribution())
    caps = {
        ed.id: ed.capacity
        for ed in e.graph.venue.edges
    }
    e.optimize(horizon_min=4.0)
    assert dict(e.gate_distribution()) == gate_dist
    assert dict(e.exit_distribution()) == exit_dist
    assert all(ed.capacity == caps[ed.id] for ed in e.graph.venue.edges)


def test_apply_intervention_mutates_and_records(make_engine):
    e = make_engine("normal")
    _run_to(e, 120)
    before = dict(e.exit_distribution())
    intervention = Intervention(
        id="test_shift",
        type=InterventionType.USE_ALTERNATE_EXIT,
        description="test shift",
        parameters={"percent": 30, "from": "EXIT_N", "to": "EXIT_E"},
    )
    e.apply_intervention(intervention)
    after = e.exit_distribution()
    assert after["EXIT_N"] < before["EXIT_N"]
    assert after["EXIT_E"] > before["EXIT_E"]
    assert intervention in e.interventions


def test_apply_emergency_response_via_intervention(make_engine):
    e = make_engine("exit_surge", seed=7)
    _run_to(e, 118)
    e.apply_intervention(
        Intervention(
            id="test_emerg",
            type=InterventionType.EMERGENCY_RESPONSE,
            description="test emergency",
            parameters={},
        )
    )
    assert e.emergency_active is True


def test_clone_isolation(make_engine):
    e = make_engine("exit_surge", seed=7)
    _run_to(e, 118)
    clone = e.clone(fast=True)
    clone.set_emergency(True)
    clone.tick()
    assert e.emergency_active is False
    assert clone.emergency_active is True


def test_generate_candidates_never_empty(make_engine):
    e = make_engine("normal")
    _run_to(e, 130)
    candidates = e.generate_candidates()
    assert len(candidates) >= 1
