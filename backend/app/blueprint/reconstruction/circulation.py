"""Circulation path generator: aisles, vomitories, concourse connections (Phase 6)."""
from __future__ import annotations
import math
from typing import List, Tuple
from ...models import PathGeometryModel, Point2D
from .profile import StadiumProfile, SeatingBowlProfile, ConcourseProfile


def _midpoint(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _path(path_id: str, pts: List[Tuple[float, float]], level_id: str,
          width_m: float = 1.8, path_type: str = "AISLE",
          is_emergency: bool = False) -> PathGeometryModel:
    return PathGeometryModel(
        id=path_id,
        level_id=level_id,
        centerline=[Point2D(x=round(x, 2), y=round(y, 2)) for x, y in pts],
        width_m=round(width_m, 2),
        metadata={
            "source": "PROCEDURAL",
            "path_type": path_type,
            "is_emergency": is_emergency
        },
    )


def build_vomitory_paths(bowl: SeatingBowlProfile, profile: StadiumProfile) -> List[PathGeometryModel]:
    """Generate vomitory (aisle from field-level to concourse) paths for a seating bowl."""
    paths: List[PathGeometryModel] = []
    if not bowl.tiers:
        return paths

    # One vomitory per ~45-degree arc segment (8 per full oval)
    first_tier = bowl.tiers[0]
    last_tier = bowl.tiers[-1]
    if not first_tier.inner_boundary or not last_tier.outer_boundary:
        return paths

    n_pts = len(first_tier.inner_boundary)
    vomitory_count = max(4, n_pts // 8)  # roughly every 8th point
    step = n_pts // vomitory_count if vomitory_count > 0 else n_pts

    for i in range(vomitory_count):
        idx = (i * step) % n_pts
        inner_pt = first_tier.inner_boundary[idx]
        outer_pt = last_tier.outer_boundary[idx % len(last_tier.outer_boundary)]
        path_id = f"{bowl.id}_VOM_{i:02d}"
        paths.append(_path(
            path_id,
            [inner_pt, outer_pt],
            last_tier.level_id,
            width_m=2.5,
            path_type="VOMITORY",
        ))
    return paths


def build_concourse_ring_path(concourse: ConcourseProfile) -> List[PathGeometryModel]:
    """Generate a circulation path along the concourse ring."""
    if len(concourse.polygon) < 3:
        return []
    pts = concourse.polygon
    # Simplified: path through centroid-offset points
    path_id = f"{concourse.id}_RING"
    return [
        _path(path_id, pts + [pts[0]], concourse.level_id,
              width_m=concourse.width_m * 0.6,
              path_type="CONCOURSE")
    ]


def build_circulation_paths(profile: StadiumProfile) -> List[PathGeometryModel]:
    """Build all circulation paths for the stadium."""
    paths: List[PathGeometryModel] = []
    for bowl in profile.seating_bowls:
        paths.extend(build_vomitory_paths(bowl, profile))
    for concourse in profile.concourses:
        paths.extend(build_concourse_ring_path(concourse))
    return paths
