"""Seating row/seat geometry data for InstancedMesh (Phase 6).

Generates compact seat instance data (position + rotation arrays) that
the frontend Three.js layer can consume via InstancedMesh without creating
one React component per seat.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple
from .profile import SeatingTierProfile, SeatingBowlProfile


def _interpolate_boundary(
    inner: List[Tuple[float, float]],
    outer: List[Tuple[float, float]],
    t: float,
) -> List[Tuple[float, float]]:
    """Linear interpolation between two polygon boundaries at parameter t (0=inner,1=outer)."""
    n = min(len(inner), len(outer))
    return [
        (
            inner[i][0] * (1 - t) + outer[i][0] * t,
            inner[i][1] * (1 - t) + outer[i][1] * t,
        )
        for i in range(n)
    ]


def generate_seat_instances(tier: SeatingTierProfile) -> Dict[str, Any]:
    """Generate seat instance data for one seating tier.

    Returns a dict with:
      positions  : [[x, y, z], ...]
      rotations  : [[rx, ry, rz], ...]  (Euler XYZ in radians)
      count      : int
    """
    inner = tier.inner_boundary
    outer = tier.outer_boundary
    row_count = max(1, tier.row_count)
    seat_depth = tier.seat_depth_m
    aisle_every = tier.aisle_spacing_rows

    positions: List[List[float]] = []
    rotations: List[List[float]] = []

    depth_total = 0.0
    # Calculate total depth from inner to outer edge at centroid
    if inner and outer:
        cx_in = sum(p[0] for p in inner) / len(inner)
        cy_in = sum(p[1] for p in inner) / len(inner)
        cx_out = sum(p[0] for p in outer) / len(outer)
        cy_out = sum(p[1] for p in outer) / len(outer)
        depth_total = math.hypot(cx_out - cx_in, cy_out - cy_in)

    if depth_total < 0.1:
        depth_total = row_count * seat_depth * 1.1

    for row_idx in range(row_count):
        # Skip aisle rows
        if aisle_every > 0 and (row_idx % aisle_every) == (aisle_every - 1):
            continue

        t = (row_idx + 0.5) / row_count
        row_pts = _interpolate_boundary(inner, outer, t)
        n_pts = len(row_pts)
        if n_pts < 2:
            continue

        row_y = tier.floor_elevation_m + (row_idx / row_count) * (
            tier.top_elevation_m - tier.floor_elevation_m
        )

        for pt_idx in range(n_pts):
            x, z = row_pts[pt_idx]
            # Facing vector: tangent to boundary, pointing inward (toward field)
            next_pt = row_pts[(pt_idx + 1) % n_pts]
            prev_pt = row_pts[(pt_idx - 1) % n_pts]
            tangent_x = next_pt[0] - prev_pt[0]
            tangent_z = next_pt[1] - prev_pt[1]
            tl = math.hypot(tangent_x, tangent_z)
            if tl > 0:
                tangent_x /= tl
                tangent_z /= tl
            # Normal inward
            normal_x = -tangent_z
            normal_z = tangent_x
            rot_y = math.atan2(normal_x, normal_z)

            positions.append([round(x, 3), round(row_y, 3), round(z, 3)])
            rotations.append([0.0, round(rot_y, 4), 0.0])

    return {
        "tier_id": tier.id,
        "level_id": tier.level_id,
        "floor_elevation_m": tier.floor_elevation_m,
        "top_elevation_m": tier.top_elevation_m,
        "count": len(positions),
        "positions": positions,
        "rotations": rotations,
    }


def generate_bowl_seats(bowl: SeatingBowlProfile) -> List[Dict[str, Any]]:
    """Generate seat instance data for all tiers in a bowl."""
    return [generate_seat_instances(tier) for tier in bowl.tiers]
