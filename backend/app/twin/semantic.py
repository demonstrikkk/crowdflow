"""Semantic venue model — the bridge between AI/GLB output and the simulation.

The Colab worker / local reconstruction produces:

    venue.glb                    visual 3D model
    semantic.json                semantic venue description + bindings
    generation.metadata.json     provenance / model / timing

This module owns the contract and the conversion into the existing CrowdFlow
models:

    AI semantic output  ->  VenueSpatialModel  ->  VenueModel  ->  simulation

The VenueModel stays authoritative for movement. The GLB is a render artifact
whose nodes are named after semantic ids so the frontend can bind
``click Gate A in 3D -> simulation node -> live metrics``.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from ..blueprint.navigation import build_venue_from_spatial
from ..models import (
    LevelModel, NodeType, OpeningModel, PathGeometryModel, Point2D,
    Polygon2D, StructureModel, VenueModel, VenueSpatialModel,
)
from ..storage import storage
from .glb import GlbMesh, write_glb
from .schemas import TwinArtifact, TwinBinding

# Openings carry capacity in ``metadata.capacity_ppm``; mirrors navigation.py.
_DEFAULT_CAPACITY_PPM = 120.0

_OPENING_COLOR = {
    "ENTRY_GATE": (0.36, 0.78, 0.42),
    "EXIT_GATE": (0.36, 0.6, 0.95),
    "EMERGENCY_EXIT": (0.9, 0.3, 0.26),
    "DOOR": (0.75, 0.65, 0.45),
    "SERVICE_ENTRY": (0.85, 0.72, 0.35),
}

_STRUCTURE_COLOR = {
    "FLOOR": (0.24, 0.26, 0.30),
    "WALL": (0.42, 0.46, 0.53),
    "FIELD": (0.30, 0.52, 0.36),
    "SEATING": (0.62, 0.24, 0.26),
    "CONCOURSE": (0.35, 0.38, 0.44),
    "ROOM": (0.45, 0.36, 0.28),
    "STAIR": (0.55, 0.5, 0.47),
    "ROOF": (0.3, 0.32, 0.38),
    "ZONE": (0.4, 0.42, 0.48),
}

_STRUCTURE_HEIGHT = {
    "FLOOR": 0.3, "WALL": 3.0, "FIELD": 0.15, "SEATING": 1.6,
    "CONCOURSE": 0.25, "ROOM": 3.0, "STAIR": 0.5, "ROOF": 0.5, "ZONE": 0.2,
}


def _to_world(x: float, y: float, width: float, height: float) -> Tuple[float, float, float]:
    """Venue metres -> GLB world frame (matches the frontend twin renderer)."""
    return (x - width / 2.0, 0.0, -(y - height / 2.0))


def _level_elevation(spatial: VenueSpatialModel, level_id: str) -> float:
    for lv in spatial.levels:
        if lv.id == level_id:
            return lv.elevation_m
    return 0.0


# --------------------------------------------------------------------------- #
#  GLB generation from the spatial model
# --------------------------------------------------------------------------- #
def build_venue_glb(venue: VenueModel, spatial: VenueSpatialModel) -> bytes:
    """Produce ``venue.glb`` bytes from the semantic/spatial venue model."""
    width, height = venue.width, venue.height
    meshes: List[GlbMesh] = []

    has_floor = any(s.type == "FLOOR" for s in spatial.structures)
    if not has_floor:
        ground = GlbMesh("Structure_GROUND", (0.22, 0.24, 0.28))
        ground.add_box(0, -0.15, 0, width * 1.4, 0.3, height * 1.4)
        meshes.append(ground)

    for s in spatial.structures:
        elev = _level_elevation(spatial, s.level_id)
        color = _STRUCTURE_COLOR.get(s.type, (0.4, 0.42, 0.48))
        h = s.height_m or _STRUCTURE_HEIGHT.get(s.type, 1.0)
        mesh = GlbMesh(f"Structure_{s.id}", color)
        pts = [(p.x, p.y) for p in s.polygon.points]
        wpts = []
        for (px, py) in pts:
            wx, _, wz = _to_world(px, py, width, height)
            wpts.append((wx, wz))
        mesh.add_prism(wpts, elev, max(elev + 0.05, elev + h))
        meshes.append(mesh)

    for o in spatial.openings:
        color = _OPENING_COLOR.get(o.type, (0.75, 0.65, 0.45))
        mesh = GlbMesh(f"Opening_{o.id}", color)
        elev = _level_elevation(spatial, o.level_id)
        wx, _, wz = _to_world(o.position.x, o.position.y, width, height)
        w = max(1.0, o.width_m or 2.0)
        rot = math.radians(o.rotation_deg or 0)
        sin, cos = math.sin(rot), math.cos(rot)
        half = w / 2
        # two posts + lintel, aligned with the opening's rotation
        for sgn in (-1.0, 1.0):
            px = wx + sgn * half * cos
            pz = wz + sgn * half * sin
            mesh.add_box(px, elev + 1.6, pz, 0.25, 3.2, 0.25)
        mesh.add_box(wx, elev + 3.2, wz, w + 0.3, 0.25, 0.4)
        mesh.add_box(wx, elev + 0.15, wz, w, 0.25, 0.4)
        meshes.append(mesh)

    for p in spatial.paths:
        if len(p.centerline) < 2:
            continue
        elev = _level_elevation(spatial, p.level_id)
        mesh = GlbMesh(f"Path_{p.id}", (0.55, 0.58, 0.64))
        wpts = []
        for pt in p.centerline:
            wx, _, wz = _to_world(pt.x, pt.y, width, height)
            wpts.append((wx, wz))
        mesh.add_quad_strip(wpts, elev + 0.12, (p.width_m or 3.0) / 2.0)
        meshes.append(mesh)

    return write_glb(meshes)


# --------------------------------------------------------------------------- #
#  Worker output contract (semantic.json)
# --------------------------------------------------------------------------- #
def build_semantic_output(
    venue: VenueModel,
    spatial: VenueSpatialModel,
    source: str,
    model: str,
    notes: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[TwinBinding]]:
    """Build the semantic.json contract + GLB<->sim bindings for a venue."""
    gates = []
    exits = []
    emergency = []
    for o in spatial.openings:
        item = {
            "id": o.id,
            "label": o.id.replace("_", " ").title(),
            "type": o.type,
            "position": {"x": o.position.x, "y": o.position.y},
            "width_m": o.width_m,
            "capacity": float(o.metadata.get("capacity_ppm", _DEFAULT_CAPACITY_PPM))
            if o.metadata else _DEFAULT_CAPACITY_PPM,
        }
        if o.type == "ENTRY_GATE":
            gates.append(item)
        elif o.type == "EXIT_GATE":
            exits.append(item)
        elif o.type == "EMERGENCY_EXIT":
            emergency.append(item)

    bindings = [
        TwinBinding(
            semantic_id=o.id,
            type=o.type,
            label=o.id.replace("_", " ").title(),
            mesh_reference=f"Opening_{o.id}",
            world_position={"x": o.position.x, "y": o.position.y},
            simulation_node=o.id,
        )
        for o in spatial.openings
    ]

    semantic = {
        "schema": "crowdflow.twin.semantic.v1",
        "venue": {
            "id": venue.id,
            "name": venue.name,
            "type": "stadium" if "stadium" in venue.name.lower() else "venue",
            "width_m": venue.width,
            "height_m": venue.height,
        },
        "levels": [
            {"id": lv.id, "name": lv.name, "elevation_m": lv.elevation_m, "height_m": lv.height_m}
            for lv in spatial.levels
        ],
        "structures": [
            {
                "id": s.id, "type": s.type, "level_id": s.level_id,
                "polygon": {"points": [{"x": p.x, "y": p.y} for p in s.polygon.points]},
                "height_m": s.height_m,
            }
            for s in spatial.structures
        ],
        "gates": gates,
        "exits": exits,
        "emergency_exits": emergency,
        "zones": [n.id for n in venue.nodes if n.type == NodeType.ZONE],
        "paths": [
            {
                "id": p.id, "level_id": p.level_id,
                "centerline": [{"x": pt.x, "y": pt.y} for pt in p.centerline],
                "width_m": p.width_m,
            }
            for p in spatial.paths
        ],
        "navigation": {
            "nodes": [
                {"id": n.id, "type": n.type.value, "position": {"x": n.position.x, "y": n.position.y}}
                for n in venue.nodes
            ],
            "edges": [
                {"id": e.id, "source": e.source, "destination": e.destination,
                 "capacity": e.capacity, "is_emergency": e.is_emergency}
                for e in venue.edges
            ],
        },
        "bindings": [b.model_dump() for b in bindings],
        "metadata": {
            "source": source,
            "model": model,
            "notes": notes or [],
        },
    }
    return semantic, bindings


# --------------------------------------------------------------------------- #
#  Semantic -> CrowdFlow venue document (with validation guarantees)
# --------------------------------------------------------------------------- #
def _clean_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(value)).upper()
    return cleaned if cleaned else "ELEMENT"


def semantic_to_venue_document(
    semantic: Dict[str, Any],
    venue_id: str,
    width: float,
    height: float,
) -> Tuple[VenueModel, VenueSpatialModel, List[str]]:
    """Convert a semantic.json payload into a validated CrowdFlow venue.

    Returns ``(venue, spatial, notes)``. The returned models already satisfy
    the hard ``VenueModel._validate_graph`` gate (>=1 ENTRY, >=1 EXIT,
    fully connected) because ``build_venue_from_spatial`` guarantees it and
    this function adds synthetic entry/exit openings when a semantic payload
    omits them.
    """
    notes: List[str] = []
    levels: List[LevelModel] = []
    for lv in semantic.get("levels", []):
        levels.append(LevelModel(
            id=_clean_id(lv.get("id", "L0")),
            name=str(lv.get("name", "Ground")),
            elevation_m=float(lv.get("elevation_m", 0.0)),
            height_m=float(lv.get("height_m", 5.0)),
        ))
    if not levels:
        levels.append(LevelModel(id="L0", name="Ground", elevation_m=0.0, height_m=5.0))

    structures: List[StructureModel] = []
    for s in semantic.get("structures", []):
        try:
            points = [Point2D(x=float(p["x"]), y=float(p["y"])) for p in s["polygon"]["points"]]
        except (KeyError, TypeError, ValueError):
            notes.append(f"structure '{s.get('id')}' ignored: invalid polygon")
            continue
        structures.append(StructureModel(
            id=_clean_id(s.get("id", "STRUCT")),
            level_id=_clean_id(s.get("level_id", levels[0].id)),
            type=str(s.get("type", "ROOM")).upper(),
            polygon=Polygon2D(points=points),
            height_m=float(s.get("height_m", _STRUCTURE_HEIGHT.get(str(s.get("type", "")).upper(), 1.0))),
        ))

    openings: List[OpeningModel] = []
    gate_sources = (
        [("ENTRY_GATE", g) for g in semantic.get("gates", [])]
        + [("EXIT_GATE", x) for x in semantic.get("exits", [])]
        + [("EMERGENCY_EXIT", e) for e in semantic.get("emergency_exits", [])]
        + [("DOOR", d) for d in semantic.get("doors", [])]
        + [("ENTRY_GATE", o) for o in semantic.get("openings", [])]
    )
    for otype, o in gate_sources:
        if not isinstance(o, dict):
            continue
        try:
            px = float(o["position"]["x"])
            py = float(o["position"]["y"])
        except (KeyError, TypeError, ValueError):
            notes.append(f"opening '{o.get('id')}' ignored: missing position")
            continue
        openings.append(OpeningModel(
            id=_clean_id(o.get("id", "OPENING")),
            level_id=_clean_id(o.get("level_id", levels[0].id)),
            type=otype,
            position=Point2D(x=px, y=py),
            width_m=float(o.get("width_m", 2.0)),
            metadata={
                "capacity_ppm": float(o.get("capacity", _DEFAULT_CAPACITY_PPM)),
                "source": "AI_TWIN",
            },
        ))

    paths: List[PathGeometryModel] = []
    for p in semantic.get("paths", []):
        try:
            center = [Point2D(x=float(pt["x"]), y=float(pt["y"])) for pt in p["centerline"]]
        except (KeyError, TypeError, ValueError):
            continue
        if len(center) < 2:
            continue
        paths.append(PathGeometryModel(
            id=_clean_id(p.get("id", "PATH")),
            level_id=_clean_id(p.get("level_id", levels[0].id)),
            centerline=center,
            width_m=float(p.get("width_m", 3.0)),
        ))

    # ---- guarantee >=1 ENTRY and >=1 EXIT (hard validation gate) ----------
    has_entry = any(o.type == "ENTRY_GATE" for o in openings)
    has_exit = any(o.type in ("EXIT_GATE", "EMERGENCY_EXIT") for o in openings)
    if not has_entry:
        openings.append(OpeningModel(
            id="GATE_SYNTH_ENTRY", level_id=levels[0].id, type="ENTRY_GATE",
            position=Point2D(x=10.0, y=10.0), width_m=6.0,
            metadata={"capacity_ppm": _DEFAULT_CAPACITY_PPM, "source": "SYNTHETIC"},
        ))
        notes.append("semantic payload had no entry gate; synthetic ENTRY added")
    if not has_exit:
        openings.append(OpeningModel(
            id="GATE_SYNTH_EXIT", level_id=levels[0].id, type="EXIT_GATE",
            position=Point2D(x=width - 10.0, y=height - 10.0), width_m=6.0,
            metadata={"capacity_ppm": _DEFAULT_CAPACITY_PPM, "source": "SYNTHETIC"},
        ))
        notes.append("semantic payload had no exit; synthetic EXIT added")

    spatial = VenueSpatialModel(
        venue_id=venue_id,
        levels=levels,
        structures=structures,
        openings=openings,
        paths=paths,
        metadata={"source": "AI_TWIN", "generation": semantic.get("schema")},
    )
    venue, nav_notes = build_venue_from_spatial(spatial, width, height)
    notes.extend(nav_notes)
    if venue.id != venue_id:
        venue.id = venue_id
    venue.name = str(semantic.get("venue", {}).get("name", "Generated Venue"))
    return venue, spatial, notes


# --------------------------------------------------------------------------- #
#  Job finalisation: save venue + clone a default scenario for the twin
# --------------------------------------------------------------------------- #
def register_twin_venue(
    job: Any,
    venue: VenueModel,
    spatial: VenueSpatialModel,
    notes: List[str],
    provenance: str,
) -> None:
    """Persist the generated venue + a runnable scenario, then bind job state."""
    venue.metadata["twin"] = {
        "job_id": job.id,
        "provenance": provenance,
        "provider": job.provider,
        "model": job.model,
        "glb": "venue.glb",
    }
    storage.save_venue_document(
        venue=venue,
        spatial=spatial,
        report=None,
        reconstruction_version=f"twin-{provenance.lower()}-v1",
    )

    scenario = _build_twin_scenario(job, venue)
    if scenario is not None:
        storage.save_scenario(scenario)
        job.metadata["scenario_id"] = scenario.id

    job.venue_id = venue.id
    job.metadata["venue_name"] = venue.name
    job.metadata["venue_width"] = venue.width
    job.metadata["venue_height"] = venue.height
    job.metadata["notes"] = notes
    job.metadata["provenance"] = provenance


def _build_twin_scenario(job: Any, venue: VenueModel) -> Optional[Any]:
    """Build a scenario whose distributions reference the generated venue.

    Distributions are derived from the actual venue nodes so the simulation
    engine never routes towards a missing node id.
    """
    from ..models import ScenarioModel

    entries = [n.id for n in venue.nodes if n.type == NodeType.ENTRY]
    exits = [n.id for n in venue.nodes if n.type in (NodeType.EXIT, NodeType.EMERGENCY_EXIT)]
    zones = [n.id for n in venue.nodes if n.type == NodeType.ZONE]
    if not zones:
        zones = [n.id for n in venue.nodes if n.type not in (NodeType.ENTRY, NodeType.EXIT, NodeType.EMERGENCY_EXIT)]
    if not entries or not exits:
        raise ValueError("generated venue has no entry or exit nodes; cannot build scenario")

    equal = lambda keys: {k: round(1.0 / len(keys), 6) for k in keys}  # noqa: E731
    crowd = int(job.metadata.get("crowd_size", 5000))

    # prefer the default seeded scenario for phases/conditions, else a generic one
    base = None
    for sc in storage.list_scenarios():
        if sc.special and sc.special.get("default") is True:
            base = sc
            break
    if base is None and storage.list_scenarios():
        base = storage.list_scenarios()[0]

    if base is not None:
        scenario = base.model_copy(deep=True)
        scenario.id = f"scenario_twin_{job.id.lower()}"
        scenario.name = f"{venue.name} · Default Event"
        scenario.venue_id = venue.id
        scenario.crowd_size = crowd
        scenario.gate_distribution = equal(entries)
        scenario.exit_distribution = equal(exits)
        scenario.destination_distribution = equal(zones)
        return scenario

    return ScenarioModel(
        id=f"scenario_twin_{job.id.lower()}",
        name=f"{venue.name} · Default Event",
        venue_id=venue.id,
        crowd_size=crowd,
        arrival_rate_per_minute=170,
        exit_rate_per_minute=180,
        surge_departure_spread_min=5.0,
        gate_distribution=equal(entries),
        destination_distribution=equal(zones),
        exit_distribution=equal(exits),
        event_phases=[
            {"name": "ENTRY", "start_minute": 0, "end_minute": 35, "arrival_rate_multiplier": 1.0},
            {"name": "PEAK", "start_minute": 35, "end_minute": 95, "arrival_rate_multiplier": 0.12},
            {"name": "INTERVAL", "start_minute": 95, "end_minute": 110, "arrival_rate_multiplier": 0.06},
            {"name": "EXIT_SURGE", "start_minute": 110, "end_minute": 140, "arrival_rate_multiplier": 1.0},
        ],
        special={},
    )


def artifacts_to_job(job: Any, files: Dict[str, bytes]) -> None:
    """Register produced files as job artifacts (paths relative to job dir)."""
    kinds = {
        "venue.glb": "GLB",
        "semantic.json": "SEMANTIC",
        "generation.metadata.json": "METADATA",
        "preview.png": "PREVIEW",
    }
    for filename, data in files.items():
        size = len(data)
        job.artifacts.append(TwinArtifact(
            kind=kinds.get(filename, "OTHER"),
            name=filename,
            path=filename,
            size_bytes=size,
            mime="model/gltf-binary" if filename.endswith(".glb")
            else "application/json" if filename.endswith(".json")
            else "image/png" if filename.endswith(".png")
            else "application/octet-stream",
        ))
    if "venue.glb" in files:
        job.output_asset = "venue.glb"


def save_generation_metadata(job: Any, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Write generation.metadata.json content (also returned)."""
    meta = {
        "job_id": job.id,
        "provider": job.provider,
        "model": job.model,
        "provenance": job.provenance.value,
        "status": job.status.value,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "venue_id": job.venue_id,
        "input_name": job.input_name,
        "stages": list(job.logs),
    }
    if extra:
        meta.update(extra)
    return meta


def parse_semantic_text(text: str) -> Dict[str, Any]:
    """Parse + minimally validate a semantic.json payload.

    Raises ValueError on malformed output so the job fails loudly instead of
    injecting unvalidated AI text into the simulation.
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("semantic output is not a JSON object")
    venue = data.get("venue")
    if not isinstance(venue, dict):
        raise ValueError("semantic output missing 'venue' object")
    width = float(venue.get("width_m", 200.0))
    height = float(venue.get("height_m", 120.0))
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid venue dimensions {width}x{height}")
    return data