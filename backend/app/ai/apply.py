"""Apply a validated ScenarioDelta to a scenario + venue.

The delta comes from the AI layer (or a manual "what if" form), but everything
here is deterministic: unknown ids are rejected, distributions are re-normalised
and the result is a real runnable ScenarioModel/VenueModel pair.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Tuple

from ..ai.base import AIValidationError, ScenarioDelta
from ..models import NodeType, ScenarioModel, VenueModel


def _normalise_distribution(dist: Dict[str, float]) -> Dict[str, float]:
    total = sum(dist.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in dist.items()}


def _node_ids(venue: VenueModel) -> set:
    return {n.id for n in venue.nodes}


def _edge_ids(venue: VenueModel) -> set:
    return {e.id for e in venue.edges}


def apply_delta(scenario: ScenarioModel, venue: VenueModel, delta: ScenarioDelta) -> Tuple[ScenarioModel, VenueModel]:
    """Return derived (scenario, venue) with the delta applied.

    Raises AIValidationError when the delta references ids that do not exist,
    so a bad LLM output can never corrupt a venue.
    """
    derived_scenario = scenario.model_copy(deep=True)
    derived_venue = venue.model_copy(deep=True)

    nodes = _node_ids(venue)
    edges = _edge_ids(venue)
    gate_ids = {n.id for n in venue.nodes if n.type == NodeType.ENTRY}

    if delta.crowd_size is not None:
        derived_scenario.crowd_size = delta.crowd_size

    if delta.event_end_delta_minutes is not None:
        # shift the EXIT_SURGE phase (and later phases) so the event ends
        # earlier/later; keep phases in time order and non-negative.
        shift = delta.event_end_delta_minutes
        for phase in derived_scenario.event_phases:
            if phase.name.value in ("EXIT_SURGE", "INTERVAL"):
                phase.start_minute = max(0.0, phase.start_minute + shift)
                phase.end_minute = max(phase.start_minute + 0.5, phase.end_minute + shift)

    def _check_gates(ids: List[str], what: str) -> None:
        unknown = [g for g in ids if g not in gate_ids]
        if unknown:
            raise AIValidationError(f"{what} reference unknown gate ids: {', '.join(unknown)}")

    def _check_edges(ids: List[str], what: str) -> None:
        unknown = [e for e in ids if e not in edges]
        if unknown:
            raise AIValidationError(f"{what} reference unknown edge ids: {', '.join(unknown)}")

    _check_gates(delta.close_gates, "close_gates")
    _check_gates(delta.open_gates, "open_gates")
    _check_edges(delta.close_edges, "close_edges")
    _check_edges(delta.open_edges, "open_edges")

    # gate closures: drop the gate from inflow distribution and close its edges
    closed_gate_set = set(delta.close_gates)
    for gate in closed_gate_set:
        for e in derived_venue.edges:
            if e.source == gate or e.destination == gate:
                e.is_open = False
        dist = derived_scenario.gate_distribution
        if gate in dist:
            del dist[gate]
            derived_scenario.gate_distribution = _normalise_distribution(dist)

    open_gate_set = set(delta.open_gates) - closed_gate_set
    for gate in open_gate_set:
        for e in derived_venue.edges:
            if e.source == gate or e.destination == gate:
                e.is_open = True

    edge_by_id = {e.id: e for e in derived_venue.edges}
    for eid in delta.close_edges:
        edge_by_id[eid].is_open = False
    for eid in delta.open_edges:
        edge_by_id[eid].is_open = True

    for name, dist in (
        ("gate_distribution", delta.gate_distribution),
        ("exit_distribution", delta.exit_distribution),
        ("destination_distribution", delta.destination_distribution),
    ):
        if dist is not None:
            unknown = [k for k in dist if k not in nodes]
            if unknown:
                raise AIValidationError(f"{name} reference unknown node ids: {', '.join(unknown)}")
            setattr(derived_scenario, name, _normalise_distribution(dist))

    if delta.incident is not None:
        if delta.incident.location not in nodes:
            raise AIValidationError(
                f"incident references unknown node id: {delta.incident.location}"
            )
        unknown_exits = [x for x in delta.incident.blocks_exits if x not in nodes]
        if unknown_exits:
            raise AIValidationError(
                f"incident blocks_exits reference unknown node ids: {', '.join(unknown_exits)}"
            )
        derived_scenario.special["incident"] = delta.incident.model_dump(mode="json")

    if delta.weather is not None:
        derived_scenario.special["weather"] = delta.weather.model_dump(mode="json")

    if delta.name_suffix:
        derived_scenario.name = f"{scenario.name} — {delta.name_suffix}"

    return derived_scenario, derived_venue


def scenario_context(venue: VenueModel, scenario: ScenarioModel) -> str:
    """Compact venue inventory fed to the LLM so it can only use real ids."""
    lines = [f"venue={venue.id} name={venue.name} scenario={scenario.id}"]
    nodes = sorted(venue.nodes, key=lambda n: n.id)
    gates = [n.id for n in nodes if n.type == NodeType.ENTRY]
    exits = [n.id for n in nodes if n.type in (NodeType.EXIT, NodeType.EMERGENCY_EXIT)]
    lines.append(f"gates={','.join(gates)}")
    lines.append(f"exits={','.join(exits)}")
    lines.append(f"zones={','.join(n.id for n in nodes if n.type in (NodeType.ZONE, NodeType.CONCESSION, NodeType.CHECKPOINT))}")
    edges = ",".join(e.id for e in venue.edges)
    lines.append(f"edges={edges}")
    lines.append(f"crowd_size={scenario.crowd_size}")
    lines.append(f"phases={','.join(f'{p.name.value}@{p.start_minute}-{p.end_minute}' for p in scenario.event_phases)}")
    return "\n".join(lines)


def metrics_summary(sim_state) -> str:
    m = sim_state.metrics
    lines = [
        f"time={m.t_min:.1f}min phase={sim_state.phase}",
        f"in_venue={m.in_venue} completed={m.total_completed}",
        f"global_density={m.global_density:.2f}/m2 max_util={m.max_utilisation:.2f}",
        f"queue_total={m.queue_total} avg_travel={m.avg_travel_time_min:.1f}min",
        f"bottlenecks={m.bottleneck_count} risk={m.risk_level}",
    ]
    return "\n".join(lines)


def bottlenecks_summary(sim_state) -> str:
    if not sim_state.bottlenecks:
        return "no active bottlenecks"
    lines = []
    for b in sim_state.bottlenecks[:6]:
        lines.append(
            f"{b.location} risk={b.current_risk.value} util={b.capacity_utilisation:.2f} "
            f"queue={b.queue} density={b.current_density:.2f} trend={b.trend} ttc={b.estimated_time_to_critical_min}"
        )
    return "\n".join(lines)


def world_summary(sim_state) -> str:
    """Live external-world state (demand pipeline) fed to the LLM.

    The world is where venue entry actually comes from, so AI explanations
    about "why gate A is overloaded" must see the queues and delivery rates
    outside the gates — not just the venue interior.
    """
    w = getattr(sim_state, "world", None)
    if w is None:
        return "no external world layer"
    lines = [f"world t={w.t_min:.1f}min risk={w.risk.value} congested_edges={w.congested_edges}"]
    gates = [g for g in w.gates.values() if g.queue > 0 or g.served_per_min > 0]
    gates = sorted(w.gates.values(), key=lambda g: g.queue, reverse=True)[:6]
    for g in gates:
        wait = f"{g.queue_wait_min:.0f}min" if g.queue_wait_min is not None else "-"
        lines.append(
            f"{g.gate_id} arrivals={g.arrivals_per_min:.0f}/min served={g.served_per_min:.0f}/min "
            f"queue={g.queue} wait~{wait} risk={g.risk.value}"
        )
    for p in w.predictions[:4]:
        lines.append(f"prediction {p.kind}:{p.ref} -> {p.message}")
    return "\n".join(lines)
