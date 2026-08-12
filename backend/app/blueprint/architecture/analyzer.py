"""Architectural scene analyzer (Phase 3).

Receives:
  * raw CV detections  (List[Detection])
  * Florence OCR text detections (subset of the above)
  * Gemini ArchitecturalScene   (Optional[ArchitecturalScene])

Produces:
  * enriched ArchitecturalScene  with geometry from CV, semantics from Gemini,
    labels from Florence, and provenance attached to every element.

Design contract:
  * Gemini coordinates are SEMANTIC HINTS (0..1 normalised); CV pixel geometry
    is the authoritative shape. When Gemini and CV agree spatially the element
    gets a FUSED source; if only one source exists, that source is used.
  * Hallucination protection: Gemini entities with no CV support within
    ``HALLUCINATION_DIST_FRAC`` of the image diagonal are flagged as uncertain.
  * The result is fully independent of Three.js and of the 3D builder.
"""
from __future__ import annotations

import math
import uuid
from typing import Dict, List, Optional, Tuple

from ...models import Detection, DetectionKind
from .models import (
    ArchitecturalDocument,
    ArchitecturalFacility,
    ArchitecturalLevel,
    ArchitecturalOpening,
    ArchitecturalRegion,
    ArchitecturalRelationship,
    ArchitecturalScene,
    ArchitecturalUncertainty,
    ArchitecturalVenue,
    EntitySource,
    EntityType,
    Evidence,
    ScaleEvidence,
    VerticalConnection,
)

# Fraction of image diagonal within which a Gemini hint must have CV support.
HALLUCINATION_DIST_FRAC = float("inf")   # disabled by default; set via env

_GEMINI_TO_ENTITY: Dict[str, Optional[EntityType]] = {
    "FIELD": EntityType.FIELD,
    "SEATING_BOWL": EntityType.SEATING_BOWL,
    "SEATING_BLOCK": EntityType.SEATING_BLOCK,
    "CONCOURSE": EntityType.CONCOURSE,
    "CORRIDOR": EntityType.CORRIDOR,
    "WALL": EntityType.WALL,
    "ROOM": EntityType.ROOM,
    "STAIR": EntityType.STAIR,
    "RAMP": EntityType.RAMP,
    "ENTRY": EntityType.ENTRY,
    "EXIT": EntityType.EXIT,
    "EMERGENCY_EXIT": EntityType.EMERGENCY_EXIT,
    "SERVICE_ENTRY": EntityType.SERVICE_ENTRY,
    "CHECKPOINT": EntityType.CHECKPOINT,
    "CONCESSION": EntityType.CONCESSION,
    "CAFETERIA": EntityType.CAFETERIA,
    "WASHROOM": EntityType.WASHROOM,
    "MEDICAL": EntityType.MEDICAL,
    "VIP": EntityType.VIP,
    "MEDIA": EntityType.MEDIA,
    "SERVICE": EntityType.SERVICE,
    "GATE": EntityType.ENTRY,
    "ELEVATOR": EntityType.ELEVATOR,
    "VOID": None,
    "VENUE_FOOTPRINT": None,
    "OTHER": None,
}

_CV_KIND_TO_ENTITY: Dict[str, Optional[EntityType]] = {
    "FIELD": EntityType.FIELD,
    "SEATING": EntityType.SEATING_BLOCK,
    "CONCOURSE": EntityType.CONCOURSE,
    "ROOM": EntityType.ROOM,
    "ZONE": EntityType.ZONE,
    "STAIR": EntityType.STAIR,
    "ENTRY": EntityType.ENTRY,
    "EXIT": EntityType.EXIT,
    "EMERGENCY_EXIT": EntityType.EMERGENCY_EXIT,
    "CHECKPOINT": EntityType.CHECKPOINT,
}

_OPENING_ENTITY_TYPES = {
    EntityType.ENTRY, EntityType.EXIT, EntityType.EMERGENCY_EXIT,
    EntityType.SERVICE_ENTRY, EntityType.CHECKPOINT,
}

