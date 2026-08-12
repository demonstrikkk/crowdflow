"""Florence-2 vision-language OCR + semantic provider (Phase 2B).

``FlorenceOcrProvider`` replaces Tesseract/WinRT as the *primary* OCR path:
one `<OCR_WITH_REGION>` pass returns every readable label plus its bounding
box in blueprint pixels, which the semantic stage associates with gates and
regions by geometry (not centroid proximity) to fix the "text not associated
with a gate/room" problem in residential-OCR pipelines.

Design rules (mirror the rest of the perception layer):

  * Feature-flagged: ``FLORENCE_ENABLED=1`` activates the provider. Model id
    comes from ``FLORENCE_MODEL`` (HF id) or ``FLORENCE_MODEL_PATH`` (local
    weights, the benchmark's helper). When inactive or the runtime fails the
    provider returns ``[]`` so ``get_ocr_providers`` falls back exactly as it
    does today (DeepSeek-OCR -> Tesseract -> WinRT).
  * Lazy, cached, thread-guarded loading: the ~0.77B model is loaded once and
    reused; loading/errors never break the import endpoint (empty result ->
    fallback).
  * ``microsoft/Florence-2-large`` repo ships old remote code + a tokenizer
    without transformers-native image tokens, so ``trust_remote_code`` is used
    (as the model card documents) and the attention implementation is forced
    to ``eager`` (SDPA dispatch is incompatible with that legacy code).
  * No CUDA assumption: CPU fp32 inference is the default; a CUDA build is
    honoured when present.
"""
from __future__ import annotations

import importlib.util
import os
import re
import threading
from typing import List, Optional

from PIL import Image

from ...models import Detection, DetectionGeometry, DetectionKind, GeometryType, Point2D
from .base import OCRProvider

DEFAULT_MODEL_ID = "microsoft/Florence-2-large"

# Conservative per-word confidence: Florence does not expose per-word scores.
_OCR_CONFIDENCE = 0.85

_TAG_RE = re.compile(r"^\s*</?[a-zA-Z0-9_]+>\s*")

_load_lock = threading.Lock()
_runtime: dict = {}


def _torch_and_transformers() -> bool:
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("transformers") is not None


def model_path() -> Optional[str]:
    """Resolve the configured model: local path wins, else HF id."""
    path = os.getenv("FLORENCE_MODEL_PATH")
    if path and os.path.isdir(path):
        return path
    return os.getenv("FLORENCE_MODEL") or DEFAULT_MODEL_ID


class FlorenceOcrProvider(OCRProvider):
    id = "florence"
    name = "Florence-2 VLM OCR (text + boxes)"

    def __init__(self):
        self._fails_when = None  # cache 'unavailable' reason once determined

    def available(self) -> bool:
        if self._fails_when is not None:
            return self._fails_when is False
        enabled = os.getenv("FLORENCE_ENABLED", "").lower() in ("1", "true", "yes")
        if not enabled:
            self._fails_when = "florence disabled (FLORENCE_ENABLED not set)"
            return False
        if not _torch_and_transformers():
            self._fails_when = "torch/transformers missing"
            return False
        path = model_path()
        if not path:
            self._fails_when = "no model configured"
            return False
        self._fails_when = None
        return True

    def disabled_reason(self) -> Optional[str]:
        if self.available():
            return None
        return self._fails_when

    def extract(self, image: Image.Image) -> List[Detection]:
        if not self.available():
            return []
        try:
            model, processor = _get_runtime()
        except Exception:
            return []
        return _run_ocr(model, processor, image)


def _get_runtime():
    """Load (once, thread-safe) the Florence model + processor."""
    global _runtime
    with _load_lock:
        if _runtime:
            return _runtime["model"], _runtime["processor"]
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        target = model_path()
        processor = AutoProcessor.from_pretrained(
            target,
            trust_remote_code=True,
            local_files_only=not target.startswith(("http", "hf://")),
        )
        kwargs = {"trust_remote_code": True, "attn_implementation": "eager"}
        if torch.cuda.is_available():
            kwargs["torch_dtype"] = torch.float16
        model = AutoModelForCausalLM.from_pretrained(target, **kwargs).eval()
        _runtime = {"model": model, "processor": processor, "id": target}
        return model, processor


