"""Congestion-aware routing engine.

route cost = distance + congestion penalty + danger penalty

Penalties grow with utilisation and risk so that paths around congested
walkways are preferred once congestion appears, while free-flow paths keep
the minimum-distance behaviour the brief requires (brief section 15).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import networkx as nx

from ..models import NodeType, RiskLevel
from .venue import VenueGraph


@dataclass
class EdgeUsage:
    """Live utilisation of a directed walkway, maintained by the simulator."""
    people: int = 0
    flow_per_min: float = 0.0
    utilisation: float = 0.0
    risk_score: float = 0.0


@dataclass
class RouteOptions:
    """Tunables for the routing objective (brief section 15)."""
    congestion_penalty_weight: float = 3.0   # multiplies excess utilisation
    congestion_threshold: float = 0.6        # utilisation above this is penalised
    risk_penalty: Dict[RiskLevel, float] = field(default_factory=lambda: {
        RiskLevel.NORMAL: 0.0,
        RiskLevel.ELEVATED: 6.0,
        RiskLevel.HIGH: 18.0,
        RiskLevel.CRITICAL: 40.0,
    })
    emergency_discount: float = 0.35         # emergency-exit walkways preferred in emergency mode


class RoutingEngine:
    def __init__(self, graph: VenueGraph):
        self.graph = graph
        self.edge_usage: Dict[tuple, EdgeUsage] = {}
        self.node_risk: Dict[str, RiskLevel] = {}
        self.emergency_active: bool = False
        self.options = RouteOptions()
        self.avoid_edges: set = set()

    # ------------------------------------------------------------------ #
    def set_edge_usage(self, usage: Dict[tuple, EdgeUsage]) -> None:
        self.edge_usage = usage

    def set_node_risk(self, node_risk: Dict[str, RiskLevel]) -> None:
        self.node_risk = node_risk

    def set_avoid_edges(self, edges) -> None:
        self.avoid_edges = set(edges or ())

    def set_emergency(self, active: bool) -> None:
        self.emergency_active = active

    # ------------------------------------------------------------------ #
    def _edge_weight(self, source: str, destination: str, _edge_data=None) -> Optional[float]:
        """Cost of traversing source -> destination, or None if blocked."""
        if not self.graph.is_open(source, destination):
            return None
        if (source, destination) in self.avoid_edges:
            return None

        length = self.graph.edge_length(source, destination)
        if length == float("inf"):
            return None

        usage = self.edge_usage.get((source, destination), EdgeUsage())
        util = max(0.0, min(1.5, usage.utilisation))

        # distance is the base cost (free-flow = plain shortest path)
        cost = length
        # congestion penalty grows quadratically past the threshold
        excess = max(0.0, util - self.options.congestion_threshold)
        cost += length * self.options.congestion_penalty_weight * (excess ** 2)
        # danger penalty from the destination node's risk level
        risk = self.node_risk.get(destination, RiskLevel.NORMAL)
        cost += self.options.risk_penalty.get(risk, 0.0)
        # in emergency mode walkways feeding emergency exits are discounted so
        # evacuation paths favour them without creating impossible routes
        if self.emergency_active and self.graph.edge_is_emergency(source, destination):
            cost *= self.options.emergency_discount
        return cost

    # ------------------------------------------------------------------ #
    def find_path(self, source: str, destination: str) -> List[str]:
        """Congestion-aware path (A* with the dynamic edge weight)."""
        if source == destination:
            return [source]
        try:
            path = nx.astar_path(
                self.graph.graph, source, destination, weight=self._edge_weight,
                heuristic=self._heuristic,
            )
            return list(path)
        except nx.NetworkXNoPath:
            return []

    def _heuristic(self, a: str, b: str) -> float:
        pa, pb = self.graph.position(a), self.graph.position(b)
        return ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2) ** 0.5 * 0.1

    # ------------------------------------------------------------------ #
    def nearest_emergency_exit(self, source: str) -> Optional[str]:
        """Closest reachable emergency exit by congestion-aware cost."""
        best_exit: Optional[str] = None
        best_cost = float("inf")
        for exit_id in self.graph.emergency_exits:
            path = self.find_path(source, exit_id)
            if not path:
                continue
            cost = sum(
                self._edge_weight(u, v) or 1e9
                for u, v in zip(path[:-1], path[1:])
            )
            if cost < best_cost:
                best_cost = cost
                best_exit = exit_id
        return best_exit

    # ------------------------------------------------------------------ #
    def evacuation_path(self, source: str) -> List[str]:
        """Path to the nearest emergency exit (emergency mode).

        Planning query: emergency-designated walkways count as usable even
        before the emergency is declared, so the route can be prepared.
        """
        was_active = self.graph.emergency_active
        self.graph.emergency_active = True
        try:
            exit_id = self.nearest_emergency_exit(source)
            if exit_id is None:
                return []
            return self.find_path(source, exit_id)
        finally:
            self.graph.emergency_active = was_active
