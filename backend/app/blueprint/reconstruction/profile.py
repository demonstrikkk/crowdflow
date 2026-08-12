"""StadiumProfile: authoritative procedural generation specification (Phase 5).

The StadiumProfile is constructed from an ArchitecturalScene (after fusion)
and encodes everything the procedural builder needs:

  - footprint shape & polygon
  - field polygon & center
  - seating bowls / tiers (each with inner/outer boundary + elevation)
  - concourses
  - circulation paths
  - gates / exits
  - facilities
  - vertical connections
  - roof strategy
  - structural style
  - provenance for every element

The profile does NOT contain Three.js geometry. It is a data specification
that the builder modules (bowl.py, concourse.py, etc.) transform into
VenueSpatialModel structures.
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ...models import Point2D, Polygon2D
from ..architecture.models import (
    ArchitecturalScene,
    ArchitecturalRegion,
    ArchitecturalOpening,
    ArchitecturalFacility,
    EntitySource,
    EntityType,
)


class FootprintShape(str, Enum):
    ELLIPSE = "ELLIPSE"
    OVAL = "OVAL"
    ROUNDED_RECTANGLE = "ROUNDED_RECTANGLE"
    CIRCLE = "CIRCLE"
    POLYGON = "POLYGON"
    IRREGULAR = "IRREGULAR"
    RECTANGLE = "RECTANGLE"


class StructuralStyle(str, Enum):
    BOWL = "BOWL"
    ARENA = "ARENA"
    OPEN_STADIUM = "OPEN_STADIUM"
    COVERED = "COVERED"
    UNKNOWN = "UNKNOWN"


class RoofStrategy(str, Enum):
    FULL = "FULL"           # full roof from blueprint
    PARTIAL = "PARTIAL"     # partial roof from blueprint
    PROCEDURAL = "PROCEDURAL"  # inferred procedural cantilever
    NONE = "NONE"           # no roof


class ProfileProvenance(BaseModel):
    source: EntitySource
    source_entity_id: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    derived_from: Optional[str] = None


class SeatingTierProfile(BaseModel):
    """One level of seating (lower, middle, upper, etc.)."""
    id: str
    name: str
    level_id: str
    inner_boundary: List[Tuple[float, float]]  # polygon in local metric
    outer_boundary: List[Tuple[float, float]]
    floor_elevation_m: float
    top_elevation_m: float
    row_count: int
    seat_depth_m: float = 0.85
    aisle_spacing_rows: int = 8
    capacity_estimate: Optional[int] = None
    curvature: float = 0.8  # 0 = straight, 1 = circular
    provenance: ProfileProvenance


class SeatingBowlProfile(BaseModel):
    """Complete seating bowl (one or more tiers)."""
    id: str
    label: Optional[str]
    tiers: List[SeatingTierProfile]
    field_facing: bool = True
    provenance: ProfileProvenance


class ConcourseProfile(BaseModel):
    id: str
    label: Optional[str]
    level_id: str
    polygon: List[Tuple[float, float]]  # local metric
    elevation_m: float
    is_ring: bool
    width_m: float = 8.0
    provenance: ProfileProvenance


class GateProfile(BaseModel):
    id: str
    label: Optional[str]
    type: str  # ENTRY_GATE | EXIT_GATE | EMERGENCY_EXIT | SERVICE_ENTRY
    level_id: str
    position: Tuple[float, float]  # local metric
    width_m: float
    rotation_deg: float
    capacity_ppm: float = 600.0   # people per minute
    is_emergency: bool = False
    connected_region_id: Optional[str] = None
    provenance: ProfileProvenance


class FacilityProfile(BaseModel):
    id: str
    label: Optional[str]
    type: str  # WASHROOM | CONCESSION | CAFETERIA | MEDICAL | VIP | MEDIA | SERVICE
    level_id: str
    position: Tuple[float, float]
    area_m2: float = 25.0
    provenance: ProfileProvenance


class VerticalConnectionProfile(BaseModel):
    id: str
    label: Optional[str]
    type: str  # STAIR | RAMP | ELEVATOR
    from_level_id: str
    to_level_id: str
    position: Tuple[float, float]
    width_m: float = 3.0
    provenance: ProfileProvenance


class StadiumProfile(BaseModel):
    """Full procedural specification for a stadium twin.

    Built from ArchitecturalScene; consumed by the builder modules.
    """
    venue_id: str
    stadium_type: str  # SOCCER | FOOTBALL | CRICKET | ATHLETICS | MULTI_PURPOSE | ARENA | UNKNOWN
    structural_style: StructuralStyle
    roof_strategy: RoofStrategy

    # Spatial anchors (local metric)
    footprint_shape: FootprintShape
    footprint_polygon: List[Tuple[float, float]]
    footprint_center: Tuple[float, float]
    footprint_width_m: float
    footprint_depth_m: float

    field_polygon: List[Tuple[float, float]]
    field_center: Tuple[float, float]
    field_width_m: float
    field_depth_m: float
    field_orientation_deg: float = 0.0

    # Spatial elements
    seating_bowls: List[SeatingBowlProfile] = Field(default_factory=list)
    concourses: List[ConcourseProfile] = Field(default_factory=list)
    gates: List[GateProfile] = Field(default_factory=list)
    emergency_exits: List[GateProfile] = Field(default_factory=list)
    facilities: List[FacilityProfile] = Field(default_factory=list)
    vertical_connections: List[VerticalConnectionProfile] = Field(default_factory=list)

    # Metadata
    level_ids: List[str] = Field(default_factory=list)
    scale_m_per_px: float = 1.0
    image_w_px: int = 1
    image_h_px: int = 1
    prompt_version: str = "unknown"
    provenance: ProfileProvenance

    metadata: Dict[str, Any] = Field(default_factory=dict)


def build_profile(
    scene: ArchitecturalScene,
    image_w_px: int,
    image_h_px: int,
    scale_m_per_px: float,
    venue_id: str = "BLUEPRINT_VENUE",
) -> StadiumProfile:
    """Build a StadiumProfile from an ArchitecturalScene.

    This is the authoritative conversion step between the AI perception layer
    and the procedural builder. All coordinates are converted to local metric.
    """
    w_m = image_w_px * scale_m_per_px
    h_m = image_h_px * scale_m_per_px

    def norm_to_metric(nx: float, ny: float) -> Tuple[float, float]:
        return (nx * w_m, ny * h_m)

    def bbox_to_polygon_metric(bbox) -> List[Tuple[float, float]]:
        """Convert (x0,y0,x1,y1) bbox to 4-point polygon in metric coords."""
        x0, y0, x1, y1 = bbox
        return [
            norm_to_metric(x0, y0),
            norm_to_metric(x1, y0),
            norm_to_metric(x1, y1),
            norm_to_metric(x0, y1),
        ]

    def entity_polygon(e) -> List[Tuple[float, float]]:
        """Extract a polygon for an entity (from evidence bbox or location)."""
        for ev in (e.evidence or []):
            if ev.bbox:
                return bbox_to_polygon_metric(ev.bbox)
        if e.location:
            # Point entity: generate a small square
            cx, cy = norm_to_metric(*e.location)
            s = 5.0
            return [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s)]
        # Fallback to full footprint center
        cx, cy = w_m / 2.0, h_m / 2.0
        return [(cx - 5, cy - 5), (cx + 5, cy - 5), (cx + 5, cy + 5), (cx - 5, cy + 5)]

    def polygon_center(poly: List[Tuple[float, float]]) -> Tuple[float, float]:
        if not poly:
            return (0.0, 0.0)
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        return (cx, cy)

    def polygon_extents(poly: List[Tuple[float, float]]) -> Tuple[float, float]:
        if not poly:
            return (1.0, 1.0)
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return (max(xs) - min(xs), max(ys) - min(ys))

    # ------------------------------------------------------------------ #
    # Footprint
    # ------------------------------------------------------------------ #
    footprint_poly = _make_footprint(scene, w_m, h_m, norm_to_metric)
    footprint_center = polygon_center(footprint_poly)
    fp_w, fp_d = polygon_extents(footprint_poly)

    # Footprint shape: derive from venue metadata
    shape_str = (scene.venue.overall_footprint_shape or "POLYGON").upper()
    shape = FootprintShape.POLYGON
    for fs in FootprintShape:
        if fs.value in shape_str:
            shape = fs
            break

    # ------------------------------------------------------------------ #
    # Field
    # ------------------------------------------------------------------ #
    field_regions = [r for r in scene.regions if r.type == EntityType.FIELD]
    if field_regions:
        field_poly = entity_polygon(field_regions[0])
    elif scene.venue.field_location:
        cx, cy = norm_to_metric(*scene.venue.field_location)
        fw = fp_w * 0.45
        fd = fp_d * 0.6
        field_poly = [(cx - fw/2, cy - fd/2), (cx + fw/2, cy - fd/2),
                      (cx + fw/2, cy + fd/2), (cx - fw/2, cy + fd/2)]
    else:
        # default: centered rectangle, 68×105m football field
        cx, cy = footprint_center
        field_poly = [(cx - 34, cy - 52.5), (cx + 34, cy - 52.5),
                      (cx + 34, cy + 52.5), (cx - 34, cy + 52.5)]

    field_center = polygon_center(field_poly)
    field_w, field_d = polygon_extents(field_poly)

    # ------------------------------------------------------------------ #
    # Seating bowls
    # ------------------------------------------------------------------ #
    seating_regions = [r for r in scene.regions if r.type in (EntityType.SEATING_BOWL, EntityType.SEATING_BLOCK)]
    bowls = _build_seating_bowls(seating_regions, scene.levels, entity_polygon, field_center)

    # ------------------------------------------------------------------ #
    # Concourses
    # ------------------------------------------------------------------ #
    concourse_regions = [r for r in scene.regions if r.type == EntityType.CONCOURSE]
    concourses = _build_concourses(concourse_regions, scene.levels, entity_polygon)

    # ------------------------------------------------------------------ #
    # Gates & emergency exits
    # ------------------------------------------------------------------ #
    gates, emergency_exits = _build_gates(
        scene.openings, w_m, h_m, norm_to_metric, image_w_px, image_h_px, scale_m_per_px
    )

    # ------------------------------------------------------------------ #
    # Facilities
    # ------------------------------------------------------------------ #
    facilities = _build_facilities(
        scene.facilities, concourses, norm_to_metric, scene.levels
    )

    # ------------------------------------------------------------------ #
    # Vertical connections
    # ------------------------------------------------------------------ #
    vert_conns = _build_vertical(scene.vertical_connections, scene.levels, norm_to_metric)

    # ------------------------------------------------------------------ #
    # Structural style
    # ------------------------------------------------------------------ #
    n_bowls = len(bowls)
    if n_bowls >= 2:
        style = StructuralStyle.BOWL
    elif n_bowls == 1:
        style = StructuralStyle.OPEN_STADIUM
    else:
        style = StructuralStyle.ARENA

    # Roof
    has_roof = any(r.type == EntityType.ROOF for r in scene.regions)
    roof_strategy = RoofStrategy.FULL if has_roof else RoofStrategy.PROCEDURAL

    return StadiumProfile(
        venue_id=venue_id,
        stadium_type=_infer_stadium_type(scene),
        structural_style=style,
        roof_strategy=roof_strategy,
        footprint_shape=shape,
        footprint_polygon=footprint_poly,
        footprint_center=footprint_center,
        footprint_width_m=round(fp_w, 2),
        footprint_depth_m=round(fp_d, 2),
        field_polygon=field_poly,
        field_center=field_center,
        field_width_m=round(field_w, 2),
        field_depth_m=round(field_d, 2),
        seating_bowls=bowls,
        concourses=concourses,
        gates=gates,
        emergency_exits=emergency_exits,
        facilities=facilities,
        vertical_connections=vert_conns,
        level_ids=[lv.id for lv in scene.levels],
        scale_m_per_px=round(scale_m_per_px, 6),
        image_w_px=image_w_px,
        image_h_px=image_h_px,
        provenance=ProfileProvenance(
            source=EntitySource.FUSED,
            confidence=round(scene.confidence, 3),
        ),
    )


# --------------------------------------------------------------------------- #
#  Private helpers
# --------------------------------------------------------------------------- #

def _make_footprint(
    scene: ArchitecturalScene,
    w_m: float,
    h_m: float,
    norm_to_metric,
) -> List[Tuple[float, float]]:
    """Build the outer stadium footprint polygon in metric coords."""
    # Try to find a venue footprint region in the scene
    footprint_region = next(
        (r for r in scene.regions if r.label and "footprint" in (r.label or "").lower()),
        None
    )
    if footprint_region and footprint_region.evidence:
        ev = footprint_region.evidence[0]
        if ev.bbox:
            x0, y0, x1, y1 = ev.bbox
            return [
                norm_to_metric(x0, y0), norm_to_metric(x1, y0),
                norm_to_metric(x1, y1), norm_to_metric(x0, y1),
            ]

    # Fallback: use the full image extent scaled 95% (5% margin)
    margin = 0.025
    return [
        (w_m * margin, h_m * margin), (w_m * (1 - margin), h_m * margin),
        (w_m * (1 - margin), h_m * (1 - margin)), (w_m * margin, h_m * (1 - margin)),
    ]


def _build_seating_bowls(
    regions: List[ArchitecturalRegion],
    levels,
    entity_polygon,
    field_center: Tuple[float, float],
) -> List[SeatingBowlProfile]:
    """Build seating bowl profiles from ArchitecturalRegion objects."""
    if not regions:
        return []

    # Group by level if possible
    level_groups: Dict[str, List] = {}
    for r in regions:
        lid = r.level_id or "L0"
        level_groups.setdefault(lid, []).append(r)

    bowls = []
    bowl_id_counter = 1
    for lid, level_regions in level_groups.items():
        tiers = []
        tier_counter = 1
        for r in level_regions:
            outer = entity_polygon(r)
            # Inner boundary: shrink polygon towards field_center by 30%
            inner = _shrink_polygon(outer, field_center, 0.30)

            # Elevation: look up from levels
            elev = 0.0
            for lv in levels:
                if lv.id == lid:
                    elev = lv.elevation_m
                    break

            tiers.append(SeatingTierProfile(
                id=f"TIER_{bowl_id_counter}_{tier_counter}",
                name=r.label or f"Tier {tier_counter}",
                level_id=lid,
                inner_boundary=inner,
                outer_boundary=outer,
                floor_elevation_m=elev,
                top_elevation_m=elev + 12.0,
                row_count=max(5, int(len(outer) * 2.5)),
                capacity_estimate=None,
                curvature=_estimate_curvature(outer),
                provenance=ProfileProvenance(
                    source=r.source,
                    source_entity_id=r.id,
                    confidence=r.confidence,
                ),
            ))
            tier_counter += 1

        bowls.append(SeatingBowlProfile(
            id=f"BOWL_{bowl_id_counter}",
            label=f"Seating Bowl {bowl_id_counter}",
            tiers=tiers,
            provenance=ProfileProvenance(
                source=EntitySource.FUSED,
                confidence=max((r.confidence for r in level_regions), default=0.5),
            ),
        ))
        bowl_id_counter += 1

    return bowls


def _build_concourses(
    regions: List[ArchitecturalRegion],
    levels,
    entity_polygon,
) -> List[ConcourseProfile]:
    results = []
    for i, r in enumerate(regions):
        poly = entity_polygon(r)
        cx = sum(p[0] for p in poly) / max(1, len(poly))
        cy = sum(p[1] for p in poly) / max(1, len(poly))
        extents = (
            max(p[0] for p in poly) - min(p[0] for p in poly),
            max(p[1] for p in poly) - min(p[1] for p in poly),
        )
        width_m = min(extents) * 0.5 or 8.0

        elev = 0.0
        for lv in levels:
            if lv.id == (r.level_id or "L0"):
                elev = lv.elevation_m
                break

        results.append(ConcourseProfile(
            id=r.id or f"CONCOURSE_{i + 1}",
            label=r.label,
            level_id=r.level_id or "L0",
            polygon=poly,
            elevation_m=elev,
            is_ring=_is_ring(poly),
            width_m=round(max(4.0, width_m), 2),
            provenance=ProfileProvenance(
                source=r.source,
                source_entity_id=r.id,
                confidence=r.confidence,
            ),
        ))
    return results


def _build_gates(
    openings: List[ArchitecturalOpening],
    w_m: float,
    h_m: float,
    norm_to_metric,
    image_w_px: int,
    image_h_px: int,
    scale_m_per_px: float,
) -> Tuple[List[GateProfile], List[GateProfile]]:
    gates = []
    emergency = []

    for o in openings:
        loc = o.location or (0.5, 0.5)
        pos = norm_to_metric(loc[0], loc[1])

        # Estimate width from evidence bbox if available
        width_m = 3.0
        for ev in o.evidence:
            if ev.bbox:
                bw = (ev.bbox[2] - ev.bbox[0]) * w_m
                bh = (ev.bbox[3] - ev.bbox[1]) * h_m
                width_m = round(max(2.0, min(bw, bh)), 2)
                break

        # Rotation: infer from position relative to footprint center
        rot = _infer_gate_rotation(pos, (w_m / 2.0, h_m / 2.0))

        gtype = _opening_type_str(o.type)
        is_em = o.type == EntityType.EMERGENCY_EXIT

        gp = GateProfile(
            id=o.id,
            label=o.label,
            type=gtype,
            level_id=o.level_id or "L0",
            position=pos,
            width_m=width_m,
            rotation_deg=rot,
            is_emergency=is_em,
            provenance=ProfileProvenance(
                source=o.source,
                source_entity_id=o.id,
                confidence=o.confidence,
            ),
        )

        if is_em:
            emergency.append(gp)
        else:
            gates.append(gp)

    return gates, emergency


def _build_facilities(
    facilities: List[ArchitecturalFacility],
    concourses: List[ConcourseProfile],
    norm_to_metric,
    levels,
) -> List[FacilityProfile]:
    result = []
    for fac in facilities:
        loc = fac.location or (0.5, 0.5)
        pos = norm_to_metric(loc[0], loc[1])

        # Find best concourse to assign to
        lid = fac.level_id or "L0"

        result.append(FacilityProfile(
            id=fac.id,
            label=fac.label,
            type=fac.type.value if hasattr(fac.type, "value") else str(fac.type),
            level_id=lid,
            position=pos,
            area_m2=25.0,
            provenance=ProfileProvenance(
                source=fac.source,
                source_entity_id=fac.id,
                confidence=fac.confidence,
            ),
        ))
    return result


def _build_vertical(
    vert_conns,
    levels,
    norm_to_metric,
) -> List[VerticalConnectionProfile]:
    result = []
    level_list = list(levels)
    for i, vc in enumerate(vert_conns):
        loc = vc.location or (0.5, 0.5)
        pos = norm_to_metric(loc[0], loc[1])

        lid = vc.level_id or "L0"
        # Find adjacent level
        level_ids_ordered = [lv.id for lv in level_list]
        try:
            idx = level_ids_ordered.index(lid)
        except ValueError:
            idx = 0
        to_level = level_ids_ordered[min(idx + 1, len(level_ids_ordered) - 1)]

        vtype = vc.type.value if hasattr(vc.type, "value") else str(vc.type)
        result.append(VerticalConnectionProfile(
            id=vc.id,
            label=vc.label,
            type=vtype,
            from_level_id=lid,
            to_level_id=to_level,
            position=pos,
            provenance=ProfileProvenance(
                source=vc.source,
                source_entity_id=vc.id,
                confidence=vc.confidence,
            ),
        ))
    return result


def _shrink_polygon(
    poly: List[Tuple[float, float]],
    center: Tuple[float, float],
    factor: float,
) -> List[Tuple[float, float]]:
    """Shrink polygon toward center by factor (0=no change, 1=collapse to center)."""
    result = []
    for x, y in poly:
        nx = x + (center[0] - x) * factor
        ny = y + (center[1] - y) * factor
        result.append((round(nx, 2), round(ny, 2)))
    return result


def _estimate_curvature(poly: List[Tuple[float, float]]) -> float:
    """Estimate how curved a polygon is (0=rectangle, 1=circle)."""
    if len(poly) <= 4:
        return 0.1
    if len(poly) >= 16:
        return 0.9
    return round(0.1 + (len(poly) - 4) / 20.0, 2)


def _is_ring(poly: List[Tuple[float, float]]) -> bool:
    """Heuristic: a concourse is a ring if it has 8+ points and is fairly compact."""
    if len(poly) < 8:
        return False
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w < 1 or h < 1:
        return False
    aspect = min(w, h) / max(w, h)
    return aspect > 0.6


def _infer_gate_rotation(
    gate_pos: Tuple[float, float],
    center: Tuple[float, float],
) -> float:
    dx = gate_pos[0] - center[0]
    dy = gate_pos[1] - center[1]
    angle = math.degrees(math.atan2(dy, dx))
    return round(angle % 360.0, 1)


def _opening_type_str(entity_type: EntityType) -> str:
    mapping = {
        EntityType.ENTRY: "ENTRY_GATE",
        EntityType.EXIT: "EXIT_GATE",
        EntityType.EMERGENCY_EXIT: "EMERGENCY_EXIT",
        EntityType.SERVICE_ENTRY: "SERVICE_ENTRY",
        EntityType.CHECKPOINT: "CHECKPOINT",
    }
    return mapping.get(entity_type, "ENTRY_GATE")


def _infer_stadium_type(scene: ArchitecturalScene) -> str:
    vt = (scene.document.venue_type or "UNKNOWN").upper()
    if "SOCCER" in vt or "FOOTBALL" in vt:
        return "SOCCER"
    if "CRICKET" in vt:
        return "CRICKET"
    if "ATHLETICS" in vt or "TRACK" in vt:
        return "ATHLETICS"
    if "ARENA" in vt or "BASKETBALL" in vt or "HOCKEY" in vt:
        return "ARENA"
    return "MULTI_PURPOSE"
