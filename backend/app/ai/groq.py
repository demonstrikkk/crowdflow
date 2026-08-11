"""Groq provider (PRIMARY). Uses Groq's OpenAI-compatible API, server-side."""
from __future__ import annotations

from ..ai.base import (
    AIProvider,
    ParsedScenario,
    SimulationExplanation,
    SuggestionBundle,
)
from ..ai.client import OpenAICompatTransport
from ..ai.config import GROQ_BASE_URL, AISettings
from ..ai.prompts import (
    explain_messages,
    parse_scenario_messages,
    suggestions_messages,
)


class GroqProvider(AIProvider):
    name = "groq"

    def __init__(self, settings: AISettings):
        self.settings = settings
        self.transport = OpenAICompatTransport(
            settings, GROQ_BASE_URL, settings.groq_api_key, settings.groq_model
        )

    def parseScenario(self, query: str, venue_context: str) -> ParsedScenario:
        content = self.transport.chat_json(parse_scenario_messages(query, venue_context))
        return self.transport.parse_json(content, ParsedScenario)

    def explainSimulation(
        self, metrics_summary: str, bottlenecks_summary: str
    ) -> SimulationExplanation:
        content = self.transport.chat_json(explain_messages(metrics_summary, bottlenecks_summary))
        return self.transport.parse_json(content, SimulationExplanation)

    def generateScenarioSuggestions(self, context: str) -> SuggestionBundle:
        content = self.transport.chat_json(suggestions_messages(context))
        return self.transport.parse_json(content, SuggestionBundle)

    def health(self) -> dict:
        return {"provider": self.name, "model": self.settings.groq_model, "configured": "true"}