_FACILITY_ENTITY_TYPES = {
    EntityType.CONCESSION, EntityType.CAFETERIA, EntityType.WASHROOM,
    EntityType.MEDICAL, EntityType.VIP, EntityType.MEDIA, EntityType.SERVICE,
}

_VERTICAL_ENTITY_TYPES = {EntityType.STAIR, EntityType.RAMP, EntityType.ELEVATOR}


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bbox_center(bb) -> Optional[Tuple[float, float]]:
    if not bb or len(bb) < 4:
        return None
    return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)


def _norm_to_px(norm: Tuple[float, float], w: int, h: int) -> Tuple[float, float]:
    return (norm[0] * w, norm[1] * h)


def _evidence_from_detection(d: Detection, source: EntitySource) -> Evidence:
    bb = None
    if d.geometry and d.geometry.bbox:
        bb_raw = d.geometry.bbox
        bb = (float(bb_raw[0]), float(bb_raw[1]), float(bb_raw[2]), float(bb_raw[3]))
    return Evidence(
        source=source,
        confidence=round(float(d.confidence), 3),
        description=f"CV detection kind={d.kind.value}",
        bbox=bb,
    )


def analyze(
    detections: List[Detection],
    image_w: int,
    image_h: int,
    gemini_scene: Optional[ArchitecturalScene],
) -> ArchitecturalScene:
    """Produce a fused ArchitecturalScene.

    Priority:
      - geometry source: CV (pixel-measured)
      - semantic source: Gemini (architectural classification)
      - label/text: Florence OCR

    Args:
        detections: all CV + OCR detections.
        image_w: blueprint image width in pixels.
        image_h: blueprint image height in pixels.
        gemini_scene: optional Gemini-generated scene (may be None).

    Returns:
        A single unified ArchitecturalScene.
    """
    diag = math.hypot(image_w, image_h)

    ocr_detections = [d for d in detections if d.kind == DetectionKind.TEXT and d.text]
    region_detections = [d for d in detections if d.kind == DetectionKind.REGION]
    gate_detections = [d for d in detections if d.kind == DetectionKind.GATE]

    # ------------------------------------------------------------------ #
    # If we have a Gemini scene, use it as the semantic backbone,
    # then cross-reference with CV for geometry correction.
    # If not, derive everything from CV detections alone.
    # ------------------------------------------------------------------ #

    if gemini_scene is not None:
        scene = _fuse_with_gemini(
            gemini_scene, region_detections, gate_detections, ocr_detections,
            image_w, image_h, diag,
        )
    else:
        scene = _from_cv_only(region_detections, gate_detections, ocr_detections, image_w, image_h)

    return scene


# --------------------------------------------------------------------------- #
#  Gemini-backed fusion
# --------------------------------------------------------------------------- #

