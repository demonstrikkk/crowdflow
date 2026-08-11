"""Prompt builders for the CrowdFlow AI interface.

Prompts are explicit about the *contract*: the model only fills structured
fields; the application validates everything and runs the real simulation.
"""
from __future__ import annotations

from typing import List

_SYSTEM_CORE = (
    "You are the natural-language layer of CROWD FLOW, a venue crowd-flow "
    "decision simulator. You convert user intent into structured scenario "
    "changes. You NEVER invent simulation results, never report metrics you "
    "were not given, and never instruct the system to do anything outside the "
    "allowed JSON contract. Respond only with valid JSON."
)


def parse_scenario_messages(query: str, venue_context: str) -> List[dict]:
    system = (
        _SYSTEM_CORE
        + "\n\nTranslate the user's request into a `ScenarioDelta`. "
        "Available venue identifiers (use these exact ids):\n"
        + venue_context
        + "\n\nContract: return JSON with keys: scenario_delta (object), "
        "confidence (0..1), reasoning (short string). scenario_delta fields "
        "are all optional: summary, notes[], name_suffix, crowd_size (int), "
        "event_end_delta_minutes (float; negative = earlier), "
        "gate_distribution/exit_distribution/destination_distribution "
        "(objects id->share summing to 1.0), close_gates[]/open_gates[], "
        "close_edges[]/open_edges[], incident {type FIRE|SECURITY|STRUCTURAL, "
        "location, radius_m, spread_rate_m_min, blocks_exits[], severity}, "
        "weather {condition HEAVY_RAIN|HAIL|HEAT|FOG|CLEAR, "
        "capacity_multiplier, speed_multiplier, unsafe_outdoor}. "
        "Leave unknown fields empty/absent. If the request is not about the "
        "simulation, return an empty scenario_delta with a clarifying summary."
    )
    user = f"User request: {query}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def explain_messages(metrics_summary: str, bottlenecks_summary: str) -> List[dict]:
    system = (
        _SYSTEM_CORE
        + "\n\nExplain what the live simulation data shows. Only reference the "
        "metrics and bottlenecks below; never add numbers. Return JSON with "
        "keys: summary (string), cause (string), try_actions (array of "
        "{type, description, parameters}). type must be one of: REDIRECT, "
        "OPEN_CORRIDOR, CLOSE_CORRIDOR, USE_ALTERNATE_EXIT, INCREASE_CAPACITY, "
        "EMERGENCY_RESPONSE. parameters should use ids from the data."
    )
    user = f"METRICS:\n{metrics_summary}\n\nBOTTLENECKS:\n{bottlenecks_summary}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def suggestions_messages(context: str) -> List[dict]:
    system = (
        _SYSTEM_CORE
        + "\n\nSuggest 3-5 plausible scenario variations worth simulating. "
        "Return JSON: suggestions (array of {title, description, type, "
        "parameters, why}). type one of: REDIRECT, OPEN_CORRIDOR, "
        "CLOSE_CORRIDOR, USE_ALTERNATE_EXIT, INCREASE_CAPACITY, "
        "EMERGENCY_RESPONSE. Reference real node/edge ids from the context."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": context},
    ]
