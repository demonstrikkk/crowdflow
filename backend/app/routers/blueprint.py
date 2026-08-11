from fastapi import APIRouter, File, HTTPException, UploadFile, status
from typing import Optional

from ..blueprint import pipeline
from ..models import BlueprintResult
from ..storage import storage

router = APIRouter()


@router.post("/import", response_model=BlueprintResult)
def import_blueprint(
    file: UploadFile = File(...),
):
    """Import a venue blueprint image and return a validated VenueModel.

    Optional engines (OpenCV geometry, Tesseract OCR) are used when installed;
    otherwise the pipeline degrades to heuristic geometry and reports the
    degradation level in the response.
    """
    data = file.file.read()
    result = pipeline.import_blueprint(data)

    if result.venue.id == "BLUEPRINT_VENUE":
        # deterministic id; a previous import is replaced (both come from the
        # same generic pipeline), keeping the endpoint idempotent
        result.venue = storage.save_venue(result.venue)
    return result