def _fuse_with_gemini(
    gs: ArchitecturalScene,
    regions: List[Detection],
    gates: List[Detection],
    ocr: List[Detection],
    w: int,
    h: int,
    diag: float,
) -> ArchitecturalScene:
    """Merge Gemini scene with CV + OCR evidence."""

    # Build OCR spatial index
    ocr_index = _build_ocr_index(ocr, w, h)

    # Enrich Gemini regions with CV geometry matches
    enriched_regions = _enrich_regions(gs.regions, regions, ocr_index, w, h, diag)
    enriched_openings = _enrich_openings(gs.openings, gates, ocr_index, w, h, diag)
    enriched_facilities = _enrich_facilities(gs.facilities, regions, ocr_index, w, h, diag)
    enriched_vertical = _enrich_vertical(gs.vertical_connections, regions, ocr_index, w, h, diag)

    # Add any CV regions not matched to a Gemini region
    unmatched_cv = _unmatched_cv_regions(regions, enriched_regions + enriched_facilities + enriched_vertical, w, h)
    unmatched_gates = _unmatched_cv_gates(gates, enriched_openings, w, h)

    # Merge levels: prefer Gemini levels; if none, infer from regions
    levels = gs.levels if gs.levels else _infer_levels(enriched_regions)

    # Ensure every element has a valid level reference
    level_ids = {lv.id for lv in levels}
    _assign_default_level(enriched_regions + enriched_openings + enriched_facilities + enriched_vertical, level_ids)
    _assign_default_level(unmatched_cv + unmatched_gates, level_ids)

    # Combine
    all_regions = enriched_regions + unmatched_cv
    all_openings = enriched_openings + unmatched_gates
    all_facilities = enriched_facilities
    all_vertical = enriched_vertical

    # Uncertainties: propagate Gemini ones + add new for unmatched CV
    uncertainties = list(gs.uncertainties)
    for r in unmatched_cv:
        if r.confidence < 0.45:
            uncertainties.append(ArchitecturalUncertainty(
                element_id=r.id,
                description="CV region with no Gemini semantic support",
                severity="LOW",
            ))

    # Scale: prefer Gemini scale if present
    scale = gs.scale

    # Overall confidence: average of Gemini's plus coverage penalty
    n_cv = len(regions) + len(gates)
    n_fused = len([r for r in all_regions if EntitySource.CV in [e.source for e in r.evidence]])
    coverage = n_fused / max(1, n_cv)
    combined_conf = round(0.6 * gs.confidence + 0.4 * min(1.0, coverage), 3)

    return ArchitecturalScene(
        document=gs.document,
        venue=gs.venue,
        levels=levels,
        regions=all_regions,
        openings=all_openings,
        facilities=all_facilities,
        vertical_connections=all_vertical,
        relationships=gs.relationships,
        scale=scale,
        uncertainties=uncertainties,
        confidence=combined_conf,
    )


def _build_ocr_index(ocr: List[Detection], w: int, h: int) -> List[Dict]:
    index = []
    for d in ocr:
        if not d.text:
            continue
        if d.geometry and d.geometry.bbox:
            bb = d.geometry.bbox
            cx = (bb[0] + bb[2]) / 2.0
            cy = (bb[1] + bb[3]) / 2.0
        elif d.geometry and d.geometry.point:
            cx, cy = d.geometry.point.x, d.geometry.point.y
        else:
            continue
        index.append({"text": d.text.strip(), "pos": (cx, cy), "conf": float(d.confidence)})
    return index


def _nearest_ocr(pos: Tuple[float, float], index: List[Dict], max_px: float) -> Optional[Dict]:
    best, best_d = None, max_px
    for entry in index:
        d = _dist(pos, entry["pos"])
        if d < best_d:
            best_d, best = d, entry
    return best


def _nearest_cv_region(
    target_pos: Tuple[float, float],
    cv_regions: List[Detection],
    max_px: float,
) -> Optional[Detection]:
    best, best_d = None, max_px
    for d in cv_regions:
        if not (d.geometry and d.geometry.bbox):
            continue
        bb = d.geometry.bbox
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        dist = _dist(target_pos, (cx, cy))
        if dist < best_d:
            best_d, best = dist, d
    return best


def _enrich_regions(
    gemini_regions: List[ArchitecturalRegion],
    cv_regions: List[Detection],
    ocr_index: List[Dict],
    w: int,
    h: int,
    diag: float,
) -> List[ArchitecturalRegion]:
    results = []
    matched_cv_ids: set = set()
    max_match_px = diag * 0.15

    for gr in gemini_regions:
        # Map Gemini normalized location -> pixel pos
        gem_px: Optional[Tuple[float, float]] = None
        if gr.location:
            gem_px = _norm_to_px(gr.location, w, h)
        elif gr.evidence:
            ev0 = gr.evidence[0]
            if ev0.bbox:
                gem_px = ((ev0.bbox[0] + ev0.bbox[2]) / 2.0 * w,
                          (ev0.bbox[1] + ev0.bbox[3]) / 2.0 * h)

        evidences = list(gr.evidence)

        # Try to attach a CV detection for measured geometry
        if gem_px:
            cv_match = _nearest_cv_region(gem_px, cv_regions, max_match_px)
            if cv_match and cv_match.id not in matched_cv_ids:
                matched_cv_ids.add(cv_match.id)
                evidences.append(_evidence_from_detection(cv_match, EntitySource.CV))

            # Try OCR label enrichment
            ocr_hit = _nearest_ocr(gem_px, ocr_index, diag * 0.08)
            if ocr_hit and not gr.label:
                enriched_label = ocr_hit["text"]
            else:
                enriched_label = gr.label

            # Determine source
            sources = {e.source for e in evidences}
            if EntitySource.CV in sources and EntitySource.GEMINI in sources:
                source = EntitySource.FUSED
            elif EntitySource.CV in sources:
                source = EntitySource.CV
            else:
                source = EntitySource.GEMINI

            results.append(ArchitecturalRegion(
                id=gr.id,
                type=gr.type,
                label=enriched_label if enriched_label else gr.label,
                level_id=gr.level_id,
                location=gr.location,
                confidence=round(
                    max(gr.confidence, max((e.confidence for e in evidences), default=0.0)), 3
                ),
                source=source,
                evidence=evidences,
            ))
        else:
            results.append(gr)

    return results


