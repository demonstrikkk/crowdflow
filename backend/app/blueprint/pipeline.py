"""Blueprint import pipeline (brief section 21).

Stages:

  PREPROCESS  -> decode PNG/JPG/PDF, deskew, denormalise to a stable frame
  PERCEPTION  -> CV provider (walls, regions, gates, doors, stairs, corridors)
                 with optional Hugging Face provider; OCR adds TEXT detections
  SEMANTIC    -> combine geometry + text + context into venue elements
  SPATIAL     -> VenueSpatialModel (floors, walls, field, seating, concourse,
                 rooms, openings, corridors)
  NAVIGATION  -> VenueModel derived from the spatial model + graph builder
  VALIDATE    -> geometry/spatial/navigation checks + confidence report

Each stage consumes/produces the shared intermediate representation
(``Detection``), so perception backends are interchangeable. The pipeline
never fails hard: without OpenCV it degrades to the legacy heuristic geometry
path, and the graph stage guarantees a valid, simulation-ready venue.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..models import BlueprintElement, BlueprintImageMeta, BlueprintResult, Detection, DocumentType, WorldPosition
from ..spatial.coordinates import estimate_dimensions_m, meters_per_px
from . import fusion, graph, navigation, preprocess, reconstruct, scale, semantic, validate
from .perception.base import get_gemini_provider, get_ocr_providers, get_providers

_IMAGE_META_WIDTH = 1600
_GATE_KINDS = {"ENTRY", "EXIT", "EMERGENCY_EXIT"}


@dataclass
class DetectionStage:
    """Output of the PREPROCESS + PERCEPTION + OCR stage.

    ``result`` is populated when the pipeline resolved early (template fallback
    for undecodable images, or the legacy heuristic flow when OpenCV is absent);
    otherwise ``detections``/``image_meta`` feed the semantic round trip.
    """
    result: Optional[BlueprintResult] = None
    detections: Optional[List[Detection]] = None
    image_meta: Optional[BlueprintImageMeta] = None
    providers_used: List[str] = field(default_factory=list)
    ocr_provider: Optional[str] = None
    gemini_analysis: Optional[dict] = None
    architectural_scene: Optional[dict] = None
    provider_status: Dict[str, str] = field(default_factory=dict)
    pre_notes: List[str] = field(default_factory=list)


def import_blueprint(
    data: bytes,
    filename: str = "blueprint",
    page: int = 1,
) -> BlueprintResult:
    stage = detect_blueprint(data, filename, page)
    if stage.result is not None:
        return stage.result

    # SEMANTIC -> SPATIAL -> NAVIGATION -> VALIDATE
    return reconstruct_result(
        detections=stage.detections,
        image_meta=stage.image_meta,
        providers_used=stage.providers_used,
        ocr_provider=stage.ocr_provider,
        gemini_analysis=stage.gemini_analysis,
        architectural_scene=stage.architectural_scene,
        provider_status=stage.provider_status,
        pre_notes=stage.pre_notes,
    )


def detect_blueprint(
    data: bytes,
    filename: str = "blueprint",
    page: int = 1,
) -> DetectionStage:
    """PREPROCESS + PERCEPTION + OCR stage, stopping before semantic typing.

    Exposed so the UI can show/edit raw detections before the correction round
    trip (``POST /api/blueprint/reconstruct``).
    """
    pre = preprocess.preprocess(data, filename, page)
    if pre is None:
        return DetectionStage(
            result=_template_fallback(filename, pre_format="pdf" if data[:5].lstrip() == b"%PDF-" else "unknown")
        )

    # DOC CLASS (Phase 2C item 1): is this source an orthographic floor plan at
    # all? Perspective/elevation/unknown projections must not be treated as a
    # top-down plan. Advisory only - the quality gate decides on commit.
    doc_type = DocumentType.UNKNOWN
    doc_conf = 0.0
    doc_reasons: List[str] = []
    try:
        from . import docclass
        doc = docclass.classify(pre.image)
    except ImportError:  # no OpenCV -> legacy heuristic path (see below)
        pass
    except Exception as exc:  # noqa: BLE001 - classification is advisory
        doc_reasons.append(f"classification unavailable ({type(exc).__name__})")
    else:
        doc_type = doc.document_type
        doc_conf = doc.confidence
        doc_reasons = doc.reasons

    # PERCEPTION (geometry backends) + OCR (text backends)
    detections: List[Detection] = []
    vision_providers_used: List[str] = []
    for provider in get_providers():
        detections.extend(provider.detect(pre.image))
        vision_providers_used.append(provider.id)

    ocr_dets: List[Detection] = []
    ocr_provider: Optional[str] = None
    for provider in get_ocr_providers():
        ocr_dets = provider.extract(pre.image)
        if ocr_dets:
            ocr_provider = provider.id
            break
    detections.extend(ocr_dets)

    # GEMINI VISION (optional architectural reasoning; never blocks the pipeline)
    gemini_analysis: Optional[dict] = None
    architectural_scene: Optional[dict] = None
    provider_status: Dict[str, str] = {p.id: "ok" for p in get_providers()}
    if ocr_provider:
        provider_status[f"ocr:{ocr_provider}"] = "ok"
    gemini = get_gemini_provider()
    if gemini is not None:
        try:
            analysis = gemini.analyze(pre.image)
            if analysis is not None:
                architectural_scene = analysis.model_dump(mode="json")
                gemini_analysis = architectural_scene
                provider_status["gemini"] = "ok"
            else:
                provider_status["gemini"] = "error:analysis returned no structured output"
        except Exception as exc:  # noqa: BLE001 - graceful degradation only
            provider_status["gemini"] = f"error:{type(exc).__name__}"
    else:
        from .perception.gemini_provider import GeminiVisionProvider

        probe = GeminiVisionProvider()
        provider_status["gemini"] = (
            "disabled" if not os.environ.get("GEMINI_API_KEY") else probe.unavailable_reason
        )

    # SCALE: recover a real pixel->metre ratio from OCR text + ink (falls back
    # to the 0.6 m/px default when the drawing does not state its scale).
    scale_hint = scale.estimate_scale(ocr_dets, pre.image)
    width_m, height_m = estimate_dimensions_m(
        pre.width_px, pre.height_px,
        meters_per_px_hint=scale_hint.meters_per_px if scale_hint else None,
    )
    image_meta = BlueprintImageMeta(
        filename=filename,
        format=pre.format,
        page=pre.page,
        pages=pre.pages,
        width_px=pre.width_px,
        height_px=pre.height_px,
        deskew_deg=pre.deskew_deg,
        width_m=width_m,
        height_m=height_m,
        scale_m_per_px=round(meters_per_px(width_m, height_m, pre.width_px, pre.height_px), 4),
        document_type=doc_type,
        document_type_confidence=doc_conf,
        document_type_reasons=doc_reasons,
    )
    pre_notes = list(pre.notes)
    pre_notes.append(f"source classified as {doc_type.value} ({doc_conf:.0%})")
    if scale_hint:
        pre_notes.append(f"scale: {scale_hint.note} ({scale_hint.confidence})")

    if not vision_providers_used or not detections:
        # no OpenCV available -> legacy heuristic geometry path
        return DetectionStage(result=_legacy_flow(data, filename, pre, width_m, height_m, image_meta))

    return DetectionStage(
        detections=detections,
        image_meta=image_meta,
        providers_used=vision_providers_used,
        ocr_provider=ocr_provider,
        gemini_analysis=gemini_analysis,
        architectural_scene=architectural_scene,
        provider_status=provider_status,
        pre_notes=pre_notes,
    )


def reconstruct_result(
    detections: List[Detection],
    image_meta: BlueprintImageMeta,
    providers_used: Optional[List[str]] = None,
    ocr_provider: Optional[str] = None,
    gemini_analysis: Optional[dict] = None,
    architectural_scene: Optional[dict] = None,
    provider_status: Optional[Dict[str, str]] = None,
    pre_notes: Optional[List[str]] = None,
) -> BlueprintResult:
    """Run semantic + spatial + navigation + validation over raw detections.

    Shared by the live import pipeline and the human-correction round trip
    (``POST /api/blueprint/reconstruct``), so corrections re-run the exact same
    stages instead of a parallel path.
    """
    providers_used = providers_used or []
    pre_notes = pre_notes or []
    px_w, px_h = image_meta.width_px, image_meta.height_px
    width_m, height_m = image_meta.width_m, image_meta.height_m

    # ARCHITECTURAL FUSION (Stage 1 + 2): Gemini is a semantic source, not
    # geometric ground truth. Best-effort doc-class from Gemini feeds the
    # quality gate; per-object evidence scores annotate the detections that
    # semantic.interpret then consumes.
    fusion.annotate(detections, image_meta, gemini_analysis)
    _doc_from_gemini(image_meta, gemini_analysis)

    # NEW: Architecture-level fusion → StadiumProfile → VenueSpatialModel
    arch_scene_obj = None
    if architectural_scene:
        try:
            from .architecture.fusion import fuse as arch_fuse
            from .architecture.models import ArchitecturalScene
            from .reconstruction.profile import build_profile
            from .reconstruction import build as build_spatial_from_profile
            
            # Parse ArchitecturalScene from dict
            arch_scene_obj = ArchitecturalScene.model_validate(architectural_scene)
            arch_scene_obj = arch_fuse(list(detections), px_w, px_h, arch_scene_obj)
            profile = build_profile(
                arch_scene_obj,
                px_w, px_h,
                image_meta.scale_m_per_px or 1.0,
                venue_id="BLUEPRINT_VENUE",
            )
            spatial = build_spatial_from_profile(profile, venue_id="BLUEPRINT_VENUE")
            pre_notes.append(f"architectural reconstruction: {len(spatial.structures)} structures, {len(spatial.openings)} openings, {len(spatial.paths)} paths")
        except Exception as _arch_exc:  # noqa: BLE001
            pre_notes.append(f"architectural pipeline failed ({type(_arch_exc).__name__}), falling back")
            arch_scene_obj = None

    sem = semantic.interpret(detections, px_w, px_h)

    if arch_scene_obj is None:
        spatial = reconstruct.build_spatial(
            sem.structures, sem.walls, sem.gates, sem.openings_extra, sem.corridors,
            width_m, height_m, px_w, px_h,
        )

    # Phase 7: use architectural nav when procedural spatial is available
    if arch_scene_obj is not None and spatial.openings:
        venue, notes = navigation.build_venue_from_spatial(spatial, width_m, height_m)
    else:
        venue, notes = navigation.build_venue(
            spatial, sem.gates, sem.interior, width_m, height_m, px_w, px_h
        )


    canonical2d = reconstruct.build_canonical2d(
        sem.structures, sem.gates, sem.corridors, image_meta
    )
    scale_evidence = fusion.extract_scale_evidence(gemini_analysis)
    if scale_evidence:
        canonical2d.metadata["scale_evidence"] = scale_evidence
    quality = validate.build_quality(
        canonical2d, sem.structures, sem.gates, sem.corridors,
        sem.rejected, sem.footprint_bbox, image_meta, detections,
    )
    if scale_evidence and quality.scale_confidence < 0.7:
        quality.scale_confidence = 0.7  # Gemini ratio contributes evidence (never invents m/px)

    unresolved = _unresolved(detections, sem)
    report = validate.build_report(
        spatial, venue, width_m, height_m, sem.warnings, unresolved, detections, quality
    )

    confidence = report.overall_confidence
    degraded = not providers_used or ocr_provider is None
    level = 1 if providers_used and not ocr_provider else 0

    elements = _to_elements(sem.gates, sem.interior, width_m, height_m, px_w, px_h)

    steps = {
        "PERCEPTION": ",".join(providers_used) if providers_used else "from detections",
        "OCR": f"{len([d for d in detections if d.kind.value == 'TEXT'])} label(s)"
               + (f" via {ocr_provider}" if ocr_provider else ""),
        "SEMANTIC": f"{len(sem.gates)} gate(s), {len(sem.structures)} structure(s), "
                    f"{len(sem.walls)} wall(s), {len(sem.corridors)} corridor(s)",
        "SPATIAL": (f"{len(spatial.structures)} structure(s), {len(spatial.openings)} opening(s), "
                    f"{len(spatial.paths)} path(s)"),
        "NAVIGATION": "built" if venue.id == "BLUEPRINT_VENUE" else "template fallback",
        "VALIDATION": f"{len(report.warnings)} warning(s), {len(report.unresolved)} unresolved",
        "QUALITY": "passed" if quality.passed else "; ".join(quality.reasons[:2]) or "blocked",
    }
    steps.update({f"NOTE_{i}": n for i, n in enumerate(pre_notes)})
    if gemini_analysis:
        steps["GEMINI"] = f"architectural interpretation ({gemini_analysis.get('document', {}).get('type')})"
    for pid, st in (provider_status or {}).items():
        if st != "ok":
            steps[f"PROVIDER_{pid}"] = st

    return BlueprintResult(
        venue=venue,
        spatial=spatial,
        elements=elements,
        detections=detections,
        image=image_meta,
        report=report,
        confidence=confidence,
        degradation_level=level,
        degraded=degraded,
        canonical2d=canonical2d,
        gemini_analysis=gemini_analysis,
        architectural_scene=architectural_scene,
        provider_status=provider_status or {},
        steps=steps,
        notes=notes,
    )


def _doc_from_gemini(image_meta: BlueprintImageMeta, gemini_analysis: Optional[dict]) -> None:
    """Populate the document type from Gemini when it is confident.

    Gemini is not ground truth, but a confident reading (>= 0.5) that *also*
    outranks the deterministic classifier is adopted so that e.g. a confidently
    identified ``PERSPECTIVE_ARCHITECTURAL_DRAWING`` reliably fails the quality
    gate instead of being reconstructed as an orthographic plan.
    """
    got = fusion.document_type_from_gemini(gemini_analysis)
    if got is None:
        return
    dtype, conf, reason = got
    if conf < image_meta.document_type_confidence:
        return
    image_meta.document_type = dtype
    image_meta.document_type_confidence = round(conf, 2)
    if reason:
        image_meta.document_type_reasons = [f"gemini: {reason}"]


def _unresolved(detections: List[Detection], sem: semantic.SemanticOutput) -> List[str]:
    """Text detections that never attached to a gate or a region."""
    used_ids = {d.id for d in detections}
    unresolved = list(sem.warnings)
    # labels whose box overlaps no semantic element become "unresolved text"
    attached = set()
    for g in sem.gates:
        if g.get("label"):
            attached.add(g["label"].strip().upper())
    for s in sem.structures:
        if s.get("label"):
            attached.add(s["label"].strip().upper())
    for d in detections:
        if d.kind.value == "TEXT" and d.text and d.text.strip().upper() not in attached:
            unresolved.append(f"text '{d.text}' not associated with a gate/room")
    return list(dict.fromkeys(unresolved))


def _to_elements(
    gates: List[dict],
    interior: List[dict],
    width_m: float,
    height_m: float,
    px_w: int,
    px_h: int,
) -> List[BlueprintElement]:
    scale = meters_per_px(width_m, height_m, px_w, px_h)
    out: List[BlueprintElement] = []
    for i, g in enumerate(gates):
        pos = g["position"]
        out.append(
            BlueprintElement(
                id=g.get("id") or f"B{i + 1}",
                kind=g.get("kind", "ENTRY"),
                position=WorldPosition(x=round(pos[0] * scale, 2), y=round(pos[1] * scale, 2)),
                confidence=g.get("confidence", 0.4),
                label=g.get("label"),
                source="OCR" if g.get("label") else "GEOMETRY",
            )
        )
    for i, n in enumerate(interior):
        pos = n["position"]
        out.append(
            BlueprintElement(
                id=n.get("id") or f"I{i + 1}",
                kind=n.get("kind", "INTERSECTION"),
                position=WorldPosition(x=round(pos[0] * scale, 2), y=round(pos[1] * scale, 2)),
                area_m2=n.get("area_m2"),
                confidence=n.get("confidence", 0.5),
                label=n.get("label"),
                source="OCR" if n.get("label") else "GEOMETRY",
            )
        )
    return out


def _template_fallback(filename: str, pre_format: str) -> BlueprintResult:
    w, h = 1000.0, 620.0
    notes = ["image could not be decoded; template venue returned"]
    venue = graph._template_venue(w, h)
    return BlueprintResult(
        venue=venue,
        confidence=0.2,
        degradation_level=3,
        degraded=True,
        steps={
            "PREPROCESS": f"failed: unreadable {pre_format} input",
            "PERCEPTION": "skipped",
            "OCR": "skipped",
            "SEMANTIC": "skipped (template fallback)",
            "NAVIGATION": "template venue",
        },
        notes=notes,
    )


def _legacy_flow(
    data: bytes,
    filename: str,
    pre: preprocess.PreprocessedImage,
    width_m: float,
    height_m: float,
    image_meta: BlueprintImageMeta,
) -> BlueprintResult:
    """Heuristic fallback used when OpenCV is not installed."""
    from . import classify, geometry, spatial_parser

    geom = geometry.analyze_geometry(pre.image)
    labels = []
    for provider in get_ocr_providers():
        labels = _legacy_labels(provider.extract(pre.image))
        if labels:
            break

    gates = classify.classify_boundary_openings(geom.openings, len(geom.perimeter))
    interior_nodes = classify.assign_interior_kinds(geom.interior_walls)
    overlay = _legacy_overlay(gates + interior_nodes, labels)

    gates = [g for g in overlay if g["kind"] in _GATE_KINDS]
    interior = [g for g in overlay if g["kind"] not in _GATE_KINDS]
    for i, g in enumerate(gates):
        g.setdefault("id", f"B{i + 1}")
    for i, n in enumerate(interior):
        n.setdefault("id", f"I{i + 1}")

    spatial = spatial_parser.build_spatial(
        geom.perimeter, geom.interior_walls, gates, width_m, height_m, geom.width_px, geom.height_px
    )
    venue, notes = navigation.build_venue(
        spatial, gates, interior, width_m, height_m, geom.width_px, geom.height_px
    )

    from ..models import Detection, DetectionGeometry, DetectionKind, GeometryType, Point2D

    detections: List[Detection] = []
    for i, g in enumerate(gates):
        detections.append(Detection(
            id=g["id"], kind=DetectionKind.GATE,
            geometry=DetectionGeometry(type=GeometryType.POINT,
                                       point=Point2D(x=g["position"][0], y=g["position"][1]),
                                       bbox=(g["position"][0] - 10, g["position"][1] - 10,
                                             g["position"][0] + 10, g["position"][1] + 10)),
            confidence=g.get("confidence", 0.4), source="GEOMETRY",
            metadata={"side": g.get("side")},
        ))

    report = validate.build_report(
        spatial, venue, width_m, height_m,
        ["degraded: OpenCV unavailable, heuristic geometry used"], [], detections
    )
    elements = _to_elements(gates, interior, width_m, height_m, geom.width_px, geom.height_px)
    return BlueprintResult(
        venue=venue,
        spatial=spatial,
        elements=elements,
        detections=detections,
        image=image_meta,
        report=report,
        confidence=report.overall_confidence,
        degradation_level=2,
        degraded=True,
        steps={
            "PREPROCESS": "ok",
            "PERCEPTION": "heuristic (opencv unavailable)",
            "OCR": f"{len(labels)} label(s)" if labels else "none (tesseract unavailable)",
            "SEMANTIC": f"{len(gates)} gate(s), {len(interior)} interior node(s)",
            "SPATIAL": (f"{len(spatial.structures)} structure(s), "
                        f"{len(spatial.openings)} opening(s)"),
            "NAVIGATION": "built" if venue.id == "BLUEPRINT_VENUE" else "template fallback",
            "VALIDATION": f"{len(report.warnings)} warning(s)",
        },
        notes=notes,
    )


def _legacy_labels(detections: List[Detection]) -> List[dict]:
    return [
        {
            "text": d.text,
            "position": (int((d.geometry.bbox[0] + d.geometry.bbox[2]) / 2),
                         int((d.geometry.bbox[1] + d.geometry.bbox[3]) / 2)),
            "confidence": d.confidence,
        }
        for d in detections if d.text
    ]


def _legacy_overlay(elements: List[dict], labels: List[dict]) -> List[dict]:
    from . import classify

    for label in labels:
        best = None
        best_dist = 141
        for elem in elements:
            d = (elem["position"][0] - label["position"][0]) ** 2 + (
                elem["position"][1] - label["position"][1]
            ) ** 2
            if d < best_dist:
                best_dist = d
                best = elem
        if best is not None:
            kind, conf = classify.classify_text(label["text"])
            if kind in _GATE_KINDS or kind in ("CONCESSION", "CHECKPOINT", "ZONE"):
                best["kind"] = kind
                best["confidence"] = max(best.get("confidence", 0.0), conf)
                best["label"] = label["text"]
    return elements
