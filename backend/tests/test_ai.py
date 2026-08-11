"""Tests for the AI provider abstraction + NL scenario interface (Gap A)."""
import json

import pytest

from app.ai.base import (
    AIProviderFailure,
    AIValidationError,
    ParsedScenario,
    ScenarioDelta,
    extract_json_object,
)
from app.ai.config import AISettings
from app.ai.apply import apply_delta, scenario_context
from app.ai.factory import create_provider
from app.storage import storage


def make_settings(provider: str) -> AISettings:
    return AISettings(
        provider=provider,
        groq_api_key="test-groq-key" if provider == "groq" else "",
        gemini_api_key="test-gemini-key" if provider == "gemini" else "",
    )


class TestProviderSwitch:
    def test_groq_default(self):
        from app.ai.groq import GroqProvider

        assert isinstance(create_provider(make_settings("groq")), GroqProvider)

    def test_gemini_switch(self):
        from app.ai.gemini import GeminiProvider

        assert isinstance(create_provider(make_settings("gemini")), GeminiProvider)

    def test_active_model_follows_provider(self):
        g = make_settings("groq")
        assert g.active_model == g.groq_model
        m = make_settings("gemini")
        assert m.active_model == m.gemini_model

    def test_configured_flag(self):
        assert make_settings("groq").configured is True
        assert AISettings(provider="groq", groq_api_key="").configured is False


class TestJSONExtraction:
    def test_plain(self):
        assert extract_json_object('{"a": 1}') == '{"a": 1}'

    def test_fenced(self):
        text = '```json\n{"a": 1}\n```'
        assert json.loads(extract_json_object(text)) == {"a": 1}

    def test_prose_wrapped(self):
        text = 'Sure! Here it is: {"a": {"b": [1, 2, 3]}} hope that helps.'
        assert json.loads(extract_json_object(text)) == {"a": {"b": [1, 2, 3]}}

    def test_unbalanced_raises(self):
        with pytest.raises(AIValidationError):
            extract_json_object('{"a": 1')


