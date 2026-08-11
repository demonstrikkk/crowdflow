"""CrowdFlow simulation engine.

Time-stepped pedestrian simulation over the venue graph:

  - agents spawn at entry gates during arrival phases and travel along
    congestion-aware routes to their destination zone (seats / concessions);
  - during the exit-surge phase seated agents are assigned exit destinations;
  - agents slow down under congestion and queue at saturated walkways;
  - every tick produces node/edge metrics, risk scores, bottleneck forecasts
    and a recommended intervention (brief sections 9-16).

Simulation population vs visual population (brief section 9):
  each simulated agent represents `scale_units` real people. Metrics are
  reported in real-people units; the frontend draws the simulated agents.

Route invariant: an agent's route always starts with its current node; while
an agent is traversing walkway (u, v), route[0] == u and route[1] == v.
"""
from __future__ import annotations

import copy
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..models import (
    AgentModel,
    Bottleneck,
    EdgeModel,
    ElementState,
    EventPhaseModel,
    EventPhaseName,
    IncidentSpec,
    Intervention,
    InterventionType,
    NodeType,
    Position,
    RiskLevel,
    ScenarioModel,
    SimulationMetrics,
    SimulationState,
    SimulationStatus,
    WeatherSpec,
)
from .predictor import classify_trend, predict_time_to_critical, risk_level_from_score
from .routing import EdgeUsage, RoutingEngine
from .venue import VenueGraph
from .environment import ExternalCongestion, build_bundled_environment

TICK_DT_MIN = 4.0 / 60.0            # one tick = 4 simulated seconds
MAX_AGENTS = 1200                   # simulation population cap
CRITICAL_UTIL = 0.85                # prediction threshold
WALKING_SPEED = 1.2                 # m/s free flow
COMFORT_DENSITY = 2.0               # people / m^2 used to normalise densities
SAMPLES_PER_MIN = 1.0 / TICK_DT_MIN


@dataclass
class Agent:
    id: int
    origin: str
    destination: str
    route: List[str]
    speed_mps: float
    scale_units: int
    spawned_at: float
    completed_at: Optional[float] = None
    on_node: Optional[str] = None
    on_edge: Optional[Tuple[str, str]] = None
    progress: float = 0.0
    idle: bool = False
    waiting_since: Optional[float] = None
    is_rerouted: bool = False
    is_emergency: bool = False

    def to_model(self, pos: Position) -> AgentModel:
        return AgentModel(
            id=self.id,
            position=pos,
            destination=self.destination,
            route=list(self.route),
            speed_mps=self.speed_mps,
            scale_units=self.scale_units,
            is_rerouted=self.is_rerouted,
            is_emergency=self.is_emergency,
        )


@dataclass
class NodeState:
    people: int = 0                 # real-people units at the node
    queue: int = 0                  # real-people units waiting to proceed
    flow_per_min: float = 0.0
    utilisation: float = 0.0
    density: float = 0.0
    risk_score: float = 0.0
    usage_history: List[float] = field(default_factory=list)
    trend: str = "Stable"
    time_to_critical: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.NORMAL


@dataclass
class EdgeState:
    people: int = 0                 # real-people units transiting
    completions: float = 0.0        # real-people units that finished this edge
    entries: float = 0.0            # real-people units that started this edge this tick
    flow_per_min: float = 0.0
    utilisation: float = 0.0
    density: float = 0.0
    risk_score: float = 0.0
    usage_history: List[float] = field(default_factory=list)
    trend: str = "Stable"
    time_to_critical: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.NORMAL


