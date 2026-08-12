from fastapi import APIRouter, Body, File, HTTPException, UploadFile, status
from typing import List, Optional

from ..blueprint import pipeline
from ..models import BlueprintDetectionResult, BlueprintImageMeta, BlueprintResult, Detection
from ..storage import storage

router = APIRouter()


def _commit_reconstruction(result: BlueprintResult) -> None:
    """Atomically commit a reconstruction: only a quality-passing result may
    replace the active venue. A failing reconstruction is returned to the UI
    (with reasons) but never persisted, so the previous venue stays live."""
    if result.venue.id != "BLUEPRINT_VENUE":
        return
    quality = result.report.quality if result.report else None
    if quality is not None and not quality.passed:
        return
    result.venue = storage.save_venue_document(result.venue, result.spatial).venue


@router.post("/import", response_model=BlueprintResult)
def import_blueprint(
    file: UploadFile = File(...),
):
    """Import a venue blueprint image and return a validated VenueModel.

    Optional engines (OpenCV geometry, Tesseract OCR) are used when installed;
    otherwise the pipeline degrades to heuristic geometry and reports the
    degradation level in the response.

    The result only becomes the active venue when the reconstruction quality
    gate passes (source is an orthographic floor plan with credible openings).
    """
    data = file.file.read()
    result = pipeline.import_blueprint(data, filename=file.filename or "blueprint")

    if result.venue.id == "BLUEPRINT_VENUE":
        # deterministic id; a previous import is replaced (both come from the
        # same generic pipeline), keeping the endpoint idempotent
        _commit_reconstruction(result)
    return result


@router.post("/detect", response_model=BlueprintDetectionResult)
def detect_blueprint(
    file: UploadFile = File(...),
):
    """Run only the PREPROCESS + PERCEPTION + OCR stage.

    Returns raw detections and image metadata so the UI can overlay and let a
    human correct them before ``POST /api/blueprint/reconstruct`` finalises the
    venue.
    """
    data = file.file.read()
    stage = pipeline.detect_blueprint(data, filename=file.filename or "blueprint")
    if stage.result is not None:
        # early-resolved paths (template fallback / legacy geometry)
        if stage.result.image is None or not stage.result.detections:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="image could not be decoded; no detections produced",
            )
        return BlueprintDetectionResult(
            image=stage.result.image,
            detections=stage.result.detections,
            provider="heuristic" if stage.result.degradation_level >= 2 else "cv",
            warnings=[f"degradation level {stage.result.degradation_level}"] + stage.result.report.warnings[:10],
        )
    return BlueprintDetectionResult(
        image=stage.image_meta,
        detections=stage.detections,
        provider="cv" + (f"+{stage.ocr_provider}" if stage.ocr_provider else ""),
        warnings=[],
        gemini_analysis=stage.gemini_analysis,
    )


@router.post("/reconstruct", response_model=BlueprintResult)
def reconstruct_blueprint(
    image: BlueprintImageMeta = Body(..., embed=True),
    detections: List[Detection] = Body(..., embed=True),
    provider: Optional[str] = Body(None, embed=True),
    ocr_provider: Optional[str] = Body(None, embed=True),
    gemini_analysis: Optional[dict] = Body(None, embed=True),
):
    """Finalise a venue from (possibly human-corrected) detections.

    Re-runs architectural fusion (with optional Gemini analysis), semantic
    typing, spatial model, navigation graph and validation over the submitted
    detections, then persists the venue under ``BLUEPRINT_VENUE`` when the
    quality gate passes. This is the correction round trip: POST /detect, edit
    in the UI, POST /reconstruct. ``provider``/``ocr_provider``/``gemini_analysis``
    echo the /detect backends so the degradation flag stays accurate.
    """
    result = pipeline.reconstruct_result(
        detections=detections,
        image_meta=image,
        providers_used=[provider] if provider else None,
        ocr_provider=ocr_provider,
        gemini_analysis=gemini_analysis,
    )

    if result.venue.id == "BLUEPRINT_VENUE":
        _commit_reconstruction(result)
    return result


