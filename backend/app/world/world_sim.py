"""External world simulation — aggregate crowd flow over the unified graph.

Level 1 of CrowdFlow's hierarchical model: *aggregate external flow*. Demand
sources emit arrivals which travel along congestion-aware routes to venue
gates; gates serve at their capacity and queue excess outside. Egress from
venue exits flows back toward outer sinks. The venue digital twin consumes the
served gate rates (Level 2); microscopic detail around bottlenecks (Level 3)
is deferred to the venue simulation.

Everything here is deterministic and derived from the world model — scenario
demand routed over the real external graph with capacity heuristics. No
fabricated numbers.
"""
from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Set, Tuple

from ..engine.predictor import predict_time_to_critical, risk_level_from_score
from ..models import (
    Intervention,
    InterventionType,
    NodeType,
    RiskLevel,
    ScenarioModel,
    VenueModel,
)
from .demand import DemandPlan, plan_demand, redistribute_gates
from .models import (
    AccessPoint,
    ExternalEdge,
    WorldEdgeState,
    WorldGateState,
    WorldGraph,
    WorldPrediction,
    WorldSourceState,
    WorldState,
)

CRITICAL_UTIL = 0.85
GATE_CRITICAL_QUEUE_FACTOR = 4.0  # gate congestion=1.0 at ~4 minutes of queued service
SAMPLE_PER_MIN = 15.0
HISTORY_LEN = 90
REROUTE_EVERY_TICKS = 20
# Organic gate rebalancing: when a gate is congested or closed, a bounded
# fraction of its assigned arrivals drifts to the least-loaded open gate. This
# models the crowd adapting to congestion without an operator intervention.
REBALANCE_EVERY_MIN = 3.0
REBALANCE_TRIGGER_QUEUE_MIN = 2.0  # queue > 2 minutes of service triggers drift
REBALANCE_CONGESTED_PCT = 8.0      # % of share moved per cycle when congested
REBALANCE_CLOSED_PCT = 30.0        # % moved per cycle when the gate is closed


class _Packet:
    __slots__ = ("amount", "path", "idx", "ready_t", "gate", "rerouted")

    def __init__(self, amount: float, path: List[str], gate: Optional[str]):
        self.amount = amount
        self.path = path
        self.idx = 0
        self.ready_t = float("inf")
        self.gate = gate
        self.rerouted = False