class SimulationEngine:
    def __init__(
        self,
        sim_id: str,
        scenario: ScenarioModel,
        graph: VenueGraph,
        routing: RoutingEngine,
        seed: int = 42,
        max_agents: int = MAX_AGENTS,
    ):
        self.sim_id = sim_id
        self.scenario = scenario.model_copy(deep=True)  # interventions never leak
        self.venue = graph.venue
        self.graph = graph
        self.routing = routing
        self.rng = random.Random(seed)
        self.max_agents = max_agents
        self.scale = max(1, math.ceil(scenario.crowd_size / max_agents))
        self._surge_spread_min = getattr(scenario, "surge_departure_spread_min", 8.0)

        self.t_min = 0.0
        self.tick_count = 0
        self.status = SimulationStatus.IDLE
        self.speed = 30.0
        self.emergency_active = False
        self.interventions: List[Intervention] = []

        self.agents: List[Agent] = []
        self._next_agent_id = 1
        self._spawn_budget = 0.0
        self._prev_phase: Optional[str] = None
        self._surge_started_at: Optional[float] = None
        self._egress_started_at: Optional[float] = None

        self.nodes: Dict[str, NodeState] = {n.id: NodeState() for n in self.venue.nodes}
        self.edges: Dict[Tuple[str, str], EdgeState] = {}
        for e in self.venue.edges:
            self.edges.setdefault((e.source, e.destination), EdgeState())
            self.edges.setdefault((e.destination, e.source), EdgeState())

        # Operational conditions (weather / incidents). State is derived from the
        # scenario's `special` block and can be changed at runtime by interventions.
        self.weather: Optional[WeatherSpec] = None
        self.incident: Optional[IncidentSpec] = None
        self._hazard_nodes: Set[str] = set()
        self._hazard_edges: Set[Tuple[str, str]] = set()
        self._hazard_radius_m: float = 0.0
        self._edge_capacity_mult: Dict[Tuple[str, str], float] = {}
        self._edge_speed_mult: Dict[Tuple[str, str], float] = {}
        self._apply_scenario_conditions()

        self.total_spawned = 0
        self.total_completed = 0
        self._completed_travel_times: List[float] = []
        self._completion_window: deque = deque(maxlen=15)   # completions per minute (15 ticks/min)
        self._queue_prev = 0
        self.history: List[Dict] = []
        self.metrics: SimulationMetrics = self._empty_metrics()

        # external road network + congestion (brief section 20)
        self.environment = build_bundled_environment(self.venue)
        self.external = ExternalCongestion(self.environment, self.venue)

        self._default_gate_distribution = self._default_distribution(
            self.graph.entries, self.graph.entry_capacities
        )
        self._default_destination_distribution = self._default_distribution(
            self.graph.zones + self.graph.concessions, None
        )
        self._default_exit_distribution = self._default_distribution(self.graph.exits, None)

    # ------------------------------------------------------------------ #
    #  Public control API
    # ------------------------------------------------------------------ #
    def play(self) -> None:
        self.status = SimulationStatus.RUNNING

    def pause(self) -> None:
        self.status = SimulationStatus.PAUSED

    def reset(self) -> None:
        self.agents.clear()
        self.t_min = 0.0
        self.tick_count = 0
        self._next_agent_id = 1
        self._spawn_budget = 0.0
        self.total_spawned = 0
        self.total_completed = 0
        self._completed_travel_times.clear()
        self._completion_window.clear()
        self._queue_prev = 0
        self.history.clear()
        self.interventions.clear()
        self.emergency_active = False
        self.routing.set_emergency(False)
        self.status = SimulationStatus.IDLE
        self.scenario = self.scenario.model_copy(deep=True)
        for ns in self.nodes.values():
            ns.people = 0
            ns.queue = 0
            ns.flow_per_min = 0.0
            ns.utilisation = 0.0
            ns.density = 0.0
            ns.risk_score = 0.0
            ns.usage_history.clear()
            ns.trend = "Stable"
            ns.time_to_critical = None
            ns.risk_level = RiskLevel.NORMAL
        for es in self.edges.values():
            es.people = 0
            es.completions = 0.0
            es.entries = 0.0
            es.flow_per_min = 0.0
            es.utilisation = 0.0
            es.density = 0.0
            es.risk_score = 0.0
            es.usage_history.clear()
            es.trend = "Stable"
            es.time_to_critical = None
            es.risk_level = RiskLevel.NORMAL
        self.metrics = self._empty_metrics()
        self.external.reset()

    def set_speed(self, speed: float) -> None:
        self.speed = max(1.0, min(240.0, speed))

    def _empty_metrics(self) -> SimulationMetrics:
        return SimulationMetrics(
            t_min=0.0, in_venue=0, total_spawned=0, total_completed=0
        )

    # ------------------------------------------------------------------ #
    #  Operational conditions (weather / incident / static edge policy)
    # ------------------------------------------------------------------ #
    def _apply_scenario_conditions(self) -> None:
        """Load weather/incident/edge-policy from scenario.special at (re)start."""
        self.weather = None
        self.incident = None
        self._edge_capacity_mult.clear()
        self._edge_speed_mult.clear()
        self._hazard_nodes.clear()
        self._hazard_edges.clear()
        self._hazard_radius_m = 0.0

        special = self.scenario.special or {}
        if special.get("weather"):
            self.set_weather(WeatherSpec.model_validate(special["weather"]))
        if special.get("incident"):
            self.set_incident(IncidentSpec.model_validate(special["incident"]))
        self._recompute_multipliers()

    def _edge_outdoor(self, u: str, v: str) -> bool:
        edge = self.graph.edge(u, v)
        return bool(edge and edge.exposure == "OUTDOOR")

    def edge_capacity_effective(self, u: str, v: str) -> float:
        base = self.graph.edge_capacity(u, v)
        mult = self._edge_capacity_mult.get((u, v), 1.0)
        return base * mult

    def _edge_speed_factor(self, u: str, v: str) -> float:
        return self._edge_speed_mult.get((u, v), 1.0)

    def _recompute_multipliers(self) -> None:
        """Rebuild effective edge multipliers from static policy + weather + incident."""
        self._edge_capacity_mult.clear()
        self._edge_speed_mult.clear()
        for e in self.venue.edges:
            if not e.is_open:
                self._edge_capacity_mult[(e.source, e.destination)] = 0.0
                self._edge_capacity_mult[(e.destination, e.source)] = 0.0

        weather = self.weather
        if weather:
            for (u, v) in list(self.edges.keys()):
                outdoor = self._edge_outdoor(u, v)
                if weather.applies_outdoor_only and not outdoor:
                    continue
                if weather.unsafe_outdoor and outdoor:
                    self._edge_capacity_mult[(u, v)] = 0.0
                    self._edge_speed_mult[(u, v)] = 0.3
                else:
                    self._edge_capacity_mult[(u, v)] = weather.capacity_multiplier
                    self._edge_speed_mult[(u, v)] = weather.speed_multiplier

        incident = self.incident
        if incident:
            for (u, v) in self._hazard_edges:
                if incident.type in ("FIRE", "STRUCTURAL"):
                    self._edge_capacity_mult[(u, v)] = 0.0
                else:
                    self._edge_capacity_mult[(u, v)] = min(
                        self._edge_capacity_mult.get((u, v), 1.0), 0.5
                    )

    def set_weather(self, weather: WeatherSpec) -> None:
        """Apply operational weather consequences to outdoor walkways."""
        self.weather = weather
        self._recompute_multipliers()

    def set_incident(self, incident: IncidentSpec) -> None:
        """Arm an incident; its affected area grows each tick via spread_rate."""
        self.incident = incident
        self._hazard_radius_m = incident.radius_m
        self._update_incident()

    def _incident_radius(self) -> float:
        inc = self.incident
        if not inc:
            return 0.0
        return inc.radius_m + inc.spread_rate_m_min * max(0.0, self.t_min)

    def _update_incident(self) -> None:
        """Recompute the affected node/edge set for the current incident radius."""
        inc = self.incident
        if not inc:
            self._hazard_nodes.clear()
            self._hazard_edges.clear()
            self._recompute_multipliers()
            return
        radius = self._incident_radius()
        self._hazard_radius_m = radius
        location = self.graph.node(inc.location)
        loc_pos = location.position if location else None

        affected_nodes: Set[str] = set()
        affected_edges: Set[Tuple[str, str]] = set()

        for n in self.venue.nodes:
            if loc_pos is None or self._point_distance(n.position, loc_pos) <= radius:
                affected_nodes.add(n.id)
            elif n.id in inc.blocks_exits:
                affected_nodes.add(n.id)

        for (u, v) in self.edges.keys():
            if not self.graph.edge(u, v):
                continue
            if self._edge_affected(u, v, loc_pos, radius):
                affected_edges.add((u, v))
            elif u in affected_nodes or v in affected_nodes:
                affected_edges.add((u, v))

        for nid in inc.blocks_exits:
            for (u, v) in list(self.edges.keys()):
                if v == nid:
                    affected_edges.add((u, v))

        self._hazard_nodes = affected_nodes
        self._hazard_edges = affected_edges
        self.routing.set_avoid_edges(affected_edges)
        self._recompute_multipliers()

    def _point_distance(self, a: Position, b: Position) -> float:
        return math.hypot(a.x - b.x, a.y - b.y)

    def _edge_affected(
        self, u: str, v: str, loc_pos: Optional[Position], radius: float
    ) -> bool:
        if loc_pos is None:
            return False
        if not self.graph.edge(u, v):
            return False
        p = self.graph.node(u).position if self.graph.node(u) else None
        q = self.graph.node(v).position if self.graph.node(v) else None
        if p is None or q is None:
            return False
        return self._segment_distance(loc_pos, p, q) <= radius

    @staticmethod
    def _segment_distance(p: Position, a: Position, b: Position) -> float:
        px, py = p.x, p.y
        ax, ay, bx, by = a.x, a.y, b.x, b.y
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    # ------------------------------------------------------------------ #
    #  Event phases
    # ------------------------------------------------------------------ #
    def _phases(self) -> List[EventPhaseModel]:
        return sorted(self.scenario.event_phases, key=lambda p: p.start_minute)

    def current_phase(self) -> Optional[EventPhaseModel]:
        for phase in self._phases():
            if phase.start_minute <= self.t_min < phase.end_minute:
                return phase
        return None

    def phase_name(self) -> str:
        phase = self.current_phase()
        if phase:
            return phase.name.value
        if self.t_min >= max(p.end_minute for p in self._phases()):
            return "CLOSED"
        return "PRE_EVENT"

    @staticmethod
    def _spawn_mode(phase: EventPhaseModel) -> str:
        if phase.spawn:
            return phase.spawn
        if phase.name == EventPhaseName.EXIT_SURGE:
            return "EXIT_SURGE"
        return "ARRIVAL"

    # ------------------------------------------------------------------ #
    #  Distributions
    # ------------------------------------------------------------------ #
    @staticmethod
    def _default_distribution(node_ids: List[str], weights: Optional[Dict[str, float]]) -> Dict[str, float]:
        if not node_ids:
            return {}
        if weights:
            total = sum(weights.get(n, 1.0) for n in node_ids)
            return {n: weights.get(n, 1.0) / total for n in node_ids}
        return {n: 1.0 / len(node_ids) for n in node_ids}

    def _weighted_choice(self, dist: Dict[str, float]) -> str:
        if not dist:
            raise ValueError("cannot sample from empty distribution")
        r = self.rng.random()
        acc = 0.0
        for key, weight in dist.items():
            acc += weight
            if r <= acc:
                return key
        return list(dist.keys())[-1]

    def gate_distribution(self) -> Dict[str, float]:
        dist = self.scenario.gate_distribution or self._default_gate_distribution
        return {g: w for g, w in dist.items() if self.graph.node_type(g) == NodeType.ENTRY}

    def destination_distribution(self) -> Dict[str, float]:
        return self.scenario.destination_distribution or self._default_destination_distribution

    def exit_distribution(self) -> Dict[str, float]:
        return self.scenario.exit_distribution or self._default_exit_distribution

    # ------------------------------------------------------------------ #
    #  Spawning
    # ------------------------------------------------------------------ #
    def _spawn_arrivals(self, rate_per_min: float) -> None:
        if self.total_spawned >= self.scenario.crowd_size:
            return
        budget = self._spawn_budget + rate_per_min * TICK_DT_MIN / self.scale
        count = math.floor(budget)
        self._spawn_budget = budget - count
        for _ in range(count):
            if self.total_spawned + self.scale > self.scenario.crowd_size:
                break
            gate = self._weighted_choice(self.gate_distribution())
            destination = self._weighted_choice(self.destination_distribution())
            route = self.routing.find_path(gate, destination)
            if not route:
                continue
            self._add_agent(gate, destination, route)

    def _spawn_leavers(self, rate_per_min: float) -> None:
        if self.total_spawned >= self.scenario.crowd_size:
            return
        budget = self._spawn_budget + rate_per_min * TICK_DT_MIN / self.scale
        count = math.floor(budget)
        self._spawn_budget = budget - count
        for _ in range(count):
            if self.total_spawned + self.scale > self.scenario.crowd_size:
                break
            zone = self._weighted_choice(self.destination_distribution())
            exit_id = self._weighted_choice(self.exit_distribution())
            agent = self._add_agent(zone, exit_id, [zone])
            if agent is not None:
                self._reroute(agent, exit_id)

    def _add_agent(self, origin: str, destination: str, route: List[str]) -> Optional[Agent]:
        if len(self.agents) >= self.max_agents:
            return None
        agent = Agent(
            id=self._next_agent_id,
            origin=origin,
            destination=destination,
            route=route,
            speed_mps=self.rng.uniform(1.0, 1.4),
            scale_units=self.scale,
            spawned_at=self.t_min,
            on_node=route[0],
        )
        if self.graph.node_type(route[0]) in (
            NodeType.ZONE, NodeType.CONCESSION, NodeType.EXIT, NodeType.EMERGENCY_EXIT,
        ):
            agent.idle = True
        self._next_agent_id += 1
        self.agents.append(agent)
        self.total_spawned += self.scale
        self.nodes[route[0]].people += self.scale
        if self.graph.node_type(route[0]) == NodeType.ENTRY:
            self.external.record_arrival(route[0], self.scale)
        return agent

    # ------------------------------------------------------------------ #
    #  Movement
    # ------------------------------------------------------------------ #
    def _reroute(self, agent: Agent, destination: str) -> bool:
        """Re-route an agent, preserving any walkway it is currently on.

        If the requested destination is unreachable (e.g. an incident has cut
        off an exit), the agent falls back to the nearest reachable exit rather
        than standing still - real crowds head for any available way out.
        """
        if agent.is_emergency and not self.emergency_active:
            return False
        if agent.on_edge is not None:
            u, v = agent.on_edge
            path = self.routing.find_path(v, destination)
            if not path:
                path = self._reachable_exit_path(v)
            if not path:
                return False
            agent.route = [u, v] + path[1:]
            if path[-1] != destination:
                destination = path[-1]
        else:
            current = agent.on_node or agent.route[0]
            path = self.routing.find_path(current, destination)
            if not path:
                path = self._reachable_exit_path(current)
            if not path:
                return False
            agent.route = path
            if path and path[-1] != destination:
                destination = path[-1]
        agent.destination = destination
        agent.idle = False
        agent.waiting_since = None
        agent.is_rerouted = True
        return True

    def _reachable_exit_path(self, current: str) -> List[str]:
        """Cheapest reachable route to any exit, sorted by straight-line distance."""
        candidates = []
        for exit_id in self.graph.exits + self.graph.emergency_exits:
            path = self.routing.find_path(current, exit_id)
            if path:
                candidates.append((len(path), exit_id, path))
        if not candidates:
            return []
        candidates.sort(key=lambda c: (c[0], c[1]))
        return candidates[0][2]

    def _step_agent(self, agent: Agent) -> None:
        if agent.completed_at is not None or agent.idle:
            return
        if agent.on_edge is not None:
            u, v = agent.on_edge
            edge_state = self.edges[(u, v)]
            util = edge_state.utilisation
            # crowds keep free-flow pace up to capacity; only overloaded
            # walkways (utilisation > 1.0) slow movement down; weather/incident
            # multipliers also slow outdoor routes
            speed_factor = 1.0 if util <= 1.0 else max(0.25, 1.0 - 0.3 * (util - 1.0))
            speed_factor *= self._edge_speed_factor(u, v)
            length = self.graph.edge_length(u, v)
            step = agent.speed_mps * speed_factor * (TICK_DT_MIN * 60.0) / length
            agent.progress += step
            if agent.progress >= 1.0:
                agent.on_edge = None
                agent.on_node = v
                agent.progress = 0.0
                agent.route.pop(0)
                self.nodes[v].people += agent.scale_units
                self.edges[(u, v)].people -= agent.scale_units
                self.edges[(u, v)].completions += agent.scale_units
                self._arrive(agent)
        if agent.completed_at is not None or agent.idle:
            return
        if agent.on_node is not None and len(agent.route) >= 2:
            u, v = agent.route[0], agent.route[1]
            edge_state = self.edges[(u, v)]
            if not self.graph.is_open(u, v):
                return
            pipe = self._pipe_capacity(u, v)
            if pipe <= 0:
                if agent.waiting_since is None:
                    agent.waiting_since = self.t_min
                return
            rate_room = edge_state.entries + agent.scale_units <= self._entry_rate_capacity(u, v, TICK_DT_MIN)
            if edge_state.people + agent.scale_units <= pipe and rate_room:
                agent.on_node = None
                agent.on_edge = (u, v)
                agent.progress = 0.0
                self.nodes[u].people -= agent.scale_units
                self.edges[(u, v)].people += agent.scale_units
                self.edges[(u, v)].entries += agent.scale_units
                agent.waiting_since = None
                agent.is_rerouted = False
            elif agent.waiting_since is None:
                agent.waiting_since = self.t_min

    def _pipe_capacity(self, u: str, v: str) -> float:
        length = self.graph.edge_length(u, v)
        cap = self.edge_capacity_effective(u, v)
        if cap <= 0:
            return 0.0
        transit_min = length / (WALKING_SPEED * 60.0)
        return max(float(self.scale), cap * transit_min)

    def _entry_rate_capacity(self, u: str, v: str, dt_min: float) -> float:
        """Throughput gate: an edge admits at most `cap` people per minute."""
        cap = self.edge_capacity_effective(u, v)
        if cap <= 0:
            return 0.0
        return max(float(self.scale), cap * dt_min)

    def _arrive(self, agent: Agent) -> None:
        node = agent.on_node
        if self.graph.node_type(node) in (NodeType.EXIT, NodeType.EMERGENCY_EXIT):
            self._complete(agent)
            return
        at_destination = (
            node == agent.destination
            and self.graph.node_type(node) in (NodeType.ZONE, NodeType.CONCESSION)
        )
        phase = self.current_phase()
        if at_destination and phase is not None and self._spawn_mode(phase) == "EXIT_SURGE":
            self._reroute(agent, self._weighted_choice(self.exit_distribution()))
        elif at_destination:
            agent.idle = True
            agent.waiting_since = None
        # otherwise the agent keeps walking along its route

    def _complete(self, agent: Agent) -> None:
        exit_node = agent.on_node or ""
        agent.completed_at = self.t_min
        agent.idle = False
        agent.on_node = None
        self.total_completed += agent.scale_units
        self._completion_window.append(agent.scale_units)
        self._completed_travel_times.append(agent.completed_at - agent.spawned_at)
        # people who cleared an exit flow onto the surrounding road network
        self.external.record_exit(exit_node, agent.scale_units)

    # ------------------------------------------------------------------ #
    #  Controlled rerouting (brief section 15: never reroute everyone)
    # ------------------------------------------------------------------ #
    def _controlled_reroute(self) -> None:
        for agent in self.agents:
            if agent.completed_at is not None or agent.idle or agent.is_emergency:
                continue
            if agent.waiting_since is None or agent.is_rerouted:
                continue
            waited = self.t_min - agent.waiting_since
            if waited >= 1.0 and self.rng.random() < 0.05:
                self._reroute(agent, agent.destination)
                agent.is_rerouted = True

    # ------------------------------------------------------------------ #
    #  Main tick
    # ------------------------------------------------------------------ #
    def tick(self) -> None:
        if self.status == SimulationStatus.COMPLETED:
            return
        self.tick_count += 1
        self.t_min += TICK_DT_MIN
        self._update_incident()

        phase = self.current_phase()
        phase_name = self.phase_name()

        if phase is not None and not self.emergency_active:
            if self._spawn_mode(phase) == "EXIT_SURGE":
                self._spawn_leavers(self.scenario.exit_rate_per_minute * phase.arrival_rate_multiplier)
            else:
                self._spawn_arrivals(self.scenario.arrival_rate_per_minute * phase.arrival_rate_multiplier)

        # exit surge: seated agents leave their zones in a staggered wave
        # (brief section 12: real crowds depart gradually; emergencies reroute
        # everyone immediately via set_emergency instead). The wave is bounded
        # so stragglers are guaranteed to depart as the surge matures.
        if phase_name == "EXIT_SURGE":
            if self._surge_started_at is None:
                self._surge_started_at = self.t_min
                self._egress_started_at = self.t_min
            elapsed = self.t_min - self._surge_started_at
            remaining_span = max(0.5, self._surge_spread_min - elapsed)
            departure_prob = min(1.0, TICK_DT_MIN / remaining_span)
            for agent in self.agents:
                if agent.completed_at is None and agent.idle and self.rng.random() < departure_prob:
                    self._reroute(agent, self._weighted_choice(self.exit_distribution()))
        self._prev_phase = phase_name

        # per-tick edge accounting: carry over true occupancy, reset completions
        for key in self.edges:
            self.edges[key].people = 0
            self.edges[key].completions = 0.0
            self.edges[key].entries = 0.0
        for agent in self.agents:
            if agent.on_edge is not None:
                u, v = agent.on_edge
                self.edges[(u, v)].people += agent.scale_units

        # movement
        for agent in self.agents:
            self._step_agent(agent)

        self._controlled_reroute()
        self._prune_completed()
        self._update_stats(TICK_DT_MIN)
        self.external.step(TICK_DT_MIN)

    def _prune_completed(self) -> None:
        if any(a.completed_at is not None for a in self.agents):
            self.agents = [a for a in self.agents if a.completed_at is None]

    # ------------------------------------------------------------------ #
    #  Statistics
    # ------------------------------------------------------------------ #
    def _update_stats(self, dt_min: float) -> None:
        max_util = 0.0
        util_sum = 0.0
        for (u, v), state in self.edges.items():
            edge = self.graph.edge(u, v)
            length = self.graph.edge_length(u, v)
            width = edge.width_m if edge else 1.0
            cap = self.edge_capacity_effective(u, v)
            transit_min = length / (WALKING_SPEED * 60.0)
            pipe = max(float(self.scale), cap * transit_min)      # people that fit in transit
            state.people = max(0, state.people)
            state.utilisation = state.people / pipe if self.graph.is_open(u, v) else 0.0
            state.density = state.people / max(1.0, length * width)
            state.flow_per_min = state.completions / dt_min
            state.usage_history.append(state.utilisation)
            state.usage_history = state.usage_history[-60:]
            state.trend = classify_trend(state.usage_history)
            state.time_to_critical = predict_time_to_critical(
                state.usage_history, CRITICAL_UTIL, SAMPLES_PER_MIN
            )
            if not self.graph.is_open(u, v):
                state.risk_score = 0.0
                state.risk_level = RiskLevel.NORMAL
                continue
            state.risk_score = self._risk_score(
                utilisation=state.utilisation,
                density=state.utilisation * COMFORT_DENSITY,
                queue=0.0, trend=state.trend
            )
            if (u, v) in self._hazard_edges:
                if self.incident and self.incident.type in ("FIRE", "STRUCTURAL"):
                    state.risk_score = 1.0
                else:
                    state.risk_score = max(state.risk_score, 0.8)
            state.risk_level = RiskLevel(risk_level_from_score(state.risk_score))
            max_util = max(max_util, state.utilisation)
            util_sum += state.utilisation

        queue_total = 0
        max_risk = 0.0
        for node_id, state in self.nodes.items():
            node = self.graph.node(node_id)
            area = self.graph.node_area(node_id)
            if node.type in (NodeType.EXIT, NodeType.EMERGENCY_EXIT):
                state.people = 0
                state.density = 0.0
                state.utilisation = 0.0
                state.queue = 0
                state.risk_score = 0.0
                state.risk_level = RiskLevel.NORMAL
                continue
            state.people = max(0, state.people)
            state.density = state.people / area
            state.utilisation = min(1.5, state.people / max(1.0, area * COMFORT_DENSITY))
            state.queue = max(0, state.people - int(area * COMFORT_DENSITY * 0.5))
            queue_total += state.queue
            state.usage_history.append(state.utilisation)
            state.usage_history = state.usage_history[-60:]
            state.trend = classify_trend(state.usage_history)
            state.time_to_critical = predict_time_to_critical(
                state.usage_history, 0.9, SAMPLES_PER_MIN
            )
            state.risk_score = self._risk_score(
                utilisation=state.utilisation,
                density=state.density,
                queue=state.queue / max(1.0, node.capacity or area),
                trend=state.trend,
            )
            if node_id in self._hazard_nodes:
                if self.incident and self.incident.type in ("FIRE", "STRUCTURAL"):
                    state.risk_score = 1.0
                else:
                    state.risk_score = max(state.risk_score, 0.85)
            state.risk_level = RiskLevel(risk_level_from_score(state.risk_score))
            max_risk = max(max_risk, state.risk_score)

        in_venue = self.total_spawned - self.total_completed
        total_area = sum(self.graph.node_area(n) for n in self.nodes) + sum(
            self.graph.edge_area(u, v) for (u, v) in self.edges
        )
        global_density = in_venue / max(1.0, total_area)
        completion_rate = sum(self._completion_window) / 1.0
        if in_venue > 0 and completion_rate > 0:
            clearance = in_venue / completion_rate
        elif self._egress_started_at is not None:
            clearance = self.t_min - self._egress_started_at
        else:
            clearance = None

        avg_travel = (
            sum(self._completed_travel_times) / len(self._completed_travel_times)
            if self._completed_travel_times else 0.0
        )
        max_travel = max(self._completed_travel_times) if self._completed_travel_times else 0.0

        n_elements = max(1, len(self.edges) + len(self.nodes))
        avg_util = util_sum / n_elements
        queue_growth = (queue_total - self._queue_prev) / dt_min
        self._queue_prev = queue_total

        risk_level = RiskLevel(risk_level_from_score(max_risk))
        bottleneck_count = sum(
            1 for s in self.edges.values() if s.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        ) + sum(
            1 for s in self.nodes.values() if s.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        )

        self.metrics = SimulationMetrics(
            t_min=round(self.t_min, 2),
            in_venue=in_venue,
            total_spawned=self.total_spawned,
            total_completed=self.total_completed,
            global_density=round(global_density, 3),
            flow_per_min=round(
                self.scenario.exit_rate_per_minute if self.phase_name() == "EXIT_SURGE"
                else self.scenario.arrival_rate_per_minute, 2),
            max_utilisation=round(max_util, 3),
            avg_utilisation=round(avg_util, 3),
            queue_total=queue_total,
            queue_growth=round(queue_growth, 2),
            avg_travel_time_min=round(avg_travel, 2),
            max_travel_time_min=round(max_travel, 2),
            bottleneck_count=bottleneck_count,
            risk_level=risk_level,
            risk_score=round(max_risk, 3),
            clearance_time_min=round(clearance, 1) if clearance is not None else None,
        )

        self._update_history()
        self._wire_routing()

    @staticmethod
    def _risk_score(utilisation: float, density: float, queue: float, trend: str) -> float:
        """Simulation risk thresholds (brief section 13) - configurable here."""
        util_term = 0.45 * min(1.5, max(0.0, utilisation))
        density_term = 0.30 * min(1.5, density / COMFORT_DENSITY)
        queue_term = 0.15 * min(1.0, queue)
        trend_term = 0.10 * (0.9 if trend == "Increasing" else -0.1 if trend == "Decreasing" else 0.0)
        return round(max(0.0, min(1.0, util_term + density_term + queue_term + trend_term)), 3)

    def _wire_routing(self) -> None:
        """Feed live utilisation back into the congestion-aware router."""
        usage = {
            key: EdgeUsage(
                people=state.people,
                flow_per_min=state.flow_per_min,
                utilisation=state.utilisation,
                risk_score=state.risk_score,
            )
            for key, state in self.edges.items()
        }
        self.routing.set_edge_usage(usage)
        self.routing.set_node_risk({nid: ns.risk_level for nid, ns in self.nodes.items()})

    def _update_history(self) -> None:
        self.history.append({
            "t": round(self.t_min, 2),
            "phase": self.phase_name(),
            "in_venue": self.metrics.in_venue,
            "max_util": self.metrics.max_utilisation,
            "avg_util": self.metrics.avg_utilisation,
            "queue_total": self.metrics.queue_total,
            "avg_travel_time": self.metrics.avg_travel_time_min,
            "risk_score": self.metrics.risk_score,
            "bottleneck_count": self.metrics.bottleneck_count,
            "total_completed": self.metrics.total_completed,
            "total_spawned": self.metrics.total_spawned,
        })
        if len(self.history) > 720:
            self.history = self.history[-720:]

    # ------------------------------------------------------------------ #
    #  Bottleneck detection & recommendations
    # ------------------------------------------------------------------ #
    def bottlenecks(self) -> List[Bottleneck]:
        result: List[Bottleneck] = []
        for (u, v), state in self.edges.items():
            if state.risk_level not in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                continue
            edge = self.graph.edge(u, v)
            result.append(Bottleneck(
                id=f"edge_{u}_{v}",
                kind="edge",
                location=f"{u} → {v}",
                current_risk=state.risk_level,
                current_density=round(state.density, 2),
                capacity_utilisation=round(min(1.5, state.utilisation), 3),
                queue=state.people,
                trend=state.trend,
                estimated_time_to_critical_min=state.time_to_critical,
                explanation=self._explain_edge(u, v, state, edge),
            ))
        for node_id, state in self.nodes.items():
            if state.risk_level not in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                continue
            result.append(Bottleneck(
                id=f"node_{node_id}",
                kind="node",
                location=node_id,
                current_risk=state.risk_level,
                current_density=round(state.density, 2),
                capacity_utilisation=round(min(1.5, state.utilisation), 3),
                queue=state.queue,
                trend=state.trend,
                estimated_time_to_critical_min=state.time_to_critical,
                explanation=self._explain_node(node_id, state),
            ))
        result.sort(key=lambda b: (-b.capacity_utilisation, b.id))
        return result[:12]

    def _explain_edge(self, u: str, v: str, state: EdgeState, edge: EdgeModel) -> str:
        parts = [
            f"Walkway {u} → {v} at {state.utilisation*100:.0f}% of its {edge.capacity:.0f} "
            f"people/min capacity",
            f"flow {state.flow_per_min:.0f}/min",
            f"{state.people} people transiting",
        ]
        if (u, v) in self._hazard_edges:
            if self.incident:
                parts.append(f"{self.incident.type.lower()} incident zone (avoid)")
            else:
                parts.append("inside incident hazard zone (avoid)")
        if state.time_to_critical is not None:
            parts.append(f"simulation projection: critical in ~{state.time_to_critical:.1f} min")
        parts.append(f"trend {state.trend}")
        return ". ".join(parts) + "."

    def _explain_node(self, node_id: str, state: NodeState) -> str:
        parts = [
            f"{node_id} at {state.density:.1f} people/m²",
            f"{state.people} people present",
            f"{state.queue} waiting to proceed",
        ]
        if node_id in self._hazard_nodes:
            parts.append("inside incident hazard zone (avoid)")
        if state.time_to_critical is not None:
            parts.append(f"simulation projection: critical in ~{state.time_to_critical:.1f} min")
        parts.append(f"trend {state.trend}")
        return ". ".join(parts) + "."

    # ------------------------------------------------------------------ #
    #  Recommended action (feeds dashboard + optimisation)
    # ------------------------------------------------------------------ #
    def feeding_gates(self, edge_key: Tuple[str, str]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for agent in self.agents:
            if agent.on_edge == edge_key:
                counts[agent.origin] = counts.get(agent.origin, 0) + 1
        return counts

    def least_loaded_entry(self, exclude: Optional[str] = None) -> str:
        entries = [e for e in self.graph.entries if e != exclude]
        if not entries:
            return exclude
        return min(entries, key=lambda e: (self.nodes[e].people, e))

    def least_loaded_exit(self, exclude: Optional[str] = None) -> str:
        exits = [e for e in self.graph.exits if e != exclude]
        if not exits:
            return exclude
        counts = {e: sum(s.people for (u, v), s in self.edges.items() if v == e) for e in exits}
        return min(exits, key=lambda e: (counts[e], e))

    def recommended_action(self) -> Optional[str]:
        bns = self.bottlenecks()
        if not bns:
            return None
        top = bns[0]
        if self.phase_name() == "EXIT_SURGE" and top.kind == "edge":
            dest = top.location.split("→")[-1].strip()
            if dest in self.graph.exits:
                alt = self.least_loaded_exit(dest)
                if alt and alt != dest:
                    return (
                        f"Shift 30% of leavers from {dest} to {alt}: bottleneck at "
                        f"{top.location} is at {top.capacity_utilisation*100:.0f}% capacity."
                    )
        if top.kind == "edge":
            u = top.location.split("→")[0].strip()
            v = top.location.split("→")[1].strip()
            gates = self.feeding_gates((u, v))
            if gates:
                gate = max(gates, key=gates.get)
                alt = self.least_loaded_entry(gate)
                if alt and alt != gate:
                    return (
                        f"Redirect 25% of arrivals at {gate} to {alt}: bottleneck at "
                        f"{top.location} is at {top.capacity_utilisation*100:.0f}% capacity."
                    )
        return f"Bottleneck at {top.location}: {top.explanation}"

    # ------------------------------------------------------------------ #
    #  Interventions
    # ------------------------------------------------------------------ #
    def apply_intervention(self, intervention: Intervention) -> None:
        p = intervention.parameters
        kind = intervention.type
        if kind in (InterventionType.REDIRECT, InterventionType.CHANGE_GATE):
            self._apply_redirect(p.get("from"), p.get("to"), p.get("percent", 100))
        elif kind == InterventionType.OPEN_CORRIDOR:
            self._set_edge_open(p.get("edge_id"), True)
        elif kind == InterventionType.CLOSE_CORRIDOR:
            self._set_edge_open(p.get("edge_id"), False)
        elif kind == InterventionType.USE_ALTERNATE_EXIT:
            self._apply_exit_shift(p.get("from"), p.get("to"), p.get("percent", 30))
        elif kind == InterventionType.ADJUST_ROUTING:
            self.routing.options.congestion_penalty_weight = float(p.get("congestion_penalty_weight", 6.0))
        elif kind == InterventionType.EMERGENCY_RESPONSE:
            self.set_emergency(True)
        elif kind == InterventionType.INCREASE_CAPACITY:
            self._increase_edge_capacity(p.get("edge_id"), float(p.get("multiplier", 1.5)))
        elif kind == InterventionType.ADD_INCIDENT:
            self.set_incident(IncidentSpec.model_validate(p.get("incident") or {}))
        elif kind == InterventionType.SET_WEATHER:
            self.set_weather(WeatherSpec.model_validate(p.get("weather") or {}))
        self.interventions.append(intervention)

    def _increase_edge_capacity(self, edge_id: Optional[str], multiplier: float) -> None:
        edge = next((e for e in self.venue.edges if e.id == edge_id), None)
        if edge is None:
            return
        edge.capacity = edge.capacity * multiplier

    def _apply_redirect(self, from_gate: str, to_gate: str, percent: float) -> None:
        dist = dict(self.gate_distribution())
        share = dist.get(from_gate, 0.0)
        amount = share * percent / 100.0
        dist[from_gate] = max(0.0, share - amount)
        dist[to_gate] = dist.get(to_gate, 0.0) + amount
        self.scenario.gate_distribution = dist
        for agent in self.agents:
            if (agent.completed_at is None and not agent.idle and not agent.is_emergency
                    and agent.origin == from_gate and agent.on_node == from_gate
                    and self.rng.random() < percent / 100.0):
                self._reroute(agent, agent.destination)

    def _apply_exit_shift(self, from_exit: str, to_exit: str, percent: float) -> None:
        dist = dict(self.exit_distribution())
        share = dist.get(from_exit, 0.0)
        amount = share * percent / 100.0
        dist[from_exit] = max(0.0, share - amount)
        dist[to_exit] = dist.get(to_exit, 0.0) + amount
        self.scenario.exit_distribution = dist
        for agent in self.agents:
            if (agent.completed_at is None and not agent.idle and not agent.is_emergency
                    and agent.destination == from_exit and self.rng.random() < percent / 100.0):
                self._reroute(agent, to_exit)

    def _set_edge_open(self, edge_id: Optional[str], open_: bool) -> None:
        edge = next((e for e in self.venue.edges if e.id == edge_id), None)
        if edge is None:
            return
        edge.is_open = open_
        self._recompute_multipliers()
        if open_:
            return
        affected = []
        blocked = {(edge.source, edge.destination), (edge.destination, edge.source)}
        for agent in self.agents:
            if agent.completed_at is not None or agent.is_emergency:
                continue
            if agent.on_edge is not None and agent.on_edge in blocked:
                affected.append(agent)
            elif (agent.on_node is not None and len(agent.route) >= 2
                    and (agent.route[0], agent.route[1]) in blocked):
                affected.append(agent)
        for agent in affected:
            self._reroute(agent, agent.destination)

    # ------------------------------------------------------------------ #
    #  Emergency mode
    # ------------------------------------------------------------------ #
    def set_emergency(self, active: bool) -> None:
        self.emergency_active = active
        self.routing.set_emergency(active)
        self.graph.set_emergency(active)
        if not active:
            return
        if self._egress_started_at is None:
            self._egress_started_at = self.t_min
        for agent in self.agents:
            if agent.completed_at is not None:
                continue
            if agent.on_edge is not None:
                exit_id = self.routing.nearest_emergency_exit(agent.on_edge[1])
                path = self.routing.find_path(agent.on_edge[1], exit_id) if exit_id else []
            else:
                current = agent.on_node or agent.route[0]
                exit_id = self.routing.nearest_emergency_exit(current)
                path = self.routing.find_path(current, exit_id) if exit_id else []
            if not path:
                continue
            if agent.on_edge is not None:
                u, v = agent.on_edge
                agent.route = [u, v] + path[1:]
            else:
                agent.route = path
            agent.destination = path[-1]
            agent.idle = False
            agent.waiting_since = None
            agent.is_emergency = True

    # ------------------------------------------------------------------ #
    #  State serialisation
    # ------------------------------------------------------------------ #
    def _element_state(self, node_id: str, ns: NodeState) -> ElementState:
        node = self.graph.node(node_id)
        return ElementState(
            id=node_id,
            type="node",
            people=ns.people,
            flow_per_min=round(ns.flow_per_min, 1),
            capacity=round(self.graph.node_area(node_id) * COMFORT_DENSITY),
            utilisation=round(ns.utilisation, 3),
            density=round(ns.density, 2),
            risk=ns.risk_level,
            risk_score=ns.risk_score,
            queue=ns.queue,
            trend=ns.trend,
            time_to_critical_min=ns.time_to_critical,
            hazard=node_id in self._hazard_nodes,
        )

    def _edge_element_state(self, key: Tuple[str, str], es: EdgeState) -> ElementState:
        edge = self.graph.edge(*key)
        return ElementState(
            id=edge.id if edge else f"{key[0]}_{key[1]}",
            type="edge",
            people=es.people,
            flow_per_min=round(es.flow_per_min, 1),
            capacity=round(self.edge_capacity_effective(*key), 1),
            utilisation=round(es.utilisation, 3),
            density=round(es.density, 2),
            risk=es.risk_level,
            risk_score=es.risk_score,
            queue=es.people if es.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL) else 0,
            trend=es.trend,
            time_to_critical_min=es.time_to_critical,
            hazard=(key in self._hazard_edges),
        )

    def _agent_position(self, agent: Agent) -> Position:
        if agent.on_edge is not None:
            u, v = agent.on_edge
            pu, pv = self.graph.position(u), self.graph.position(v)
            t = min(0.999, max(0.0, agent.progress))
            return Position(
                x=round(pu.x + (pv.x - pu.x) * t, 1),
                y=round(pu.y + (pv.y - pu.y) * t, 1),
            )
        node = agent.on_node or (agent.route[0] if agent.route else None)
        if node and self.graph.node(node):
            p = self.graph.position(node)
            return Position(
                x=round(p.x + self.rng.uniform(-4, 4), 1),
                y=round(p.y + self.rng.uniform(-4, 4), 1),
            )
        return Position(x=0, y=0)

    def state(self, include_agents: bool = True) -> SimulationState:
        bottlenecks = self.bottlenecks()
        agent_models: List[AgentModel] = []
        if include_agents:
            agents = self.agents
            if len(agents) > 900:
                step = len(agents) / 900.0
                agents = [agents[int(i * step)] for i in range(900)]
            agent_models = [a.to_model(self._agent_position(a)) for a in agents]
        return SimulationState(
            sim_id=self.sim_id,
            scenario_id=self.scenario.id,
            venue_id=self.venue.id,
            status=self.status,
            t_min=round(self.t_min, 2),
            tick=self.tick_count,
            phase=self.phase_name(),
            speed=self.speed,
            emergency_active=self.emergency_active,
            interventions_applied=list(self.interventions),
            metrics=self.metrics,
            history=self.history,
            nodes={nid: self._element_state(nid, ns) for nid, ns in self.nodes.items()},
            edges={"|".join(k): self._edge_element_state(k, es) for k, es in self.edges.items()},
            bottlenecks=bottlenecks,
            agents=agent_models,
            recommended_action=self.recommended_action(),
            simulation_scale=self.scale,
            node_positions={nid: self.graph.position(nid) for nid in self.graph.graph.nodes},
            incident=self.incident.model_dump() if self.incident else None,
            weather=self.weather.model_dump() if self.weather else None,
            external=self.external.state(),
            hazard_zones=[
                {
                    "location": self.incident.location if self.incident else None,
                    "radius_m": round(self._hazard_radius_m, 1),
                    "nodes": sorted(self._hazard_nodes),
                    "edges": sorted(["|".join(k) for k in self._hazard_edges]),
                }
            ] if (self.incident and (self._hazard_nodes or self._hazard_edges)) else [],
        )

    # ------------------------------------------------------------------ #
    #  Counterfactual optimisation (brief sections 17-18, 24)
    # ------------------------------------------------------------------ #
    def clone(self, fast: bool = False) -> "SimulationEngine":
        """Cheap clone with an isolated venue model (counterfactuals can mutate edges)."""
        from .routing import RouteOptions

        clone_graph = VenueGraph(copy.deepcopy(self.graph.venue))
        clone_graph.emergency_active = self.emergency_active
        clone_routing = RoutingEngine(clone_graph)
        clone_routing.options = RouteOptions(
            congestion_penalty_weight=self.routing.options.congestion_penalty_weight,
            emergency_discount=self.routing.options.emergency_discount,
        )
        clone_routing.emergency_active = self.emergency_active

        clone = SimulationEngine(
            f"{self.sim_id}_clone",
            self.scenario,
            clone_graph,
            clone_routing,
            seed=self.rng.randint(0, 2**31),
            max_agents=600 if fast else self.max_agents,
        )
        clone.t_min = self.t_min
        clone.tick_count = self.tick_count
        clone.scale = self.scale if not fast else max(1, math.ceil(self.scenario.crowd_size / 600))
        clone.status = SimulationStatus.RUNNING
        clone.speed = self.speed
        clone.emergency_active = self.emergency_active
        clone.interventions = list(self.interventions)
        clone.total_spawned = self.total_spawned
        clone.total_completed = self.total_completed
        clone._surge_started_at = self._surge_started_at
        clone._egress_started_at = self._egress_started_at
        clone.agents = [
            Agent(
                id=a.id,
                origin=a.origin,
                destination=a.destination,
                route=list(a.route),
                speed_mps=a.speed_mps,
                scale_units=clone.scale,
                spawned_at=a.spawned_at,
                completed_at=a.completed_at,
                on_node=a.on_node,
                on_edge=a.on_edge,
                progress=a.progress,
                idle=a.idle,
                waiting_since=a.waiting_since,
                is_rerouted=a.is_rerouted,
                is_emergency=a.is_emergency,
            )
            for a in self.agents
        ]
        clone._next_agent_id = self._next_agent_id
        clone._queue_prev = self._queue_prev
        clone.external = self.external.copy()
        return clone

    def run_horizon(self, horizon_min: float = 8.0, dt_min: float = 0.125) -> None:
        """Run the simulation forward (used to rank optimisation candidates)."""
        steps = max(8, int(horizon_min / dt_min))
        for _ in range(steps):
            if self.phase_name() == "CLOSED" and not self.agents:
                break
            self.tick_with_dt(dt_min)

    def tick_with_dt(self, dt_min: float) -> None:
        """Coarse tick used by optimisation clones (larger dt)."""
        if self.status == SimulationStatus.COMPLETED:
            return
        self.tick_count += 1
        self.t_min += dt_min
        phase = self.current_phase()
        phase_name = self.phase_name()

        if phase is not None and not self.emergency_active:
            if self._spawn_mode(phase) == "EXIT_SURGE":
                budget = self._spawn_budget + (
                    self.scenario.exit_rate_per_minute * phase.arrival_rate_multiplier * dt_min / self.scale
                )
                count = math.floor(budget)
                self._spawn_budget = budget - count
                for _ in range(count):
                    if self.total_spawned + self.scale > self.scenario.crowd_size:
                        break
                    zone = self._weighted_choice(self.destination_distribution())
                    exit_id = self._weighted_choice(self.exit_distribution())
                    agent = self._add_agent(zone, exit_id, [zone])
                    if agent is not None:
                        self._reroute(agent, exit_id)
            else:
                budget = self._spawn_budget + (
                    self.scenario.arrival_rate_per_minute * phase.arrival_rate_multiplier * dt_min / self.scale
                )
                count = math.floor(budget)
                self._spawn_budget = budget - count
                for _ in range(count):
                    if self.total_spawned + self.scale > self.scenario.crowd_size:
                        break
                    gate = self._weighted_choice(self.gate_distribution())
                    destination = self._weighted_choice(self.destination_distribution())
                    route = self.routing.find_path(gate, destination)
                    if route:
                        self._add_agent(gate, destination, route)

        if phase_name == "EXIT_SURGE":
            if self._surge_started_at is None:
                self._surge_started_at = self.t_min
                self._egress_started_at = self.t_min
            elapsed = self.t_min - self._surge_started_at
            remaining_span = max(0.5, self._surge_spread_min - elapsed)
            departure_prob = min(1.0, dt_min / remaining_span)
            for agent in self.agents:
                if agent.completed_at is None and agent.idle and self.rng.random() < departure_prob:
                    self._reroute(agent, self._weighted_choice(self.exit_distribution()))
        self._prev_phase = phase_name

        for key in self.edges:
            self.edges[key].people = 0
            self.edges[key].completions = 0.0
            self.edges[key].entries = 0.0
        for agent in self.agents:
            if agent.on_edge is not None:
                u, v = agent.on_edge
                self.edges[(u, v)].people += agent.scale_units
        for agent in self.agents:
            self._move_agent_coarse(agent, dt_min)
        self._prune_completed()
        self._update_stats(dt_min)
        self.external.step(dt_min)

    def _move_agent_coarse(self, agent: Agent, dt_min: float) -> None:
        if agent.completed_at is not None or agent.idle:
            return
        if agent.on_edge is not None:
            u, v = agent.on_edge
            edge_state = self.edges[(u, v)]
            util = edge_state.utilisation
            speed_factor = 1.0 if util <= 1.0 else max(0.25, 1.0 - 0.3 * (util - 1.0))
            length = self.graph.edge_length(u, v)
            step = agent.speed_mps * speed_factor * (dt_min * 60.0) / length
            agent.progress += step
            if agent.progress >= 1.0:
                agent.on_edge = None
                agent.on_node = v
                agent.progress = 0.0
                agent.route.pop(0)
                self.nodes[v].people += agent.scale_units
                self.edges[(u, v)].people -= agent.scale_units
                self.edges[(u, v)].completions += agent.scale_units
                if self.graph.node_type(v) in (NodeType.EXIT, NodeType.EMERGENCY_EXIT):
                    self._complete(agent)
                elif (v == agent.destination
                        and self.graph.node_type(v) in (NodeType.ZONE, NodeType.CONCESSION)
                        and self.current_phase()
                        and self._spawn_mode(self.current_phase()) == "EXIT_SURGE"):
                    self._reroute(agent, self._weighted_choice(self.exit_distribution()))
                elif v == agent.destination:
                    agent.idle = True
                # otherwise keep walking
        if agent.completed_at is not None or agent.idle:
            return
        if agent.on_node is not None and len(agent.route) >= 2:
            u, v = agent.route[0], agent.route[1]
            edge_state = self.edges[(u, v)]
            if not self.graph.is_open(u, v):
                return
            pipe = self._pipe_capacity(u, v)
            rate_room = edge_state.entries + agent.scale_units <= self._entry_rate_capacity(u, v, dt_min)
            if edge_state.people + agent.scale_units <= pipe and rate_room:
                agent.on_node = None
                agent.on_edge = (u, v)
                agent.progress = 0.0
                self.nodes[u].people -= agent.scale_units
                self.edges[(u, v)].people += agent.scale_units
                self.edges[(u, v)].entries += agent.scale_units
                agent.is_rerouted = False

    # ------------------------------------------------------------------ #
    #  Candidate generation & optimisation scoring
    # ------------------------------------------------------------------ #
    def generate_candidates(self) -> List[Intervention]:
        candidates: List[Intervention] = []
        bns = self.bottlenecks()
        phase = self.phase_name()

        edge_bns = [b for b in bns if b.kind == "edge"]
        for bn in edge_bns[:2]:
            u, v = bn.location.split("→")
            u, v = u.strip(), v.strip()
            gates = self.feeding_gates((u, v))
            if gates and phase != "EXIT_SURGE":
                gate = max(gates, key=gates.get)
                alt = self.least_loaded_entry(gate)
                if alt and alt != gate:
                    for pct in (15, 30, 50):
                        candidates.append(Intervention(
                            id=f"redirect_{pct}_{gate}_{alt}",
                            type=InterventionType.REDIRECT,
                            description=f"Redirect {pct}% of arrivals at {gate} to {alt}",
                            parameters={"percent": pct, "from": gate, "to": alt},
                        ))

        if phase == "EXIT_SURGE":
            loaded_exit = max(
                self.graph.exits,
                key=lambda e: sum(s.people for (u, v), s in self.edges.items() if v == e),
                default=None,
            )
            if loaded_exit:
                alt = self.least_loaded_exit(loaded_exit)
                if alt and alt != loaded_exit:
                    candidates.append(Intervention(
                        id=f"exit_shift_{loaded_exit}_{alt}",
                        type=InterventionType.USE_ALTERNATE_EXIT,
                        description=f"Shift 30% of leavers from {loaded_exit} to {alt}",
                        parameters={"percent": 30, "from": loaded_exit, "to": alt},
                    ))
                for exit_node in {loaded_exit, alt} - {None}:
                    hot_in = max(
                        ((u, v) for (u, v) in self.edges.keys()
                         if v == exit_node and self.graph.is_open(u, v)),
                        key=lambda kv: self.edges[kv].utilisation,
                        default=None,
                    )
                    if hot_in:
                        edge = self.graph.edge(*hot_in)
                        candidates.append(Intervention(
                            id=f"boost_exit_{edge.id}",
                            type=InterventionType.INCREASE_CAPACITY,
                            description=f"Deploy extra staff at exit corridor {edge.source} → {edge.destination} (+50% capacity)",
                            parameters={"edge_id": edge.id, "multiplier": 1.5},
                        ))

        for bn in edge_bns[:2]:
            u, v = bn.location.split("→")
            u, v = u.strip(), v.strip()
            edge = self.graph.edge(u, v)
            if edge is None or not edge.is_open:
                continue
            if bn.capacity_utilisation >= 0.9 and self._has_alternate(u, v):
                candidates.append(Intervention(
                    id=f"close_{edge.id}",
                    type=InterventionType.CLOSE_CORRIDOR,
                    description=f"Close corridor {u} → {v} and reroute around it",
                    parameters={"edge_id": edge.id},
                ))
            candidates.append(Intervention(
                id=f"boost_{edge.id}",
                type=InterventionType.INCREASE_CAPACITY,
                description=f"Deploy extra staff at corridor {u} → {v} (+50% capacity)",
                parameters={"edge_id": edge.id, "multiplier": 1.5},
            ))

        node_bns = [b for b in bns if b.kind == "node"]
        for bn in node_bns[:2]:
            node_id = bn.location.strip()
            edges_out = [
                (u, v) for (u, v) in self.edges.keys()
                if u == node_id and self.graph.is_open(u, v)
            ]
            if not edges_out:
                continue
            hot_edge = max(
                edges_out,
                key=lambda kv: self.edges[kv].utilisation,
                default=None,
            )
            if hot_edge is None:
                continue
            u, v = hot_edge
            edge = self.graph.edge(u, v)
            candidates.append(Intervention(
                id=f"boost_{edge.id}",
                type=InterventionType.INCREASE_CAPACITY,
                description=f"Deploy extra staff at corridor {u} → {v} (+50% capacity)",
                parameters={"edge_id": edge.id, "multiplier": 1.5},
            ))
            gates = self.feeding_gates((u, v))
            if gates and phase != "EXIT_SURGE":
                gate = max(gates, key=gates.get)
                alt = self.least_loaded_entry(gate)
                if alt and alt != gate:
                    candidates.append(Intervention(
                        id=f"redirect_{15}_{gate}_{alt}",
                        type=InterventionType.REDIRECT,
                        description=f"Redirect 15% of arrivals at {gate} to {alt}",
                        parameters={"percent": 15, "from": gate, "to": alt},
                    ))

        critical = any(b.current_risk.value in ("HIGH", "CRITICAL") for b in bns)
        if critical and not self.emergency_active and phase != "ENTRY":
            candidates.append(Intervention(
                id="emergency_response",
                type=InterventionType.EMERGENCY_RESPONSE,
                description="Activate emergency egress: route crowds to emergency exits",
                parameters={},
            ))

        for e in self.venue.edges:
            if not e.is_open:
                candidates.append(Intervention(
                    id=f"open_{e.id}",
                    type=InterventionType.OPEN_CORRIDOR,
                    description=f"Open corridor {e.source} → {e.destination}",
                    parameters={"edge_id": e.id},
                ))
                break

        if not candidates:
            candidates.append(Intervention(
                id="adjust_routing",
                type=InterventionType.ADJUST_ROUTING,
                description="Increase congestion sensitivity of all routes",
                parameters={"congestion_penalty_weight": 8.0},
            ))

        seen: set = set()
        unique: List[Intervention] = []
        for c in candidates:
            key = (c.type.value, tuple(sorted(c.parameters.items())))
            if key not in seen:
                seen.add(key)
                unique.append(c)
        emergency = next(
            (c for c in unique if c.type == InterventionType.EMERGENCY_RESPONSE), None
        )
        if emergency:
            unique.remove(emergency)
            unique.insert(0, emergency)
        return unique[:8]

    def _has_alternate(self, u: str, v: str) -> bool:
        """True if u can still reach v after closing walkway u->v."""
        edge = self.graph.edge(u, v)
        if edge is None:
            return False
        edge.is_open = False
        try:
            return bool(self.routing.find_path(u, v))
        finally:
            edge.is_open = True

    def optimize(self, horizon_min: float = 8.0, dt_min: float = 0.125) -> Dict:
        """Run real counterfactual simulations and rank the candidates."""
        baseline_clone = self.clone(fast=True)
        baseline_clone.run_horizon(horizon_min, dt_min)
        baseline_metrics = baseline_clone.metrics
        baseline_bns = baseline_clone.bottlenecks()

        ranked: List[Dict] = []
        for intervention in self.generate_candidates():
            clone = self.clone(fast=True)
            clone.apply_intervention(intervention)
            clone.run_horizon(horizon_min, dt_min)
            candidate_metrics = clone.metrics
            candidate_bns = clone.bottlenecks()

            def norm(base: float, cand: float) -> float:
                return max(0.0, min(1.0, (base - cand) / max(1e-6, base)))

            critical_base = sum(1 for b in baseline_bns if b.current_risk.value in ("HIGH", "CRITICAL"))
            critical_cand = sum(1 for b in candidate_bns if b.current_risk.value in ("HIGH", "CRITICAL"))
            improvement = {
                "critical_zones": -(critical_base - critical_cand),
                "peak_density": round(candidate_metrics.global_density - baseline_metrics.global_density, 3),
                "avg_travel_time_min": round(
                    candidate_metrics.avg_travel_time_min - baseline_metrics.avg_travel_time_min, 2
                ),
                "max_queue": candidate_metrics.queue_total - baseline_metrics.queue_total,
                "max_utilisation": round(
                    candidate_metrics.max_utilisation - baseline_metrics.max_utilisation, 3
                ),
            }
            score = (
                0.4 * norm(max(1, critical_base), max(1, critical_cand))
                + 0.3 * norm(max(0.5, baseline_metrics.avg_travel_time_min),
                             max(0.5, candidate_metrics.avg_travel_time_min))
                + 0.2 * norm(max(0.05, baseline_metrics.max_utilisation),
                             max(0.05, candidate_metrics.max_utilisation))
                + 0.1 * norm(max(1, baseline_metrics.queue_total),
                             max(1, candidate_metrics.queue_total))
            )
            ranked.append({
                "intervention": intervention,
                "score": round(score, 4),
                "improvement": improvement,
                "baseline_metrics": baseline_metrics,
                "candidate_metrics": candidate_metrics,
                "baseline_bottlenecks": baseline_bns,
                "candidate_bottlenecks": candidate_bns,
            })
        ranked.sort(key=lambda r: -r["score"])
        return {"baseline_metrics": baseline_metrics, "candidates": ranked}
