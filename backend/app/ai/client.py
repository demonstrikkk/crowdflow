"""OpenAI-compatible transport shared by Groq and Gemini.

Both providers expose the Chat Completions API, so one small transport with
timeout / retry / 429 handling / rate limiting / error normalisation is used by
both. Provider-specific behaviour is limited to config and prompts.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ..ai.base import (
    AIProviderFailure,
    AITimeoutError,
    AIValidationError,
    extract_json_object,
)
from ..ai.config import AISettings

logger = logging.getLogger("crowdflow.ai")


class ProviderRateLimit(Exception):
    """Raised after bounded retries on 429/5xx — surfaces as an AI error."""


class OpenAICompatTransport:
    def __init__(self, settings: AISettings, base_url: str, api_key: str, model: str):
        self.settings = settings
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._client: Optional[Any] = None
        # simple client-side throttle: at most N structured calls per window
        self._calls: List[float] = []

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - env dependent
            raise AIProviderFailure(
                "openai SDK not installed. Run: pip install openai"
            ) from exc
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.settings.timeout_s,
            max_retries=0,  # we handle retries so we can log them
        )
        return self._client

    def _throttle(self) -> None:
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < 60.0]
        if len(self._calls) >= 30:  # hard safety ceiling; never spam providers
            raise ProviderRateLimit("provider rate-limit ceiling reached (30 calls/min)")
        self._calls.append(now)

    def chat_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Chat completion constrained to JSON, with bounded retries + logging."""
        self._throttle()
        client = self._ensure_client()
        last_error: Optional[Exception] = None
        for attempt in range(self.settings.max_retries + 1):
            started = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.settings.temperature,
                    response_format={"type": "json_object"},
                )
                latency_ms = (time.monotonic() - started) * 1000.0
                content = resp.choices[0].message.content or ""
                logger.info(
                    "ai.call provider=%s model=%s ok=true latency_ms=%.0f attempt=%d",
                    self.base_url.rsplit("/", 2)[-2] or "openai-compat",
                    self.model,
                    latency_ms,
                    attempt,
                )
                return content
            except Exception as exc:  # noqa: BLE001 - normalise all provider errors
                latency_ms = (time.monotonic() - started) * 1000.0
                status = getattr(exc, "status_code", None)
                retryable = status in (429, 500, 502, 503, 504) or isinstance(
                    exc, (TimeoutError, OSError)
                )
                logger.warning(
                    "ai.call provider=%s model=%s ok=false attempt=%d status=%s "
                    "latency_ms=%.0f error=%s",
                    self.base_url.rsplit("/", 2)[-2] or "openai-compat",
                    self.model,
                    attempt,
                    status,
                    latency_ms,
                    type(exc).__name__,
                )
                last_error = exc
                if retryable and attempt < self.settings.max_retries:
                    time.sleep(0.8 * (2 ** attempt))
                    continue
                if status == 401:
                    raise AIProviderFailure(
                        "provider rejected the API key (401). Check the backend environment."
                    ) from exc
                if status == 429:
                    raise AIProviderFailure(
                        "provider rate limit hit (429). Wait and retry, or switch "
                        "AI_PROVIDER."
                    ) from exc
                if isinstance(exc, (TimeoutError, OSError)) or "timed out" in str(
                    exc
                ).lower():
                    raise AITimeoutError(f"AI request timed out ({self.settings.timeout_s}s)") from exc
                raise AIProviderFailure(f"provider error: {exc}") from exc
        raise AIProviderFailure(f"provider failed after retries: {last_error}")  # pragma: no cover

    def parse_json(self, content: str, model_type: Any) -> Any:
        """Validate model JSON against a Pydantic model."""
        raw = extract_json_object(content)
        try:
            import json

            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIValidationError(f"provider returned invalid JSON: {exc}") from exc
        try:
            return model_type.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - surface as validation error
            raise AIValidationError(f"provider output failed validation: {exc}") from exc
