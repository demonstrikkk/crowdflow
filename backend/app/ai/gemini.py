"""Gemini provider (SECONDARY). Drop-in alternative via Gemini's
OpenAI-compatible endpoint. The application does not care which provider is
active — switch with AI_PROVIDER=gemini in the environment.
"""
from __future__ import annotations

from ..ai.base import (
    AIProvider,
    ParsedScenario,
    SimulationExplanation,
    SuggestionBundle,
)
from ..ai.client import OpenAICompatTransport
from ..ai.config import GEMINI_BASE_URL, AISettings
from ..ai.prompts import (
    explain_messages,
    parse_scenario_messages,
    suggestions_messages,
)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, settings: AISettings):
        self.settings = settings
        self.transport = OpenAICompatTransport(
            settings, GEMINI_BASE_URL, settings.gemini_api_key, settings.gemini_model
        )

    def parseScenario(self, query: str, venue_context: str) -> ParsedScenario:
        content = self.transport.chat_json(parse_scenario_messages(query, venue_context))
        return self.transport.parse_json(content, ParsedScenario)

    def explainSimulation(
        self, metrics_summary: str, bottlenecks_summary: str, world_summary: str = ""
    ) -> SimulationExplanation:
        content = self.transport.chat_json(
            explain_messages(metrics_summary, bottlenecks_summary, world_summary)
        )
        return self.transport.parse_json(content, SimulationExplanation)

    def generateScenarioSuggestions(self, context: str) -> SuggestionBundle:
        content = self.transport.chat_json(suggestions_messages(context))
        return self.transport.parse_json(content, SuggestionBundle)

    def health(self) -> dict:
        return {"provider": self.name, "model": self.settings.gemini_model, "configured": "true"}
