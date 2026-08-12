"""DeepSeek-OCR provider (Phase 2B, fallback tier for the primary OCR path).

When Florence is unavailable/disabled, ``DeepSeekOcrProvider`` provides text +
bounding boxes from the Apache-2.0 ``deepseek-ai/DeepSeek-OCR`` VLM. It is
heavier (~3B) than Florence and is only activated when the operator opts in:

  * ``DEEPSEEK_OCR_ENABLED=1`` and ``DEEPSEEK_OCR_MODEL`` (default HF id),
  * torch + transformers present.

Like every provider here it is lazy and fails soft: any runtime error returns
``[]`` and the pipeline continues to the Tesseract / WinRT tier.
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

DEFAULT_MODEL_ID = "deepseek-ai/DeepSeek-OCR"
_OCR_CONFIDENCE = 0.82
_TAG_RE = re.compile(r"^\s*</?[a-zA-Z0-9_]+>\s*")
_load_lock = threading.Lock()
_runtime: dict = {}


class DeepSeekOcrProvider(OCRProvider):
    id = "deepseek-ocr"
    name = "DeepSeek-OCR VLM (text + boxes)"

    def __init__(self):
        self._unavailable_reason: Optional[str] = None

    def available(self) -> bool:
        if self._unavailable_reason is not None:
            return False
        enabled = os.getenv("DEEPSEEK_OCR_ENABLED", "").lower() in ("1", "true", "yes")
        if not enabled:
            self._unavailable_reason = "deepseek-ocr disabled (DEEPSEEK_OCR_ENABLED not set)"
            return False
        if not (importlib.util.find_spec("torch") and importlib.util.find_spec("transformers")):
            self._unavailable_reason = "torch/transformers missing"
            return False
        model = os.getenv("DEEPSEEK_OCR_MODEL") or DEFAULT_MODEL_ID
        if not model:
            self._unavailable_reason = "no model configured"
            return False
        return True

    def extract(self, image: Image.Image) -> List[Detection]:
        if not self.available():
            return []
        try:
            model, processor = _get_runtime()
        except Exception:
            return []
        return _run_ocr(model, processor, image)


def _get_runtime():
    global _runtime
    with _load_lock:
        if _runtime:
            return _runtime["model"], _runtime["processor"]
        import torch
        from transformers import AutoModel, AutoProcessor

        target = os.getenv("DEEPSEEK_OCR_MODEL") or DEFAULT_MODEL_ID
        only_local = not target.startswith(("http", "hf://"))
        processor = AutoProcessor.from_pretrained(target, trust_remote_code=True, local_files_only=only_local)
        kwargs = {"trust_remote_code": True}
        if torch.cuda.is_available():
            kwargs["torch_dtype"] = torch.float16
        model = AutoModel.from_pretrained(target, **kwargs).eval()
        _runtime = {"model": model, "processor": processor, "id": target}
        return model, processor


def _run_ocr(model, processor, image: Image.Image) -> List[Detection]:
    import torch

    inputs = processor(images=[image.convert("RGB")], return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    with torch.no_grad():
        out = model.generate(**inputs, cache_implementation=None)
    result = processor.post_process_generation(out, image)
    return _parse_result(result)


def _parse_result(result) -> List[Detection]:
    """DeepSeek-OCR returns lines as ``[{ 'lines': [{ 'text', 'quad_box' }] }]``.

    Parsed defensively so a shape drift degrades to [] rather than a crash.
    """
    out: List[Detection] = []
    seen: set = set()
    pages = result if isinstance(result, list) else [result]
    for page in pages:
        lines = []
        if isinstance(page, dict):
            lines = page.get("lines") or page.get("words") or []
        elif isinstance(page, list):
            lines = page
        for li, line in enumerate(lines):
            if not isinstance(line, dict):
                continue
            txt = _clean_label(str(line.get("text") or ""))
            if not txt:
                continue
            box = _quad_bbox(line.get("quad_box") or line.get("box") or [])
            if box is None:
                continue
            x0, y0, x1, y1 = box
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            key = (txt.upper(), round(x0), round(y0))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Detection(
                    id=f"OCR_D{li + 1}",
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
                    metadata={"bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], "engine": "deepseek-ocr"},
                )
            )
    return out


def _clean_label(raw: str) -> str:
    return _TAG_RE.sub("", raw).strip()


def _quad_bbox(quad) -> Optional[tuple]:
    if not quad:
        return None
    try:
        xs = [float(quad[i]) for i in range(0, len(quad), 2)][:4]
        ys = [float(quad[i]) for i in range(1, len(quad), 2)][:4]
    except (TypeError, ValueError):
        return None
    if len(xs) < 4 or len(ys) < 4 or all(v == 0 for v in xs + ys):
        return None
    return (min(xs), min(ys), max(xs), max(ys))