class WorldSimulation:
    def __init__(self, graph: WorldGraph, venue: VenueModel, scenario: ScenarioModel):
        self.graph = graph
        self.venue = venue
        self.scenario = scenario
        self.plan: DemandPlan = plan_demand(graph, scenario, venue)

        self._adj: Dict[str, List[ExternalEdge]] = {}
        for e in graph.edges:
            self._adj.setdefault(e.source, []).append(e)

        self._gate_node: Dict[str, str] = {}
        self._gate_service: Dict[str, float] = {}
        self._default_gate_service: Dict[str, float] = {}
        self._exit_aps: List[AccessPoint] = []
        for ap in graph.access_points:
            if ap.kind == "ENTRY":
                self._gate_node[ap.gate_id] = ap.node_id
                self._gate_service[ap.gate_id] = ap.service_ppm
                self._default_gate_service[ap.gate_id] = ap.service_ppm
            else:
                self._exit_aps.append(ap)

        self._source_node: Dict[str, str] = {
            s.id: s.node_id for s in graph.demand_sources
        }
        self._sinks: List[str] = graph.sink_ids or []

        self.t_min = 0.0
        self.tick_count = 0
        self.last_dt = 0.0
        # Virtual clock advance from engine warm-up: the world may have been
        # running for N minutes before the event clock starts. state() reports
        # ``t_min - time_offset`` so the world clock lines up with the venue.
        self.time_offset = 0.0
        self.edge_flow: Dict[str, float] = {}
        self.edge_people: Dict[str, float] = {}
        self.edge_pkts: Dict[str, List[_Packet]] = {}
        self._held: List[_Packet] = []
        self.gate_queues: Dict[str, float] = {}
        self.gate_arrivals: Dict[str, float] = {}
        self.gate_served: Dict[str, float] = {}
        # Smoothed per-minute rates so consumers (the venue spawn coupling) see
        # stable delivery numbers instead of bursty per-tick fractions. Flow
        # packets arrive in lumps, so instantaneous ``served/dt`` flickers wildly.
        self.gate_arrivals_rate: Dict[str, float] = {}
        self.gate_served_rate: Dict[str, float] = {}
        self.source_emitted: Dict[str, float] = {}
        self.source_rate: Dict[str, float] = {}
        self.history_util: Dict[str, List[float]] = {}
        self.closed: Set[str] = set()
        self.rerouted_edges: Set[str] = set()
        self._paths_cache: Dict[Tuple[str, str], Optional[List[str]]] = {}
        self._reroute_clock = 0
        self._last_rebalance = 0.0

        self._sink_nodes: Dict[str, Optional[str]] = {}
        for ap in self._exit_aps:
            self._sink_nodes[ap.gate_id] = self._nearest_sink(ap.node_id)

        # scenario-level world conditions (road closures / gate failures) must
        # apply before warm-up so the pre-event state reflects them too.
        self._apply_scenario_world_conditions()

    # ------------------------------------------------------------------ #
    #  Scenario world conditions
    # ------------------------------------------------------------------ #
    def _apply_scenario_world_conditions(self) -> None:
        """Apply ``scenario.special.world`` conditions at (re)start.

        - ``gate_capacities``: {gate_id: people/min} overrides the gate service
          rate (0 closes the gate). Deterministic, topology-agnostic, and safe
          under ``reset()`` — this is what road-closure / multi-gate-failure
          scenarios use to model throttled or failed approaches. The organic
          rebalancing then drifts demand to the least-loaded open gate.
        - ``closed_edges``: explicit external edge ids to close outright
          (both directions), for scenarios that want a literal road closure.
        """
        special = self.scenario.special or {}
        world = special.get("world") or {}
        for gate_id, cap in (world.get("gate_capacities") or {}).items():
            if gate_id in self._gate_service:
                self._gate_service[gate_id] = max(0.0, float(cap))
        for edge_id in world.get("closed_edges") or []:
            if self.graph.edge(edge_id) is not None:
                self._set_edge_closed(edge_id, True)

    # ------------------------------------------------------------------ #
    #  Routing
    # ------------------------------------------------------------------ #
    def _travel(self, edge_id: str) -> float:
        e = self.graph.edge(edge_id)
        if e is None or e.id in self.closed:
            return float("inf")
        return e.travel_min(self.edge_flow.get(edge_id, 0.0))

    def _shortest_path(self, start: str, goal: str) -> Optional[List[str]]:
        if start == goal:
            return []
        key = (start, goal)
        cached = self._paths_cache.get(key)
        if cached is not None:
            return cached
        dist = {start: 0.0}
        prev: Dict[str, Tuple[str, str]] = {}
        pq: List[Tuple[float, str]] = [(0.0, start)]
        seen: Set[str] = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in seen:
                continue
            seen.add(u)
            if u == goal:
                break
            for e in self._adj.get(u, []):
                if e.id in self.closed:
                    continue
                cost = e.travel_min(self.edge_flow.get(e.id, 0.0))
                if math.isinf(cost):
                    continue
                nd = d + cost
                if nd < dist.get(e.target, float("inf")):
                    dist[e.target] = nd
                    prev[e.target] = (u, e.id)
                    heapq.heappush(pq, (nd, e.target))
        if goal not in prev:
            self._paths_cache[key] = None
            return None
        path: List[str] = []
        cur = goal
        while cur != start:
            parent, eid = prev.get(cur, (None, None))
            if parent is None:
                self._paths_cache[key] = None
                return None
            path.append(eid)
            cur = parent
        path.reverse()
        self._paths_cache[key] = path
        return path

    def _path(self, start: str, goal: str) -> Optional[List[str]]:
        key = (start, goal)
        if key not in self._paths_cache:
            self._paths_cache[key] = self._shortest_path(start, goal)
        return self._paths_cache.get(key)

    def _nearest_sink(self, node_id: str) -> Optional[str]:
        best: Optional[Tuple[float, str]] = None
        for sink in self._sinks:
            path = self._shortest_path(node_id, sink)
            if path is None:
                continue
            cost = sum(self._travel(e) for e in path)
            if best is None or cost < best[0]:
                best = (cost, sink)
        return best[1] if best else None

    def _route_cost(self, path: Optional[List[str]]) -> float:
        if not path:
            return float("inf")
        return sum(self._travel(e) for e in path)

    # ------------------------------------------------------------------ #
    #  Flow primitives
    # ------------------------------------------------------------------ #
    def _emit(self, path: List[str], gate: Optional[str], amount: float, rerouted: bool) -> None:
        if not path or amount <= 1e-9:
            return
        p = _Packet(amount, list(path), gate)
        p.rerouted = rerouted
        first = path[0]
        p.ready_t = self.t_min + self._travel(first)
        if math.isinf(p.ready_t):
            self._held.append(p)
            return
        self.edge_pkts.setdefault(first, []).append(p)

    def _advance(self, p: _Packet, completions: Dict[str, float], staging: Dict[str, List[_Packet]]) -> None:
        edge_id = p.path[p.idx]
        completions[edge_id] = completions.get(edge_id, 0.0) + p.amount
        p.idx += 1
        if p.idx >= len(p.path):
            if p.gate is not None:
                self.gate_arrivals[p.gate] = self.gate_arrivals.get(p.gate, 0.0) + p.amount
            return
        nxt = p.path[p.idx]
        if nxt in self.closed:
            # reroute around the closure from the node we are arriving at
            e = self.graph.edge(edge_id)
            node = e.target if e else None
            alt = self._path(node, p.gate) if node else None
            if alt:
                p.path = alt
                p.idx = 0
                p.rerouted = True
                for a in alt:
                    self.rerouted_edges.add(a)
            else:
                self._held.append(p)
                return
            nxt = p.path[p.idx]
        p.ready_t = self.t_min + self._travel(nxt)
        if math.isinf(p.ready_t):
            self._held.append(p)
            return
        staging.setdefault(nxt, []).append(p)

    def _settle(self) -> Dict[str, float]:
        completions: Dict[str, float] = {}
        staging: Dict[str, List[_Packet]] = {}
        moved_held: List[_Packet] = []
        for p in self._held:
            if self._travel(p.path[p.idx]) < float("inf"):
                p.ready_t = self.t_min + self._travel(p.path[p.idx])
                staging.setdefault(p.path[p.idx], []).append(p)
            else:
                moved_held.append(p)
        self._held = moved_held

        for edge in self.graph.edges:
            bucket = self.edge_pkts.pop(edge.id, [])
            if not bucket:
                continue
            keep: List[_Packet] = []
            for p in bucket:
                if p.ready_t <= self.t_min:
                    self._advance(p, completions, staging)
                else:
                    keep.append(p)
            if keep:
                self.edge_pkts[edge.id] = keep
        for eid, pkts in staging.items():
            self.edge_pkts.setdefault(eid, []).extend(pkts)
        return completions

    # ------------------------------------------------------------------ #
    #  Demand / egress emission
    # ------------------------------------------------------------------ #
    def _emit_arrivals(self, arrival_rate: float, dt: float) -> None:
        for sid, splan in self.plan.sources.items():
            rate = arrival_rate * splan.share
            self.source_rate[sid] = rate
            if rate <= 0:
                continue
            self.source_emitted[sid] = self.source_emitted.get(sid, 0.0) + rate * dt
            src_node = self._source_node.get(sid)
            if src_node is None:
                continue
            for gate, gshare in splan.gates.items():
                gate_node = self._gate_node.get(gate)
                if gate_node is None or gshare <= 0:
                    continue
                path = self._path(src_node, gate_node)
                if path is None:
                    continue
                self._emit(path, gate, gshare * rate * dt, rerouted=False)

    def _emit_egress(self, exit_rate: float, dt: float) -> None:
        if exit_rate <= 0 or not self._exit_aps:
            return
        exits = [ap.gate_id for ap in self._exit_aps]
        dist = self.scenario.exit_distribution or {}
        weights = {g: dist.get(g, 1.0) for g in exits}
        total = sum(weights.values()) or 1.0
        for ap in self._exit_aps:
            share = (weights.get(ap.gate_id, 1.0) / total) * exit_rate
            if share <= 0:
                continue
            sink = self._sink_nodes.get(ap.gate_id)
            path = self._path(ap.node_id, sink) if sink else None
            if path is None:
                continue
            self._emit(path, None, share * dt, rerouted=False)

    # ------------------------------------------------------------------ #
    #  Gate service
    # ------------------------------------------------------------------ #
    def _serve_gates(self, dt: float) -> None:
        for gate_id, service in self._gate_service.items():
            arrivals = self.gate_arrivals.get(gate_id, 0.0)
            queue = self.gate_queues.get(gate_id, 0.0)
            avail = arrivals + queue
            served = min(avail, service * dt)
            self.gate_served[gate_id] = served
            self.gate_queues[gate_id] = avail - served

    def served_gate_rates(self, dt: float) -> Dict[str, float]:
        """Smoothed per-gate served rates (people/min) as of the last step.

        ``dt`` is accepted for API compatibility but the returned rates are
        already expressed per minute — they are not divided by the caller's
        step size (doing so corrupted rates when warm-up used larger steps).
        """
        return {g: self.gate_served_rate.get(g, 0.0) for g in self._gate_service}

    # ------------------------------------------------------------------ #
    #  Organic gate rebalancing
    # ------------------------------------------------------------------ #
    def _rebalance_gates(self) -> None:
        """Shift a bounded share of arrivals off congested/closed gates.

        When a gate's queue exceeds a small multiple of its service rate (or
        the gate is closed), a fraction of that gate's assigned arrivals drifts
        to the least-loaded *open* gate. Deterministic, gradual, and distinct
        from the operator's REDIRECT intervention (an immediate arbitrary
        override). Runs only on the live event clock (not during warm-up) so
        the event starts on the scenario's static plan and the crowd adapts
        from there.
        """
        now = self.t_min
        if self.time_offset <= 0:
            self._last_rebalance = now
            return
        if now - self._last_rebalance < REBALANCE_EVERY_MIN:
            return
        self._last_rebalance = now

        loaded: List[Tuple[float, str]] = []
        for gate_id in self._gate_service:
            service = self._gate_service[gate_id]
            queue = self.gate_queues.get(gate_id, 0.0)
            if service <= 0:
                loaded.append((float("inf"), gate_id))
            elif queue > service * REBALANCE_TRIGGER_QUEUE_MIN:
                loaded.append((queue / service, gate_id))
        if not loaded:
            return

        open_gates = [g for g in self._gate_service if self._gate_service[g] > 0]
        if not open_gates:
            return
        target = min(
            open_gates,
            key=lambda g: self.gate_queues.get(g, 0.0) / max(1.0, self._gate_service[g]),
        )
        _, source = max(loaded, key=lambda x: x[0])
        if source == target:
            return
        # never push share onto a gate already more loaded than the source
        src_load = self.gate_queues.get(source, 0.0) / max(1.0, self._gate_service[source])
        tgt_load = self.gate_queues.get(target, 0.0) / max(1.0, self._gate_service[target])
        if tgt_load >= src_load:
            return

        pct = REBALANCE_CLOSED_PCT if self._gate_service[source] <= 0 else REBALANCE_CONGESTED_PCT
        redistribute_gates(self.plan, source, target, pct)
        self._paths_cache.clear()

    # ------------------------------------------------------------------ #
    #  Main step
    # ------------------------------------------------------------------ #
    def step(self, dt_min: float, arrival_rate: float, exit_rate: float) -> None:
        if dt_min <= 0:
            return
        self.tick_count += 1
        self.t_min += dt_min
        self.last_dt = dt_min
        self._reroute_clock += 1
        if self._reroute_clock >= REROUTE_EVERY_TICKS:
            self._paths_cache.clear()
            self._reroute_clock = 0
        self.rerouted_edges.clear()
        for g in self._gate_service:
            self.gate_arrivals[g] = 0.0
            self.gate_served[g] = 0.0

        completions = self._settle()
        self._emit_egress(exit_rate, dt_min)
        self._emit_arrivals(arrival_rate, dt_min)
        self._serve_gates(dt_min)
        if arrival_rate > 0:
            self._rebalance_gates()

        # smooth per-gate rates (independent of step size, immune to bursty
        # packet arrivals)
        step_min = max(dt_min, 1e-9)
        for gate_id in self._gate_service:
            inst_arr = self.gate_arrivals.get(gate_id, 0.0) / step_min
            inst_srv = self.gate_served.get(gate_id, 0.0) / step_min
            prev_a = self.gate_arrivals_rate.get(gate_id, 0.0)
            prev_s = self.gate_served_rate.get(gate_id, 0.0)
            self.gate_arrivals_rate[gate_id] = 0.7 * prev_a + 0.3 * inst_arr
            self.gate_served_rate[gate_id] = 0.7 * prev_s + 0.3 * inst_srv

        # per-edge stats
        for e in self.graph.edges:
            people = sum(p.amount for p in self.edge_pkts.get(e.id, []))
            flow = completions.get(e.id, 0.0) / dt_min
            prev = self.edge_flow.get(e.id, 0.0)
            smoothed = 0.7 * prev + 0.3 * flow
            self.edge_flow[e.id] = smoothed
            self.edge_people[e.id] = people
            util = smoothed / max(1.0, e.capacity_estimate)
            self.history_util.setdefault(e.id, []).append(util)
            hist = self.history_util[e.id]
            if len(hist) > HISTORY_LEN:
                self.history_util[e.id] = hist[-HISTORY_LEN:]

    def reset(self) -> None:
        self.t_min = 0.0
        self.tick_count = 0
        self.last_dt = 0.0
        self.time_offset = 0.0
        self.edge_flow.clear()
        self.edge_people.clear()
        self.edge_pkts.clear()
        self._held.clear()
        self.gate_queues.clear()
        self.gate_arrivals.clear()
        self.gate_served.clear()
        self.gate_arrivals_rate.clear()
        self.gate_served_rate.clear()
        self.source_emitted.clear()
        self.source_rate.clear()
        self.history_util.clear()
        self.closed.clear()
        self._paths_cache.clear()
        self._reroute_clock = 0
        self._last_rebalance = 0.0
        self.plan = plan_demand(self.graph, self.scenario, self.venue)
        # restore scenario-level closures/restrictions that reset() cleared
        self._apply_scenario_world_conditions()

    def copy(self) -> "WorldSimulation":
        clone = WorldSimulation(self.graph, self.venue, self.scenario)
        clone.t_min = self.t_min
        clone.tick_count = self.tick_count
        clone.last_dt = self.last_dt
        clone.time_offset = self.time_offset
        clone.edge_flow = dict(self.edge_flow)
        clone.edge_people = dict(self.edge_people)
        clone.edge_pkts = {
            eid: [self._copy_packet(p) for p in pkts]
            for eid, pkts in self.edge_pkts.items()
        }
        clone._held = [self._copy_packet(p) for p in self._held]
        clone.gate_queues = dict(self.gate_queues)
        clone.gate_arrivals = dict(self.gate_arrivals)
        clone.gate_served = dict(self.gate_served)
        clone.gate_arrivals_rate = dict(self.gate_arrivals_rate)
        clone.gate_served_rate = dict(self.gate_served_rate)
        clone.source_emitted = dict(self.source_emitted)
        clone.source_rate = dict(self.source_rate)
        clone.history_util = {k: list(v) for k, v in self.history_util.items()}
        clone.closed = set(self.closed)
        clone._last_rebalance = self._last_rebalance
        clone.plan = self.plan.model_copy(deep=True)
        return clone

    @staticmethod
    def _copy_packet(p: _Packet) -> _Packet:
        c = _Packet(p.amount, list(p.path), p.gate)
        c.idx = p.idx
        c.ready_t = p.ready_t
        c.rerouted = p.rerouted
        return c

    # ------------------------------------------------------------------ #
    #  Interventions
    # ------------------------------------------------------------------ #
    def apply_intervention(self, intervention: Intervention) -> None:
        p = intervention.parameters
        kind = intervention.type

        if kind == InterventionType.REDIRECT:
            from_gate = str(p.get("from") or "")
            to_gate = str(p.get("to") or "")
            pct = float(p.get("percent", 15))
            if from_gate and to_gate and from_gate in self._gate_service:
                redistribute_gates(self.plan, from_gate, to_gate, pct)
                self._paths_cache.clear()
        elif kind == InterventionType.CHANGE_GATE:
            gate = str(p.get("gate") or p.get("from") or "")
            if gate in self._gate_service:
                if p.get("restore"):
                    # re-open: back to the graph's default gate throughput
                    self._gate_service[gate] = self._default_gate_service.get(gate, 100.0)
                else:
                    cap = float(p.get("capacity") or p.get("capacity_ppm") or 0)
                    # 0 closes the gate (service stops -> the venue receives
                    # nothing there and demand queues outside)
                    self._gate_service[gate] = max(0.0, cap)
        elif kind == InterventionType.CLOSE_CORRIDOR:
            edge_id = str(p.get("external_edge") or p.get("edge_id") or "")
            self._set_edge_closed(edge_id, True)
        elif kind == InterventionType.OPEN_CORRIDOR:
            edge_id = str(p.get("external_edge") or p.get("edge_id") or "")
            self._set_edge_closed(edge_id, False)

    def _set_edge_closed(self, edge_id: str, closed: bool) -> None:
        e = self.graph.edge(edge_id)
        if e is None:
            return
        reverse = next(
            (x.id for x in self.graph.edges if x.source == e.target and x.target == e.source),
            None,
        )
        if closed:
            self.closed.add(e.id)
            if reverse:
                self.closed.add(reverse)
        else:
            self.closed.discard(e.id)
            if reverse:
                self.closed.discard(reverse)
        self._paths_cache.clear()

    def set_gate_capacity(self, gate_id: str, capacity_ppm: float) -> None:
        if gate_id in self._gate_service:
            self._gate_service[gate_id] = max(0.0, capacity_ppm)

    # ------------------------------------------------------------------ #
    #  State
    # ------------------------------------------------------------------ #
    def state(self) -> WorldState:
        edges: Dict[str, WorldEdgeState] = {}
        congested = 0
        worst_risk = 0.0
        for e in self.graph.edges:
            util = self.edge_flow.get(e.id, 0.0) / max(1.0, e.capacity_estimate)
            closed = e.id in self.closed
            if closed:
                util = 0.0
            congestion = min(1.0, util)
            risk_score = util
            if congestion > 0.35:
                congested += 1
            worst_risk = max(worst_risk, risk_score)
            hist = self.history_util.get(e.id, [])
            ttc = predict_time_to_critical(hist, CRITICAL_UTIL, SAMPLE_PER_MIN)
            edges[e.id] = WorldEdgeState(
                id=e.id,
                kind=e.kind,
                flow_per_min=round(self.edge_flow.get(e.id, 0.0), 1),
                people=int(round(self.edge_people.get(e.id, 0.0))),
                utilisation=round(util, 3),
                congestion=round(congestion, 3),
                risk=RiskLevel(risk_level_from_score(risk_score)),
                time_to_critical_min=ttc,
                closed=closed,
                rerouted=e.id in self.rerouted_edges,
            )

        gates: Dict[str, WorldGateState] = {}
        for gate_id, service in self._gate_service.items():
            arrivals = self.gate_arrivals.get(gate_id, 0.0)
            served = self.gate_served.get(gate_id, 0.0)
            queue = self.gate_queues.get(gate_id, 0.0)
            arrivals_rate = self.gate_arrivals_rate.get(gate_id, 0.0)
            served_rate = self.gate_served_rate.get(gate_id, 0.0)
            congestion = min(1.0, queue / max(1.0, service * GATE_CRITICAL_QUEUE_FACTOR))
            gates[gate_id] = WorldGateState(
                gate_id=gate_id,
                arrivals_per_min=round(arrivals_rate, 2),
                served_per_min=round(served_rate, 2),
                queue=int(round(queue)),
                queue_wait_min=round(queue / max(1e-6, served_rate), 1) if queue > 0 else None,
                congestion=round(congestion, 3),
                risk=RiskLevel(risk_level_from_score(congestion)),
                demand_by_source={},
            )

        sources: Dict[str, WorldSourceState] = {}
        for s in self.graph.demand_sources:
            sources[s.id] = WorldSourceState(
                id=s.id,
                kind=s.kind,
                emitted_total=int(round(self.source_emitted.get(s.id, 0.0))),
                current_rate_per_min=round(self.source_rate.get(s.id, 0.0), 1),
            )

        predictions: List[WorldPrediction] = []
        for eid, state in edges.items():
            if state.time_to_critical_min is not None and 0 < state.time_to_critical_min <= 6.0:
                predictions.append(WorldPrediction(
                    id=f"WP_{eid}",
                    kind="EDGE",
                    ref=eid,
                    in_minutes=round(state.time_to_critical_min, 1),
                    severity=state.risk,
                    message=f"External edge {eid} projected to saturate in ~{state.time_to_critical_min:.1f} min",
                ))
        for gate_id, gstate in gates.items():
            service = self._gate_service[gate_id]
            if gstate.queue >= max(1.0, service * 2.0) and gstate.congestion > 0.4:
                predictions.append(WorldPrediction(
                    id=f"WP_GATE_{gate_id}",
                    kind="GATE",
                    ref=gate_id,
                    in_minutes=round(gstate.queue / max(1e-6, gstate.served_per_min), 1),
                    severity=gstate.risk,
                    message=f"Queue at {gate_id} ~{gstate.queue} people (~{gstate.queue_wait_min or 0:.0f} min wait)",
                ))

        queue_gates = {g: s.queue for g, s in gates.items() if s.queue > 0}
        if queue_gates:
            worst = max(queue_gates, key=queue_gates.get)
            summary = (
                f"External: {sum(self.source_rate.values()):.0f}/min arrivals, "
                f"{len(self._gate_service)} gates serving; queue at {worst} "
                f"({queue_gates[worst]} people)"
            )
        else:
            summary = (
                f"External: {sum(self.source_rate.values()):.0f}/min arrivals flowing "
                f"to {len(self._gate_service)} gates, no queues"
            )

        return WorldState(
            t_min=round(max(0.0, self.t_min - self.time_offset), 2),
            edges=edges,
            gates=gates,
            sources=sources,
            risk=RiskLevel(risk_level_from_score(worst_risk)),
            congested_edges=congested,
            summary=summary,
            predictions=predictions,
        )