"""Emergency protocol: graph gating, rerouting to emergency exits, recovery."""


def test_emergency_activates_graph_egress(make_engine):
    e = make_engine("normal")
    e.play()
    while e.t_min < 112:
        e.tick()
    e.set_emergency(True)
    assert e.graph.emergency_active is True
    assert e.emergency_active is True
    is_emergency_edges_open = [
        (u, v) for (u, v) in e.graph.graph.edges
        if e.graph.edge(u, v) and getattr(e.graph.edge(u, v), "is_emergency", False)
    ]
    assert is_emergency_edges_open, "no emergency edges in venue"


def test_all_agents_reroute_to_emergency_exits(make_engine):
    e = make_engine("normal")
    e.play()
    while e.t_min < 112:
        e.tick()
    e.set_emergency(True)
    e.tick()
    active = [a for a in e.agents if a.completed_at is None and not a.idle]
    assert active, "expected agents in venue at emergency time"
    for a in active:
        assert a.destination.startswith("EMERGENCY_"), (
            f"agent {a.id} still heading to {a.destination}"
        )


def test_evacuation_paths_exist_from_all_nodes(make_engine):
    e = make_engine("normal")
    e.play()
    for node_id in list(e.graph.graph.nodes):
        path = e.routing.evacuation_path(node_id)
        assert path, f"no evacuation path from {node_id}"
        assert path[-1].startswith("EMERGENCY_")


def test_emergency_clears_venue_fast(make_engine):
    e = make_engine("normal")
    e.play()
    while e.t_min < 112:
        e.tick()
    done_before = e.metrics.total_completed
    in_at_emergency = e.metrics.in_venue
    e.set_emergency(True)
    for _ in range(150):
        e.tick()
    done_after = e.metrics.total_completed
    assert done_after - done_before >= 900, f"only {done_after - done_before} cleared in 10 min"
    assert e.metrics.in_venue < in_at_emergency * 0.7, "drain too slow after emergency"
    assert e.metrics.risk_level.value != "CRITICAL", "risk still critical 10 min after emergency"


def test_emergency_toggle_closes_emergency_edges(make_engine):
    e = make_engine("normal")
    e.play()
    e.set_emergency(True)
    assert e.graph.emergency_active is True
    e.set_emergency(False)
    assert e.graph.emergency_active is False
    for (u, v) in e.graph.graph.edges:
        edge = e.graph.edge(u, v)
        if edge and edge.is_emergency:
            assert not e.graph.is_open(u, v), f"emergency edge {u}->{v} open after toggle"


def test_emergency_edges_blocked_without_emergency(make_engine):
    e = make_engine("normal")
    e.play()
    for (u, v) in e.graph.graph.edges:
        edge = e.graph.edge(u, v)
        if edge and edge.is_emergency:
            assert not e.graph.is_open(u, v), f"emergency edge {u}->{v} open pre-emergency"
