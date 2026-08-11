"""Bottleneck prediction (brief section 14).

Given a time series of utilisation measurements for an element (edge or node),
fit a simple least-squares line and extrapolate when the utilisation will cross
a configurable critical threshold. The prediction is explicitly a simulation
projection, not a real-world guarantee.
"""
from __future__ import annotations

from typing import List, Optional


def linear_slope(values: List[float]) -> Optional[float]:
    """Slope of the least-squares line through `values`, or None if unstable."""
    n = len(values)
    if n < 3:
        return None
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs)
    if abs(den) < 1e-9:
        return None
    return num / den


def predict_time_to_critical(
    history: List[float],
    critical_utilisation: float = 0.85,
    samples_per_minute: float = 15.0,
) -> Optional[float]:
    """Minutes until utilisation crosses `critical_utilisation`.

    Returns None when the trend is flat, decreasing or the series is too
    short to fit a line. History is interpreted in order, newest last.
    """
    if not history:
        return None
    window = history[-12:]
    slope = linear_slope(window)
    if slope is None or slope <= 1e-6:
        return None
    current = window[-1]
    if current >= critical_utilisation:
        return 0.0
    steps_to_cross = (critical_utilisation - current) / slope
    return round(steps_to_cross / samples_per_minute, 2)


def classify_trend(history: List[float]) -> str:
    """'Increasing' | 'Decreasing' | 'Stable' based on the fitted slope."""
    if len(history) < 3:
        return "Stable"
    slope = linear_slope(history[-8:])
    if slope is None:
        return "Stable"
    if slope > 0.004:
        return "Increasing"
    if slope < -0.004:
        return "Decreasing"
    return "Stable"


def risk_level_from_score(score: float) -> str:
    """Simulation thresholds (brief section 13) - not real safety standards."""
    if score >= 0.80:
        return "CRITICAL"
    if score >= 0.60:
        return "HIGH"
    if score >= 0.35:
        return "ELEVATED"
    return "NORMAL"