class TestDeltaValidation:
    def test_bad_distribution_rejected(self):
        with pytest.raises(ValueError):
            ScenarioDelta(gate_distribution={"GATE_A": 0.5, "GATE_B": 0.2})

    def test_unknown_gate_rejected(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        delta = ScenarioDelta(close_gates=["GATE_ZZ"])
        with pytest.raises(AIValidationError):
            apply_delta(scenario, venue_model, delta)

    def test_unknown_edge_rejected(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        delta = ScenarioDelta(close_edges=["nope"])
        with pytest.raises(AIValidationError):
            apply_delta(scenario, venue_model, delta)

    def test_unknown_incident_node_rejected(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        delta = ScenarioDelta(incident={"type": "FIRE", "location": "NOPE", "radius_m": 40})
        with pytest.raises(AIValidationError):
            apply_delta(scenario, venue_model, delta)


class TestApplyDelta:
    def test_gate_closure_drops_inflow_and_blocks_edges(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        from app.models import NodeType

        delta = ScenarioDelta(close_gates=["GATE_A"])
        derived_scenario, derived_venue = apply_delta(scenario, venue_model, delta)

        assert "GATE_A" not in derived_scenario.gate_distribution
        for e in derived_venue.edges:
            if e.source == "GATE_A" or e.destination == "GATE_A":
                assert e.is_open is False
        # other gates still open
        assert all(
            e.is_open
            for e in derived_venue.edges
            if e.source in ("GATE_B",) or e.destination in ("GATE_B",)
        )

    def test_edge_closure_and_opening(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        # find an emergency-only edge (is_emergency=True, currently closed by default)
        emergency_edge = next(e for e in venue_model.edges if e.is_emergency)
        delta = ScenarioDelta(open_edges=[emergency_edge.id])
        _, derived_venue = apply_delta(scenario, venue_model, delta)
        edge = next(e for e in derived_venue.edges if e.id == emergency_edge.id)
        assert edge.is_open is True

    def test_distribution_normalised(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        delta = ScenarioDelta(gate_distribution={"GATE_A": 0.75, "GATE_B": 0.25})
        derived, _ = apply_delta(scenario, venue_model, delta)
        assert abs(sum(derived.gate_distribution.values()) - 1.0) < 1e-6
        assert derived.gate_distribution["GATE_A"] == pytest.approx(0.75)

    def test_crowd_size_and_event_shift(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        delta = ScenarioDelta(crowd_size=30000, event_end_delta_minutes=-10)
        derived, _ = apply_delta(scenario, venue_model, delta)
        assert derived.crowd_size == 30000
        surge = next(p for p in derived.event_phases if p.name.value == "EXIT_SURGE")
        original_surge = next(p for p in scenario.event_phases if p.name.value == "EXIT_SURGE")
        assert surge.start_minute == pytest.approx(original_surge.start_minute - 10)
        assert surge.start_minute >= 0

    def test_incident_and_weather_stored_in_special(self, venue_model):
        scenario = storage.get_scenario("exit_surge")
        delta = ScenarioDelta(
            incident={"type": "FIRE", "location": "CONCESSION_N", "radius_m": 30},
            weather={"condition": "HEAVY_RAIN", "capacity_multiplier": 0.6, "speed_multiplier": 0.8},
        )
        derived, _ = apply_delta(scenario, venue_model, delta)
        assert derived.special["incident"]["type"] == "FIRE"
        assert derived.special["weather"]["condition"] == "HEAVY_RAIN"


class TestParsedScenarioContract:
    def test_contract_parses(self):
        raw = json.dumps(
            {
                "scenario_delta": {
                    "summary": "Gate B closes",
                    "close_gates": ["GATE_B"],
                    "confidence": "ignored",
                },
                "confidence": 0.9,
                "reasoning": "user asked to close gate B",
            }
        )
        parsed = ParsedScenario.model_validate(json.loads(raw))
        assert parsed.scenario_delta.close_gates == ["GATE_B"]
        assert parsed.confidence == 0.9

    def test_scenario_context_lists_real_ids(self, venue_model):
        ctx = scenario_context(
            venue_model, storage.get_scenario("exit_surge")
        )
        assert "GATE_A" in ctx
        assert "EXIT_N" in ctx
        # edge ids are normalised to upper case by the venue validator
        assert "E_GA_CN" in ctx


class TestTransportFailure:
    def test_provider_failure_normalised(self):
        """Transport must surface provider errors as typed AI errors (no secrets)."""
        from app.ai.client import OpenAICompatTransport

        transport = OpenAICompatTransport(make_settings("groq"), "http://x", "k", "m")
        with pytest.raises(AIProviderFailure):
            raise AIProviderFailure("provider rate limit hit (429)")

    def test_extract_requires_object(self):
        with pytest.raises(AIValidationError):
            extract_json_object("the model just said hello")


def test_ai_endpoints_degrade_without_keys():
    """When no AI key is configured, endpoints fail cleanly (503), never crash."""
    import os

    from fastapi.testclient import TestClient

    from app.ai import config as ai_config
    from app.main import app

    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    ai_config.reset_settings()

    client = TestClient(app)
    resp = client.post(
        "/api/ai/interpret",
        json={"query": "what if Gate B closes", "scenario_id": "exit_surge"},
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"].lower()
    assert "groq_api_key" in detail or "gemini_api_key" in detail or "configure" in detail
    ai_config.reset_settings()


def test_ai_simulate_with_supplied_delta_runs_engine():
    """Supplying a validated delta bypasses the LLM and runs a real simulation."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/ai/simulate",
        json={
            "scenario_id": "exit_surge",
            "delta": {
                "summary": "Gate B closes",
                "close_gates": ["GATE_B"],
                "notes": ["test"],
            },
        },
    )
    assert resp.status_code == 200
    state = resp.json()
    assert state["sim_id"]
    assert state["metrics"]["in_venue"] >= 0
    assert state["scenario_id"] == "exit_surge"
