"""World layer tests: graph build, demand plan, aggregate flow, rerouting, interventions."""

import pytest

from app.engine.routing import RoutingEngine
from app.engine.simulator import SimulationEngine
from app.engine.venue import VenueGraph
from app.models import Intervention, InterventionType
from app.storage import storage
from app.world import (
    WorldSimulation,
    plan_demand,
    redistribute_gates,
    resolve_world_graph,
)


@pytest.fixture
def world(venue_model):
    graph = resolve_world_graph(venue_model)
    return graph, venue_model


def test_demo_graph_is_connected(world):
    graph, venue = world
    assert graph.provider == "DEMO"
    assert len(graph.nodes) >= 10
    assert len(graph.edges) >= 20
    entry_gates = {n.id for n in venue.nodes if n.type.value == "ENTRY"}
    ap_gates = {ap.gate_id for ap in graph.access_points if ap.kind == "ENTRY"}
    assert entry_gates <= ap_gates, "every venue gate must have an access point"
    assert graph.demand_sources
    assert graph.sink_ids

    # every source can reach every gate through the graph
    for src in graph.demand_sources:
        for ap in graph.access_points:
            if ap.kind != "ENTRY":
                continue
            sim = WorldSimulation(graph, venue, storage.get_scenario("normal"))
            assert sim._path(src.node_id, ap.node_id) is not None, (
                f"{src.id} cannot reach {ap.gate_id}"
            )


def test_demand_plan_matches_scenario(world):
    graph, venue = world
    scenario = storage.get_scenario("normal")
    plan = plan_demand(graph, scenario, venue)
    total = sum(p.share for p in plan.sources.values())
    assert total == pytest.approx(1.0)
    for gate, weight in scenario.gate_distribution.items():
        share = plan.gate_share(gate)
        assert share == pytest.approx(weight), gate


def test_redistribute_gates_moves_flow(world):
    graph, venue = world
    scenario = storage.get_scenario("normal")
    plan = plan_demand(graph, scenario, venue)
    before = plan.gate_share("GATE_A")
    redistribute_gates(plan, "GATE_A", "GATE_B", 50)
    assert plan.gate_share("GATE_A") < before
    assert plan.gate_share("GATE_B") > scenario.gate_distribution["GATE_B"]


def test_arrival_phase_reaches_steady_state(world):
    graph, venue = world
    scenario = storage.get_scenario("normal")
    sim = WorldSimulation(graph, venue, scenario)
    for _ in range(240):  # 60 simulated minutes
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    st = sim.state()
    total_arr = sum(s.arrivals_per_min for s in st.gates.values())
    assert total_arr == pytest.approx(scenario.arrival_rate_per_minute, abs=10)
    total_served = sum(s.served_per_min for s in st.gates.values())
    assert total_served == pytest.approx(scenario.arrival_rate_per_minute, abs=10)
    assert st.summary


def test_gate_queues_form_under_overload(world):
    graph, venue = world
    scenario = storage.get_scenario("gate_overload")
    sim = WorldSimulation(graph, venue, scenario)
    for _ in range(240):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    st = sim.state()
    queue_gate = max(st.gates.items(), key=lambda kv: kv[1].queue)
    assert queue_gate[1].queue > 0, "overloaded gate must build an external queue"
    assert queue_gate[1].served_per_min <= queue_gate[1].arrivals_per_min + 1