def _run_ocr(model, processor, image: Image.Image) -> List[Detection]:
    import torch

    task = "<OCR_WITH_REGION>"
    inputs = processor(text=task, images=image.convert("RGB"), return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            max_new_tokens=768,
            num_beams=1,
            early_stopping=False,
        )
    text = processor.batch_decode(generated, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(text, task=task, image_size=image.size)
    region = parsed.get(task) or parsed.get("<OCR>") or {}
    quad_boxes = region.get("quad_boxes") or []
    labels = region.get("labels") or []

    out: List[Detection] = []
    seen: set = set()
    for i, raw in enumerate(labels):
        txt = _clean_label(raw)
        if not txt:
            continue
        box = _quad_bbox(quad_boxes[i]) if i < len(quad_boxes) else None
        if box is None:
            continue
        x0, y0, x1, y1 = box
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        key = (txt.upper(), round(x0, 0), round(y0, 0), round(x1, 0), round(y1, 0))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Detection(
                id=f"OCR_F{i + 1}",
                kind=DetectionKind.TEXT,
                geometry=DetectionGeometry(
                    type=GeometryType.POLYGON,
                    polygon=[
                        Point2D(x=round(x0, 2), y=round(y0, 2)),
                        Point2D(x=round(x1, 2), y=round(y0, 2)),
                        Point2D(x=round(x1, 2), y=round(y1, 2)),
                        Point2D(x=round(x0, 2), y=round(y1, 2)),
                    ],
                    bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                ),
                text=txt,
                confidence=_OCR_CONFIDENCE,
                source="OCR",
                metadata={"bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], "engine": "florence-2"},
            )
        )
    return out


def _clean_label(raw: str) -> str:
    txt = _TAG_RE.sub("", raw).strip()
    return txt


# --------------------------------------------------------------------------- #
#  Optional semantic (grounding) provider: FLORENCE_GROUNDING=1
#  Converts an open-vocabulary phrase list into GATE / STAIR detections so the
#  open-vocabulary model can *locate* structure (not just read labels). Off by
#  default: the A/B perception baseline stays deterministic CV geometry.
# --------------------------------------------------------------------------- #
_GROUNDING_PHRASES = "entrance gate. exit. emergency exit. staircase. stairs. ramp."
_GROUNDING_KIND = {
    "entrance gate": DetectionKind.GATE,
    "exit": DetectionKind.GATE,
    "emergency exit": DetectionKind.GATE,
    "staircase": DetectionKind.STAIR,
    "stairs": DetectionKind.STAIR,
    "ramp": DetectionKind.STAIR,
}


class FlorenceSemanticProvider(OCRProvider):
    """Grounding pass exposing Florence as a perception backend."""

    id = "florence-semantic"
    name = "Florence-2 open-vocabulary grounding"

    def available(self) -> bool:
        enabled = os.getenv("FLORENCE_GROUNDING", "").lower() in ("1", "true", "yes")
        return enabled and _torch_and_transformers() and bool(model_path())

    def detect(self, image: Image.Image) -> List[Detection]:
        if not self.available():
            return []
        try:
            model, processor = _get_runtime()
        except Exception:
            return []
        return _run_grounding(model, processor, image)

    def extract(self, image: Image.Image) -> List[Detection]:
        return self.detect(image)


def _run_grounding(model, processor, image: Image.Image) -> List[Detection]:
    import torch

    task = "<CAPTION_TO_PHRASE_GROUNDING>"
    prompt = task + " " + _GROUNDING_PHRASES
    inputs = processor(text=prompt, images=image.convert("RGB"), return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    with torch.no_grad():
        generated = model.generate(**inputs, max_new_tokens=512, num_beams=1)
    text = processor.batch_decode(generated, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(text, task=task, image_size=image.size)
    region = parsed.get(task) or {}
    bboxes = region.get("bboxes") or []
    labels = region.get("labels") or []

    out: List[Detection] = []
    for i, raw in enumerate(labels):
        label = _clean_label(raw).lower().strip()
        kind = _GROUNDING_KIND.get(label)
        if kind is None or i >= len(bboxes):
            continue
        b = bboxes[i]
        if not b or len(b) != 4:
            continue
        x0, y0, x1, y1 = [float(v) for v in b]
        if x1 - x0 < 8 or y1 - y0 < 8 or x1 - x0 > 0.95 * image.width:
            continue  # drop speculations and full-page boxes
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        geom = DetectionGeometry(
            type=GeometryType.POINT,
            point=Point2D(x=round(cx, 2), y=round(cy, 2)),
            bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
        )
        if kind == DetectionKind.STAIR:
            geom = DetectionGeometry(
                type=GeometryType.POLYGON,
                polygon=[
                    Point2D(x=round(x0, 2), y=round(y0, 2)),
                    Point2D(x=round(x1, 2), y=round(y0, 2)),
                    Point2D(x=round(x1, 2), y=round(y1, 2)),
                    Point2D(x=round(x0, 2), y=round(y1, 2)),
                ],
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
            )
        out.append(
            Detection(
                id=f"FLG{i + 1}", kind=kind, geometry=geom,
                text=raw, confidence=0.6, source="HF",
                metadata={"bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], "engine": "florence-2"},
            )
        )
    return out


def _quad_bbox(quad: List[float]) -> Optional[tuple]:
    """quad (x0,y0, x1,y1, x2,y2, x3,y3) -> axis-aligned bbox or None."""
    if not quad or len(quad) != 8:
        return None
    xs = quad[0::2]
    ys = quad[1::2]
    if all(v == 0 for v in xs + ys):
        return None
    return (min(xs), min(ys), max(xs), max(ys))