"""Semantic venue model for the Colab 3D worker.

The worker produces the same ``crowdflow.twin.semantic.v1`` payload the
CrowdFlow backend expects (``parse_semantic_text`` -> ``semantic_to_venue_document``),
so a job generated on Colab is identical in shape to one generated locally.

The 3D model (``venue.glb``) is always derived from the semantic structure —
never from free-form AI geometry — and uses the same world frame as the
frontend twin renderer:

    worldX = venue_x - width/2
    worldY = elevation
    worldZ = -(venue_y - height/2)
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

from .glb import GlbMesh, write_glb

_OPENING_COLOR = {
    "ENTRY_GATE": (0.36, 0.78, 0.42),
    "EXIT_GATE": (0.36, 0.6, 0.95),
    "EMERGENCY_EXIT": (0.9, 0.3, 0.26),
    "DOOR": (0.75, 0.65, 0.45),
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


def generate_stadium_semantic(width: float = 200.0, height: float = 120.0) -> Dict[str, Any]:
    """Deterministic stadium semantic payload (the procedural fallback).

    Contract-compatible with the CrowdFlow backend. Used whenever no real AI
    model is available (fresh Colab instance, no weights, no API keys).
    """
    cx, cy = width / 2.0, height / 2.0
    rx, ry = width * 0.34, height * 0.40

    def ellipse(n: int) -> List[Dict[str, float]]:
        return [{"x": round(cx + rx * math.cos(2 * math.pi * i / n), 2),
                 "y": round(cy + ry * math.sin(2 * math.pi * i / n), 2)} for i in range(n)]

    pitch = [{"x": round(cx - width * 0.20, 2), "y": round(cy - height * 0.16, 2)},
             {"x": round(cx + width * 0.20, 2), "y": round(cy - height * 0.16, 2)},
             {"x": round(cx + width * 0.20, 2), "y": round(cy + height * 0.16, 2)},
             {"x": round(cx - width * 0.20, 2), "y": round(cy + height * 0.16, 2)}]
    outer = ellipse(16)

    gates = [
        {"id": "GATE_A", "label": "Gate A", "type": "ENTRY_GATE",
         "position": {"x": round(cx - width * 0.30, 2), "y": 12.0}, "width_m": 8.0, "capacity": 180},
        {"id": "GATE_B", "label": "Gate B", "type": "ENTRY_GATE",
         "position": {"x": round(cx + width * 0.30, 2), "y": 12.0}, "width_m": 8.0, "capacity": 180},
        {"id": "GATE_C", "label": "Gate C", "type": "ENTRY_GATE",
         "position": {"x": 12.0, "y": round(cy, 2)}, "width_m": 8.0, "capacity": 180},
        {"id": "GATE_D", "label": "Gate D", "type": "ENTRY_GATE",
         "position": {"x": round(width - 12.0, 2), "y": round(cy, 2)}, "width_m": 8.0, "capacity": 180},
        {"id": "EXIT_N", "label": "Exit North", "type": "EXIT_GATE",
         "position": {"x": round(cx, 2), "y": round(height - 12.0, 2)}, "width_m": 10.0, "capacity": 220},
        {"id": "EXIT_S", "label": "Exit South", "type": "EXIT_GATE",
         "position": {"x": round(cx, 2), "y": 12.0}, "width_m": 10.0, "capacity": 220},
        {"id": "EMERGENCY_1", "label": "Emergency Exit 1", "type": "EMERGENCY_EXIT",
         "position": {"x": round(cx - width * 0.28, 2), "y": round(height - 12.0, 2)}, "width_m": 6.0, "capacity": 140},
        {"id": "EMERGENCY_2", "label": "Emergency Exit 2", "type": "EMERGENCY_EXIT",
         "position": {"x": round(cx + width * 0.28, 2), "y": round(height - 12.0, 2)}, "width_m": 6.0, "capacity": 140},
    ]

    structures = [
        {"id": "PITCH", "type": "FIELD", "level_id": "L0", "polygon": {"points": pitch}, "height_m": 0.15},
        {"id": "STAND_N", "type": "SEATING", "level_id": "L0", "polygon": {"points": ellipse(10)}, "height_m": 1.6},
        {"id": "CONCOURSE_1", "type": "CONCOURSE", "level_id": "L0",
         "polygon": {"points": [{"x": round(cx - width * 0.42, 2), "y": round(cy - height * 0.3, 2)},
                                 {"x": round(cx + width * 0.42, 2), "y": round(cy - height * 0.3, 2)},
                                 {"x": round(cx + width * 0.42, 2), "y": round(cy + height * 0.3, 2)},
                                 {"x": round(cx - width * 0.42, 2), "y": round(cy + height * 0.3, 2)}]},
         "height_m": 0.25},
    ]
    for i, (x, y) in enumerate(((10, 10), (width - 10, 10), (10, height - 10), (width - 10, height - 10))):
        structures.append({"id": f"WALL_CORNER_{i}", "type": "WALL", "level_id": "L0",
                           "polygon": {"points": [{"x": x, "y": y}, {"x": x + 6, "y": y},
                                                  {"x": x + 6, "y": y + 6}, {"x": x, "y": y + 6}]},
                           "height_m": 3.0})

    paths = []
    for g in gates:
        if g["type"] == "ENTRY_GATE":
            paths.append({"id": f"PATH_{g['id']}_PITCH", "level_id": "L0",
                          "centerline": [g["position"], {"x": round(cx, 2), "y": round(cy, 2)}],
                          "width_m": 5.0})
    for e in ("EMERGENCY_1", "EMERGENCY_2"):
        paths.append({"id": f"PATH_{e}_EXIT", "level_id": "L0",
                      "centerline": [{"x": round(cx, 2), "y": round(cy, 2)},
                                     {"x": round(cx, 2), "y": round(height - 12.0, 2)}],
                      "width_m": 6.0})

    return {
        "schema": "crowdflow.twin.semantic.v1",
        "venue": {"id": "GENERATED", "name": "Generated Stadium", "type": "stadium",
                  "width_m": width, "height_m": height},
        "levels": [{"id": "L0", "name": "Ground", "elevation_m": 0.0, "height_m": 5.0}],
        "structures": structures,
        "gates": [g for g in gates if g["type"] == "ENTRY_GATE"],
        "exits": [g for g in gates if g["type"] == "EXIT_GATE"],
        "emergency_exits": [g for g in gates if g["type"] == "EMERGENCY_EXIT"],
        "zones": [],
        "paths": paths,
        "navigation": {"nodes": [], "edges": []},
        "bindings": [],
        "metadata": {"source": "PROCEDURAL", "model": "deterministic-stadium-v1", "notes": []},
    }


def analyze_blueprint(input_path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Very light, dependency-free blueprint analysis.

    Computes a sensible venue footprint from the image aspect ratio so the
    generated venue reflects the input drawing's proportions. Returns ``None``
    when the image cannot be read (the caller then uses the stadium default).
    """
    width = float(params.get("width_m") or 0)
    height = float(params.get("height_m") or 0)
    if width <= 0 or height <= 0:
        try:
            from PIL import Image
            with Image.open(input_path) as im:
                w_px, h_px = im.size
            if w_px > 0 and h_px > 0:
                # assume ~1 metre per ~4 px (a loose but reasonable default)
                width = max(40.0, w_px / 4.0)
                height = max(40.0, h_px / 4.0)
        except Exception:  # noqa: BLE001 - PIL optional / unreadable image
            return None
    if width <= 0 or height <= 0:
        return None
    semantic = generate_stadium_semantic(width, height)
    semantic["metadata"]["notes"] = [
        "worker analysis: venue footprint scaled from blueprint aspect ratio"
    ]
    return semantic