# ---------------------------------------------------------------------------
#  NEW endpoints: ANALYZE / BUILD / COMMIT / architecture / canonical
#  (spec sections 58-59)
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=BlueprintDetectionResult)
def analyze_blueprint(
    file: UploadFile = File(...),
):
    """ANALYZE stage: run full perception (CV + Florence + Gemini) and return
    the architectural scene and detections for review BEFORE building spatial model.

    This is the first step in the ANALYZE → BUILD → COMMIT workflow.
    """
    data = file.file.read()
    stage = pipeline.detect_blueprint(data, filename=file.filename or "blueprint")
    if stage.result is not None:
        if stage.result.image is None or not stage.result.detections:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="image could not be decoded",
            )
        return BlueprintDetectionResult(
            image=stage.result.image,
            detections=stage.result.detections or [],
            provider="heuristic",
            warnings=[f"degradation level {stage.result.degradation_level}"],
            gemini_analysis=stage.gemini_analysis,
            architectural_scene=stage.architectural_scene,
        )
    return BlueprintDetectionResult(
        image=stage.image_meta,
        detections=stage.detections or [],
        provider="cv" + (f"+{stage.ocr_provider}" if stage.ocr_provider else ""),
        warnings=[],
        gemini_analysis=stage.gemini_analysis,
        architectural_scene=stage.architectural_scene,
    )


@router.post("/build", response_model=BlueprintResult)
def build_blueprint(
    image: BlueprintImageMeta = Body(..., embed=True),
    detections: List[Detection] = Body(..., embed=True),
    provider: Optional[str] = Body(None, embed=True),
    ocr_provider: Optional[str] = Body(None, embed=True),
    gemini_analysis: Optional[dict] = Body(None, embed=True),
    architectural_scene: Optional[dict] = Body(None, embed=True),
):
    """BUILD stage: reconstruct spatial model from analyzed detections.

    Runs the full ArchitecturalScene → StadiumProfile → VenueSpatialModel
    pipeline. Result is a DRAFT (not persisted) until POST /commit.
    """
    result = pipeline.reconstruct_result(
        detections=detections,
        image_meta=image,
        providers_used=[provider] if provider else None,
        ocr_provider=ocr_provider,
        gemini_analysis=gemini_analysis,
        architectural_scene=architectural_scene,
    )
    # BUILD returns draft without committing
    return result


@router.post("/commit", response_model=BlueprintResult)
def commit_blueprint(
    image: BlueprintImageMeta = Body(..., embed=True),
    detections: List[Detection] = Body(..., embed=True),
    provider: Optional[str] = Body(None, embed=True),
    ocr_provider: Optional[str] = Body(None, embed=True),
    gemini_analysis: Optional[dict] = Body(None, embed=True),
    architectural_scene: Optional[dict] = Body(None, embed=True),
):
    """COMMIT stage: persist a validated reconstruction.

    Only commits if reconstruction passes the quality gate (field present,
    footprint valid, seating present, gates valid, navigation connected).
    A failed reconstruction returns 422 without overwriting the last valid venue.
    """
    result = pipeline.reconstruct_result(
        detections=detections,
        image_meta=image,
        providers_used=[provider] if provider else None,
        ocr_provider=ocr_provider,
        gemini_analysis=gemini_analysis,
        architectural_scene=architectural_scene,
    )
    if result.venue.id == "BLUEPRINT_VENUE":
        _commit_reconstruction(result)
    if result.report and result.report.quality and not result.report.quality.passed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Reconstruction quality gate failed; venue not persisted",
                "reasons": result.report.quality.reasons,
                "result": result.model_dump(mode="json"),
            },
        )
    return result


@router.get("/{venue_id}/architecture")
def get_venue_architecture(venue_id: str):
    """Return the persisted ArchitecturalScene for a venue (if available)."""
    doc = storage.get_venue_document(venue_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Venue {venue_id!r} not found")
    arch = getattr(doc, "architectural_scene", None) or (
        doc.metadata.get("architectural_scene") if hasattr(doc, "metadata") else None
    )
    if arch is None:
        raise HTTPException(
            status_code=404,
            detail=f"No architectural scene stored for venue {venue_id!r}",
        )
    return arch


@router.get("/{venue_id}/canonical")
def get_venue_canonical(venue_id: str):
    """Return the persisted Canonical2D model for a venue (if available)."""
    doc = storage.get_venue_document(venue_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Venue {venue_id!r} not found")
    canon = getattr(doc, "canonical2d", None) or (
        doc.metadata.get("canonical2d") if hasattr(doc, "metadata") else None
    )
    if canon is None:
        raise HTTPException(
            status_code=404,
            detail=f"No canonical 2D model stored for venue {venue_id!r}",
        )
    return canon
