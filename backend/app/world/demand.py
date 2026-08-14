"""External demand model.

Demand sources are *scenario inputs* by default (SIMULATED provenance). Each
source produces a share of the total arrival rate, distributed across venue
gates by the scenario's gate distribution (or uniformly). Later these can be
driven by ticketing / turnstiles / camera counts / transit APIs — the model
stays the same, only ``data_source`` changes.
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

from ..models import NodeType, ScenarioModel, VenueModel
from .models import DemandSource, WorldGraph


class SourcePlan(BaseModel):
    source_id: str
    kind: str
    share: float = Field(ge=0, le=1)
    gates: Dict[str, float] = Field(default_factory=dict)


class DemandPlan(BaseModel):
    """How the scenario's arrival rate is split across sources and gates."""

    total_rate_per_min: float = 0.0
    sources: Dict[str, SourcePlan] = Field(default_factory=dict)

    def gate_share(self, gate_id: str) -> float:
        """Total arrival share arriving at a given gate across all sources."""
        total = 0.0
        for plan in self.sources.values():
            total += plan.share * plan.gates.get(gate_id, 0.0)
        return total


def plan_demand(
    graph: WorldGraph,
    scenario: ScenarioModel,
    venue: VenueModel,
) -> DemandPlan:
    """Build the demand plan from graph sources + scenario gate distribution."""
    entries = [n.id for n in venue.nodes if n.type == NodeType.ENTRY]
    if not entries:
        return DemandPlan()

    scenario_gates = scenario.gate_distribution or {}
    if scenario_gates:
        total = sum(scenario_gates.values())
        gate_weights = {g: w / total for g, w in scenario_gates.items()}
        # only keep entries actually present in the venue
        gate_weights = {g: w for g, w in gate_weights.items() if g in entries}
    else:
        gate_weights = {g: 1.0 / len(entries) for g in entries}
    if not gate_weights:
        return DemandPlan()

    sources: List[DemandSource] = graph.demand_sources or []
    total_share = sum(s.share for s in sources) or 1.0
    plan = DemandPlan(total_rate_per_min=float(scenario.arrival_rate_per_minute))

    for source in sources:
        share = source.share / total_share
        plan.sources[source.id] = SourcePlan(
            source_id=source.id,
            kind=source.kind,
            share=share,
            gates=dict(gate_weights),
        )
    return plan


def redistribute_gates(plan: DemandPlan, from_gate: str, to_gate: str, pct: float) -> DemandPlan:
    """Redirect `pct`% of each source's `from_gate` arrivals to `to_gate`.

    Mutates and returns the plan so world-level REDIRECT interventions change
    the actual flow assignment (the simulation state really changes).
    """
    factor = max(0.0, min(1.0, pct / 100.0))
    for src in plan.sources.values():
        from_share = src.gates.get(from_gate, 0.0)
        if from_share <= 0:
            continue
        move = from_share * factor
        src.gates[from_gate] = from_share - move
        src.gates[to_gate] = src.gates.get(to_gate, 0.0) + move
    return plan