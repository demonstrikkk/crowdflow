"""Relationship graph analysis (Phase 3).

Provides helpers for computing derived relationships in the ArchitecturalScene:
connectivity, level coherence, and missing connection warnings.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .models import (
    ArchitecturalLevel,
    ArchitecturalRelationship,
    ArchitecturalScene,
    ArchitecturalUncertainty,
    EntityType,
)


def infer_missing_relationships(scene: ArchitecturalScene) -> List[ArchitecturalRelationship]:
    """Infer CONNECTS_TO relationships that Gemini didn't provide.

    Heuristic: if a seating region and a concourse region are within 15% of the
    image diagonal of each other and have no existing CONNECTS_TO relationship,
    add one with inferred confidence.
    """
    existing_pairs: Set[Tuple[str, str]] = {
        (r.source_id, r.target_id) for r in scene.relationships
    }
    inferred: List[ArchitecturalRelationship] = []

    seating = [r for r in scene.regions if r.type in (EntityType.SEATING_BOWL, EntityType.SEATING_BLOCK)]
    concourses = [r for r in scene.regions if r.type == EntityType.CONCOURSE]
    fields = [r for r in scene.regions if r.type == EntityType.FIELD]

    # seating <-> nearest concourse
    for s in seating:
        if not s.location:
            continue
        best_c = _nearest_entity(s.location, concourses)
        if best_c and (s.id, best_c.id) not in existing_pairs:
            inferred.append(ArchitecturalRelationship(
                source_id=s.id,
                relation="CONNECTS_TO",
                target_id=best_c.id,
                confidence=0.55,
            ))
            existing_pairs.add((s.id, best_c.id))

    # seating <-> field (ADJACENT_TO)
    for s in seating:
        if not s.location:
            continue
        best_f = _nearest_entity(s.location, fields)
        if best_f and (s.id, best_f.id) not in existing_pairs:
            inferred.append(ArchitecturalRelationship(
                source_id=s.id,
                relation="ADJACENT_TO",
                target_id=best_f.id,
                confidence=0.6,
            ))
            existing_pairs.add((s.id, best_f.id))

    # openings <-> nearest concourse (ACCESSIBLE_FROM)
    for o in scene.openings:
        if not o.location:
            continue
        best_c = _nearest_entity(o.location, concourses)
        if best_c and (o.id, best_c.id) not in existing_pairs:
            inferred.append(ArchitecturalRelationship(
                source_id=o.id,
                relation="ACCESSIBLE_FROM",
                target_id=best_c.id,
                confidence=0.5,
            ))
            existing_pairs.add((o.id, best_c.id))

    return inferred


def level_coherence_check(scene: ArchitecturalScene) -> List[str]:
    """Return warning strings for any level coherence issues."""
    warnings: List[str] = []

    level_ids = {lv.id for lv in scene.levels}
    all_entities = (
        list(scene.regions)
        + list(scene.openings)
        + list(scene.facilities)
        + list(scene.vertical_connections)
    )
    for e in all_entities:
        if e.level_id and e.level_id not in level_ids:
            warnings.append(f"Entity '{e.id}' references unknown level '{e.level_id}'")

    # Check that each level has at least one region assigned
    level_usage: Dict[str, int] = defaultdict(int)
    for e in all_entities:
        if e.level_id:
            level_usage[e.level_id] += 1
    for lv in scene.levels:
        if level_usage[lv.id] == 0 and not lv.is_inferred:
            warnings.append(f"Level '{lv.id}' ({lv.name}) has no entities assigned")

    # Check vertical connections span two levels
    vc_level_ids = {vc.level_id for vc in scene.vertical_connections if vc.level_id}
    if len(scene.levels) > 1 and not vc_level_ids:
        warnings.append("Multi-level scene has no vertical connections (stairs/ramps/elevators)")

    return warnings


def _nearest_entity(location: Tuple[float, float], entities: List) -> Optional[object]:
    """Find entity with location closest to ``location`` (normalised 0..1 coords)."""
    best, best_d = None, float("inf")
    for e in entities:
        if not e.location:
            continue
        dx = e.location[0] - location[0]
        dy = e.location[1] - location[1]
        d = dx * dx + dy * dy
        if d < best_d:
            best_d, best = d, e
    return best
