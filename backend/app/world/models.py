"""Unified spatial model for the external world (CrowdFlow world layer).

The world graph is the bridge between the real map and the venue digital twin:

    WORLD GRAPH                     VENUE GRAPH
    ─────────────────────────────   ─────────────────────────────
    demand sources (metro / bus /   gates (ENTRY)  -> checkpoints
      parking / drop-off / walking)  -> corridors -> zones/seats
        |                             -> exits (egress back to world)
        v
    external nodes / edges
        |  (boundary connectors)
        v
    access points (gate links)

Every element carries provenance so nothing is silently fabricated:
capacities are marked ``source="estimated"`` when they are heuristics, and
demand is always labelled SIMULATED / HISTORICAL / LIVE.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..models import RiskLevel, WorldPosition


class ExternalNode(BaseModel):
    """A node in the external (world) graph, in venue coordinate space.

    ``kind`` mirrors the OSM taxonomy the node came from and is used for
    visual styling and routing eligibility (e.g. footpath-only vs road).
    """

    id: str = Field(min_length=1)
    kind: str = Field(
        default="FOOTPATH",
        description="ROAD | FOOTPATH | TRANSIT | PARKING | GATE_LINK | SINK",
    )
    position: WorldPosition
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: str = Field(default="OSM", description="OSM | DEMO | DERIVED")

    @classmethod
    def _norm(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "_")


class ExternalEdge(BaseModel):
    """A walkable/road link in the external graph.

    The CrowdFlow world layer models *people* movement, so every edge carries a
    pedestrian capacity estimate (people/minute). Real capacities are not known
    from OSM — they are heuristics per class and are always marked
    ``source="estimated"``.
    """

    id: str = Field(min_length=1)
    source: str
    target: str
    kind: str = Field(
        default="FOOTPATH",
        description="ROAD | FOOTPATH | STREET | GATE_LINK",
    )
    length_m: float = Field(gt=0)
    walking_allowed: bool = True
    road_allowed: bool = False
    capacity_estimate: float = Field(gt=0, description="people/minute heuristic")
    speed_mps: float = Field(default=1.2, gt=0)
    free_flow_min: float = Field(gt=0)
    geometry: List[WorldPosition] = Field(default_factory=list)
    capacity_source: str = Field(
        default="estimated",
        description="'estimated' for heuristic capacities, else 'measured'",
    )
    closed: bool = False

    def travel_min(self, flow_per_min: float) -> float:
        """BPR-style link cost: free-flow time inflated by congestion.

        Deterministic and honest — flow relative to the capacity heuristic.
        A quadratic term capped at 3x free flow keeps the feedback loop stable
        (a v^4 curve turns a congested edge into "infinite" cost and produces
        flow oscillations as packets thrash between routes).
        """
        if self.closed:
            return float("inf")
        v = flow_per_min / max(1.0, self.capacity_estimate)
        return self.free_flow_min * (1.0 + 0.35 * min(2.0, v ** 2.0))


class AccessPoint(BaseModel):
    """Explicit connector between a venue gate node and the external graph.

    ``gate_id`` is the venue semantic id (e.g. ``GATE_A``) so AI reasoning,
    interventions and the simulation all reference the same entity.
    """

    id: str
    gate_id: str
    node_id: str
    kind: str = Field(default="ENTRY", description="ENTRY | EXIT | EMERGENCY_EXIT")
    position: WorldPosition
    service_ppm: float = Field(gt=0, description="people/minute gate throughput")


class DemandSource(BaseModel):
    """A producer of external arrivals (SIMULATED by default; never fabricated live data)."""

    id: str
    kind: str = Field(
        default="WALKING",
        description="METRO | BUS | PARKING | DROP_OFF | WALKING | GATHERING",
    )
    name: str
    node_id: str
    position: WorldPosition
    capacity: int = Field(default=0, ge=0)
    share: float = Field(default=0.0, ge=0, le=1, description="share of total arrivals")
    gate_share: Dict[str, float] = Field(
        default_factory=dict, description="gate id -> share of this source's arrivals"
    )
    data_source: str = Field(
        default="SIMULATED",
        description="SIMULATED | HISTORICAL | LIVE | USER_INPUT",
    )


class WorldProvenance(BaseModel):
    provider: str = Field(default="DEMO", description="OSM | DEMO | CACHED_OSM")
    fetched_at: Optional[str] = None
    confidence: str = Field(default="estimated", description="high | estimated | demo")
    notes: List[str] = Field(default_factory=list)


class WorldGraph(BaseModel):
    """The unified external graph for a venue: nodes, edges, gate links, demand."""

    venue_id: str
    provider: str = Field(default="DEMO", description="OSM | DEMO | CACHED_OSM")
    provenance: WorldProvenance = Field(default_factory=WorldProvenance)
    bbox: Dict[str, float] = Field(default_factory=dict)
    nodes: List[ExternalNode] = Field(default_factory=list)
    edges: List[ExternalEdge] = Field(default_factory=list)
    access_points: List[AccessPoint] = Field(default_factory=list)
    demand_sources: List[DemandSource] = Field(default_factory=list)
    sink_ids: List[str] = Field(
        default_factory=list, description="nodes that absorb egress (outer boundary / transit)"
    )
    notes: List[str] = Field(default_factory=list)

    def node(self, node_id: str) -> Optional[ExternalNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def edge(self, edge_id: str) -> Optional[ExternalEdge]:
        for e in self.edges:
            if e.id == edge_id:
                return e
        return None


class WorldEdgeState(BaseModel):
    id: str
    kind: str = "FOOTPATH"
    flow_per_min: float = 0.0
    people: int = 0
    utilisation: float = 0.0
    congestion: float = 0.0
    risk: RiskLevel = RiskLevel.NORMAL
    time_to_critical_min: Optional[float] = None
    closed: bool = False
    rerouted: bool = False


class WorldGateState(BaseModel):
    gate_id: str
    arrivals_per_min: float = 0.0
    served_per_min: float = 0.0
    queue: int = 0
    queue_wait_min: Optional[float] = None
    congestion: float = 0.0
    risk: RiskLevel = RiskLevel.NORMAL
    demand_by_source: Dict[str, float] = Field(default_factory=dict)


class WorldSourceState(BaseModel):
    id: str
    kind: str = "WALKING"
    emitted_total: int = 0
    current_rate_per_min: float = 0.0


class WorldPrediction(BaseModel):
    id: str
    kind: str = Field(default="EDGE", description="EDGE | GATE | ROUTE")
    ref: str
    in_minutes: float
    severity: RiskLevel = RiskLevel.ELEVATED
    message: str


class WorldState(BaseModel):
    """Live state of the external world simulation.

    Every number is derived from the world model: scenario demand routed over
    the external graph, gate service capacities and queue dynamics. Nothing is
    fabricated.
    """

    t_min: float = 0.0
    edges: Dict[str, WorldEdgeState] = Field(default_factory=dict)
    gates: Dict[str, WorldGateState] = Field(default_factory=dict)
    sources: Dict[str, WorldSourceState] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.NORMAL
    congested_edges: int = 0
    summary: str = ""
    predictions: List[WorldPrediction] = Field(default_factory=list)
