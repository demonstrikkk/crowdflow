"""Provider factory: the only place that maps AI_PROVIDER -> class."""
from __future__ import annotations

import logging
from typing import Optional

from ..ai.base import AIError, AIProvider
from ..ai.config import AISettings, get_settings

logger = logging.getLogger("crowdflow.ai")


def create_provider(settings: Optional[AISettings] = None) -> AIProvider:
    settings = settings or get_settings()
    if settings.provider == "gemini":
        from ..ai.gemini import GeminiProvider

        return GeminiProvider(settings)
    from ..ai.groq import GroqProvider

    return GroqProvider(settings)


_provider: Optional[AIProvider] = None


def get_provider(settings: Optional[AISettings] = None) -> AIProvider:
    """Cached provider; pass a settings override in tests to force a provider."""
    global _provider
    if settings is not None or _provider is None:
        _provider = create_provider(settings)
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None


def provider_status() -> dict:
    settings = get_settings()
    if not settings.configured:
        return {
            "provider": settings.provider,
            "configured": False,
            "model": settings.active_model,
            "message": settings.missing_key_message(),
        }
    try:
        provider = get_provider()
        return {**provider.health(), "configured": True}
    except AIError as exc:  # pragma: no cover - defensive
        logger.warning("provider status failed: %s", exc)
        return {"provider": settings.provider, "configured": False, "message": str(exc)}


__all__ = ["AIError", "create_provider", "get_provider", "provider_status", "reset_provider"]
