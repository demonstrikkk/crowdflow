"""Canonical coordinate conversion for CrowdFlow.

The rest of the codebase must not scatter pixel<->metre math around. Every
blueprint stage goes through here.

Frames:
  * pixels     - raw image coordinates (x right, y down)
  * venue      - local metric frame [0..width] x [0..height] (y down, metres)
  * world      - signed frame used by the external environment (y up)
"""
from __future__ import annotations

from typing import Optional, Tuple


def estimate_dimensions_m(
    px_w: int, px_h: int, meters_per_px_hint: Optional[float] = None
) -> Tuple[float, float]:
    """Map a normalised blueprint to a venue frame in metres.

    Prefers an explicit scale hint (e.g. a detected dimension annotation or a
    known drawing scale); otherwise defaults to 0.6 m/px (a 10 m gate ~ 16 px)
    clamped to sane venue sizes.
    """
    if meters_per_px_hint and 0.05 <= meters_per_px_hint <= 2.0:
        return round(px_w * meters_per_px_hint), round(px_h * meters_per_px_hint)
    scale = 0.6
    width_m = min(2000.0, max(300.0, px_w * scale))
    height_m = min(2000.0, max(200.0, px_h * scale))
    return round(width_m), round(height_m)


def meters_per_px(width_m: float, height_m: float, px_w: int, px_h: int) -> float:
    """Uniform scale mapping the full blueprint footprint into the venue frame.

    The smaller axis defines the scale so nothing is distorted; clamped to a
    sane 0.05-2.0 m/px band.
    """
    scale = min(width_m / max(1, px_w), height_m / max(1, px_h))
    return max(0.05, min(2.0, scale))


def px_to_venue(
    x_px: float,
    y_px: float,
    width_m: float,
    height_m: float,
    px_w: int,
    px_h: int,
) -> Tuple[float, float]:
    scale = meters_per_px(width_m, height_m, px_w, px_h)
    return x_px * scale, y_px * scale


def px_to_world(
    x_px: float,
    y_px: float,
    width_m: float,
    height_m: float,
    px_w: int,
    px_h: int,
) -> Tuple[float, float]:
    """Blueprint pixel -> signed world metres (y up), centred on the venue."""
    x, y = px_to_venue(x_px, y_px, width_m, height_m, px_w, px_h)
    return x - width_m / 2.0, height_m / 2.0 - y