def _to_world(x: float, y: float, width: float, height: float) -> Tuple[float, float, float]:
    return (x - width / 2.0, 0.0, -(y - height / 2.0))


def build_glb_from_semantic(semantic: Dict[str, Any]) -> bytes:
    """Render a semantic payload into ``venue.glb`` bytes (self-contained)."""
    width = float(semantic.get("venue", {}).get("width_m", 200.0))
    height = float(semantic.get("venue", {}).get("height_m", 120.0))
    meshes: List[GlbMesh] = []

    ground = GlbMesh("Structure_GROUND", (0.22, 0.24, 0.28))
    ground.add_box(0, -0.15, 0, width * 1.4, 0.3, height * 1.4)
    meshes.append(ground)

    for s in semantic.get("structures", []):
        color = _STRUCTURE_COLOR.get(s.get("type", ""), (0.4, 0.42, 0.48))
        h = float(s.get("height_m", _STRUCTURE_HEIGHT.get(s.get("type", ""), 1.0)))
        mesh = GlbMesh(f"Structure_{s.get('id', 'STRUCT')}", color)
        wpts = []
        for p in s.get("polygon", {}).get("points", []):
            wx, _, wz = _to_world(float(p["x"]), float(p["y"]), width, height)
            wpts.append((wx, wz))
        if len(wpts) >= 3:
            mesh.add_prism(wpts, 0.0, max(0.05, h))
        meshes.append(mesh)

    for otype, key in (("ENTRY_GATE", "gates"), ("EXIT_GATE", "exits"), ("EMERGENCY_EXIT", "emergency_exits"), ("DOOR", "doors")):
        for o in semantic.get(key, []):
            if not isinstance(o, dict):
                continue
            try:
                ox = float(o["position"]["x"])
                oy = float(o["position"]["y"])
            except (KeyError, TypeError, ValueError):
                continue
            color = _OPENING_COLOR.get(otype, (0.75, 0.65, 0.45))
            mesh = GlbMesh(f"Opening_{o.get('id', 'OPENING')}", color)
            wx, _, wz = _to_world(ox, oy, width, height)
            w = max(1.0, float(o.get("width_m", 2.0)))
            rot = math.radians(float(o.get("rotation_deg", 0)))
            sin, cos = math.sin(rot), math.cos(rot)
            half = w / 2
            for sgn in (-1.0, 1.0):
                px = wx + sgn * half * cos
                pz = wz + sgn * half * sin
                mesh.add_box(px, 1.6, pz, 0.25, 3.2, 0.25)
            mesh.add_box(wx, 3.2, wz, w + 0.3, 0.25, 0.4)
            mesh.add_box(wx, 0.15, wz, w, 0.25, 0.4)
            meshes.append(mesh)

    for p in semantic.get("paths", []):
        pts = p.get("centerline", [])
        if len(pts) < 2:
            continue
        mesh = GlbMesh(f"Path_{p.get('id', 'PATH')}", (0.55, 0.58, 0.64))
        wpts = []
        for pt in pts:
            wx, _, wz = _to_world(float(pt["x"]), float(pt["y"]), width, height)
            wpts.append((wx, wz))
        mesh.add_quad_strip(wpts, 0.12, float(p.get("width_m", 3.0)) / 2.0)
        meshes.append(mesh)

    return write_glb(meshes)


def build_metadata(job_id: str, model: str, provenance: str, used_adapter: str, notes: List[str]) -> Dict[str, Any]:
    return {
        "job_id": job_id,
        "provider": "colab",
        "model": model,
        "provenance": provenance,
        "used_adapter": used_adapter,
        "notes": notes,
        "worker": "crowdflow-colab-3d-worker",
    }
