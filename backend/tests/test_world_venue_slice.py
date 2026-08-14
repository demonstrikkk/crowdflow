"""World -> venue coupling acceptance tests.

Proves the P0 chain end-to-end at the state level (deterministic, no UI):

    world demand -> world edges -> access point -> venue gate -> venue agent

and that interventions change REAL flow: closing/redirecting a world gate
changes world served rates, which the venue entry coupling follows.

Evidence is derived from simulation state (WorldState gates/queues, engine
gate_spawns, metrics) — not from geometry or rendering.
"""

import pytest

from app.engine.routing import RoutingEngine
from app.engine.simulator import SimulationEngine
from app.engine.venue import VenueGraph
from app.models import Intervention, InterventionType
from app.storage import storage

TICKS = 90  # 90 ticks x 4s = 6 sim minutes, after the engine's 25-min world warm-up
TICK_MIN = 4.0 / 60.0
GATES = ("GATE_A", "GATE_B", "GATE_C", "GATE_D", "GATE_E", "GATE_F")


@pytest.fixture()
def engine(venue_model):
    graph = VenueGraph(venue_model)
    e = SimulationEngine(
        "slice", storage.get_scenario("gate_overload"), graph, RoutingEngine(graph), seed=7
    )
    e.play()
    return e


def _run(engine, ticks: int = TICKS):
    """Tick the engine and return cumulative per-gate world served (raw)."""
    cum = {g: 0.0 for g in engine.world._gate_service}
    for _ in range(ticks):
        engine.tick()
        for g, v in engine.world.gate_served.items():
            cum[g] = cum.get(g, 0.0) + v
    return cum


def test_venue_entry_tracks_world_served_per_gate(engine):
    cum = _run(engine)
    world_total = sum(cum.values())
    venue_total = sum(engine.gate_spawns.values())

    # the world and the venue share one clock (warm-up offset applied)
    st = engine.state()
    assert st.world is not None
    assert st.world.t_min == pytest.approx(engine.t_min, abs=0.01)

    # every gate actually delivers demand from the world into the venue
    for gate in GATES:
        assert engine.gate_spawns[gate] > 0, f"venue must receive people at {gate}"

    # venue entry equals world delivery (person-exact coupling, quantized to
    # agent scale units)
    assert venue_total == pytest.approx(world_total, rel=0.10)

    # the overloaded gate (GATE_A, 75% of 320/min vs 100/min capacity) is the
    # dominant entry point: its venue entry beats every other gate
    dominant = max(engine.gate_spawns, key=engine.gate_spawns.get)
    assert dominant == "GATE_A"
    for gate in GATES:
        if gate != "GATE_A":
            assert engine.gate_spawns["GATE_A"] > engine.gate_spawns[gate]


def test_capacity_reduction_cuts_venue_throughput(engine):
    _run(engine)  # baseline window
    before = dict(engine.gate_spawns)
    baseline_total = sum(before.values())

    # close GATE_A in the world (capacity 0) — the world's busiest gate
    engine.apply_intervention(Intervention(
        id="close_a",
        type=InterventionType.CHANGE_GATE,
        description="close GATE_A to external demand",
        parameters={"gate": "GATE_A", "capacity": 0, "external": True},
    ))
    cum2 = _run(engine)

    w = engine.world.state()
    # world GATE_A stops serving and its queue balloons
    assert w.gates["GATE_A"].served_per_min == pytest.approx(0.0, abs=1.0)
    assert w.gates["GATE_A"].queue > 500

    # world throughput collapses to ~half (only B-F still deliver)
    closed_total = sum(cum2.values())
    assert closed_total < 0.7 * baseline_total, "closing the busiest gate must cut world delivery"
    assert cum2["GATE_A"] < 1.0, "no demand may be served at the closed gate"
    for gate in ("GATE_B", "GATE_C", "GATE_D", "GATE_E", "GATE_F"):
        assert cum2[gate] > 0, f"remaining gates must keep serving: {gate}"

    # venue entry follows: entry at A nearly stops, other gates carry on
    assert engine.gate_spawns["GATE_A"] - before["GATE_A"] <= 0.15 * before["GATE_A"]
    for gate in ("GATE_B", "GATE_C", "GATE_D", "GATE_E", "GATE_F"):
        assert engine.gate_spawns[gate] > before[gate], f"venue keeps entering at {gate}"


def test_redirect_changes_venue_entry_flow(engine):
    _run(engine)  # baseline window
    before = dict(engine.gate_spawns)

    engine.apply_intervention(Intervention(
        id="redirect",
        type=InterventionType.REDIRECT,
        description="shift GATE_A arrivals to GATE_B",
        parameters={"from": "GATE_A", "to": "GATE_B", "percent": 50, "external": True},
    ))

    # the world's real flow assignment changed (GATE_B now carries 42.5%)
    assert engine.world.plan.gate_share("GATE_B") > 0.4

    _run(engine)  # post-intervention window
    spawned_since = {g: engine.gate_spawns[g] - before[g] for g in GATES}
    # the venue follows the rerouted world: entry at GATE_B rises
    assert spawned_since["GATE_B"] > before["GATE_B"], "venue entry must shift to GATE_B"