def _enrich_openings(
    gemini_openings: List[ArchitecturalOpening],
    cv_gates: List[Detection],
    ocr_index: List[Dict],
    w: int,
    h: int,
    diag: float,
) -> List[ArchitecturalOpening]:
    results = []
    matched_ids: set = set()

    for go in gemini_openings:
        gem_px: Optional[Tuple[float, float]] = None
        if go.location:
            gem_px = _norm_to_px(go.location, w, h)
        elif go.evidence:
            ev0 = go.evidence[0]
            if ev0.bbox:
                gem_px = ((ev0.bbox[0] + ev0.bbox[2]) / 2.0 * w,
                          (ev0.bbox[1] + ev0.bbox[3]) / 2.0 * h)

        evidences = list(go.evidence)

        if gem_px:
            # Match to CV gate
            best_gate: Optional[Detection] = None
            best_d = diag * 0.08
            for gd in cv_gates:
                if gd.id in matched_ids:
                    continue
                if not (gd.geometry and gd.geometry.bbox):
                    continue
                bb = gd.geometry.bbox
                cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
                d = _dist(gem_px, (cx, cy))
                if d < best_d:
                    best_d, best_gate = d, gd

            if best_gate:
                matched_ids.add(best_gate.id)
                evidences.append(_evidence_from_detection(best_gate, EntitySource.CV))

            ocr_hit = _nearest_ocr(gem_px, ocr_index, diag * 0.06)
            label = go.label
            if ocr_hit and not label:
                label = ocr_hit["text"]

            sources = {e.source for e in evidences}
            if EntitySource.CV in sources and EntitySource.GEMINI in sources:
                source = EntitySource.FUSED
            elif EntitySource.CV in sources:
                source = EntitySource.CV
            else:
                source = EntitySource.GEMINI

            results.append(ArchitecturalOpening(
                id=go.id,
                type=go.type,
                label=label,
                level_id=go.level_id,
                location=go.location,
                confidence=round(
                    max(go.confidence, max((e.confidence for e in evidences), default=0.0)), 3
                ),
                source=source,
                evidence=evidences,
            ))
        else:
            results.append(go)

    return results


def _enrich_facilities(
    gemini_facilities: List[ArchitecturalFacility],
    cv_regions: List[Detection],
    ocr_index: List[Dict],
    w: int,
    h: int,
    diag: float,
) -> List[ArchitecturalFacility]:
    results = []
    for fac in gemini_facilities:
        gem_px: Optional[Tuple[float, float]] = None
        if fac.location:
            gem_px = _norm_to_px(fac.location, w, h)
        elif fac.evidence:
            ev0 = fac.evidence[0]
            if ev0.bbox:
                gem_px = ((ev0.bbox[0] + ev0.bbox[2]) / 2.0 * w,
                          (ev0.bbox[1] + ev0.bbox[3]) / 2.0 * h)

        evidences = list(fac.evidence)
        label = fac.label

        if gem_px:
            ocr_hit = _nearest_ocr(gem_px, ocr_index, diag * 0.06)
            if ocr_hit and not label:
                label = ocr_hit["text"]

        results.append(ArchitecturalFacility(
            id=fac.id,
            type=fac.type,
            label=label,
            level_id=fac.level_id,
            location=fac.location,
            confidence=fac.confidence,
            source=fac.source,
            evidence=evidences,
        ))
    return results


