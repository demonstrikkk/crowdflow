"""CrowdFlow Optimiser - shared Pydantic schemas.

All data flowing between the frontend, API and simulation engine is typed here.
The venue is modelled as a directed graph of walkable nodes and edges.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# --------------------------------------------------------------------------- #
#  Enums
# --------------------------------------------------------------------------- #
class NodeType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    INTERSECTION = "INTERSECTION"
    CONCESSION = "CONCESSION"
    CHECKPOINT = "CHECKPOINT"
    ZONE = "ZONE"


class RiskLevel(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ScenarioPhase(str, Enum):
    """Preconfigured scenario archetypes (brief section 29)."""
    NORMAL = "NORMAL"
    GATE_OVERLOAD = "GATE_OVERLOAD"
    POST_EVENT_EXIT_SURGE = "POST_EVENT_EXIT_SURGE"


class EventPhaseName(str, Enum):
    ENTRY = "ENTRY"
    PEAK = "PEAK"
    INTERVAL = "INTERVAL"
    EXIT_SURGE = "EXIT_SURGE"


class InterventionType(str, Enum):
    REDIRECT = "REDIRECT"
    CHANGE_GATE = "CHANGE_GATE"
    OPEN_CORRIDOR = "OPEN_CORRIDOR"
    CLOSE_CORRIDOR = "CLOSE_CORRIDOR"
    USE_ALTERNATE_EXIT = "USE_ALTERNATE_EXIT"
    ADJUST_ROUTING = "ADJUST_ROUTING"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"
    INCREASE_CAPACITY = "INCREASE_CAPACITY"
    ADD_INCIDENT = "ADD_INCIDENT"
    SET_WEATHER = "SET_WEATHER"


class SimulationStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


# --------------------------------------------------------------------------- #
#  Operational incident / weather models (sections 24-26 of the brief)
# --------------------------------------------------------------------------- #
class IncidentSpec(BaseModel):
    """An incident's *operational consequences*, not human psychology.

    The simulation models how the affected area alters routes, capacity and
    risk — it never claims to predict real-world behaviour.
    """

    type: str = Field(default="FIRE", description="FIRE | SECURITY | STRUCTURAL")
    location: str = Field(description="venue node id where the incident starts")
    radius_m: float = Field(default=40.0, ge=0)
    spread_rate_m_min: float = Field(default=0.0, ge=0, description="0 = static")
    blocks_exits: List[str] = Field(default_factory=list)
    severity: str = Field(default="MODERATE", description="MODERATE | SEVERE | EXTREME")

    @field_validator("type")
    @classmethod
    def _norm_type(cls, v: str) -> str:
        return v.upper()


class WeatherSpec(BaseModel):
    """Operational weather consequences — capacity/speed modifiers, no physics."""

    condition: str = Field(default="HEAVY_RAIN", description="HEAVY_RAIN | HAIL | HEAT | FOG | CLEAR")
    capacity_multiplier: float = Field(default=0.65, ge=0, le=1.5)
    speed_multiplier: float = Field(default=0.8, ge=0, le=1.5)
    unsafe_outdoor: bool = Field(default=False, description="outdoor routes fully closed")
    applies_outdoor_only: bool = Field(default=True)

    @field_validator("condition")
    @classmethod
    def _norm_condition(cls, v: str) -> str:
        return v.upper()


# --------------------------------------------------------------------------- #
#  Venue model
# --------------------------------------------------------------------------- #
class Position(BaseModel):
    x: float = Field(ge=0, description="X coordinate in venue units")
    y: float = Field(ge=0, description="Y coordinate in venue units")


class WorldPosition(BaseModel):
    """Signed position in the world frame (used by the external environment)."""
    x: float = Field(description="X coordinate in venue (world) units")
    y: float = Field(description="Y coordinate in venue (world) units")


class NodeModel(BaseModel):
    id: str = Field(min_length=1)
    position: Position
    type: NodeType
    capacity: Optional[float] = Field(
        default=None, ge=0, description="People capacity (zone) or throughput/minute (gate)"
    )
    area_m2: Optional[float] = Field(
        default=None, gt=0, description="Physical area of the node (for density)"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _norm_id(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not v:
            raise ValueError("node id cannot be empty")
        return v


class EdgeModel(BaseModel):
    id: str = Field(min_length=1)
    source: str
    destination: str
    length_m: float = Field(gt=0, description="Walkway length in metres")
    width_m: float = Field(gt=0, description="Walkway width in metres")
    capacity: float = Field(
        gt=0, description="Throughput capacity in people/minute"
    )
    is_open: bool = True
    is_emergency: bool = False
    exposure: str = Field(
        default="INDOOR",
        description="INDOOR | OUTDOOR (drives weather/incident operational effects)",
    )

    @field_validator("id")
    @classmethod
    def _norm_id(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not v:
            raise ValueError("edge id cannot be empty")
        return v

    @field_validator("exposure")
    @classmethod
    def _norm_exposure(cls, v: str) -> str:
        v = (v or "").strip().upper()
        return v if v in ("INDOOR", "OUTDOOR") else "INDOOR"


class VenueModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    width: float = Field(default=1000, gt=0)
    height: float = Field(default=620, gt=0)
    nodes: List[NodeModel] = Field(default_factory=list)
    edges: List[EdgeModel] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="free-form venue metadata (e.g. {'location': {'lat', 'lon'}})",
    )

    @model_validator(mode="after")
    def _validate_graph(self) -> "VenueModel":
        """Structural validation: unique ids, existing endpoints, sane graph."""
        node_ids = {n.id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("duplicate node ids in venue")

        for e in self.edges:
            if e.source not in node_ids:
                raise ValueError(f"edge '{e.id}' references unknown source node '{e.source}'")
            if e.destination not in node_ids:
                raise ValueError(f"edge '{e.id}' references unknown destination node '{e.destination}'")
            if e.source == e.destination:
                raise ValueError(f"edge '{e.id}' is a self-loop")

        entries = {n.id for n in self.nodes if n.type == NodeType.ENTRY}
        exits = {n.id for n in self.nodes if n.type in (NodeType.EXIT, NodeType.EMERGENCY_EXIT)}
        if not entries:
            raise ValueError("venue must contain at least one ENTRY node")
        if not exits:
            raise ValueError("venue must contain at least one EXIT or EMERGENCY_EXIT node")

        # connectivity: every node must be reachable from an entry and able to
        # reach an exit (both directions of the walkway graph). Emergency-only
        # walkways count as traversable: they are usable in emergency mode.
        from .engine.venue import VenueGraph
        graph = VenueGraph(self)
        graph.set_emergency(True)
        if len(graph.reachable_from(entries)) != len(node_ids):
            raise ValueError("venue graph is disconnected: some nodes cannot be reached from an entry")
        if len(graph.reachable_to(exits)) != len(node_ids):
            raise ValueError("venue graph is disconnected: some nodes cannot reach an exit")
        return self


# --------------------------------------------------------------------------- #
#  Scenario model
# --------------------------------------------------------------------------- #
class EventPhaseModel(BaseModel):
    name: EventPhaseName
    start_minute: float = Field(ge=0)
    end_minute: float = Field(gt=0)
    arrival_rate_multiplier: float = Field(default=1.0, ge=0)
    spawn: Optional[str] = Field(
        default=None,
        description="overrides where agents spawn during this phase: 'ARRIVAL' or 'EXIT_SURGE'",
    )

    @model_validator(mode="after")
    def _sane(self) -> "EventPhaseModel":
        if self.end_minute <= self.start_minute:
            raise ValueError(f"phase '{self.name}' ends before it starts")
        return self


class ScenarioModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    venue_id: str = Field(min_length=1)
    crowd_size: int = Field(gt=0, description="Expected number of visitors")
    arrival_rate_per_minute: float = Field(gt=0, description="Baseline arrival rate (people/min)")
    exit_rate_per_minute: float = Field(default=0, ge=0, description="Exit-surge rate (people/min)")
    surge_departure_spread_min: float = Field(
        default=8.0,
        ge=0.5,
        description="mean delay (minutes) over which seated crowds depart during the exit surge",
    )
    gate_distribution: Dict[str, float] = Field(
        default_factory=dict, description="entry gate id -> share of arrivals (sums to 1)"
    )
    destination_distribution: Dict[str, float] = Field(
        default_factory=dict, description="destination node id -> share (sums to 1)"
    )
    exit_distribution: Dict[str, float] = Field(
        default_factory=dict, description="exit node id -> share of leavers (sums to 1)"
    )
    event_phases: List[EventPhaseModel] = Field(default_factory=list)
    special: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_distributions(self) -> "ScenarioModel":
        for name, dist in (
            ("gate_distribution", self.gate_distribution),
            ("destination_distribution", self.destination_distribution),
            ("exit_distribution", self.exit_distribution),
        ):
            if dist and abs(sum(dist.values()) - 1.0) > 1e-6:
                raise ValueError(f"{name} must sum to 1.0 (got {sum(dist.values())})")
        if not self.event_phases:
            raise ValueError("scenario must define at least one event phase")
        return self


# --------------------------------------------------------------------------- #
#  Simulation / runtime models
# --------------------------------------------------------------------------- #
class AgentModel(BaseModel):
    id: int
    position: Position
    destination: str
    route: List[str]
    speed_mps: float
    scale_units: int = 1
    is_rerouted: bool = False
    is_emergency: bool = False


class ElementState(BaseModel):
    """Per node / per edge live state pushed to the frontend each tick."""
    id: str
    type: str
    people: int = 0
    flow_per_min: float = 0.0
    capacity: float = 0.0
    utilisation: float = 0.0
    density: float = 0.0
    risk: RiskLevel = RiskLevel.NORMAL
    risk_score: float = 0.0
    queue: int = 0
    trend: str = "Stable"
    time_to_critical_min: Optional[float] = None
    hazard: bool = False


class SimulationMetrics(BaseModel):
    t_min: float
    in_venue: int
    total_spawned: int
    total_completed: int
    global_density: float = 0.0
    flow_per_min: float = 0.0
    max_utilisation: float = 0.0
    avg_utilisation: float = 0.0
    queue_total: int = 0
    queue_growth: float = 0.0
    avg_travel_time_min: float = 0.0
    max_travel_time_min: float = 0.0
    bottleneck_count: int = 0
    risk_level: RiskLevel = RiskLevel.NORMAL
    risk_score: float = 0.0
    clearance_time_min: Optional[float] = None


class Bottleneck(BaseModel):
    id: str
    kind: str  # "edge" | "node"
    location: str
    current_risk: RiskLevel
    current_density: float
    capacity_utilisation: float
    queue: int
    trend: str
    estimated_time_to_critical_min: Optional[float] = None
    explanation: str


class Intervention(BaseModel):
    id: str = Field(min_length=1)
    type: InterventionType
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class OptimizationCandidate(BaseModel):
    intervention: Intervention
    score: float
    improvement: Dict[str, float]  # real deltas, e.g. {"peak_density": -1.9}
    baseline_metrics: SimulationMetrics
    candidate_metrics: SimulationMetrics
    baseline_bottlenecks: List[Bottleneck] = Field(default_factory=list)
    candidate_bottlenecks: List[Bottleneck] = Field(default_factory=list)


class OptimizationResult(BaseModel):
    baseline_metrics: SimulationMetrics
    candidates: List[OptimizationCandidate]


class CrowdEstimate(BaseModel):
    model_id: str
    estimated_count: int
    detections: List[Dict[str, Any]] = Field(default_factory=list)
    density_score: float = Field(ge=0, le=1)
    mean_confidence: float = Field(ge=0, le=1)
    frame_area_m2: Optional[float] = None


# --------------------------------------------------------------------------- #
#  External environment / road network (brief section 20)
# --------------------------------------------------------------------------- #
class RoadSegmentModel(BaseModel):
    id: str = Field(min_length=1)
    name: Optional[str] = None
    kind: str = Field(
        default="LOCAL", description="ARTERIAL | MAJOR | LOCAL | ACCESS | RING"
    )
    from_node: str
    to_node: str
    lanes: int = Field(default=2, ge=1)
    speed_limit_kmh: float = Field(default=50, gt=0)
    capacity_veh_h: float = Field(default=800, gt=0)
    length_m: float = Field(gt=0)
    points: List[WorldPosition] = Field(
        default_factory=list, description="polyline geometry in venue (world) coords"
    )

    @field_validator("id")
    @classmethod
    def _norm_id(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not v:
            raise ValueError("road id cannot be empty")
        return v


class JunctionModel(BaseModel):
    id: str = Field(min_length=1)
    name: Optional[str] = None
    position: WorldPosition
    kind: str = Field(default="SIGNAL", description="SIGNAL | ROUNDABOUT | T_JUNCTION")

    @field_validator("id")
    @classmethod
    def _norm_id(cls, v: str) -> str:
        return v.strip().upper().replace(" ", "_")


class TransitStopModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    position: WorldPosition
    kind: str = Field(default="BUS", description="BUS | TRAM | RAIL")


class ParkingAreaModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    position: WorldPosition
    capacity: int = Field(gt=0)


class ExternalEnvironment(BaseModel):
    venue_id: str = Field(min_length=1)
    source: str = Field(default="BUNDLED", description="BUNDLED | LIVE_OSM")
    origin: Optional[str] = Field(
        default=None, description="lat/lon reference the data was fetched for"
    )
    bbox: Dict[str, float] = Field(default_factory=dict)
    roads: List[RoadSegmentModel] = Field(default_factory=list)
    junctions: List[JunctionModel] = Field(default_factory=list)
    transit: List[TransitStopModel] = Field(default_factory=list)
    parking: List[ParkingAreaModel] = Field(default_factory=list)
    notes: List[str] = Field(
        default_factory=list, description="assumptions / fallback reasons"
    )


class ExternalElementState(BaseModel):
    id: str
    kind: str  # ROAD | JUNCTION | TRANSIT | PARKING
    people_accumulated: int = 0
    queue_veh: int = 0
    congestion: float = Field(default=0.0, ge=0, le=1)
    clearance_min: Optional[float] = None
    risk: RiskLevel = RiskLevel.NORMAL


class ExternalState(BaseModel):
    """External road-network congestion derived from exit flows (deterministic).

    Explicitly an operational estimate - exit flows are drained by each element
    at a fixed outflow and congestion is backlog over that outflow. It is not a
    traffic microsimulation.
    """

    venue_id: str
    source: str = "BUNDLED"
    elements: Dict[str, ExternalElementState] = Field(default_factory=dict)
    congested_elements: int = 0
    risk: RiskLevel = RiskLevel.NORMAL
    summary: str = ""


# --------------------------------------------------------------------------- #
#  Blueprint import pipeline (brief section 21)
# --------------------------------------------------------------------------- #
class BlueprintElement(BaseModel):
    """A semantic element recovered from a blueprint image."""

    id: str
    kind: str = Field(
        default="INTERSECTION",
        description="NodeType string: ENTRY | EXIT | EMERGENCY_EXIT | INTERSECTION | CONCESSION | CHECKPOINT | ZONE",
    )
    position: WorldPosition
    area_m2: Optional[float] = None
    confidence: float = Field(ge=0, le=1)
    label: Optional[str] = None
    source: str = Field(
        default="GEOMETRY", description="GEOMETRY | OCR | CLASSIFIER | TEMPLATE"
    )


class BlueprintResult(BaseModel):
    venue: VenueModel
    elements: List[BlueprintElement] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    degradation_level: int = Field(
        default=0, description="0=full CV+OCR, 1=CV only, 2=heuristic geometry, 3=template"
    )
    degraded: bool = False
    steps: Dict[str, str] = Field(
        default_factory=dict, description="per-stage outcome (stage -> status)"
    )
    notes: List[str] = Field(default_factory=list)


class SimulationState(BaseModel):
    sim_id: str
    scenario_id: str
    venue_id: str
    status: SimulationStatus
    t_min: float
    tick: int
    phase: str
    speed: float
    emergency_active: bool
    interventions_applied: List[Intervention]
    metrics: SimulationMetrics
    history: List[Dict[str, Any]]
    nodes: Dict[str, ElementState]
    edges: Dict[str, ElementState]
    bottlenecks: List[Bottleneck]
    agents: List[AgentModel]
    recommended_action: Optional[str] = None
    simulation_scale: int = 1
    node_positions: Dict[str, Position] = Field(default_factory=dict)
    incident: Optional[Dict[str, Any]] = None
    weather: Optional[Dict[str, Any]] = None
    hazard_zones: List[Dict[str, Any]] = Field(default_factory=list)
    external: Optional["ExternalState"] = None


ExternalState.model_rebuild()
