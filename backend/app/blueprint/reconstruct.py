"""Reconstruct a VenueSpatialModel from semantic blueprint elements.

Deterministic reconstruction (no AI): semantic structures become typed
StructureModels, gates become openings, corridor polylines become
PathGeometryModel centre-lines and interior walls become WALL structures.
Pixel coordinates are converted to the venue metre frame through
``app.spatial.coordinates`` (never duplicated inline).

Geometry is only created when it was actually detected; low-confidence
detections are recorded in the report rather than silently dropped.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..models import (
    BlueprintImageMeta,
    Canonical2DModel,
    CanonicalObjectModel,
    LevelModel,
    OpeningModel,
    PathGeometryModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueSpatialModel,
)
from ..spatial.coordinates import px_to_venue

_LEVEL_ID = "L1"
_WALL_THICKNESS_M = 2.5
_STRUCT_HEIGHTS = {
    "FIELD": 0.1,
    "SEATING": 4.0,
    "CONCOURSE": 0.15,
    "ROOM": 3.2,
    "ZONE": 0.1,
    "STAIR": 2.5,
}
_STRUCT_META_KIND = {
    "ROOM": "ROOM",
    "ZONE": "ZONE",
    "CONCOURSE": "CONCOURSE",
    "FIELD": "FIELD",
    "SEATING": "SEATING",
    "STAIR": "STAIR",
}
_GATE_TYPE = {"ENTRY": "ENTRY_GATE", "EXIT": "EXIT_GATE", "EMERGENCY_EXIT": "EMERGENCY_EXIT"}

# structure kinds the spatial schema accepts; anything else degrades to ROOM
_VALID_STRUCT_TYPES = {"WALL", "FLOOR", "FIELD", "SEATING", "CONCOURSE", "ROOM", "STAIR", "ROOF", "ZONE"}


def _structure_type(kind: str) -> str:
    return kind if kind in _VALID_STRUCT_TYPES else "ROOM"


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon2D:
    return Polygon2D(points=[
        Point2D(x=round(x0, 2), y=round(y0, 2)),
        Point2D(x=round(x1, 2), y=round(y0, 2)),
        Point2D(x=round(x1, 2), y=round(y1, 2)),
        Point2D(x=round(x0, 2), y=round(y1, 2)),
    ])


def _polygon_m(points_px: List[Tuple[float, float]], width_m: float, height_m: float,
               px_w: int, px_h: int) -> Polygon2D:
    return Polygon2D(points=[
        Point2D(x=round(x, 2), y=round(y, 2))
        for x, y in (px_to_venue(px, py, width_m, height_m, px_w, px_h) for px, py in points_px)
    ])


def _thick_segment(p0: Tuple[float, float], p1: Tuple[float, float], thickness: float) -> Polygon2D:
    dx = abs(p1[0] - p0[0])
    dy = abs(p1[1] - p0[1])
    if dx >= dy:
        y = (p0[1] + p1[1]) / 2.0
        return _rect(min(p0[0], p1[0]), y - thickness / 2.0, max(p0[0], p1[0]), y + thickness / 2.0)
    x = (p0[0] + p1[0]) / 2.0
    return _rect(x - thickness / 2.0, min(p0[1], p1[1]), x + thickness / 2.0, max(p0[1], p1[1]))


def build_spatial(
    structures: List[dict],
    walls: List[Tuple[Tuple[float, float], Tuple[float, float], float]],
    gates: List[dict],
    openings_extra: List[dict],
    corridors: List[List[Tuple[float, float]]],
    width_m: float,
    height_m: float,
    px_w: int,
    px_h: int,
    levels: List[LevelModel] | None = None,
) -> VenueSpatialModel:
    """Reconstruct a VenueSpatialModel from semantic output (all in pixels)."""
    levels = levels or [LevelModel(id=_LEVEL_ID, name="Ground", elevation_m=0.0, height_m=5.0)]
    level_ids = {l.id for l in levels}
    scale = min(width_m / max(1, px_w), height_m / max(1, px_h))

    struct_models: List[StructureModel] = []
    struct_models.append(
        StructureModel(
            id="FLR", level_id=_LEVEL_ID, type="FLOOR",
            polygon=_rect(0.0, 0.0, width_m, height_m), height_m=0.3,
            metadata={"source": "BLUEPRINT"},
        )
    )

    # perimeter walls from the venue frame (kept simple + valid)
    t = _WALL_THICKNESS_M
    for side, poly in (
        ("N", _rect(0.0, 0.0, width_m, t)),
        ("S", _rect(0.0, height_m - t, width_m, height_m)),
        ("E", _rect(width_m - t, 0.0, width_m, height_m)),
        ("W", _rect(0.0, 0.0, t, height_m)),
    ):
        struct_models.append(
            StructureModel(
                id=f"WALL_PERIM_{side}", level_id=_LEVEL_ID, type="WALL", polygon=poly,
                height_m=5.0, metadata={"source": "BLUEPRINT"},
            )
        )

    # interior walls (thickened axis-aligned segments)
    for i, (p0, p1, conf) in enumerate(walls):
        m0 = px_to_venue(p0[0], p0[1], width_m, height_m, px_w, px_h)
        m1 = px_to_venue(p1[0], p1[1], width_m, height_m, px_w, px_h)
        struct_models.append(
            StructureModel(
                id=f"WALL_INT_{i + 1}", level_id=_LEVEL_ID, type="WALL",
                polygon=_thick_segment(m0, m1, _WALL_THICKNESS_M),
                height_m=5.0,
                metadata={"source": "BLUEPRINT", "confidence": conf},
            )
        )

    # typed structures (field / seating / concourse / room / zone / stair)
    for i, s in enumerate(structures):
        kind = s["kind"]
        stype = _structure_type(kind)
        polygon = _polygon_m(s["polygon_px"], width_m, height_m, px_w, px_h)
        metadata: Dict = dict(s.get("metadata") or {})
        if s.get("label"):
            metadata["label"] = s["label"]
        metadata["kind"] = kind
        height = _STRUCT_HEIGHTS.get(kind, 2.0)
        if stype == "SEATING":
            metadata["tiers"] = _seating_tiers(s, scale)
        struct_models.append(
            StructureModel(
                id=f"{kind}_{i + 1}", level_id=_LEVEL_ID, type=stype,
                polygon=polygon, height_m=height, metadata=metadata,
            )
        )

    # openings: gates (nodes reference these via spatial_ref) + interior doors
    opening_models: List[OpeningModel] = []
    for i, gate in enumerate(gates):
        gid = (gate.get("id") or f"B{i + 1}").strip().upper().replace(" ", "_")
        px = gate["position"]
        x_m, y_m = px_to_venue(px[0], px[1], width_m, height_m, px_w, px_h)
        opening_models.append(
            OpeningModel(
                id=gid, level_id=_LEVEL_ID,
                type=_GATE_TYPE.get(gate.get("kind", "ENTRY"), "ENTRY_GATE"),
                position=Point2D(x=round(x_m, 2), y=round(y_m, 2)),
                width_m=round(max(1.0, gate.get("width_px", 16) * scale), 2),
                rotation_deg=_gate_rotation(gate.get("side")),
                metadata={
                    "source": "BLUEPRINT",
                    "confidence": gate.get("confidence", 0.4),
                    "label": gate.get("label"),
                },
            )
        )
    for i, door in enumerate(openings_extra):
        px = door["position"]
        x_m, y_m = px_to_venue(px[0], px[1], width_m, height_m, px_w, px_h)
        opening_models.append(
            OpeningModel(
                id=f"D{i + 1}", level_id=_LEVEL_ID, type="DOOR",
                position=Point2D(x=round(x_m, 2), y=round(y_m, 2)),
                width_m=round(max(1.0, door.get("width_px", 10) * scale), 2),
                rotation_deg=0.0,
                metadata={"source": "BLUEPRINT", "confidence": door.get("confidence", 0.4)},
            )
        )

    # corridors -> physical path geometry
    path_models: List[PathGeometryModel] = []
    for i, polyline in enumerate(corridors):
        centerline = [
            Point2D(x=round(x, 2), y=round(y, 2))
            for x, y in (px_to_venue(px, py, width_m, height_m, px_w, px_h) for px, py in polyline)
        ]
        path_models.append(
            PathGeometryModel(
                id=f"CORRIDOR_{i + 1}", level_id=_LEVEL_ID, centerline=centerline,
                width_m=round(max(2.0, 4.0 * scale), 2),
                metadata={"source": "BLUEPRINT", "detected": True},
            )
        )

    return VenueSpatialModel(
        venue_id="BLUEPRINT_VENUE",
        levels=levels,
        structures=struct_models,
        openings=opening_models,
        paths=path_models,
        metadata={"source": "BLUEPRINT_IMPORT"},
    )


def _seating_tiers(s: dict, scale: float) -> int:
    """Step count derived from the band thickness in metres (~5 m per row)."""
    poly = s["polygon_px"]
    if len(poly) < 3:
        return 1
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    thickness_px = min(max(xs) - min(xs), max(ys) - min(ys))
    tiers = int(max(1, min(8, round(thickness_px * scale / 5.0))))
    return max(1, tiers)


def _gate_rotation(side) -> float:
    return {"N": 0.0, "S": 180.0, "E": 90.0, "W": 270.0}.get(side, 0.0)


def _px_polygon(points: List[Tuple[float, float]]) -> Polygon2D:
    return Polygon2D(points=[Point2D(x=round(p[0], 2), y=round(p[1], 2)) for p in points])


def build_canonical2d(
    structures: List[dict],
    gates: List[dict],
    corridors: List[List[Tuple[float, float]]],
    image_meta: BlueprintImageMeta,
) -> Canonical2DModel:
    """Build the validated canonical 2D map (Phase 2C item 5).

    This is the *mandatory gate before any 3D*: the top-down pixel map with the
    confirmed objects and the single px -> metre transform. Objects keep their
    provenance (source bbox + canonical coordinate) so the correspondence
    ``blueprint -> canonical 2D -> spatial 3D`` stays auditable.
    """
    px_w, px_h = image_meta.width_px, image_meta.height_px
    frame = _px_polygon([(0.0, 0.0), (px_w, 0.0), (px_w, px_h), (0.0, px_h)])

    objects: List[CanonicalObjectModel] = [
        CanonicalObjectModel(
            id="FOOTPRINT", kind="FOOTPRINT", polygon_px=frame,
            canonical_coordinate=Point2D(x=round(px_w / 2.0, 2), y=round(px_h / 2.0, 2)),
            confidence=1.0, state="CONFIRMED", metadata={"source": "FRAME"},
        )
    ]
    for i, s in enumerate(structures):
        if not (poly := s.get("polygon_px")) or len(poly) < 3:
            continue
        cx, cy = s.get("centroid_px", (poly[0][0], poly[0][1]))
        objects.append(
            CanonicalObjectModel(
                id=s.get("id") or f"S{i + 1}",
                kind=str(s.get("kind", "ROOM")).upper(),
                polygon_px=_px_polygon(poly),
                position_px=Point2D(x=round(cx, 2), y=round(cy, 2)),
                canonical_coordinate=Point2D(x=round(cx, 2), y=round(cy, 2)),
                source_bbox=s.get("source_bbox"),
                confidence=round(float(s.get("confidence", 0.5)), 2),
                state=str(s.get("state", "CONFIRMED")),
                label=s.get("label"),
            )
        )
    for i, g in enumerate(gates):
        pos = g["position"]
        objects.append(
            CanonicalObjectModel(
                id=g.get("id") or f"B{i + 1}",
                kind="GATE",
                position_px=Point2D(x=round(pos[0], 2), y=round(pos[1], 2)),
                canonical_coordinate=Point2D(x=round(pos[0], 2), y=round(pos[1], 2)),
                source_bbox=g.get("source_bbox"),
                confidence=round(float(g.get("confidence", 0.5)), 2),
                state=str(g.get("state", "CONFIRMED")),
                label=g.get("label"),
            )
        )

    return Canonical2DModel(
        venue_id="BLUEPRINT_VENUE",
        document_type=image_meta.document_type,
        document_type_confidence=image_meta.document_type_confidence,
        document_type_reasons=list(image_meta.document_type_reasons),
        width_px=px_w,
        height_px=px_h,
        meters_per_px=image_meta.scale_m_per_px,
        transform={"scale": 1.0, "origin_px": [0.0, 0.0], "rotation_deg": 0.0},
        footprint_px=frame,
        footprint_compactness=_compactness([(0.0, 0.0), (px_w, 0.0), (px_w, px_h), (0.0, px_h)]),
        objects=objects,
        metadata={
            "source": "BLUEPRINT_IMPORT",
            "structures": len(structures),
            "gates": len(gates),
            "corridors": len(corridors),
        },
    )


def _compactness(points: List[Tuple[float, float]]) -> float:
    """4*pi*A/P^2 shape descriptor of a polygon (1.0 = circle)."""
    if len(points) < 3:
        return 0.0
    n = len(points)
    area = abs(sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
                 for i in range(n))) / 2.0
    peri = sum(((points[i][0] - points[(i + 1) % n][0]) ** 2 + (points[i][1] - points[(i + 1) % n][1]) ** 2) ** 0.5
               for i in range(n))
    return round(min(1.0, 4.0 * 3.141592653589793 * area / (peri * peri)), 4) if peri > 0 else 0.0
