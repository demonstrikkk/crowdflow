"""Perception abstraction: interchangeable blueprint perception backends.

CrowdFlow does not care which model produced detections - every backend
implements :class:`BlueprintPerceptionProvider` and returns the shared
intermediate representation (``Detection`` list in normalised pixels). This
lets us swap the deterministic CV provider for a Hugging Face / vision model
later without touching the semantic, spatial or navigation stages.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List, Optional

from PIL import Image

from ...models import Detection


class BlueprintPerceptionProvider(ABC):
    """Base class for a perception backend (CV, OCR, HF, vision model)."""

    id: str = "base"
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """Whether this backend can run in the current environment."""
        raise NotImplementedError

    @abstractmethod
    def detect(self, image: Image.Image) -> List[Detection]:
        """Return detections for a normalised blueprint image (RGB, pixels)."""
        raise NotImplementedError


class OCRProvider(ABC):
    """Separate abstraction for text perception (kept distinct from geometry)."""

    id: str = "ocr-base"
    name: str = "ocr-base"

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(self, image: Image.Image) -> List[Detection]:
        """Return TEXT detections with a bounding box + confidence."""
        raise NotImplementedError


def get_providers() -> List[BlueprintPerceptionProvider]:
    """Active geometry perception backends, best first."""
    from .cv_provider import CVPerceptionProvider
    from .florence_provider import FlorenceSemanticProvider
    from .huggingface_provider import HuggingFacePerceptionProvider

    providers: List[BlueprintPerceptionProvider] = []
    cv = CVPerceptionProvider()
    if cv.available():
        providers.append(cv)
    # optional open-vocabulary structure hints (FLORENCE_GROUNDING=1); off by
    # default so CV geometry stays the perception baseline.
    fl = FlorenceSemanticProvider()
    if fl.available():
        providers.append(fl)
    hf = HuggingFacePerceptionProvider()
    if hf.available():
        providers.append(hf)
    return providers


def get_gemini_provider():
    """Optional Gemini Vision architectural-reasoning provider (Phase A).

    Returns a configured ``GeminiVisionProvider`` when enabled and available,
    else ``None``. Kept separate from ``get_providers`` because Gemini is an
    interpretation layer, not a detection provider.
    """
    try:
        from .gemini_provider import GeminiVisionProvider

        p = GeminiVisionProvider()
        return p if p.available() else None
    except Exception:
        return None


def get_ocr_providers() -> List[OCRProvider]:
    """Active OCR backends in priority order.

    Phase 2B order: Florence VLM > DeepSeek-OCR VLM > Tesseract > WinRT. The
    pipeline uses the first provider that returns detections, so enabling the
    VLM tier keeps the classical engines as automatic fallbacks.
    """
    from .deepseek_provider import DeepSeekOcrProvider
    from .florence_provider import FlorenceOcrProvider

    out: List[OCRProvider] = []
    fl = FlorenceOcrProvider()
    if fl.available():
        out.append(fl)
    ds = DeepSeekOcrProvider()
    if ds.available():
        out.append(ds)
    # pytesseract binary next (needs system tesseract)
    try:
        from ..ocr import TesseractOcrProvider

        t = TesseractOcrProvider()
        if t.available():
            out.append(t)
    except Exception:
        pass
    try:
        from ..ocr import WinRTOcrProvider

        w = WinRTOcrProvider()
        if w.available():
            out.append(w)
    except Exception:
        pass
    # A/B tooling: pin a single backend so benchmarks compare engines fairly.
    override = os.environ.get("BLUEPRINT_OCR_BACKEND", "").strip().lower()
    if override:
        out = [p for p in out if p.id == override]
    return out
