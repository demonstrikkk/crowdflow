from fastapi import APIRouter, File, HTTPException, UploadFile

from ..engine.vision import vision_service
from ..models import CrowdEstimate

router = APIRouter()


@router.post("/crowd-estimate", response_model=CrowdEstimate)
async def crowd_estimate(file: UploadFile = File(...)):
    """Estimate people count + crowd density from an uploaded image.

    Uses a Hugging Face object-detection model through the Inference API.
    The result is a people count with confidence scores - no face recognition
    and no identity data is processed or stored (privacy-first by design).
    """
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image payload")
    if len(image_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 15 MB)")
    result = vision_service.estimate_crowd(image_bytes, content_type=file.content_type)
    return CrowdEstimate.model_validate(result)
