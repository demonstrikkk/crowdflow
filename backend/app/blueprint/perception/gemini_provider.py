"""Gemini Vision architectural reasoning layer (Phase 2C - Phase A).

Gemini is the *architectural brain*, NOT the geometry extractor and NOT a 3D
mesh generator. It performs one structured interpretation of the uploaded
drawing (document type, venue type, major regions, openings, relationships)
that the fusion engine later arbitrates against measured CV geometry and
Florence OCR boxes.

Golden rules (see the Phase 2C spec):

  * coordinates returned by Gemini are SEMANTIC HINTS (normalised 0..1), never
    authoritative geometry - CV establishes measured geometry;
  * the provider is OPTIONAL behind ``BLUEPRINT_GEMINI_ENABLED=true``;
    when disabled / no key / failure the pipeline behaves exactly as before;
  * the model id is configurable via ``GEMINI_VISION_MODEL`` (default
    ``gemini-3.1-flash-lite``); the API key stays server-side only;
  * one analysis request per blueprint, cached by image+model+prompt hash.

API key handling: the key is read from ``GEMINI_API_KEY`` and is never logged,
never placed on the wire beyond the SDK, and never returned to the frontend.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ...models import DocumentType
from .base import BlueprintPerceptionProvider

DEFAULT_MODEL = "gemini-3.1-flash-lite"
PROMPT_VERSION = "2026-08-01"
_ENTITY_TYPES = (
    "VENUE_FOOTPRINT", "FIELD", "SEATING_BOWL", "SEATING_BLOCK", "CONCOURSE",
    "CORRIDOR", "WALL", "ROOM", "STAIR", "RAMP", "GATE", "ENTRY", "EXIT",
    "EMERGENCY_EXIT", "CHECKPOINT", "CONCESSION", "SERVICE_AREA", "VOID", "OTHER",
)


from ..architecture.models import ArchitecturalScene

# --------------------------------------------------------------------------- #
#  Provider
# --------------------------------------------------------------------------- #
class GeminiVisionProvider(BlueprintPerceptionProvider):
    id = "gemini"
    name = "Gemini Vision (architectural reasoning)"

    def __init__(self, cache_dir: Optional[str] = None):
        self._client = None
        self._has = None
        self._reason = ""
        self._cache_dir = Path(cache_dir or (
            Path(__file__).resolve().parents[3] / "data" / "cache" / "gemini"
        ))

    # -- availability ------------------------------------------------------ #
    def _sdk_available(self) -> bool:
        try:
            import google.genai  # noqa: F401
            from google import genai  # noqa: F401

            return True
        except Exception:
            return False

    def available(self) -> bool:
        if self._has is None:
            enabled = os.getenv("BLUEPRINT_GEMINI_ENABLED", "false").lower() in ("1", "true", "yes")
            key = os.getenv("GEMINI_API_KEY", "").strip()
            if not enabled:
                self._reason = "disabled (BLUEPRINT_GEMINI_ENABLED not set)"
                self._has = False
            elif not key:
                self._reason = "missing GEMINI_API_KEY"
                self._has = False
            elif not self._sdk_available():
                self._reason = "google-genai SDK not installed"
                self._has = False
            else:
                self._has = True
        return self._has

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def _client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                api_key=os.getenv("GEMINI_API_KEY", "").strip(),
                http_options={"timeout": int(os.getenv("GEMINI_VISION_TIMEOUT", "75"))},
            )
        return self._client

    # -- inference --------------------------------------------------------- #
    def analyze(self, image) -> Optional[ArchitecturalScene]:
        """One structured architectural interpretation of the drawing.

        Returns None on any failure (fallback to Florence + CV pipeline).
        """
        if not self.available():
            return None
        model = os.getenv("GEMINI_VISION_MODEL", DEFAULT_MODEL).strip()
        if not model:
            model = DEFAULT_MODEL

        cache_key = self._cache_key(image)
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

        prompt = self._build_prompt()
        try:
            analysis = self._generate(image, model, prompt)
        except Exception as exc:  # noqa: BLE001 - any failure -> graceful fallback
            import logging

            logging.getLogger("crowdflow.blueprint").warning(
                "Gemini vision analysis failed (%s); falling back to CV+Florence",
                type(exc).__name__,
            )
            return None

        if analysis is not None:
            self._store_cache(cache_key, analysis)
        return analysis

    def _generate(self, image, model: str, prompt: str) -> Optional[ArchitecturalScene]:
        import google.genai.types as gtypes

        client = self._client()
        image_data = self._to_bytes(image)
        contents = [
            gtypes.Part(text=prompt),
            gtypes.Part(inline_data=gtypes.Blob(mime_type="image/png", data=image_data)),
        ]
        last_err: Optional[Exception] = None
        for attempt in range(int(os.getenv("GEMINI_VISION_RETRIES", "2"))):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=gtypes.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ArchitecturalScene,
                        temperature=0.0,
                    ),
                )
                return self._parse_response(resp)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt + 1 < int(os.getenv("GEMINI_VISION_RETRIES", "2")):
                    time.sleep(1.0 + attempt)
        if last_err is not None:
            raise last_err
        return None

    def _parse_response(self, resp) -> Optional[ArchitecturalScene]:
        parsed = getattr(resp, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, ArchitecturalScene):
                return parsed
            if isinstance(parsed, dict):
                return ArchitecturalScene.model_validate(parsed)
        text = getattr(resp, "text", None)
        if text:
            try:
                return ArchitecturalScene.model_validate(json.loads(text))
            except Exception:
                return None
        return None

    # -- prompt ------------------------------------------------------------ #
    def _build_prompt(self) -> str:
        return (
            "You are an architectural drawing analyst. You return STRUCTURED JSON only. "
            "Interpret the attached building/venue drawing and describe its ARCHITECTURAL "
            "STRUCTURE. You do NOT produce geometry for rendering and you never invent "
            "elements that are not visible.\n\n"
            f"Document drawing_type - one of: {[t.value for t in DocumentType]}.\n"
            "Entity types - one of: " + ", ".join(_ENTITY_TYPES) + ".\n\n"
            "Coordinate convention: ALL coordinates in evidence.bbox are NORMALISED fractions of the image "
            "(0..1), x = left to right, y = top to bottom. Return bbox as [x0,y0,x1,y1]. "
            "Return location as [x,y]. These are APPROXIMATE semantic hints only - do not claim pixel accuracy.\n\n"
            "For each entity give: id (stable, e.g. GATE_G12, SEAT_E1), type, optional label "
            "(e.g. 'GATE A', 'SEATING BLOCK 14'), confidence (0..1), "
            "and an evidence array containing the source 'GEMINI', a description (what you actually see), and bbox.\n\n"
            "Return: document {drawing_type, venue_type, projection, floor_or_level, orientation, image_quality, "
            "confidence}; venue {overall_footprint_shape, stadium_center, field_location, field_shape}; "
            "levels[] {id, name, elevation_m, floor_height_m, is_inferred}; "
            "regions[] (large enclosed areas: FIELD, SEATING_BOWL, "
            "SEATING_BLOCK, CONCOURSE, ROOM, STAIR, RAMP, SERVICE_AREA, VOID, ZONE, OTHER); "
            "openings[] (ENTRY, EXIT, EMERGENCY_EXIT, GATE, CHECKPOINT, CONCESSION); "
            "facilities[]; vertical_connections[]; "
            "relationships[] {source_id, relation, target_id, confidence} "
            "(e.g. relation can be CONNECTS_TO, CONTAINS, ADJACENT_TO); scale {scale_source, scale_confidence}; "
            "uncertainties[] {element_id, description, severity} for anything you cannot reliably interpret."
        )

    # -- cache ------------------------------------------------------------- #
    def _cache_key(self, image) -> str:
        h = hashlib.sha256()
        h.update(self._to_bytes(image))
        h.update(os.getenv("GEMINI_VISION_MODEL", DEFAULT_MODEL).encode("utf-8"))
        h.update(PROMPT_VERSION.encode("utf-8"))
        return h.hexdigest()[:32]

    def _load_cache(self, key: str) -> Optional[ArchitecturalScene]:
        if os.getenv("GEMINI_VISION_CACHE", "1").lower() in ("0", "false"):
            return None
        try:
            path = self._cache_dir / f"{key}.json"
            if not path.exists():
                return None
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ArchitecturalScene.model_validate(raw)
        except Exception:
            return None

    def _store_cache(self, key: str, analysis: ArchitecturalScene) -> None:
        if os.getenv("GEMINI_VISION_CACHE", "1").lower() in ("0", "false"):
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            payload = analysis.model_dump(mode="json")
            payload["_meta"] = {"prompt_version": PROMPT_VERSION, "cached_at": time.time()}
            (self._cache_dir / f"{key}.json").write_text(
                json.dumps(payload, indent=1), encoding="utf-8"
            )
        except Exception:
            pass

    @staticmethod
    def _to_bytes(image) -> bytes:
        import io

        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    # -- BlueprintPerceptionProvider interface ----------------------------- #
    def detect(self, image) -> List:
        """Gemini produces no raw detections; analysis is consumed by fusion."""
        return []
