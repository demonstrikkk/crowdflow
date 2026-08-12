"""Concourse builder (Phase 6).

Generates concourse structures and circulation paths from ConcourseProfile.
Supports ring, partial ring, corridor network, and irregular polygon.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ...models import PathGeometryModel, Point2D, Polygon2D, StructureModel
from .profile import ConcourseProfile, StadiumProfile


def build_concourse(
    concourse: ConcourseProfile,
    profile: StadiumProfile,
) -> Tuple[List[StructureModel], List[PathGeometryModel]]:
    """Build concourse structures and center-line paths."""
    structures: List[StructureModel] = []
    paths: List[PathGeometryModel] = []

    poly = concourse.polygon
    if not poly or len(poly) < 3:
        return structures, paths

    # Concourse floor slab
    try:
        concourse_poly = Polygon2D(
            points=[Point2D(x=round(p[0], 2), y=round(p[1], 2)) for p in poly]
        )
        structures.append(StructureModel(
            id=concourse.id,
            level_id=concourse.level_id,
            type="CONCOURSE",
            polygon=concourse_poly,
            height_m=0.3,  # floor slab
            metadata={
                "source": concourse.provenance.source.value,
                "confidence": round(concourse.provenance.confidence, 3),
                "elevation_m": concourse.elevation_m,
                "is_ring": concourse.is_ring,
                "width_m": concourse.width_m,
                "kind": "CONCOURSE",
                "label": concourse.label,
            },
        ))
    except Exception:
        pass

    # Generate center-line paths within the concourse
    paths.extend(_build_concourse_paths(concourse))

    return structures, paths


def _build_concourse_paths(concourse: ConcourseProfile) -> List[PathGeometryModel]:
    """Generate walkable center-line paths within the concourse."""
    poly = concourse.polygon
    if not poly or len(poly) < 2:
        return []

    paths: List[PathGeometryModel] = []

    if concourse.is_ring:
        # Ring concourse: create a center-line ring path
        center = (
            sum(p[0] for p in poly) / len(poly),
            sum(p[1] for p in poly) / len(poly),
        )
        ring_path = _ring_centerline(poly, concourse.width_m, center)
        if ring_path:
            paths.append(PathGeometryModel(
                id=f"{concourse.id}_RING",
                level_id=concourse.level_id,
                centerline=ring_path,
                width_m=max(2.0, concourse.width_m * 0.6),
                metadata={
                    "source": "PROCEDURAL",
                    "concourse_id": concourse.id,
                    "kind": "CONCOURSE_PATH",
                },
            ))
    else:
        # Non-ring: create a simple spine path through the middle
        center_path = _spine_path(poly)
        if center_path:
            paths.append(PathGeometryModel(
                id=f"{concourse.id}_SPINE",
                level_id=concourse.level_id,
                centerline=center_path,
                width_m=max(2.0, concourse.width_m * 0.6),
                metadata={
                    "source": "PROCEDURAL",
                    "concourse_id": concourse.id,
                    "kind": "CONCOURSE_PATH",
                },
            ))

    return paths


def _ring_centerline(
    poly: List[Tuple[float, float]],
    ring_width: float,
    center: Tuple[float, float],
) -> List[Point2D] | None:
    """Generate ring center-line by scaling polygon toward center."""
    if len(poly) < 3:
        return None

    # Scale each vertex halfway toward center
    ring_pts = []
    for x, y in poly:
        nx = x + (center[0] - x) * 0.15
        ny = y + (center[1] - y) * 0.15
        ring_pts.append(Point2D(x=round(nx, 2), y=round(ny, 2)))

    # Close the ring
    if ring_pts:
        ring_pts.append(ring_pts[0])
    return ring_pts if len(ring_pts) >= 2 else None


def _spine_path(poly: List[Tuple[float, float]]) -> List[Point2D] | None:
    """Generate a simple bounding-box center spine path."""
    if len(poly) < 2:
        return None
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    cx = (min(xs) + max(xs)) / 2.0
    y0 = min(ys)
    y1 = max(ys)
    return [
        Point2D(x=round(cx, 2), y=round(y0, 2)),
        Point2D(x=round(cx, 2), y=round(y1, 2)),
    ]
