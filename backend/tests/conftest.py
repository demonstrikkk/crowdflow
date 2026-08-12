import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

# Keep the test suite deterministic and offline: the live Gemini provider is
# never invoked by tests. Fusion tests inject gemini_analysis explicitly.
# When disabled (default), BLUEPRINT_GEMINI_ENABLED is set from .env (true).
# To force Gemini off for a test, use the gemini_off fixture with autouse=False.
# os.environ["BLUEPRINT_GEMINI_ENABLED"] = "0"

import pytest

from app.engine.routing import RoutingEngine
from app.engine.simulator import SimulationEngine
from app.engine.venue import VenueGraph
from app.storage import storage


@pytest.fixture()
def venue_model():
    venue = storage.get_venue("unity_arena")
    assert venue is not None
    return venue


@pytest.fixture()
def make_engine(venue_model):
    """Build a fresh engine for a scenario; each call returns a new instance."""

    def _make(scenario_id: str, seed: int = 1) -> SimulationEngine:
        scenario = storage.get_scenario(scenario_id)
        assert scenario is not None
        graph = VenueGraph(venue_model)
        return SimulationEngine(
            f"test_{scenario_id}_{seed}", scenario, graph, RoutingEngine(graph), seed=seed
        )

    return _make
