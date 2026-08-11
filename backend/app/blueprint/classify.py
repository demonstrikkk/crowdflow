"""Semantic classification of recovered geometry elements.

Priority order:

  1. OCR text labels -> explicit kind (e.g. "EXIT 3", "FOOD").
  2. Geometric heuristics: boundary openings become gates (ENTRY/EXIT/
     EMERGENCY_EXIT), interior wall crossings become INTERSECTION nodes.

No model API is called; huggingface_hub based zero-shot classification is
deliberately not wired in to keep the import pipeline local and deterministic.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

_KIND_KEYWORDS = [
    ("EMERGENCY_EXIT", ("EMERGENCY", "FIRE", "EVACUATION")),
    ("EXIT", ("EXIT", "OUT", "SORTIE", "SALIDA")),
    ("ENTRY", ("ENTRY", "GATE", "IN", "ENTRANCE", "WELCOME")),
    ("CONCESSION", ("FOOD", "CAFE", "BAR", "DRINK", "CONCESSION", "VENDOR", "SHOP")),
    ("CHECKPOINT", ("TOILET", "WC", "RESTROOM", "FIRST AID", "MEDIC", "INFO", "LOST")),
    ("ZONE", ("ZONE", "AREA", "SEAT", "PIT", "MAIN STAGE", "DANCE")),
]


def classify_text(text: str) -> Tuple[str, float]:
    upper = text.upper()
    for kind, keywords in _KIND_KEYWORDS:
        for kw in keywords:
            if kw in upper:
                return kind, 0.9
    return "INTERSECTION", 0.4


def label_to_kind(text: str) -> str:
    return classify_text(text)[0]


def classify_boundary_openings(openings: List[dict], perimeter_count: int) -> List[dict]:
    """Assign gate kinds to boundary openings.

    Deterministic rule: openings on the longest sides first become ENTRY, then
    EXIT, and surplus openings become EMERGENCY_EXIT so there is always at
    least one entry and one exit.
    """
    if not openings:
        return []

    result = []
    n = len(openings)

    # longest sides get priority (roughly longest = the side with the widest span)
    order = sorted(range(n), key=lambda i: openings[i]["width_px"], reverse=True)

    for i, idx in enumerate(order):
        entry = openings[idx].copy()
        if i < max(1, n // 2):
            entry["kind"] = "ENTRY"
            entry["confidence"] = 0.45
        elif i == n - 1 and n >= 5:
            entry["kind"] = "EMERGENCY_EXIT"
            entry["confidence"] = 0.4
        else:
            entry["kind"] = "EXIT"
            entry["confidence"] = 0.45
        result.append(entry)
    return result


def assign_interior_kinds(walls: List[Tuple[Tuple[int, int], Tuple[int, int]]]) -> List[dict]:
    """Place INTERSECTION nodes at interior wall crossings/endpoints."""
    nodes: List[dict] = []
    xs = [w[0][0] for w in walls] + [w[1][0] for w in walls]
    ys = [w[0][1] for w in walls] + [w[1][1] for w in walls]
    # crossing candidates: each wall endpoint + midpoint of each wall
    for xa, ya, xb, yb in [(a[0][0], a[0][1], a[1][0], a[1][1]) for a in walls]:
        nodes.append({"position": (int((xa + xb) / 2), int((ya + yb) / 2)), "kind": "INTERSECTION", "confidence": 0.5})
        nodes.append({"position": (xa, ya), "kind": "INTERSECTION", "confidence": 0.5})
        nodes.append({"position": (xb, yb), "kind": "INTERSECTION", "confidence": 0.5})
    # dedupe within 6px
    deduped: List[dict] = []
    for node in nodes:
        px, py = node["position"]
        if any(abs(px - d["position"][0]) <= 6 and abs(py - d["position"][1]) <= 6 for d in deduped):
            continue
        deduped.append(node)
    return deduped
