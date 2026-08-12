from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

class EntitySource(str, Enum):
    BLUEPRINT = "BLUEPRINT"
    GEMINI = "GEMINI"
    FLORENCE = "FLORENCE"
    CV = "CV"
    FUSED = "FUSED"
    PROCEDURAL = "PROCEDURAL"
    USER = "USER"

class EntityType(str, Enum):
    FIELD = "FIELD"
    SEATING_BOWL = "SEATING_BOWL"
    SEATING_BLOCK = "SEATING_BLOCK"
    CONCOURSE = "CONCOURSE"
    CORRIDOR = "CORRIDOR"
    AISLE = "AISLE"
    VOMITORY = "VOMITORY"
    STAIR = "STAIR"
    RAMP = "RAMP"
    ELEVATOR = "ELEVATOR"
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    SERVICE_ENTRY = "SERVICE_ENTRY"
    CHECKPOINT = "CHECKPOINT"
    CONCESSION = "CONCESSION"
    CAFETERIA = "CAFETERIA"
    WASHROOM = "WASHROOM"
    MEDICAL = "MEDICAL"
    VIP = "VIP"
    MEDIA = "MEDIA"
    SERVICE = "SERVICE"
    ROOM = "ROOM"
    WALL = "WALL"
    COLUMN = "COLUMN"
    ROOF = "ROOF"
    ZONE = "ZONE"

class Evidence(BaseModel):
    source: EntitySource
    confidence: float = Field(ge=0.0, le=1.0)
    description: Optional[str] = None
    bbox: Optional[Tuple[float, float, float, float]] = None

class ArchitecturalBase(BaseModel):
    id: str
    type: EntityType
    label: Optional[str] = None
    level_id: Optional[str] = None
    location: Optional[Tuple[float, float]] = None  # (x, y)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: EntitySource
    evidence: List[Evidence] = Field(default_factory=list)

class ArchitecturalDocument(BaseModel):
    drawing_type: str
    projection: str
    venue_type: str
    floor_or_level: Optional[str] = None
    orientation: Optional[str] = None
    image_quality: str
    confidence: float = Field(ge=0.0, le=1.0)

class ArchitecturalVenue(BaseModel):
    overall_footprint_shape: Optional[str] = None
    stadium_center: Optional[Tuple[float, float]] = None
    stadium_orientation: Optional[str] = None
    field_location: Optional[Tuple[float, float]] = None
    field_shape: Optional[str] = None
    field_dimensions: Optional[Tuple[float, float]] = None

class ArchitecturalLevel(BaseModel):
    id: str
    name: str
    elevation_m: float = 0.0
    floor_height_m: float = 5.0
    is_inferred: bool = False

class ArchitecturalRegion(ArchitecturalBase):
    pass

class ArchitecturalOpening(ArchitecturalBase):
    pass

class ArchitecturalFacility(ArchitecturalBase):
    pass

class VerticalConnection(ArchitecturalBase):
    pass

class ArchitecturalRelationship(BaseModel):
    source_id: str
    relation: str  # CONTAINS, ADJACENT_TO, CONNECTS_TO, ABOVE, BELOW, ENTERS, EXITS_TO, SERVES, ACCESSIBLE_FROM, LEADS_TO
    target_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

class ScaleEvidence(BaseModel):
    scale_source: str
    scale_confidence: float = Field(ge=0.0, le=1.0)
    meters_per_px: Optional[float] = None

class ArchitecturalUncertainty(BaseModel):
    element_id: Optional[str] = None
    description: str
    severity: str  # LOW, MEDIUM, HIGH

class ArchitecturalScene(BaseModel):
    document: ArchitecturalDocument
    venue: ArchitecturalVenue
    levels: List[ArchitecturalLevel] = Field(default_factory=list)
    regions: List[ArchitecturalRegion] = Field(default_factory=list)
    openings: List[ArchitecturalOpening] = Field(default_factory=list)
    facilities: List[ArchitecturalFacility] = Field(default_factory=list)
    vertical_connections: List[VerticalConnection] = Field(default_factory=list)
    relationships: List[ArchitecturalRelationship] = Field(default_factory=list)
    scale: Optional[ScaleEvidence] = None
    uncertainties: List[ArchitecturalUncertainty] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