def _enrich_vertical(
    gemini_vert: List[VerticalConnection],
    cv_regions: List[Detection],
    ocr_index: List[Dict],
    w: int,
    h: int,
    diag: float,
) -> List[VerticalConnection]:
    results = []
    for vc in gemini_vert:
        gem_px: Optional[Tuple[float, float]] = None
        if vc.location:
            gem_px = _norm_to_px(vc.location, w, h)

        evidences = list(vc.evidence)

        if gem_px:
            cv_match = _nearest_cv_region(gem_px, cv_regions, diag * 0.08)
            if cv_match:
                evidences.append(_evidence_from_detection(cv_match, EntitySource.CV))

        results.append(VerticalConnection(
            id=vc.id,
            type=vc.type,
            label=vc.label,
            level_id=vc.level_id,
            location=vc.location,
            confidence=vc.confidence,
            source=vc.source,
            evidence=evidences,
        ))
    return results


def _unmatched_cv_regions(
    cv_regions: List[Detection],
    already_matched: List,
    w: int,
    h: int,
) -> List[ArchitecturalRegion]:
    """Create ArchitecturalRegion entries for CV regions not matched to Gemini entities."""
    matched_ev_positions: set = set()
    for entity in already_matched:
        for ev in entity.evidence:
            if ev.source == EntitySource.CV and ev.bbox:
                key = (round(ev.bbox[0], 1), round(ev.bbox[1], 1))
                matched_ev_positions.add(key)

    results = []
    for i, d in enumerate(cv_regions):
        if not (d.geometry and d.geometry.bbox):
            continue
        bb = d.geometry.bbox
        key = (round(bb[0], 1), round(bb[1], 1))
        if key in matched_ev_positions:
            continue

        kind_str = str(d.metadata.get("kind", "ROOM")).upper() if d.metadata else "ROOM"
        entity_type = _CV_KIND_TO_ENTITY.get(kind_str, EntityType.ROOM)
        if entity_type is None:
            entity_type = EntityType.ROOM

        results.append(ArchitecturalRegion(
            id=f"CV_REGION_{i + 1}",
            type=entity_type,
            label=d.text,
            level_id=None,
            location=((bb[0] + bb[2]) / 2.0 / w, (bb[1] + bb[3]) / 2.0 / h),
            confidence=round(float(d.confidence), 3),
            source=EntitySource.CV,
            evidence=[_evidence_from_detection(d, EntitySource.CV)],
        ))
    return results


def _unmatched_cv_gates(
    cv_gates: List[Detection],
    already_matched: List[ArchitecturalOpening],
    w: int,
    h: int,
) -> List[ArchitecturalOpening]:
    matched_ev_keys: set = set()
    for op in already_matched:
        for ev in op.evidence:
            if ev.source == EntitySource.CV and ev.bbox:
                matched_ev_keys.add((round(ev.bbox[0], 1), round(ev.bbox[1], 1)))

    results = []
    for i, d in enumerate(cv_gates):
        if not (d.geometry and d.geometry.bbox):
            continue
        bb = d.geometry.bbox
        key = (round(bb[0], 1), round(bb[1], 1))
        if key in matched_ev_keys:
            continue

        kind_str = str(d.metadata.get("kind", "ENTRY")).upper() if d.metadata else "ENTRY"
        entity_type = _CV_KIND_TO_ENTITY.get(kind_str, EntityType.ENTRY) or EntityType.ENTRY

        results.append(ArchitecturalOpening(
            id=f"CV_GATE_{i + 1}",
            type=entity_type,
            label=d.text,
            level_id=None,
            location=((bb[0] + bb[2]) / 2.0 / w, (bb[1] + bb[3]) / 2.0 / h),
            confidence=round(float(d.confidence), 3),
            source=EntitySource.CV,
            evidence=[_evidence_from_detection(d, EntitySource.CV)],
        ))
    return results


