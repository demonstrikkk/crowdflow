"""CrowdFlow AI configuration (single source of truth for provider/model).

No model name or provider URL is hard-coded anywhere else in the codebase.
Change provider by editing the environment, not application logic:

    AI_PROVIDER=groq    # PRIMARY
    AI_PROVIDER=gemini  # SECONDARY

Secrets (GROQ_API_KEY, GEMINI_API_KEY) are read here and never leave the
backend.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load backend/.env into the environment so keys work with zero setup. Existing
# shell environment variables take precedence over .env values.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

# OpenAI-compatible base URLs (verified against provider docs).
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Defaults chosen from currently available, low-latency models suitable for
# structured reasoning (Groq JSON mode; Gemini Flash class). All overridable.
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class AISettings(BaseModel):
    """Resolved AI configuration. Built once at startup from the environment."""

    provider: str = Field(default="groq", description="groq | gemini")
    groq_api_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODEL
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    timeout_s: float = 25.0
    max_retries: int = 2
    temperature: float = 0.1

    @property
    def active_model(self) -> str:
        if self.provider == "gemini":
            return self.gemini_model
        return self.groq_model

    @property
    def configured(self) -> bool:
        """True when the selected provider has a key configured."""
        key = self.groq_api_key if self.provider == "groq" else self.gemini_api_key
        return bool(key)

    def missing_key_message(self) -> str:
        var = "GROQ_API_KEY" if self.provider == "groq" else "GEMINI_API_KEY"
        return (
            f"AI is not configured. Set AI_PROVIDER={self.provider} and {var} in the "
            "backend environment, or use the manual scenario controls."
        )


def load_settings() -> AISettings:
    provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
    if provider not in ("groq", "gemini"):
        provider = "groq"
    return AISettings(
        provider=provider,
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip()
        or DEFAULT_GROQ_MODEL,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        or DEFAULT_GEMINI_MODEL,
        timeout_s=float(os.getenv("AI_TIMEOUT", "25")),
        max_retries=int(os.getenv("AI_MAX_RETRIES", "2")),
        temperature=float(os.getenv("AI_TEMPERATURE", "0.1")),
    )


settings: Optional[AISettings] = None


def get_settings() -> AISettings:
    """Cached settings; reload after changing the environment in tests."""
    global settings
    if settings is None:
        settings = load_settings()
    return settings


def reset_settings() -> None:
    global settings
    settings = None
