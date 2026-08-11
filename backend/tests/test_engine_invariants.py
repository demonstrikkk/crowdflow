"""Physical invariants: conservation, pipe caps, spawn clamps, closed edges."""

import pytest

from app.engine.simulator import COMFORT_DENSITY, MAX_AGENTS, WALKING_SPEED


def pipe_of(graph, u, v, scale):
    length = graph.edge_length(u, v)
    cap = graph.edge_capacity(u, v)
    transit_min = length / (WALKING_SPEED * 60.0)
    return max(float(scale), cap * transit_min)


def test_conservation_every_tick(make_engine):
    e = make_engine("normal")
    e.play()
    for _ in range(300):
        e.tick()
        node_people = sum(s.people for s in e.nodes.values())
        edge_people = sum(s.people for s in e.edges.values())
        assert node_people + edge_people == e.metrics.in_venue, (
            f"t={e.t_min:.2f} mismatch: nodes={node_people} edges={edge_people} "
            f"in_venue={e.metrics.in_venue}"
        )
    while e.t_min < 200 and e.metrics.in_venue > 0:
        e.tick()
    assert e.metrics.total_completed == e.metrics.total_spawned > 0
    assert e.metrics.in_venue == 0


def test_edges_never_exceed_pipe(make_engine):
    e = make_engine("exit_surge")
    e.play()
    for _ in range(400):
        e.tick()
        for (u, v), state in e.edges.items():
            pipe = pipe_of(e.graph, u, v, e.scale)
            assert state.people <= pipe + 1e-9, (
                f"t={e.t_min:.2f} {u}->{v}: {state.people} people on a {pipe:.1f} pipe"
            )


def test_no_negative_node_people(make_engine):
    e = make_engine("gate_overload")
    e.play()
    for _ in range(500):
        e.tick()
        for node_id, state in e.nodes.items():
            assert state.people >= 0, f"t={e.t_min:.2f} node {node_id} went negative"


def test_spawn_clamped_to_crowd_size(make_engine):
    e = make_engine("exit_surge")
    e.play()
    for _ in range(800):
        e.tick()
        assert e.metrics.total_spawned <= e.scenario.crowd_size, (
            f"over-spawned: {e.metrics.total_spawned} > {e.scenario.crowd_size}"
        )
    while e.t_min < 240 and e.metrics.in_venue > 0:
        e.tick()
    # whole-agent granularity: last partial agent (scale units) is not spawned
    assert e.metrics.total_completed == e.metrics.total_spawned
    assert e.metrics.total_spawned > e.scenario.crowd_size - e.scale
    assert e.metrics.in_venue == 0


def test_agents_never_step_onto_closed_edges(make_engine):
    e = make_engine("normal")
    e.play()
    for _ in range(200):
        e.tick()
        for agent in e.agents:
            if agent.on_edge is not None:
                u, v = agent.on_edge
                assert e.graph.is_open(u, v), f"t={e.t_min:.2f} agent on closed edge {u}->{v}"


def test_node_queue_matches_formula(make_engine):
    e = make_engine("gate_overload")
    e.play()
    for _ in range(300):
        e.tick()
        for node_id, state in e.nodes.items():
            node = e.graph.node(node_id)
            if node is None or node.type in ("EXIT", "EMERGENCY_EXIT"):
                continue
            area = e.graph.node_area(node_id)
            expected = max(0, state.people - int(area * COMFORT_DENSITY * 0.5))
            assert state.queue == expected, f"t={e.t_min:.2f} {node_id} queue formula broken"


def test_scale_matches_crowd_size(venue_model):
    from app.engine.routing import RoutingEngine
    from app.engine.simulator import SimulationEngine
    from app.engine.venue import VenueGraph
    from app.storage import storage

    import math

    for scenario_id, crowd in (("normal", 5000), ("exit_surge", 8000), ("gate_overload", 8000)):
        scenario = storage.get_scenario(scenario_id)
        graph = VenueGraph(venue_model)
        e = SimulationEngine(f"scale_{scenario_id}", scenario, graph, RoutingEngine(graph))
        assert e.scale == math.ceil(crowd / MAX_AGENTS), scenario_id
