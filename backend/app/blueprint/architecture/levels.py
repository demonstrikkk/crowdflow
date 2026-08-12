"""Level reconstruction helpers (Phase 3/4).

Responsible for promoting ArchitecturalScene level data into
LevelModel objects that VenueSpatialModel can consume.

When only one floor plan is available, this module conservatively
infers a vertical structure from seating/concourse tier relationships.
"""
from __future__ import annotations

from typing import List, Optional

from ...models import LevelModel
from .models import ArchitecturalLevel, ArchitecturalScene, EntityType


_DEFAULT_LEVEL_HEIGHT_M = 5.0
_TIER_HEIGHT_M = 4.0  # typical height between seating tiers


def extract_levels(scene: ArchitecturalScene) -> List[LevelModel]:
    """Convert ArchitecturalScene levels -> LevelModel list.

    If the scene has explicit levels, convert them directly.
    If not, infer from the seating/concourse tier relationships.
    """
    if scene.levels:
        return [
            LevelModel(
                id=lv.id,
                name=lv.name,
                elevation_m=lv.elevation_m,
                height_m=lv.floor_height_m if lv.floor_height_m > 0 else _DEFAULT_LEVEL_HEIGHT_M,
            )
            for lv in scene.levels
        ]
    return _infer_levels(scene)


def _infer_levels(scene: ArchitecturalScene) -> List[LevelModel]:
    """Conservative inference: count seating tiers from the scene."""
    seating = [r for r in scene.regions if r.type in (EntityType.SEATING_BOWL, EntityType.SEATING_BLOCK)]

    # Distinct level hints from seating labels: "lower", "middle", "upper"
    level_hints = set()
    for s in seating:
        label_lower = (s.label or "").lower()
        if "lower" in label_lower:
            level_hints.add("lower")
        elif "upper" in label_lower:
            level_hints.add("upper")
        elif "middle" in label_lower or "mid" in label_lower:
            level_hints.add("middle")

    # If no label hints, determine from level_id assignments
    level_id_hints = {s.level_id for s in seating if s.level_id} or {"L0"}

    if len(level_hints) == 0 and len(level_id_hints) <= 1:
        # Single-level fallback
        return [LevelModel(id="L0", name="Ground Level", elevation_m=0.0, height_m=_DEFAULT_LEVEL_HEIGHT_M)]

    # Build a level per hint
    ordered_hints = _sort_hints(level_hints or level_id_hints)
    levels = []
    for i, name in enumerate(ordered_hints):
        levels.append(LevelModel(
            id=f"L{i}",
            name=name.title(),
            elevation_m=round(i * _TIER_HEIGHT_M, 1),
            height_m=_DEFAULT_LEVEL_HEIGHT_M,
        ))
    return levels


def _sort_hints(hints: set) -> List[str]:
    order = {"lower": 0, "ground": 0, "middle": 1, "mid": 1, "upper": 2, "top": 3}
    named = sorted(hints, key=lambda h: order.get(h.lower(), 99))
    if not named:
        return ["Ground Level"]
    return named
