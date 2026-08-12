"""Architecture-level fusion helpers (Phase 3).

This module is the architecture-layer counterpart to ``blueprint.fusion``.
Whereas ``blueprint.fusion`` annotates raw detections with per-object evidence
scores, THIS module takes the final fused ArchitecturalScene and:

1. Validates cross-element relationships (do they reference real entity IDs?)
2. Computes relationship-graph metrics (degree, reachability)
3. Exposes a clean ``fuse()`` entry-point called by ``pipeline.py``

The name ``fusion`` mirrors the spec's requirement for
``backend/app/blueprint/architecture/fusion.py``.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from ...models import Detection
from .analyzer import analyze
from .models import (
    ArchitecturalRelationship,
    ArchitecturalScene,
    ArchitecturalUncertainty,
    EntitySource,
    EntityType,
)


def fuse(
    detections: List[Detection],
    image_w: int,
    image_h: int,
    gemini_scene: Optional[ArchitecturalScene],
) -> ArchitecturalScene:
    """Entry-point: fuse CV detections + optional Gemini scene.

    Returns a validated, enriched ArchitecturalScene with provenance.
    """
    scene = analyze(detections, image_w, image_h, gemini_scene)
    scene = _validate_relationships(scene)
    scene = _prune_hallucinations(scene)
    return scene


def _all_entity_ids(scene: ArchitecturalScene) -> Set[str]:
    ids: Set[str] = set()
    for r in scene.regions:
        ids.add(r.id)
    for o in scene.openings:
        ids.add(o.id)
    for f in scene.facilities:
        ids.add(f.id)
    for v in scene.vertical_connections:
        ids.add(v.id)
    return ids


def _validate_relationships(scene: ArchitecturalScene) -> ArchitecturalScene:
    """Remove relationships that reference non-existent entities."""
    known_ids = _all_entity_ids(scene)
    valid: List[ArchitecturalRelationship] = []
    invalid_refs: List[str] = []

    for rel in scene.relationships:
        if rel.source_id not in known_ids:
            invalid_refs.append(f"relation source '{rel.source_id}' not found")
            continue
        if rel.target_id not in known_ids:
            invalid_refs.append(f"relation target '{rel.target_id}' not found")
            continue
        valid.append(rel)

    if invalid_refs:
        extra_uncertainties = list(scene.uncertainties) + [
            ArchitecturalUncertainty(
                element_id=None,
                description=msg,
                severity="LOW",
            )
            for msg in invalid_refs
        ]
        return scene.model_copy(update={
            "relationships": valid,
            "uncertainties": extra_uncertainties,
        })
    return scene.model_copy(update={"relationships": valid})


def _prune_hallucinations(scene: ArchitecturalScene) -> ArchitecturalScene:
    """Mark Gemini-only entities with no evidence as uncertain hallucinations.

    We do NOT delete them — the user may wish to inspect and override —
    but we lower their confidence and add an uncertainty record.
    """
    uncertainties = list(scene.uncertainties)

    def _check(entities):
        out = []
        for e in entities:
            is_gemini_only = (
                e.source == EntitySource.GEMINI
                and not any(ev.source == EntitySource.CV for ev in e.evidence)
            )
            if is_gemini_only and e.confidence < 0.55:
                uncertainties.append(ArchitecturalUncertainty(
                    element_id=e.id,
                    description=(
                        f"Gemini-only entity '{e.id}' ({e.type.value}) has no CV support "
                        f"and low confidence ({e.confidence:.0%})"
                    ),
                    severity="MEDIUM",
                ))
                try:
                    e = e.model_copy(update={"confidence": max(0.0, e.confidence * 0.7)})
                except Exception:
                    pass
            out.append(e)
        return out

    return scene.model_copy(update={
        "regions": _check(scene.regions),
        "openings": _check(scene.openings),
        "facilities": _check(scene.facilities),
        "vertical_connections": _check(scene.vertical_connections),
        "uncertainties": uncertainties,
    })


# --------------------------------------------------------------------------- #
#  Relationship-graph helpers (used by reconstruction profile)
# --------------------------------------------------------------------------- #

def build_adjacency(scene: ArchitecturalScene) -> Dict[str, List[str]]:
    """Return adjacency list of all CONNECTS_TO / ADJACENT_TO / LEADS_TO relationships."""
    adj: Dict[str, List[str]] = {}
    for rel in scene.relationships:
        if rel.relation in ("CONNECTS_TO", "ADJACENT_TO", "LEADS_TO", "ACCESSIBLE_FROM"):
            adj.setdefault(rel.source_id, []).append(rel.target_id)
            adj.setdefault(rel.target_id, []).append(rel.source_id)  # undirected
    return adj


def seating_regions(scene: ArchitecturalScene) -> List:
    return [
        r for r in scene.regions
        if r.type in (EntityType.SEATING_BOWL, EntityType.SEATING_BLOCK)
    ]


def concourse_regions(scene: ArchitecturalScene) -> List:
    return [r for r in scene.regions if r.type == EntityType.CONCOURSE]


def field_regions(scene: ArchitecturalScene) -> List:
    return [r for r in scene.regions if r.type == EntityType.FIELD]


def entry_openings(scene: ArchitecturalScene) -> List:
    return [o for o in scene.openings if o.type in (EntityType.ENTRY,)]


def emergency_openings(scene: ArchitecturalScene) -> List:
    return [o for o in scene.openings if o.type == EntityType.EMERGENCY_EXIT]
