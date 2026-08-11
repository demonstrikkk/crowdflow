"""Venue graph engine.

Wraps a NetworkX directed multigraph representation of a venue. The graph is
built from the authoritative VenueModel and owns all structural queries used
by routing and simulation. Only this module is allowed to touch NetworkX.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx

from ..models import EdgeModel, NodeModel, NodeType, Position, VenueModel


class VenueGraph:
    """Immutable graph built from a VenueModel, plus cached structural data."""

    def __init__(self, venue: VenueModel):
        self.venue = venue
        self.emergency_active: bool = False
        self.graph: nx.DiGraph = nx.DiGraph()

        for node in venue.nodes:
            self.graph.add_node(node.id, model=node)

        self._edges: Dict[Tuple[str, str], EdgeModel] = {}
        for edge in venue.edges:
            self.graph.add_edge(edge.source, edge.destination, model=edge, length_m=edge.length_m)
            # Every walkway is bidirectional; capacity applies to each direction.
            self.graph.add_edge(edge.destination, edge.source, model=edge, length_m=edge.length_m)
            self._edges[(edge.source, edge.destination)] = edge
            self._edges[(edge.destination, edge.source)] = edge

        self.entries: List[str] = self._nodes_of_type(NodeType.ENTRY)
        self.exits: List[str] = self._nodes_of_type(NodeType.EXIT)
        self.emergency_exits: List[str] = self._nodes_of_type(NodeType.EMERGENCY_EXIT)
        self.zones: List[str] = self._nodes_of_type(NodeType.ZONE)
        self.concessions: List[str] = self._nodes_of_type(NodeType.CONCESSION)
        self.entry_capacities: Dict[str, float] = {
            n.id: (n.capacity or 60.0) for n in venue.nodes if n.type == NodeType.ENTRY
        }

    def set_emergency(self, active: bool) -> None:
        """Open emergency-designated walkways while in emergency mode."""
        self.emergency_active = active

    # ------------------------------------------------------------------ #
    def _nodes_of_type(self, ntype: NodeType) -> List[str]:
        return [n.id for n in self.venue.nodes if n.type == ntype]

    def node(self, node_id: str) -> Optional[NodeModel]:
        data = self.graph.nodes.get(node_id)
        return data["model"] if data else None

    def position(self, node_id: str) -> Position:
        return self.node(node_id).position

    def edge(self, source: str, destination: str) -> Optional[EdgeModel]:
        return self._edges.get((source, destination))

    def node_type(self, node_id: str) -> Optional[NodeType]:
        node = self.node(node_id)
        return node.type if node else None

    def neighbours(self, node_id: str) -> List[str]:
        return list(self.graph.successors(node_id))

    def walkable_neighbours(self, node_id: str) -> List[str]:
        return [n for n in self.graph.successors(node_id) if self._is_open(node_id, n)]

    def is_open(self, source: str, destination: str) -> bool:
        return self._is_open(source, destination)

    def _is_open(self, source: str, destination: str) -> bool:
        edge = self._edges.get((source, destination))
        # emergency-designated walkways (e.g. pitch crossings) are closed in
        # normal mode and only usable when the venue is in emergency mode
        return edge is not None and edge.is_open and (not edge.is_emergency or self.emergency_active)

    def edge_is_emergency(self, source: str, destination: str) -> bool:
        edge = self._edges.get((source, destination))
        return edge is not None and edge.is_emergency

    def edge_capacity(self, source: str, destination: str) -> float:
        edge = self._edges.get((source, destination))
        return edge.capacity if edge else 0.0

    def edge_length(self, source: str, destination: str) -> float:
        edge = self._edges.get((source, destination))
        return edge.length_m if edge else float("inf")

    def edge_area(self, source: str, destination: str) -> float:
        edge = self._edges.get((source, destination))
        return edge.length_m * edge.width_m if edge else 0.0

    def node_area(self, node_id: str) -> float:
        node = self.node(node_id)
        if node is None:
            return 0.0
        if node.area_m2 is not None:
            return node.area_m2
        # sensible defaults per node type (m^2)
        default = {
            NodeType.ENTRY: 60.0,
            NodeType.EXIT: 60.0,
            NodeType.EMERGENCY_EXIT: 80.0,
            NodeType.INTERSECTION: 40.0,
            NodeType.CONCESSION: 90.0,
            NodeType.CHECKPOINT: 30.0,
            NodeType.ZONE: 2000.0,
        }
        return default.get(node.type, 40.0)

    # ------------------------------------------------------------------ #
    #  Connectivity helpers (used by venue validation and error handling)
    # ------------------------------------------------------------------ #
    def reachable_from(self, sources: Iterable[str]) -> Set[str]:
        """All nodes reachable by following open edges from any source."""
        reachable: Set[str] = set(sources)
        frontier = list(sources)
        while frontier:
            current = frontier.pop()
            for nxt in self.walkable_neighbours(current):
                if nxt not in reachable:
                    reachable.add(nxt)
                    frontier.append(nxt)
        return reachable

    def reachable_to(self, targets: Iterable[str]) -> Set[str]:
        """All nodes that can reach a target following open edges."""
        reverse = nx.reverse(self.graph, copy=True)
        open_reverse = nx.DiGraph()
        for u, v, data in reverse.edges(data=True):
            model: EdgeModel = data["model"]
            if model.is_open:
                open_reverse.add_edge(u, v)
        reachable: Set[str] = set(targets)
        frontier = list(targets)
        while frontier:
            current = frontier.pop()
            for nxt in open_reverse.successors(current):
                if nxt not in reachable:
                    reachable.add(nxt)
                    frontier.append(nxt)
        return reachable
