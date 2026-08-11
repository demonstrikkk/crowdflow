"""End-to-end behaviour: entry flow, surge queueing, risk windows, clearance."""

from app.models import RiskLevel


def test_normal_scenario_full_lifecycle(make_engine):
    e = make_engine("normal")
    e.play()
    max_queue = 0
    for _ in range(200 * 15):
        e.tick()
        max_queue = max(max_queue, e.metrics.queue_total)
        if e.metrics.in_venue == 0 and e.t_min > 140:
            break

    assert e.metrics.total_completed == 5000, f"only {e.metrics.total_completed} done at t={e.t_min:.0f}"
    assert e.metrics.in_venue == 0
    assert e.metrics.clearance_time_min is not None
    assert e.metrics.clearance_time_min > 0
    assert max_queue > 0, "expected queueing during the exit surge"


def test_surge_creates_high_risk_window(make_engine):
    e = make_engine("normal")
    e.play()
    surge_t = None
    high_seen = False
    while e.t_min < 150:
        e.tick()
        if e.phase_name() == "EXIT_SURGE" and surge_t is None:
            surge_t = e.t_min
        if e.metrics.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            high_seen = True
    assert surge_t is not None
    assert high_seen, "exit surge never crossed into HIGH/CRITICAL risk"


def test_phase_progression(make_engine):
    e = make_engine("normal")
    e.play()
    seen = []
    while e.t_min < 145:
        e.tick()
        name = e.phase_name()
        if not seen or seen[-1] != name:
            seen.append(name)
    assert "ENTRY" in seen and "PEAK" in seen and "INTERVAL" in seen and "EXIT_SURGE" in seen


def test_gate_overload_queues_at_gates(make_engine):
    e = make_engine("gate_overload")
    e.play()
    peak_queue = 0
    gate_queues = 0
    while e.t_min < 140:
        e.tick()
        peak_queue = max(peak_queue, e.metrics.queue_total)
        gate_queues = max(
            gate_queues,
            sum(s.queue for n, s in e.nodes.items() if n.startswith("GATE")),
        )
    assert gate_queues > 500, f"expected heavy gate queueing, got {gate_queues}"
    assert peak_queue >= gate_queues


def test_bottlenecks_reported_during_critical_phase(make_engine):
    e = make_engine("exit_surge")
    e.play()
    while e.t_min < 118:
        e.tick()
    bns = e.bottlenecks()
    assert len(bns) >= 1
    for b in bns:
        assert b.location
        assert b.explanation
        assert b.capacity_utilisation > 0
        assert b.current_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_clearance_is_egress_based_after_surge(make_engine):
    e = make_engine("exit_surge")
    e.play()
    while e.t_min < 100:
        e.tick()
    assert e.metrics.clearance_time_min is None, "clearance should be unknown before egress starts"
    while e.t_min < 125:
        e.tick()
    assert e.metrics.clearance_time_min is not None
