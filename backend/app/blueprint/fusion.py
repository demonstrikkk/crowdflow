"""Architectural fusion engine (Phase 2C, Stage 1 + 2).

Gemini, Florence/OCR and CV are each a *source*, not a ground truth:

  * CV            -> measured geometry (boundaries, gates, regions, walls)
  * Florence/OCR  -> text localisation (labels like "EXIT 12", "CONCOURSE")
  * Gemini        -> architectural semantics + structural relationships

This module arbitrates them into a single explainable verdict per candidate
object (a ``FusionEvidence`` score with provenance). It NEVER invents geometry:
Gemini coordinates are treated as approximate hints used only to associate a
semantic claim with an already-measured CV object.

Fusion is optional and non-destructive. When Gemini is unavailable the engine
still emits pure CV/OCR evidence, so downstream behaviour is unchanged unless
the sources agree.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import Detection, DetectionKind, DetectionState, DocumentType

# Default fusion weights (configurable, so experiments can re-balance them).
W_GEOMETRY = float(os.getenv("FUSION_W_GEOMETRY", "0.40"))
W_OCR = float(os.getenv("FUSION_W_OCR", "0.20"))
W_GEMINI = float(os.getenv("FUSION_W_GEMINI", "0.25"))
W_TOPOLOGY = float(os.getenv("FUSION_W_TOPOLOGY", "0.15"))

# Gemini entity types -> existing venue schema kinds. Unknown/unusable types map
# to None and never create or re-type geometry.
GEMINI_TO_KIND: Dict[str, Optional[str]] = {
    "VENUE_FOOTPRINT": None,
    "FIELD": "FIELD",
    "SEATING_BOWL": "SEATING",
    "SEATING_BLOCK": "SEATING",
    "CONCOURSE": "CONCOURSE",
    "CORRIDOR": "ZONE",
    "WALL": "ROOM",
    "ROOM": "ROOM",
    "STAIR": "STAIR",
    "RAMP": "ZONE",
    "GATE": "ENTRY",
    "ENTRY": "ENTRY",
    "EXIT": "EXIT",
    "EMERGENCY_EXIT": "EMERGENCY_EXIT",
    "CHECKPOINT": "CHECKPOINT",
    "CONCESSION": "ROOM",
    "SERVICE_AREA": "ZONE",
    "VOID": None,
    "OTHER": None,
}

_GATE_KINDS = {"ENTRY", "EXIT", "EMERGENCY_EXIT", "CHECKPOINT", "CONCESSION"}
_STRUCT_KINDS = {"FIELD", "SEATING", "CONCOURSE", "ROOM", "ZONE", "STAIR"}

_GEMINI_OPENING_TYPES = ("ENTRY", "EXIT", "EMERGENCY_EXIT", "GATE", "CHECKPOINT", "CONCESSION")


@dataclass
class FusionEvidence:
    """Explainable per-object verdict, combining all perception sources."""

    geometry: float = 0.0
    ocr: float = 0.0
    gemini: float = 0.0
    topology: float = 0.0
    overall: float = 0.0
    state: DetectionState = DetectionState.DETECTED
    provenance: List[str] = field(default_factory=list)
    label: Optional[str] = None
    kind_hint: Optional[str] = None
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "geometry": round(self.geometry, 3),
            "ocr": round(self.ocr, 3),
            "gemini": round(self.gemini, 3),
            "topology": round(self.topology, 3),
            "overall": round(self.overall, 3),
            "state": self.state.value,
            "provenance": self.provenance,
            "label": self.label,
            "kind_hint": self.kind_hint,
            "reasons": self.reasons,
        }


def _overall(g: float, o: float, gm: float, t: float) -> float:
    return W_GEOMETRY * g + W_OCR * o + W_GEMINI * gm + W_TOPOLOGY * t


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _centroid(bb: Optional[List[float]]) -> Optional[Tuple[float, float]]:
    if not bb or len(bb) < 4:
        return None
    return ((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0)


def _norm_to_px(bbox: List[float], w: int, h: int) -> List[float]:
    return [bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h]


class _Index:
    """Pre-built lookup of OCR text and Gemini entities, normalised to px."""

    def __init__(self, image_meta, gemini_analysis):
        self.w = int(image_meta.width_px)
        self.h = int(image_meta.height_px)
        self.diag = math.hypot(self.w, self.h)
        self.ocr: List[dict] = []  # {text, pos, conf}
        self.regions: List[dict] = []  # {bbox, pos, type, label, conf}
        self.openings: List[dict] = []
        self.connections: List[dict] = []
        self._load(gemini_analysis)

    def _load(self, ga):
        if not ga:
            return
        doc = ga.get("document") or {}
        self.scale_evidence = ga.get("scale", {}).get("scale_source") if "scale" in ga else doc.get("scale_evidence")
        self.document = doc
        for r in ga.get("regions", []) or []:
            if "approximate_bbox" in r:
                bb = r.get("approximate_bbox")
            else:
                bb = r.get("evidence", [{}])[0].get("bbox") if r.get("evidence") else None
            bb = _norm_to_px(bb or [0, 0, 1, 1], self.w, self.h)
            self.regions.append({
                "bbox": bb,
                "pos": _centroid(bb),
                "type": (r.get("type") or "").upper(),
                "label": r.get("label"),
                "conf": float(r.get("confidence") or 0.0),
            })
        for o in ga.get("openings", []) or []:
            if "approximate_bbox" in o:
                bb = o.get("approximate_bbox")
            else:
                bb = o.get("evidence", [{}])[0].get("bbox") if o.get("evidence") else None
            bb = _norm_to_px(bb or [0, 0, 1, 1], self.w, self.h)
            self.openings.append({
                "bbox": bb,
                "pos": _centroid(bb),
                "type": (o.get("type") or "").upper(),
                "label": o.get("label"),
                "conf": float(o.get("confidence") or 0.0),
            })
        self.connections = list(ga.get("connections", ga.get("relationships", [])) or [])

    def nearest_ocr(self, pos, max_px: float) -> Optional[dict]:
        best = None
        best_d = max_px
        for o in self.ocr:
            d = _dist(pos, o["pos"])
            if d < best_d:
                best_d = d
                best = o
        return best

    def nearest_region(self, pos, max_px: float) -> Optional[dict]:
        best = None
        best_d = max_px
        for r in self.regions:
            d = _dist(pos, r["pos"])
            if d < best_d:
                best_d = d
                best = r
        return best

    def nearest_opening(self, pos, max_px: float) -> Optional[dict]:
        best = None
        best_d = max_px
        for o in self.openings:
            d = _dist(pos, o["pos"])
            if d < best_d:
                best_d = d
                best = o
        return best


def annotate(
    detections: List[Detection],
    image_meta,
    gemini_analysis: Optional[dict],
) -> Dict[str, FusionEvidence]:
    """Attach a ``FusionEvidence`` to every GATE/REGION detection.

    Writes ``detection.metadata["fusion"]`` (the serialised score) and returns
    a map keyed by detection id for callers that need the object directly.
    Gemini coordinates are only used to associate claims with measured objects.
    """
    idx = _Index(image_meta, gemini_analysis)
    w, h = idx.w, idx.h
    text = [d for d in detections if d.kind == DetectionKind.TEXT and d.text]
    idx.ocr = [{"text": d.text, "pos": _centroid(list(d.geometry.bbox)) or (0, 0), "conf": d.confidence}
               for d in text if d.geometry.bbox]

    results: Dict[str, FusionEvidence] = {}
    for d in detections:
        if d.kind == DetectionKind.GATE:
            fs = _fuse_gate(d, idx, w, h)
        elif d.kind == DetectionKind.REGION:
            fs = _fuse_region(d, idx, w, h)
        else:
            continue
        results[d.id] = fs
        d.metadata = dict(d.metadata or {})
        d.metadata["fusion"] = fs.as_dict()
    return results


def _fuse_gate(g: Detection, idx: _Index, w: int, h: int) -> FusionEvidence:
    bb = list(g.geometry.bbox) if g.geometry.bbox else None
    pos = _centroid(bb) or (0, 0)
    width = float(g.metadata.get("width_px", 16))
    side = str(g.metadata.get("side", "N"))
    side_len = float(w if side in ("N", "S") else h) or 1.0
    frac = width / max(1.0, side_len)

    # geometry credibility (the '28 gates' killer): a sane opening width on the
    # boundary is credible; a whole-side run or a sliver is not.
    if width < 4.0 or frac > 0.25:
        geometry = 0.15
        reasons = [f"implausible width {width}px ({frac:.0%} of side)"]
    else:
        geometry = round(max(0.0, min(1.0, 0.40 + g.confidence * 0.60)), 3)
        reasons = [f"credible boundary opening {width}px"]

    ocr = idx.nearest_ocr(pos, max_px=idx.diag * 0.06 + 40)
    gem = idx.nearest_opening(pos, max_px=idx.diag * 0.06)

    fs = FusionEvidence()
    fs.geometry = geometry
    fs.overall = _overall(geometry, 0.0, 0.0, 0.0)

    if ocr:
        fs.ocr = round(ocr["conf"], 3)
        fs.label = ocr["text"]
        fs.provenance.append("FLORENCE")
        fs.reasons.append(f"OCR '{ocr['text']}' nearby")
    if gem:
        fs.gemini = round(gem["conf"] * 0.9, 3)
        fs.label = fs.label or gem.get("label")
        kh = GEMINI_TO_KIND.get(gem["type"])
        fs.kind_hint = kh if kh in _GATE_KINDS else None
        fs.provenance.append("GEMINI")
        fs.reasons.append(f"Gemini {gem['type']} nearby")
        fs.topology = 0.5 if gem["type"] in _GEMINI_OPENING_TYPES else 0.0

    fs.overall = _overall(fs.geometry, fs.ocr, fs.gemini, fs.topology)

    # Decision: absurd geometry always rejects; otherwise require support from
    # OCR/Gemini to confirm, else fall back to a clean geometric read.
    if fs.geometry < 0.3:
        fs.state = DetectionState.REJECTED
        fs.reasons.append("no credible geometry")
    elif fs.ocr >= 0.4 or fs.gemini >= 0.4:
        fs.state = DetectionState.CONFIRMED if fs.overall >= 0.5 else DetectionState.UNCERTAIN
        fs.reasons.append(f"fused confidence {fs.overall:.0%}")
    elif fs.geometry >= 0.55:
        fs.state = DetectionState.CONFIRMED
        fs.reasons.append("clean geometric opening, no semantic evidence required")
    else:
        fs.state = DetectionState.UNCERTAIN
        fs.reasons.append("marginal geometry without OCR/Gemini support")
    return fs


def _fuse_region(r: Detection, idx: _Index, w: int, h: int) -> FusionEvidence:
    bb = list(r.geometry.bbox) if r.geometry.bbox else None
    pos = _centroid(bb) or (0, 0)
    area = ((bb[2] - bb[0]) * (bb[3] - bb[1])) if bb else 0.0
    area_frac = area / max(1.0, float(w * h))
    bw = (bb[2] - bb[0]) if bb else 0.0
    bh = (bb[3] - bb[1]) if bb else 0.0
    aspect = (bw / max(1.0, bh)) if bh >= bw else (bh / max(1.0, bw))

    if area_frac < 0.005 or aspect > 15.0 or r.confidence < 0.35:
        geometry = 0.15
        reasons = ["degenerate region (sliver or extreme aspect)"]
    else:
        geometry = round(max(0.0, min(1.0, 0.35 + area_frac * 0.5 + r.confidence * 0.3)), 3)
        reasons = [f"enclosed region, {area_frac:.0%} coverage"]

    ocr = idx.nearest_ocr(pos, max_px=idx.diag * 0.10 + 40)
    gem = idx.nearest_region(pos, max_px=idx.diag * 0.10)

    fs = FusionEvidence()
    fs.geometry = geometry
    fs.overall = _overall(geometry, 0.0, 0.0, 0.0)

    if ocr:
        fs.ocr = round(ocr["conf"], 3)
        fs.label = fs.label or ocr["text"]
        fs.provenance.append("FLORENCE")
    if gem:
        fs.gemini = round(gem["conf"], 3)
        fs.label = fs.label or gem.get("label")
        kh = GEMINI_TO_KIND.get(gem["type"])
        fs.kind_hint = kh if kh in _STRUCT_KINDS else None
        fs.provenance.append("GEMINI")
        # topology: is this region an endpoint of a Gemini connection?
        for c in idx.connections:
            # Connections could be old schema `source_region` or new `source_id`
            src = c.get("source_region") or c.get("source_id") or ""
            dst = c.get("destination_region") or c.get("target_id") or ""
            if src.upper() == gem["type"] or dst.upper() == gem["type"]:
                fs.topology = 0.5
                break
        fs.reasons.append(f"Gemini {gem['type']}")

    fs.overall = _overall(fs.geometry, fs.ocr, fs.gemini, fs.topology)
    fs.state = DetectionState.REJECTED if fs.geometry < 0.3 else DetectionState.CONFIRMED
    return fs


# --------------------------------------------------------------------------- #
#  Scale evidence (Gemini contributes evidence, never invents m/px)
# --------------------------------------------------------------------------- #
_SCALE_RATIO_RE = re.compile(r"(?:scale|ratio|1)\s*[:/]\s*(\d{1,5})", re.IGNORECASE)
_METRE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m(?:etres?|eters?)?\b", re.IGNORECASE)


def extract_scale_evidence(gemini_analysis: Optional[dict]) -> List[str]:
    """Return human/structured scale hints found in the Gemini analysis."""
    if not gemini_analysis:
        return []
    doc = gemini_analysis.get("document") or {}
    text = str(doc.get("scale_evidence") or "")
    notes = " ".join(gemini_analysis.get("notes") or [])
    hay = f"{text} {notes}"
    found: List[str] = []
    m = _SCALE_RATIO_RE.search(hay)
    if m:
        found.append(f"gemini scale ratio 1:{m.group(1)}")
    m = _METRE_RE.search(hay)
    if m:
        found.append(f"gemini dimension {m.group(1)}m")
    if found:
        found.append(f"gemini scale evidence: '{text[:120]}'")
    return list(dict.fromkeys(found))


def document_type_from_gemini(gemini_analysis: Optional[dict]) -> Optional[Tuple[DocumentType, float, str]]:
    """Extract (DocumentType, confidence, reason) from Gemini, if confident.

    Returns None when absent, invalid or below the confidence floor so the
    deterministic doc-classifier remains the default.
    """
    if not gemini_analysis:
        return None
    doc = gemini_analysis.get("document") or {}
    raw = doc.get("type") or doc.get("drawing_type")
    conf = float(doc.get("confidence") or 0.0)
    if not raw or conf < 0.5:
        return None
    try:
        dtype = DocumentType(raw)
    except ValueError:
        return None
    reason = (doc.get("reasoning") or "")[:160]
    return dtype, conf, reason