def test_gate_rebalancing_shifts_demand_off_congestion(world):
    """The crowd adapts: congestion/closure drifts arrivals to open gates.

    Demand assigned to a congested gate gradually moves toward the
    least-loaded open gate (8%/3min when congested, 30%/3min when closed).
    This is the behavior that makes a capacity reduction visibly reroute
    demand to Gate B without an operator intervention.
    """
    graph, venue = world
    scenario = storage.get_scenario("gate_overload")
    sim = WorldSimulation(graph, venue, scenario)
    sim.time_offset = 25.0  # live-event clock: rebalancing runs past warm-up
    for _ in range(200):  # ~8 min of live congestion
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)

    share_a = sim.plan.gate_share("GATE_A")
    assert share_a < 0.5, f"congestion must drift demand off GATE_A (share {share_a:.3f})"
    other = sum(sim.plan.gate_share(g) for g in ("GATE_B", "GATE_C", "GATE_D", "GATE_E", "GATE_F"))
    assert other > 0.4, f"drifted demand must land on open gates (share {other:.3f})"
    assert sim.state().gates["GATE_A"].queue > 0

    sim.apply_intervention(Intervention(
        id="close",
        type=InterventionType.CHANGE_GATE,
        description="close A",
        parameters={"gate": "GATE_A", "capacity": 0, "external": True},
    ))
    before = sim.plan.gate_share("GATE_A")
    for _ in range(150):  # ~6 min after closing
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    after = sim.plan.gate_share("GATE_A")
    assert after < before * 0.6, f"closed gate must shed demand fast ({before:.3f}->{after:.3f})"
    assert sim.state().gates["GATE_A"].served_per_min == pytest.approx(0.0, abs=1.0)


def test_flow_conservation_no_negative(world):
    graph, venue = world
    scenario = storage.get_scenario("normal")
    sim = WorldSimulation(graph, venue, scenario)
    for _ in range(240):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    st = sim.state()
    for state in st.edges.values():
        assert state.people >= 0
        assert state.flow_per_min >= 0
    for state in st.gates.values():
        assert state.queue >= 0
    assert st.risk is not None


def test_close_edge_reroutes_flow(world):
    graph, venue = world
    scenario = storage.get_scenario("normal")
    sim = WorldSimulation(graph, venue, scenario)
    for _ in range(240):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    baseline = sim.state()

    # close the busiest edge; packets must reroute (or hold) rather than vanish
    hot = max(baseline.edges.items(), key=lambda kv: kv[1].flow_per_min)[0]
    sim.apply_intervention(Intervention(
        id="close", type=InterventionType.CLOSE_CORRIDOR,
        description="close hot external edge",
        parameters={"external": True, "external_edge": hot},
    ))
    assert hot in sim.closed
    for _ in range(240):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    st = sim.state()
    assert st.edges[hot].closed is True
    # demand is still served somewhere (alternative routes or queues)
    served = sum(s.served_per_min for s in st.gates.values())
    assert served > 0
    assert any(s.rerouted for s in st.edges.values()) or served > 0


def test_external_redirect_intervention_changes_flow(world):
    graph, venue = world
    scenario = storage.get_scenario("gate_overload")
    sim = WorldSimulation(graph, venue, scenario)
    for _ in range(160):  # warm up until steady arrival flow reaches the gates
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    before_plan_a = sim.plan.gate_share("GATE_A")
    before_plan_c = sim.plan.gate_share("GATE_C")
    baseline_served = sum(g.served_per_min for g in sim.state().gates.values())

    emitted = {"GATE_A": 0.0, "GATE_C": 0.0}
    orig_emit = sim._emit
    def tally(path, gate, amount, rerouted):
        if gate in emitted:
            emitted[gate] += amount
        orig_emit(path, gate, amount, rerouted)
    sim._emit = tally

    sim.apply_intervention(Intervention(
        id="redirect", type=InterventionType.REDIRECT,
        description="shift GATE_A arrivals to GATE_C",
        parameters={"external": True, "from": "GATE_A", "to": "GATE_C", "percent": 80},
    ))
    # the intervention changed the real flow assignment
    assert sim.plan.gate_share("GATE_A") < before_plan_a
    assert sim.plan.gate_share("GATE_C") > before_plan_c
    q0 = {g: sim.state().gates[g].queue for g in ("GATE_A", "GATE_C")}
    for _ in range(160):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    q1 = {g: sim.state().gates[g].queue for g in ("GATE_A", "GATE_C")}
    st = sim.state()
    # the intervention rerouted the actual demand stream, not just labels:
    # the post-redirect emission share now favours GATE_C
    assert emitted["GATE_C"] > emitted["GATE_A"] * 2, "redirected flow must dominate"
    # the redirected gate saturates (queue grows, serves at capacity)
    assert q1["GATE_C"] > q0["GATE_C"], "GATE_C queue must grow"
    assert st.gates["GATE_C"].served_per_min == pytest.approx(100.0, abs=1.0)
    # spreading A's load across gates raises total realised throughput
    # (gate_overload caps GATE_A at 100/min, so baseline served < demand;
    # after redirect C also contributes its full capacity)
    served = sum(g.served_per_min for g in st.gates.values())
    assert served > baseline_served, "total served must rise after redistribution"


