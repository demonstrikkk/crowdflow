"""Hugging Face live-crowd-sensing integration (brief section 19).

Pipeline: camera/image -> HF object detection -> person count -> density
estimate -> optional simulation state update.

Uses the Hugging Face Inference API through `huggingface_hub` so the model
runs on HF's infrastructure - no local torch download required. When HF is
unreachable or unconfigured the endpoint fails loudly with a clear message;
the simulation never depends on this module (vision is an extension, not a
core dependency).
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger("crowdflow.vision")

DEFAULT_MODELS = [
    "facebook/detr-resnet-50",      # object detection, reliable 'person' class
    "hustvl/yolos-tiny",            # fast fallback
]
PERSON_LABELS = {"person", "people", "crowd", "pedestrian", "human"}

_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def _image_suffix(content_type: Optional[str]) -> str:
    if content_type:
        for ct, suffix in _CONTENT_TYPE_SUFFIX.items():
            if content_type.startswith(ct):
                return suffix
    return ".png"


def _detections_to_count(detections: List[Dict[str, Any]]) -> int:
    count = 0
    for d in detections:
        label = str(d.get("label", "")).lower().strip()
        if label in PERSON_LABELS or label.startswith("person"):
            count += 1
    return count


class CrowdVisionService:
    """Wraps a Hugging Face object-detection model via the Inference API."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        token: Optional[str] = None,
        fallback_models: Optional[List[str]] = None,
    ):
        self.model_id = model_id or os.getenv("HF_MODEL_ID", DEFAULT_MODELS[0])
        self.token = token if token is not None else os.getenv("HF_API_TOKEN")
        self.fallback_models = fallback_models or DEFAULT_MODELS
        self._client: Optional[Any] = None

    # ------------------------------------------------------------------ #
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from huggingface_hub import InferenceClient
        except ImportError as exc:  # pragma: no cover - env dependent
            raise HTTPException(
                status_code=503,
                detail=(
                    "Hugging Face client not installed. Run: "
                    "pip install huggingface_hub requests"
                ),
            ) from exc
        self._client = InferenceClient(self.model_id, token=self.token)
        return self._client

    # ------------------------------------------------------------------ #
    def estimate_crowd(self, image_bytes: bytes, content_type: Optional[str] = None) -> Dict[str, Any]:
        """Detect people in an image and return count + density calibration."""
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Empty image payload")

        client = self._ensure_client()
        detections: List[Dict[str, Any]] = []
        last_error: Optional[Exception] = None
        # huggingface_hub guesses the request content type from a file name;
        # raw bytes are rejected by the inference API ("no content type").
        with tempfile.NamedTemporaryFile(suffix=_image_suffix(content_type), delete=False) as tmp:
            tmp.write(image_bytes)
            image_path = tmp.name
        try:
            for model_id in [self.model_id, *[m for m in self.fallback_models if m != self.model_id]]:
                try:
                    result = client.object_detection(image_path, model=model_id)
                    detections = result if result else []
                    used_model = model_id
                    break
                except Exception as exc:  # noqa: BLE001 - try next model
                    last_error = exc
                    logger.warning("HF model %s failed: %s", model_id, exc)
            else:
                detail = "Hugging Face inference unavailable"
                if not self.token:
                    detail = (
                        "Hugging Face is not configured. Set HF_API_TOKEN (and optionally "
                        "HF_MODEL_ID) in the backend environment, then retry."
                    )
                elif last_error is not None:
                    detail = f"Hugging Face inference error: {last_error}"
                raise HTTPException(status_code=503, detail=detail)
        finally:
            os.unlink(image_path)

        people = _detections_to_count(detections)
        if people:
            mean_conf = sum(float(d.get("score", 0.0)) for d in detections) / len(detections)
        else:
            mean_conf = 0.0
        # density calibration: normalised count per frame (0..1, capped)
        density_score = min(1.0, people / 150.0)
        return {
            "model_id": used_model,
            "estimated_count": people,
            "detections": [
                {"label": d.get("label"), "score": round(float(d.get("score", 0.0)), 3)}
                for d in detections[:40]
            ],
            "density_score": round(density_score, 3),
            "mean_confidence": round(mean_conf, 3),
            "frame_area_m2": None,  # needs camera calibration in a real deployment
        }


vision_service = CrowdVisionService()