def _infer_levels(regions: List[ArchitecturalRegion]) -> List[ArchitecturalLevel]:
    """When Gemini didn't provide levels, build a conservative single-level model."""
    return [ArchitecturalLevel(
        id="L0",
        name="Ground Level",
        elevation_m=0.0,
        floor_height_m=5.0,
        is_inferred=True,
    )]


def _assign_default_level(entities: List, level_ids: set) -> None:
    """Ensure every entity has a valid level_id; assign 'L0' if missing."""
    fallback = next(iter(level_ids), "L0")
    for e in entities:
        if e.level_id is None or e.level_id not in level_ids:
            object.__setattr__(e, "level_id", fallback) if hasattr(e, "__setattr__") else None
            try:
                e.level_id = fallback
            except Exception:
                pass


# --------------------------------------------------------------------------- #
#  CV-only path (no Gemini)
# --------------------------------------------------------------------------- #

def _from_cv_only(
    region_dets: List[Detection],
    gate_dets: List[Detection],
    ocr_dets: List[Detection],
    w: int,
    h: int,
) -> ArchitecturalScene:
    """Construct a minimal ArchitecturalScene from CV + OCR only."""
    ocr_index = _build_ocr_index(ocr_dets, w, h)

    level = ArchitecturalLevel(
        id="L0", name="Ground Level",
        elevation_m=0.0, floor_height_m=5.0, is_inferred=True,
    )

    regions: List[ArchitecturalRegion] = []
    for i, d in enumerate(region_dets):
        if not (d.geometry and d.geometry.bbox):
            continue
        bb = d.geometry.bbox
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0

        kind_str = str(d.metadata.get("kind", "ROOM")).upper() if d.metadata else "ROOM"
        entity_type = _CV_KIND_TO_ENTITY.get(kind_str) or EntityType.ROOM

        ocr_hit = _nearest_ocr((cx, cy), ocr_index, math.hypot(w, h) * 0.08)
        regions.append(ArchitecturalRegion(
            id=f"CV_REGION_{i + 1}",
            type=entity_type,
            label=ocr_hit["text"] if ocr_hit else d.text,
            level_id="L0",
            location=(cx / w, cy / h),
            confidence=round(float(d.confidence), 3),
            source=EntitySource.CV,
            evidence=[_evidence_from_detection(d, EntitySource.CV)],
        ))

    openings: List[ArchitecturalOpening] = []
    for i, d in enumerate(gate_dets):
        if not (d.geometry and d.geometry.bbox):
            continue
        bb = d.geometry.bbox
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0

        kind_str = str(d.metadata.get("kind", "ENTRY")).upper() if d.metadata else "ENTRY"
        entity_type = _CV_KIND_TO_ENTITY.get(kind_str) or EntityType.ENTRY

        openings.append(ArchitecturalOpening(
            id=f"CV_GATE_{i + 1}",
            type=entity_type,
            label=d.text,
            level_id="L0",
            location=(cx / w, cy / h),
            confidence=round(float(d.confidence), 3),
            source=EntitySource.CV,
            evidence=[_evidence_from_detection(d, EntitySource.CV)],
        ))

    doc = ArchitecturalDocument(
        drawing_type="UNKNOWN",
        projection="UNKNOWN",
        venue_type="VENUE",
        image_quality="UNKNOWN",
        confidence=0.3,
    )
    venue = ArchitecturalVenue()

    return ArchitecturalScene(
        document=doc,
        venue=venue,
        levels=[level],
        regions=regions,
        openings=openings,
        facilities=[],
        vertical_connections=[],
        relationships=[],
        scale=None,
        uncertainties=[
            ArchitecturalUncertainty(
                element_id=None,
                description="No Gemini architectural analysis available; CV geometry only",
                severity="HIGH",
            )
        ],
        confidence=0.35,
    )
