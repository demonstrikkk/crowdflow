"""AI provider abstraction.

The provider interface is deliberately tiny and provider-agnostic. The rest of
the application only ever depends on this interface, never on Groq or Gemini
specifics. All three capabilities funnel natural language into *structured*
output that the application validates before it is allowed to affect a
simulation (the LLM never executes code and never invents simulation results).
"""
from __future__ import annotations

import abc
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models import IncidentSpec, WeatherSpec


# --------------------------------------------------------------------------- #
#  Errors
# --------------------------------------------------------------------------- #
class AIError(Exception):
    """Base error surfaced to the API layer (message is safe to show)."""


class AINotConfigured(AIError):
    pass


class AIProviderFailure(AIError):
    """The upstream provider returned an error (timeout, 429, 5xx, ...)."""


class AIValidationError(AIError):
    """The provider returned output we could not parse/validate."""


class AITimeoutError(AIError):
    pass


# --------------------------------------------------------------------------- #
#  Structured contracts (what the LLM is allowed to say)
# --------------------------------------------------------------------------- #


class ScenarioDelta(BaseModel):
    """A *validated* mutation of an existing scenario produced from a query.

    Every field is optional; an empty delta means "no change". The backend
    re-validates this against the real venue/scenario before any simulation.
    """

    summary: str = Field(default="", description="human-readable interpretation")
    notes: List[str] = Field(default_factory=list)
    name_suffix: str = Field(default="", max_length=80)
    crowd_size: Optional[int] = Field(default=None, gt=0)
    event_end_delta_minutes: Optional[float] = Field(
        default=None, description="shift the exit surge (negative = earlier)"
    )
    gate_distribution: Optional[Dict[str, float]] = None
    exit_distribution: Optional[Dict[str, float]] = None
    destination_distribution: Optional[Dict[str, float]] = None
    close_gates: List[str] = Field(default_factory=list)
    open_gates: List[str] = Field(default_factory=list)
    close_edges: List[str] = Field(default_factory=list)
    open_edges: List[str] = Field(default_factory=list)
    incident: Optional[IncidentSpec] = None
    weather: Optional[WeatherSpec] = None

    @model_validator(mode="after")
    def _distributions_sum_to_one(self) -> "ScenarioDelta":
        for name in (
            "gate_distribution",
            "exit_distribution",
            "destination_distribution",
        ):
            dist = getattr(self, name)
            if dist and abs(sum(dist.values()) - 1.0) > 1e-3:
                raise ValueError(f"{name} must sum to ~1.0 (got {sum(dist.values()):.3f})")
        return self


class ParsedScenario(BaseModel):
    """LLM response contract for parseScenario (wrapped for robust parsing)."""

    scenario_delta: ScenarioDelta
    confidence: float = Field(default=0.5, ge=0, le=1)
    reasoning: str = Field(default="")


class TryAction(BaseModel):
    type: str = Field(description="intervention type the app understands")
    description: str
    parameters: Dict[str, object] = Field(default_factory=dict)


class SimulationExplanation(BaseModel):
    """LLM response contract for explainSimulation (grounded in real metrics)."""

    summary: str
    cause: str = Field(description="what the data shows is causing it")
    try_actions: List[TryAction] = Field(default_factory=list)


class ScenarioSuggestion(BaseModel):
    title: str
    description: str
    type: str = "REDIRECT"
    parameters: Dict[str, object] = Field(default_factory=dict)
    why: str = Field(default="", description="why this might help")


class SuggestionBundle(BaseModel):
    suggestions: List[ScenarioSuggestion] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Provider interface
# --------------------------------------------------------------------------- #
class AIProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def parseScenario(self, query: str, venue_context: str) -> ParsedScenario:
        """Convert a natural-language question into a structured scenario delta."""

    @abc.abstractmethod
    def explainSimulation(
        self, metrics_summary: str, bottlenecks_summary: str
    ) -> SimulationExplanation:
        """Explain what the simulation data shows and what to try next."""

    @abc.abstractmethod
    def generateScenarioSuggestions(self, context: str) -> SuggestionBundle:
        """Suggest realistic scenario variations worth simulating."""

    def health(self) -> Dict[str, str]:
        """Cheap, non-network provider identity (used for status readouts)."""
        return {"provider": self.name, "configured": "true"}


# --------------------------------------------------------------------------- #
#  Robust JSON extraction (models wrap answers in fences / prose sometimes)
# --------------------------------------------------------------------------- #
def extract_json_object(text: str) -> dict:
    """Pull the first JSON object out of model output, tolerating fences."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip("\n")
    start = text.find("{")
    if start < 0:
        raise AIValidationError("provider output contained no JSON object")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AIValidationError("unbalanced JSON object in provider output")
