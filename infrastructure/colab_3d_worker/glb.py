"""Dependency-free GLB (binary glTF 2.0) exporter for the generated venue.

Mirrors the CrowdFlow backend exporter (``backend/app/twin/glb.py``) so the
worker and the backend produce identical files. It uses the same world frame
as the frontend twin renderer:

    worldX = venue_x - width/2
    worldY = elevation
    worldZ = -(venue_y - height/2)

Every exported mesh is named after its semantic id
(``Structure_<id>`` / ``Opening_<id>`` / ``Path_<id>``) so the frontend can
bind GLB nodes to simulation elements. Pure ``struct`` + ``json`` — no deps.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class GlbMesh:
    name: str
    color: Tuple[float, float, float]
    triangles: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]] = field(default_factory=list)

    def add_box(self, cx: float, cy: float, cz: float, sx: float, sy: float, sz: float) -> None:
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        c = [
            (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
            (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
            (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
            (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
        ]
        faces = [
            (0, 2, 1), (0, 3, 2),
            (4, 5, 6), (4, 6, 7),
            (0, 1, 5), (0, 5, 4),
            (3, 7, 6), (3, 6, 2),
            (1, 2, 6), (1, 6, 5),
            (0, 4, 7), (0, 7, 3),
        ]
        for a, b, cc in faces:
            self.add_triangle(c[a], c[b], c[cc])

    def add_prism(self, polygon: List[Tuple[float, float]], y0: float, y1: float) -> None:
        n = len(polygon)
        if n < 3:
            return
        for i in range(n):
            a = polygon[i]
            b = polygon[(i + 1) % n]
            self.add_triangle((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]))
            self.add_triangle((a[0], y0, a[1]), (b[0], y1, b[1]), (a[0], y1, a[1]))
        for i in range(1, n - 1):
            self.add_triangle(
                (polygon[0][0], y1, polygon[0][1]),
                (polygon[i][0], y1, polygon[i][1]),
                (polygon[i + 1][0], y1, polygon[i + 1][1]),
            )
        for i in range(1, n - 1):
            self.add_triangle(
                (polygon[0][0], y0, polygon[0][1]),
                (polygon[i + 1][0], y0, polygon[i + 1][1]),
                (polygon[i][0], y0, polygon[i][1]),
            )

    def add_quad_strip(self, centerline: List[Tuple[float, float]], y: float, half_w: float) -> None:
        pts: List[Tuple[float, float, float]] = []
        for i, (x, z) in enumerate(centerline):
            if i < len(centerline) - 1:
                nx, nz = self._perp(centerline[i], centerline[i + 1])
            elif len(centerline) > 1:
                nx, nz = self._perp(centerline[i - 1], centerline[i])
            else:
                nx, nz = 1.0, 0.0
            pts.append((x + nx * half_w, y, z + nz * half_w))
            pts.append((x - nx * half_w, y, z - nz * half_w))
        for i in range(0, len(pts) - 2, 2):
            a, b, c, d = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
            self.add_triangle(a, b, c)
            self.add_triangle(b, d, c)

    @staticmethod
    def _perp(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
        dx, dz = b[0] - a[0], b[1] - a[1]
        length = (dx * dx + dz * dz) ** 0.5 or 1.0
        return (-dz / length, dx / length)

    def add_triangle(self, a, b, c) -> None:
        self.triangles.append((a, b, c))


def _norm(a, b, c):
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    nx = ab[1] * ac[2] - ab[2] * ac[1]
    ny = ab[2] * ac[0] - ab[0] * ac[2]
    nz = ab[0] * ac[1] - ab[1] * ac[0]
    ln = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return (nx / ln, ny / ln, nz / ln)


def write_glb(meshes: List[GlbMesh], output_path: Optional[str] = None) -> bytes:
    gltf_meshes: List[dict] = []
    materials: List[dict] = []
    accessors: List[dict] = []
    buffer_views: List[dict] = []
    node_names: List[str] = []
    bin_parts: List[bytes] = []
    byte_offset = 0

    for mesh in meshes:
        if not mesh.triangles:
            continue
        materials.append({
            "name": mesh.name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [*mesh.color, 1.0],
                "metallicFactor": 0.05,
                "roughnessFactor": 0.8,
            },
            "doubleSided": True,
        })

        mesh_pos: List[float] = []
        mesh_norm: List[float] = []
        mesh_idx: List[int] = []
        for a, b, c in mesh.triangles:
            n = _norm(a, b, c)
            for v in (a, b, c):
                mesh_pos.extend(v)
                mesh_norm.extend(n)
                mesh_idx.append(len(mesh_idx))

        pos_bytes = struct.pack("<%df" % len(mesh_pos), *mesh_pos)
        norm_bytes = struct.pack("<%df" % len(mesh_norm), *mesh_norm)
        idx_bytes = struct.pack("<%dI" % len(mesh_idx), *mesh_idx)

        pos_view = {"buffer": 0, "byteOffset": byte_offset, "byteLength": len(pos_bytes)}
        byte_offset += len(pos_bytes)
        norm_view = {"buffer": 0, "byteOffset": byte_offset, "byteLength": len(norm_bytes)}
        byte_offset += len(norm_bytes)
        idx_view = {"buffer": 0, "byteOffset": byte_offset, "byteLength": len(idx_bytes)}
        byte_offset += len(idx_bytes)
        buffer_views.extend([pos_view, norm_view, idx_view])

        xs = mesh_pos[0::3]
        ys = mesh_pos[1::3]
        zs = mesh_pos[2::3]
        accessors.append({
            "bufferView": len(buffer_views) - 3,
            "componentType": 5126, "count": len(mesh_idx), "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        })
        accessors.append({
            "bufferView": len(buffer_views) - 2,
            "componentType": 5126, "count": len(mesh_idx), "type": "VEC3",
        })
        accessors.append({
            "bufferView": len(buffer_views) - 1,
            "componentType": 5125, "count": len(mesh_idx), "type": "SCALAR",
        })

        bin_parts.append(pos_bytes)
        bin_parts.append(norm_bytes)
        bin_parts.append(idx_bytes)
        node_names.append(mesh.name)

        ai = len(accessors) - 3
        gltf_meshes.append({
            "name": mesh.name,
            "primitives": [{
                "attributes": {"POSITION": ai, "NORMAL": ai + 1},
                "indices": ai + 2,
                "material": len(materials) - 1,
            }],
        })

    if not gltf_meshes:
        raise ValueError("no mesh geometry to export")

    bin_data = b"".join(bin_parts)
    if len(bin_data) % 4:
        bin_data += b"\x00" * (4 - len(bin_data) % 4)

    gltf = {
        "asset": {"version": "2.0", "generator": "crowdflow-twin-glb"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(gltf_meshes)))}],
        "nodes": [{"name": nm, "mesh": i} for i, nm in enumerate(node_names)],
        "meshes": gltf_meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_data)}],
    }

    json_data = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_data += b" " * ((4 - len(json_data) % 4) % 4)

    total = 12 + 8 + len(json_data) + 8 + len(bin_data)
    payload = struct.pack("<4sII", b"glTF", 2, total)
    payload += struct.pack("<I4s", len(json_data), b"JSON")
    payload += json_data
    payload += struct.pack("<I4s", len(bin_data), b"BIN\x00")
    payload += bin_data
    if output_path:
        with open(output_path, "wb") as f:
            f.write(payload)
    return payload
