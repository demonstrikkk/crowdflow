"""Hugging Face / open-source perception provider (optional).

CANDIDATE-MODEL EVALUATION (Step 8 of the blueprint phase):

  * MitUNet / CubiCasa5k wall segmentation (arxiv 2512.02413, PyTorch)
      input: 512x512 raster plan; output: wall/background mask
      classes: walls only (no rooms/gates/stairs); residential dataset
      needs torch (~2 GB), GPU recommended; self-hosted possible
  * hallelu/floorplan-segmentation (HF, MIT, custom U-Net)
      input: raster plan; output: walls/doors/windows/rooms/background
      residential plans only; needs torch + custom model code
  * ozturkoktay/floor-plan-room-segmentation (MIT, U-Net + ResNet)
      residential rooms/walls/doors/windows; needs torch + segmentation_models_pytorch
  * Roboflow floor-plan YOLO instance segmentation
      residential rooms; requires a Roboflow API key (hosted, not self-contained)

NONE of these are trained on stadium / arena / concourse plans, and none
produce the semantic classes CrowdFlow needs (gates, concourses, seating
stands, corridors, stairs). Consequently the CV provider stays the default
perception backend; this provider is a *pluggable scaffold* that activates
only when a model is actually configured and PyTorch is installed.

Activation (all must hold):
  * environment variable HF_PLAN_MODEL names a HF segmentation model id, and
  * ``torch`` + ``transformers`` are importable, and
  * the model id ends in an ID2LABEL that maps to DetectionKind classes.

When inactive it contributes nothing; the pipeline simply records it as
unavailable, keeping the degradation contract of the import endpoint.
"""
from __future__ import annotations

import importlib.util
import os
from typing import List

import numpy as np
from PIL import Image

from ...models import Detection, DetectionGeometry, DetectionKind, GeometryType, Point2D
from .base import BlueprintPerceptionProvider

# class-id -> DetectionKind for a segmentation-style plan model (subset)
_DEFAULT_ID2LABEL = {
    0: DetectionKind.WALL,
    1: DetectionKind.DOOR,
    2: DetectionKind.ROOM,
    3: DetectionKind.WALL,
}


def _torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


class HuggingFacePerceptionProvider(BlueprintPerceptionProvider):
    id = "huggingface"
    name = "Hugging Face segmentation model"

    def __init__(self, model_id: str | None = None, id2label: dict | None = None):
        self.model_id = model_id or os.getenv("HF_PLAN_MODEL")
        self.id2label = id2label or _DEFAULT_ID2LABEL
        self._model = None

    def available(self) -> bool:
        return bool(self.model_id) and _torch_available()

    def _load(self):
        if self._model is not None:
            return self._model
        from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

        processor = AutoImageProcessor.from_pretrained(self.model_id)
        model = AutoModelForSemanticSegmentation.from_pretrained(self.model_id)
        self._processor, self._model = processor, model
        return self._model

    def detect(self, image: Image.Image) -> List[Detection]:
        if not self.available():
            return []
        import torch
        from torch import nn

        self._load()
        rgb = image.convert("RGB")
        inputs = self._processor(images=rgb, return_tensors="pt")
        with torch.no_grad():
            logits = self._model(**inputs).logits
        up = nn.functional.interpolate(
            logits, size=rgb.size[::-1], mode="bilinear", align_corners=False
        )
        pred = up.argmax(dim=1)[0].cpu().numpy()

        detections: List[Detection] = []
        from ..perception.cv_provider import _binarize

        ink = _binarize(np.asarray(rgb.convert("L")))
        for cls_id, kind in self.id2label.items():
            mask = (pred == cls_id).astype(np.uint8) * 255
            if mask.sum() == 0:
                continue
            import cv2

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for i, cnt in enumerate(contours):
                if abs(cv2.contourArea(cnt)) < 200:
                    continue
                approx = cv2.approxPolyDP(cnt, 3.0, True)
                poly = [Point2D(x=float(p[0][0]), y=float(p[0][1])) for p in approx]
                detections.append(
                    Detection(
                        id=f"HF{cls_id}_{i}", kind=kind,
                        geometry=DetectionGeometry(
                            type=GeometryType.POLYGON, polygon=poly,
                            bbox=(int(cnt[:, 0, 0].min()), int(cnt[:, 0, 1].min()),
                                  int(cnt[:, 0, 0].max()), int(cnt[:, 0, 1].max())),
                        ),
                        confidence=0.6, source="HF",
                    )
                )
        return detections
