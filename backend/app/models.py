"""CrowdFlow Optimiser - shared Pydantic schemas.

All data flowing between the frontend, API and simulation engine is typed here.
The venue is modelled as a directed graph of walkable nodes and edges.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

from app.blueprint.architecture.models import ArchitecturalScene
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
    temperature: float = Field(default=20.0, description="temperature in Celsius")
    humidity: float = Field(default=0.5, description="humidity 0.0 to 1.0")
    wind_speed_mps: float = Field(default=2.0, description="wind speed in meters per second")
    visibility: float = Field(default=1.0, description="visibility 0.0 to 1.0")
    uv_index: float = Field(default=1.0, description="UV index")
    heat_index: float = Field(default=20.0, description="heat index in Celsius")

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
    spatial_ref: Optional[str] = Field(
        default=None,
        description="reference into VenueSpatialModel, e.g. 'opening:G01'",
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
    geometry_id: Optional[str] = Field(
        default=None,
        description="reference to a PathGeometryModel in VenueSpatialModel",
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
#  Venue spatial / architectural model
#
#  VenueModel stays authoritative for movement & simulation. VenueSpatialModel
#  is the physical-spatial counterpart: levels, wall/floor polygons, openings
#  (gates/doors) and pathway centre-lines. Nodes reference openings through
#  ``spatial_ref`` and edges reference paths through ``geometry_id``.
# --------------------------------------------------------------------------- #
class Point2D(BaseModel):
    x: float
    y: float


class Polygon2D(BaseModel):
    points: List[Point2D]

    @model_validator(mode="after")
    def _valid_polygon(self) -> "Polygon2D":
        if len(self.points) < 3:
            raise ValueError("Polygon requires at least 3 points")
        return self


class LevelModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    elevation_m: float = Field(default=0.0, ge=0)
    height_m: float = Field(default=5.0, gt=0)


class StructureModel(BaseModel):
    """A physical architectural element, expressed as a 2D footprint polygon."""

    id: str = Field(min_length=1)
    level_id: str = Field(min_length=1)
    type: Literal["WALL", "FLOOR", "FIELD", "SEATING", "CONCOURSE", "ROOM", "STAIR", "ROOF", "ZONE"]
    polygon: Polygon2D
    height_m: float = Field(default=0.0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OpeningModel(BaseModel):
    """A physical passage (gate / door) in the architecture."""

    id: str = Field(min_length=1)
    level_id: str = Field(min_length=1)
    type: Literal["ENTRY_GATE", "EXIT_GATE", "EMERGENCY_EXIT", "DOOR", "SERVICE_ENTRY"]
    position: Point2D
    width_m: float = Field(default=2.0, gt=0)
    rotation_deg: float = Field(default=0.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PathGeometryModel(BaseModel):
    """Physical walkway geometry. Capacity/width for simulation stays on EdgeModel."""

    id: str = Field(min_length=1)
    level_id: str = Field(min_length=1)
    centerline: List[Point2D]
    width_m: float = Field(default=3.0, gt=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_centerline(self) -> "PathGeometryModel":
        if len(self.centerline) < 2:
            raise ValueError("path centerline requires at least 2 points")
        return self


class VenueSpatialModel(BaseModel):
    venue_id: str = Field(min_length=1)
    coordinate_system: Literal["LOCAL_METRIC"] = "LOCAL_METRIC"
    levels: List[LevelModel] = Field(default_factory=list)
    structures: List[StructureModel] = Field(default_factory=list)
    openings: List[OpeningModel] = Field(default_factory=list)
    paths: List[PathGeometryModel] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references_valid(self) -> "VenueSpatialModel":
        level_ids = {l.id for l in self.levels}
        if not level_ids:
            raise ValueError("spatial model must define at least one level")
        for group, name in (
            (self.structures, "structure"),
            (self.openings, "opening"),
            (self.paths, "path"),
        ):
            for item in group:
                if item.level_id not in level_ids:
                    raise ValueError(f"{name} '{item.id}' references unknown level '{item.level_id}'")
        return self


class VenueDocument(BaseModel):
    """Versioned persisted venue document: navigation model + spatial model."""

    schema_version: int = 2
    venue: VenueModel
    spatial: Optional[VenueSpatialModel] = None
    canonical2d: Optional[Canonical2DModel] = None
    architectural_scene: Optional[ArchitecturalScene] = None
    report: Optional[ReconstructionReport] = None
    reconstruction_version: Optional[str] = None


# --------------------------------------------------------------------------- #
#  Venue Digital Twin (canonical semantic model)
#
#  The VenueModel / VenueSpatialModel pair is the persisted source of truth.
#  VenueDigitalTwin is the *canonical, validated, renderable* projection of that
#  document: a structured, editable, code-generated 3D model plus its own
#  navigation graph and validation report. Geometry is always produced by
#  deterministic generators from this semantic schema — the AI never emits mesh
#  code, and the schema never depends on Three.js.
# --------------------------------------------------------------------------- #
class TwinValidationIssue(BaseModel):
    id: str
    severity: Literal["ERROR", "WARNING", "INFERENCE"]
    scope: str  # e.g. "structure:WALL_N" | "navigation" | "coordinate_system"
    message: str
    element_ids: List[str] = Field(default_factory=list)


class TwinNavigationNode(BaseModel):
    id: str = Field(min_length=1)
    type: NodeType
    position: Point2D
    level_id: str = Field(default="L1")
    capacity: float = Field(default=0.0, ge=0)
    confidence: float = Field(default=0.8, ge=0, le=1)
    spatial_ref: Optional[str] = None


class TwinNavigationEdge(BaseModel):
    id: str = Field(min_length=1)
    source: str
    destination: str
    length_m: float = Field(gt=0)
    width_m: float = Field(default=3.0, gt=0)
    capacity_ppm: float = Field(default=120.0, gt=0)
    level_change: float = Field(default=0.0)
    is_emergency: bool = False
    geometry_id: Optional[str] = None


class TwinNavigationGraph(BaseModel):
    nodes: List[TwinNavigationNode] = Field(default_factory=list)
    edges: List[TwinNavigationEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_exist(self) -> "TwinNavigationGraph":
        nids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in nids:
                raise ValueError(f"nav edge '{e.id}' references unknown node '{e.source}'")
            if e.destination not in nids:
                raise ValueError(f"nav edge '{e.id}' references unknown node '{e.destination}'")
        return self


class TwinCoordinateSystem(BaseModel):
    name: str = Field(default="LOCAL_METRIC")
    units: str = Field(default="m")
    origin: Point2D = Point2D(x=0.0, y=0.0)
    north_deg: float = Field(default=0.0)
    scale_estimated: bool = Field(default=False, description="mark when scale was not measured")
    source: Optional[str] = Field(default=None, description="e.g. 'BLUEPRINT_SCALE' | 'AUTHORED' | 'DERIVED'")


class TwinDimensions(BaseModel):
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)


class TwinLevel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    index: int = Field(default=0)
    elevation_m: float = Field(default=0.0)
    height_m: float = Field(default=5.0, gt=0)


class TwinStructure(BaseModel):
    """Semantic architectural element; geometry is deterministic from this."""

    id: str = Field(min_length=1)
    type: str
    level_id: str = Field(default="L1")
    polygon: Polygon2D
    height_m: float = Field(default=2.0, ge=0)
    confidence: float = Field(default=0.8, ge=0, le=1)
    source: str = Field(default="PROCEDURAL", description="AUTHORED | BLUEPRINT | DERIVED | PROCEDURAL | USER")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TwinOpening(BaseModel):
    id: str = Field(min_length=1)
    type: str  # ENTRY_GATE | EXIT_GATE | EMERGENCY_EXIT | DOOR | SERVICE_ENTRY | WINDOW
    level_id: str = Field(default="L1")
    position: Point2D
    width_m: float = Field(default=2.0, gt=0)
    rotation_deg: float = Field(default=0.0)
    capacity_ppm: float = Field(default=120.0, gt=0)
    is_emergency: bool = Field(default=False)
    confidence: float = Field(default=0.8, ge=0, le=1)
    source: str = Field(default="PROCEDURAL")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TwinPath(BaseModel):
    id: str = Field(min_length=1)
    level_id: str = Field(default="L1")
    centerline: List[Point2D]
    width_m: float = Field(default=3.0, gt=0)
    confidence: float = Field(default=0.8, ge=0, le=1)
    source: str = Field(default="PROCEDURAL")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_centerline(self) -> "TwinPath":
        if len(self.centerline) < 2:
            raise ValueError("twin path centerline requires at least 2 points")
        return self


class TwinRoad(BaseModel):
    id: str = Field(min_length=1)
    kind: str = Field(default="LOCAL", description="ARTERIAL | MAJOR | LOCAL | ACCESS | RING")
    name: Optional[str] = None
    lanes: int = Field(default=2, ge=1)
    width_m: float = Field(default=7.0, gt=0)
    capacity_veh_h: float = Field(default=800, gt=0)
    points: List[Point2D] = Field(default_factory=list)


class TwinSite(BaseModel):
    """Surrounding infrastructure, kept as a separate layer from the venue."""
    roads: List[TwinRoad] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class TwinSourceReference(BaseModel):
    """Traceability: which blueprint region/object produced a twin element."""
    element_id: str
    kind: str = Field(default="BLUEPRINT_OBJECT", description="BLUEPRINT_OBJECT | BLUEPRINT_REGION | PROCEDURAL")
    source_bbox: Optional[List[float]] = Field(
        default=None, description="(x0, y0, x1, y1) in blueprint pixels"
    )
    note: Optional[str] = None


class VenueDigitalTwin(BaseModel):
    """Canonical, renderable digital twin of a venue.

    ``navigation`` is the simulation-ready graph derived from this schema
    (regenerated whenever the twin is edited), and ``validation`` lists every
    geometry / navigation / accuracy concern the twin currently has.
    """

    venue_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    coordinate_system: TwinCoordinateSystem = Field(default_factory=TwinCoordinateSystem)
    dimensions: TwinDimensions
    levels: List[TwinLevel] = Field(default_factory=list)
    structures: List[TwinStructure] = Field(default_factory=list)
    openings: List[TwinOpening] = Field(default_factory=list)
    paths: List[TwinPath] = Field(default_factory=list)
    navigation: TwinNavigationGraph = Field(default_factory=TwinNavigationGraph)
    site: TwinSite = Field(default_factory=TwinSite)
    validation: List[TwinValidationIssue] = Field(default_factory=list)
    confidence: float = Field(default=0.75, ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_references: List[TwinSourceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def _twin_levels_referenced(self) -> "VenueDigitalTwin":
        level_ids = {lv.id for lv in self.levels}
        if not level_ids and (self.structures or self.openings or self.paths):
            raise ValueError("digital twin with geometry must define at least one level")
        for group, name in (
            (self.structures, "structure"),
            (self.openings, "opening"),
            (self.paths, "path"),
        ):
            for item in group:
                if item.level_id not in level_ids:
                    raise ValueError(f"twin {name} '{item.id}' references unknown level '{item.level_id}'")
        return self


# --------------------------------------------------------------------------- #
#  Twin conversion + validation  (document <-> twin)
#
#  The twin is derived *from* the persisted document and written back *through*
#  it. Geometry stays deterministic; AI can only ever modify this semantic form.
# --------------------------------------------------------------------------- #
def _structure_confidence(metadata: Dict[str, Any], source: str) -> float:
    conf = metadata.get("confidence")
    if isinstance(conf, (int, float)) and 0 <= conf <= 1:
        return float(conf)
    return {"AUTHORED": 0.95, "BLUEPRINT": 0.8, "DERIVED": 0.7, "USER": 0.9}.get(source, 0.6)


def document_to_digital_twin(doc: "VenueDocument") -> "VenueDigitalTwin":
    """Build the canonical twin projection of a persisted venue document."""
    from app.spatial import derive_spatial_from_venue  # noqa: PLC0415 - avoid import cycle

    venue = doc.venue
    spatial = doc.spatial
    if spatial is None:
        spatial = derive_spatial_from_venue(venue)

    level_index = {lv.id: i for i, lv in enumerate(spatial.levels)}
    opening_level: Dict[str, str] = {o.id: o.level_id for o in spatial.openings}

    structures = [
        TwinStructure(
            id=s.id,
            type=s.type,
            level_id=s.level_id,
            polygon=s.polygon,
            height_m=s.height_m,
            confidence=_structure_confidence(s.metadata, str(s.metadata.get("source", "PROCEDURAL"))),
            source=str(s.metadata.get("source", "PROCEDURAL")),
            metadata=s.metadata,
        )
        for s in spatial.structures
    ]

    openings = [
        TwinOpening(
            id=o.id,
            type=o.type,
            level_id=o.level_id,
            position=o.position,
            width_m=o.width_m,
            rotation_deg=o.rotation_deg,
            capacity_ppm=float(o.metadata.get("capacity_ppm", 120.0)) if o.metadata else 120.0,
            is_emergency=o.type == "EMERGENCY_EXIT",
            confidence=_structure_confidence(o.metadata, str(o.metadata.get("source", "PROCEDURAL"))),
            source=str(o.metadata.get("source", "PROCEDURAL")),
            metadata=o.metadata,
        )
        for o in spatial.openings
    ]

    paths = [
        TwinPath(
            id=p.id,
            level_id=p.level_id,
            centerline=p.centerline,
            width_m=p.width_m,
            confidence=_structure_confidence(p.metadata, str(p.metadata.get("source", "PROCEDURAL"))),
            source=str(p.metadata.get("source", "PROCEDURAL")),
            metadata=p.metadata,
        )
        for p in spatial.paths
    ]

    nav_nodes = []
    for node in venue.nodes:
        nav_nodes.append(
            TwinNavigationNode(
                id=node.id,
                type=node.type,
                position=Point2D(x=node.position.x, y=node.position.y),
                level_id=opening_level.get(node.id) or "L1",
                capacity=float(node.capacity or 0.0),
                confidence=_structure_confidence(node.metadata, str(node.metadata.get("source", "PROCEDURAL"))),
                spatial_ref=node.spatial_ref,
            )
        )

    nav_edges = [
        TwinNavigationEdge(
            id=edge.id,
            source=edge.source,
            destination=edge.destination,
            length_m=edge.length_m,
            width_m=edge.width_m,
            capacity_ppm=edge.capacity,
            level_change=0.0,
            is_emergency=edge.is_emergency,
            geometry_id=edge.geometry_id,
        )
        for edge in venue.edges
    ]

    source_refs: List[TwinSourceReference] = []
    for group in (spatial.structures, spatial.openings, spatial.paths):
        for item in group:
            bbox = (item.metadata or {}).get("source_bbox")
            if bbox:
                source_refs.append(
                    TwinSourceReference(
                        element_id=item.id,
                        source_bbox=[float(v) for v in bbox],
                        note="source detection region",
                    )
                )

    metadata_notes = list(spatial.metadata.get("notes", [])) if spatial.metadata else []
    scale_estimated = "estimated" in str(spatial.metadata.get("source", "")).lower() or any(
        "estimated" in n.lower() for n in metadata_notes
    )

    twin = VenueDigitalTwin(
        venue_id=venue.id,
        name=venue.name,
        coordinate_system=TwinCoordinateSystem(
            name=spatial.coordinate_system,
            origin=Point2D(x=0.0, y=0.0),
            north_deg=float((venue.metadata.get("location") or {}).get("north_deg", 0.0)),
            scale_estimated=scale_estimated,
            source=str(spatial.metadata.get("source", "AUTHORED")) if spatial.metadata else "AUTHORED",
        ),
        dimensions=TwinDimensions(width_m=venue.width, height_m=venue.height),
        levels=[
            TwinLevel(
                id=lv.id,
                name=lv.name,
                index=level_index.get(lv.id, 0),
                elevation_m=lv.elevation_m,
                height_m=lv.height_m,
            )
            for lv in spatial.levels
        ],
        structures=structures,
        openings=openings,
        paths=paths,
        navigation=TwinNavigationGraph(nodes=nav_nodes, edges=nav_edges),
        site=TwinSite(),
        confidence=float(doc.report.overall_confidence) if doc.report and doc.report.overall_confidence else 0.75,
        metadata={"source": str(spatial.metadata.get("source", "AUTHORED")), "notes": metadata_notes} if spatial.metadata else {},
        source_references=source_refs,
    )
    twin.validation = validate_digital_twin(twin)
    return twin


_STRUCTURE_TYPE_ALLOWED = {
    "WALL", "FLOOR", "FIELD", "SEATING", "CONCOURSE", "ROOM", "STAIR", "ROOF", "ZONE",
}
_OPENING_TYPE_ALLOWED = {"ENTRY_GATE", "EXIT_GATE", "EMERGENCY_EXIT", "DOOR", "SERVICE_ENTRY"}
_OPENING_TO_NODE_FALLBACK = {
    "ENTRY_GATE": NodeType.ENTRY,
    "EXIT_GATE": NodeType.EXIT,
    "EMERGENCY_EXIT": NodeType.EMERGENCY_EXIT,
    "SERVICE_ENTRY": NodeType.ENTRY,
}


def digital_twin_to_document(dt: "VenueDigitalTwin") -> "VenueDocument":
    """Write a twin back to a persisted VenueDocument, regenerating the
    navigation graph from the (possibly edited) geometry."""
    from app.blueprint.navigation import build_venue_from_spatial  # noqa: PLC0415 - avoid cycle

    width_m = dt.dimensions.width_m
    height_m = dt.dimensions.height_m

    spatial = VenueSpatialModel(
        venue_id=dt.venue_id,
        coordinate_system="LOCAL_METRIC",
        levels=[
            LevelModel(
                id=lv.id,
                name=lv.name,
                elevation_m=lv.elevation_m,
                height_m=lv.height_m,
            )
            for lv in dt.levels
        ],
        structures=[
            StructureModel(
                id=s.id,
                level_id=s.level_id,
                type=s.type if s.type in _STRUCTURE_TYPE_ALLOWED else "ROOM",
                polygon=s.polygon,
                height_m=s.height_m,
                metadata={**s.metadata, "confidence": s.confidence, "source": s.source},
            )
            for s in dt.structures
        ],
        openings=[
            OpeningModel(
                id=o.id,
                level_id=o.level_id,
                type=o.type if o.type in _OPENING_TYPE_ALLOWED else "DOOR",
                position=o.position,
                width_m=o.width_m,
                rotation_deg=o.rotation_deg,
                metadata={**o.metadata, "capacity_ppm": o.capacity_ppm, "confidence": o.confidence, "source": o.source},
            )
            for o in dt.openings
        ],
        paths=[
            PathGeometryModel(
                id=p.id,
                level_id=p.level_id,
                centerline=p.centerline,
                width_m=p.width_m,
                metadata={**p.metadata, "confidence": p.confidence, "source": p.source},
            )
            for p in dt.paths
        ],
        metadata={"source": dt.metadata.get("source", "AUTHORED"), "notes": dt.metadata.get("notes", [])},
    )

    venue, _notes = build_venue_from_spatial(spatial, width_m, height_m)
    venue.id = dt.venue_id
    venue.name = dt.name
    venue.width = width_m
    venue.height = height_m
    spatial.venue_id = dt.venue_id

    return VenueDocument(
        schema_version=2,
        venue=venue,
        spatial=spatial,
    )


def validate_digital_twin(twin: "VenueDigitalTwin") -> List[TwinValidationIssue]:
    """Deterministic validation of the canonical twin.

    Severity contract:
      * ERROR    — invalid / unusable (duplicate ids, out-of-bounds, disconnected nav)
      * WARNING  — degraded, usable with caution (zero height, no nav connection)
      * INFERENCE — uncertain provenance (estimated scale, low confidence)
    """
    issues: List[TwinValidationIssue] = []
    seq = 0

    def add(severity: Literal["ERROR", "WARNING", "INFERENCE"], scope: str, message: str, ids: Optional[List[str]] = None):
        nonlocal seq
        seq += 1
        issues.append(
            TwinValidationIssue(
                id=f"DTW{seq}",
                severity=severity,
                scope=scope,
                message=message,
                element_ids=list(ids or []),
            )
        )

    w, h = twin.dimensions.width_m, twin.dimensions.height_m

    seen: Dict[str, str] = {}
    for s in twin.structures:
        if s.id in seen:
            add("ERROR", f"structure:{s.id}", f"duplicate structure id '{s.id}'", [s.id])
        seen[s.id] = "structure"
        xs = [p.x for p in s.polygon.points]
        ys = [p.y for p in s.polygon.points]
        if max(xs) > w * 1.01 or max(ys) > h * 1.01 or min(xs) < -0.01 or min(ys) < -0.01:
            add("ERROR", f"structure:{s.id}", "structure footprint extends outside the venue boundary", [s.id])
        if s.height_m <= 0:
            add("WARNING", f"structure:{s.id}", "structure has zero height and will render flat", [s.id])

    opening_ids = {o.id for o in twin.openings}
    for o in twin.openings:
        if o.position.x > w * 1.01 or o.position.y > h * 1.01 or o.position.x < -0.01 or o.position.y < -0.01:
            add("ERROR", f"opening:{o.id}", "opening position is outside the venue boundary", [o.id])
        if o.confidence < 0.35:
            add("INFERENCE", f"opening:{o.id}", "opening has low recovery confidence — review before simulation", [o.id])

    for p in twin.paths:
        if p.width_m < 0.5:
            add("WARNING", f"path:{p.id}", f"path width {p.width_m:.2f}m is too narrow for crowd flow", [p.id])
        xs = [pt.x for pt in p.centerline]
        ys = [pt.y for pt in p.centerline]
        if max(xs) > w * 1.01 or max(ys) > h * 1.01 or min(xs) < -0.01 or min(ys) < -0.01:
            add("WARNING", f"path:{p.id}", "path exits the venue boundary", [p.id])

    nav = twin.navigation
    node_ids = {n.id for n in nav.nodes}
    if not node_ids:
        add("ERROR", "navigation", "twin has no navigation nodes", [])
    elif not twin.openings:
        add("WARNING", "navigation", "no openings exist; graph cannot connect people to the venue", [])
    else:
        adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}
        edge_by_nodes: Dict[tuple, str] = {}
        for e in nav.edges:
            adjacency.setdefault(e.source, []).append(e.destination)
            adjacency.setdefault(e.destination, []).append(e.source)
            edge_by_nodes[(e.source, e.destination)] = e.id

        starts = [n.id for n in nav.nodes if n.type in (NodeType.ENTRY, NodeType.EMERGENCY_EXIT)]
        if not starts:
            add("ERROR", "navigation", "no ENTRY or EMERGENCY_EXIT node in the navigation graph", [])
        else:
            reachable: set[str] = set()
            stack = list(starts)
            while stack:
                cur = stack.pop()
                if cur in reachable:
                    continue
                reachable.add(cur)
                stack.extend(adjacency.get(cur, []))
            unreachable = [nid for nid in node_ids if nid not in reachable]
            if unreachable:
                add(
                    "ERROR",
                    "navigation",
                    f"{len(unreachable)} node(s) cannot be reached from any entrance: {', '.join(sorted(unreachable)[:6])}",
                    unreachable,
                )
        if not nav.edges:
            add("ERROR", "navigation", "navigation graph has no edges", [])

    for s in twin.structures:
        if s.confidence < 0.35:
            add("INFERENCE", f"structure:{s.id}", "structure has low recovery confidence — verify geometry", [s.id])

    if twin.coordinate_system.scale_estimated:
        add(
            "INFERENCE",
            "coordinate_system",
            "scale is estimated, not measured — dimensions are approximate",
            [],
        )

    order = {"ERROR": 0, "WARNING": 1, "INFERENCE": 2}
    issues.sort(key=lambda i: (order[i.severity], i.id))
    return issues


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
    patience: float = 1.0
    stress: float = 0.0
    excitement: float = 0.5
    fatigue: float = 0.0
    heat_exposure: float = 0.0
    hydration: float = 1.0
    perceived_crowding: float = 0.0
    incident_awareness: bool = False
    group_id: Optional[str] = None
    group_type: str = "INDIVIDUAL"
    current_intention: str = "ENTER"


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
    # Living crowd state aggregates
    avg_stress: float = 0.0
    avg_fatigue: float = 0.0
    avg_patience: float = 1.0
    avg_hydration: float = 1.0
    water_seekers: int = 0


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


class DetectionKind(str, Enum):
    """Intermediate detection classes produced by any perception backend."""

    WALL = "WALL"
    BOUNDARY = "BOUNDARY"
    REGION = "REGION"
    ROOM = "ROOM"
    ZONE = "ZONE"
    FIELD = "FIELD"
    SEATING = "SEATING"
    CONCOURSE = "CONCOURSE"
    DOOR = "DOOR"
    GATE = "GATE"
    STAIR = "STAIR"
    CORRIDOR = "CORRIDOR"
    TEXT = "TEXT"


class GeometryType(str, Enum):
    SEGMENT = "SEGMENT"
    POLYGON = "POLYGON"
    POINT = "POINT"
    POLYLINE = "POLYLINE"


class DocumentType(str, Enum):
    """Source-document projection class (Phase 2C: diagnose the input type).

    Only ``ORTHOGRAPHIC_PLAN`` / ``MULTI_LEVEL_PLAN`` are valid inputs for the
    top-down floor-plan reconstruction path. Perspective/elevation drawings are
    *not* treated as floor plans: their pixel coordinates are not metres.
    """

    ORTHOGRAPHIC_PLAN = "ORTHOGRAPHIC_PLAN"
    MULTI_LEVEL_PLAN = "MULTI_LEVEL_PLAN"
    ELEVATION = "ELEVATION"
    PERSPECTIVE_ARCHITECTURAL_DRAWING = "PERSPECTIVE_ARCHITECTURAL_DRAWING"
    SECTION = "SECTION"
    MASTER_PLAN = "MASTER_PLAN"
    UNKNOWN = "UNKNOWN"


class DetectionState(str, Enum):
    """Lifecycle state of a perception detection.

    ``DETECTED`` - raw perception candidate (must not become infrastructure);
    ``CONFIRMED`` - passed the semantic evidence gate, safe to materialise;
    ``REJECTED`` - kept as a review candidate only, never becomes a spatial
    object / opening / node / edge.
    ``UNCERTAIN`` - marginal evidence; requires review but may be valid.
    """

    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


PLAN_DOCUMENT_TYPES = {
    DocumentType.ORTHOGRAPHIC_PLAN,
    DocumentType.MULTI_LEVEL_PLAN,
}


class DetectionGeometry(BaseModel):
    """Geometry of one detection, in normalised blueprint pixels (y down).

    Exactly one of point/segment/polygon/polyline is populated depending on
    ``type``. ``bbox`` is the axis-aligned (x0, y0, x1, y1) pixel box.
    """

    type: GeometryType
    point: Optional[Point2D] = None
    p0: Optional[Point2D] = None
    p1: Optional[Point2D] = None
    polygon: Optional[List[Point2D]] = None
    polyline: Optional[List[Point2D]] = None
    bbox: Optional[Tuple[float, float, float, float]] = None

    @model_validator(mode="after")
    def _shape_matches_type(self) -> "DetectionGeometry":
        v = self.type
        if v == GeometryType.POINT and self.point is None:
            raise ValueError("POINT detection requires 'point'")
        if v == GeometryType.SEGMENT and (self.p0 is None or self.p1 is None):
            raise ValueError("SEGMENT detection requires p0 and p1")
        if v == GeometryType.POLYGON and (not self.polygon or len(self.polygon) < 3):
            raise ValueError("POLYGON detection requires >= 3 polygon points")
        if v == GeometryType.POLYLINE and (not self.polyline or len(self.polyline) < 2):
            raise ValueError("POLYLINE detection requires >= 2 polyline points")
        return self


class Detection(BaseModel):
    """A single perceived object from the blueprint.

    ``kind`` is the coarse class (walls, regions, openings, corridors, text);
    finer semantic typing (ENTRY_GATE vs EXIT_GATE, ROOM kind) happens in the
    semantic-interpretation stage. ``source`` records which perception backend
    produced it (CV | OCR | HF | CLASSIFIER | USER).
    """

    id: str = Field(min_length=1)
    kind: DetectionKind
    geometry: DetectionGeometry
    text: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    source: str = Field(default="CV", description="CV | OCR | HF | CLASSIFIER | USER")
    level_id: str = Field(default="L1")
    state: DetectionState = Field(
        default=DetectionState.DETECTED,
        description="DETECTED | CONFIRMED | REJECTED (semantic evidence gate)",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BlueprintImageMeta(BaseModel):
    """Normalised input description + the pixel->venue metre conversion."""

    filename: str = "blueprint"
    format: str = "png"
    page: int = 1
    pages: int = 1
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    deskew_deg: float = 0.0
    width_m: float = Field(gt=0, description="venue frame width in metres")
    height_m: float = Field(gt=0, description="venue frame height in metres")
    scale_m_per_px: float = Field(gt=0, description="metres per blueprint pixel")
    document_type: DocumentType = Field(default=DocumentType.UNKNOWN)
    document_type_confidence: float = Field(default=0.0, ge=0, le=1)
    document_type_reasons: List[str] = Field(default_factory=list)


class BlueprintDetectionResult(BaseModel):
    """Perception-stage output: everything the CV/OCR backends saw."""

    image: BlueprintImageMeta
    detections: List[Detection] = Field(default_factory=list)
    provider: str = Field(default="cv", description="which perception backends ran")
    warnings: List[str] = Field(default_factory=list)
    gemini_analysis: Optional[Dict[str, Any]] = Field(
        default=None, description="Gemini architectural interpretation (echoed back on /reconstruct)"
    )


class ElementReport(BaseModel):
    id: str
    kind: str
    confidence: float = Field(ge=0, le=1)
    source: str
    status: str = Field(
        default="ACCEPTED", description="ACCEPTED | REVIEW | REJECTED"
    )
    warning: Optional[str] = None


class CanonicalObjectModel(BaseModel):
    """One reconstructed object in the canonical 2D coordinate system (px).

    Every object keeps its provenance so the correspondence
    ``blueprint -> canonical 2D -> spatial 3D`` is auditable:
    ``GATE G12 (source bbox + canonical coord) == opening G12 == node G12``.
    """

    id: str
    kind: str  # FOOTPRINT | FIELD | SEATING | CONCOURSE | ROOM | WALL | GATE | STAIR | PATH | ZONE
    polygon_px: Optional[Polygon2D] = None
    position_px: Optional[Point2D] = None
    source_bbox: Optional[List[float]] = None  # original detection bbox (x0,y0,x1,y1)
    canonical_coordinate: Optional[Point2D] = None  # centroid in canonical px
    confidence: float = Field(ge=0, le=1)
    state: str = Field(default="CONFIRMED", description="CONFIRMED | REVIEW | REJECTED")
    label: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Canonical2DModel(BaseModel):
    """Canonical 2D reconstruction: the mandatory gate before any 3D.

    Represents the *validated* top-down map derived from the source blueprint
    (document type + footprint + confirmed objects, all in normalised pixels
    plus the single px -> metre transform). The 3D spatial model is derived
    from this map, never from raw detections directly.
    """

    venue_id: str = "BLUEPRINT_VENUE"
    document_type: DocumentType = DocumentType.UNKNOWN
    document_type_confidence: float = 0.0
    document_type_reasons: List[str] = Field(default_factory=list)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    meters_per_px: float = Field(gt=0)
    transform: Dict[str, Any] = Field(
        default_factory=lambda: {"scale": 1.0, "origin_px": [0.0, 0.0], "rotation_deg": 0.0}
    )
    footprint_px: Optional[Polygon2D] = None
    footprint_compactness: float = 0.0  # source-ink shape descriptor (4*pi*A/P^2)
    objects: List[CanonicalObjectModel] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReconstructionQuality(BaseModel):
    """Measured fidelity of the canonical 2D reconstruction to the source.

    ``pass`` (alias ``passed``) is the single gate the pipeline (and UI) must
    respect before a reconstruction may become the active venue / open a 3D
    Twin.
    """

    model_config = {"populate_by_name": True}

    document_type: str = "UNKNOWN"
    footprint_similarity: float = Field(ge=0, le=1)
    compactness_mismatch: float = Field(ge=0, le=1)
    field_present: bool = False
    region_coverage: float = Field(ge=0, le=1)
    gate_precision: float = Field(ge=0, le=1)
    gate_recall: float = Field(ge=0, le=1)
    path_coverage: float = Field(ge=0, le=1)
    scale_confidence: float = Field(ge=0, le=1)
    uncertain_count: int = 0
    passed: bool = Field(default=False, alias="pass")
    reasons: List[str] = Field(default_factory=list)


class ReconstructionReport(BaseModel):
    """Confidence + validation report for a reconstruction (uncertainty is explicit)."""

    summary: str
    overall_confidence: float = Field(ge=0, le=1)
    elements: List[ElementReport] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unresolved: List[str] = Field(default_factory=list)
    quality: Optional[ReconstructionQuality] = Field(default=None)


class BlueprintResult(BaseModel):
    venue: VenueModel
    spatial: Optional[VenueSpatialModel] = Field(
        default=None, description="reconstructed architectural model (may be absent on template fallback)"
    )
    elements: List[BlueprintElement] = Field(default_factory=list)
    detections: List[Detection] = Field(
        default_factory=list, description="raw perception detections (intermediate representation)"
    )
    image: Optional[BlueprintImageMeta] = Field(default=None)
    report: Optional[ReconstructionReport] = Field(default=None)
    confidence: float = Field(ge=0, le=1)
    degradation_level: int = Field(
        default=0, description="0=full CV+OCR, 1=CV only, 2=heuristic geometry, 3=template"
    )
    degraded: bool = False
    canonical2d: Optional[Canonical2DModel] = Field(
        default=None, description="validated canonical 2D reconstruction (gate before 3D)"
    )
    gemini_analysis: Optional[Dict[str, Any]] = Field(
        default=None, description="Gemini Vision architectural interpretation (structured JSON)"
    )
    architectural_scene: Optional[ArchitecturalScene] = Field(
        default=None, description="Authoritative architectural scene representation"
    )
    provider_status: Dict[str, str] = Field(
        default_factory=dict, description="per-provider status: ok | disabled | error:<reason>"
    )
    steps: Dict[str, str] = Field(
        default_factory=dict, description="per-stage outcome (stage -> status)"
    )
    notes: List[str] = Field(default_factory=list)


class CausalNode(BaseModel):
    id: str
    label: str
    value: str
    state: str = "NORMAL"  # NORMAL | WARNING | CRITICAL


class CausalLink(BaseModel):
    source: str
    target: str
    label: Optional[str] = None


class CausalGraph(BaseModel):
    nodes: List[CausalNode] = Field(default_factory=list)
    links: List[CausalLink] = Field(default_factory=list)


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
    causal_graph: Optional[CausalGraph] = None



ExternalState.model_rebuild()