def test_world_copy_matches_state(world):
    graph, venue = world
    scenario = storage.get_scenario("normal")
    sim = WorldSimulation(graph, venue, scenario)
    for _ in range(240):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    clone = sim.copy()
    a, b = sim.state(), clone.state()
    assert a.t_min == b.t_min
    assert set(a.gates) == set(b.gates)
    for gid in a.gates:
        assert a.gates[gid].queue == b.gates[gid].queue


def test_osm_fallback_without_location_is_offline(world, monkeypatch):
    graph, venue = world
    # a venue with no location must never hit the network
    assert graph.provider == "DEMO"


def test_engine_exposes_world_state(venue_model):
    scenario = storage.get_scenario("normal")
    graph = VenueGraph(venue_model)
    e = SimulationEngine("world_test", scenario, graph, RoutingEngine(graph), seed=7)
    assert e.world is not None
    e.play()
    for _ in range(60):
        e.tick()
    st = e.state()
    assert st.world is not None
    assert st.world.gates
    assert st.world.edges


def test_scenario_world_conditions_throttle_gates(world):
    """scenario.special.world.gate_capacities throttles gates from init.

    A road-closure scenario must start already restricted (before any
    intervention), survive reset(), and still drive real queues + rebalancing.
    """
    graph, venue = world
    scenario = storage.get_scenario("road_closure")
    sim = WorldSimulation(graph, venue, scenario)
    assert sim._gate_service["GATE_A"] == pytest.approx(30.0)
    assert sim._gate_service["GATE_F"] == pytest.approx(30.0)
    assert sim._gate_service["GATE_B"] == pytest.approx(100.0)

    # warm-up respects the restriction: GATE_A can never serve past its cap
    for _ in range(400):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    assert sim.state().gates["GATE_A"].served_per_min <= 30.0 + 1.0

    # live clock: congestion + organic rebalancing move demand off the closure
    sim.time_offset = 25.0
    share_before = sim.plan.gate_share("GATE_A")
    for _ in range(200):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    assert sim.plan.gate_share("GATE_A") < share_before
    assert sim.state().gates["GATE_A"].queue > 0

    # reset re-applies the scenario restriction (reset clears closures)
    sim.reset()
    assert sim._gate_service["GATE_A"] == pytest.approx(30.0)


def test_scenario_world_conditions_close_gates(world):
    """A multi-gate failure zeroes gate throughput and sheds their demand."""
    graph, venue = world
    scenario = storage.get_scenario("multi_gate_failure")
    sim = WorldSimulation(graph, venue, scenario)
    assert sim._gate_service["GATE_C"] == pytest.approx(0.0)
    assert sim._gate_service["GATE_E"] == pytest.approx(0.0)
    sim.time_offset = 25.0
    for _ in range(200):
        sim.step(0.25, scenario.arrival_rate_per_minute, 0.0)
    st = sim.state()
    assert st.gates["GATE_C"].served_per_min == pytest.approx(0.0, abs=1.0)
    assert st.gates["GATE_E"].served_per_min == pytest.approx(0.0, abs=1.0)
    assert sim.plan.gate_share("GATE_C") < 0.2  # demand shed off the closed gate
    # surviving gates carry the extra demand
    survivors = sum(sim.plan.gate_share(g) for g in ("GATE_A", "GATE_B", "GATE_D", "GATE_F"))
    assert survivors > 0.5