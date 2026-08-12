"""Semantic interpretation: detections -> venue-relevant semantic elements.

Combines geometry, OCR text and spatial context (not text alone):

  * enclosed REGION + label + fill/hatching  -> FIELD / SEATING / CONCOURSE /
    ROOM(kind) / ZONE / STAIR
  * perimeter GATE + label/width/side        -> ENTRY / EXIT / EMERGENCY_EXIT
  * wall gaps (DOOR)                         -> interior openings
  * walkable CORRIDOR polylines              -> physical pathway geometry

The output feeds the existing graph builder (``gates`` / ``interior`` dicts
with the same schema as today) plus a richer ``structures`` set for spatial
reconstruction. Everything is expressed in normalised pixels here; the
reconstruction stage converts to venue metres through ``coordinates``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..models import Detection, DetectionKind, DetectionState, GeometryType
from . import classify

_GATE_KINDS = ("ENTRY", "EXIT", "EMERGENCY_EXIT")
_KIND_KEYWORDS = [
    ("EMERGENCY_EXIT", ("EMERGENCY", "FIRE", "EVACUATION")),
    ("EXIT", ("EXIT", "OUT", "SORTIE", "SALIDA")),
    ("ENTRY", ("ENTRY", "GATE", "IN", "ENTRANCE", "WELCOME", "TURNSTILE")),
    ("CONCESSION", ("FOOD", "CAFE", "CAFÉ", "BAR", "DRINK", "CONCESSION", "VENDOR", "SHOP", "KIOSK", "RESTAURANT")),
    ("CHECKPOINT", ("TOILET", "WC", "RESTROOM", "FIRST AID", "MEDIC", "INFO", "LOST", "SECURITY", "TICKET", "BOOTH")),
    ("SEATING", ("STAND", "STALL", "TRIBUNE", "BLEACHER", "SEAT", "GRANDSTAND")),
    ("CONCOURSE", ("CONCOURSE", "PLAZA", "ESPLANADE", "HALL")),
    ("FIELD", ("FIELD", "PITCH", "PLAYING", "ARENA FLOOR")),
    ("ZONE", ("ZONE", "AREA", "PIT", "STAGE", "DANCE", "HOSPITALITY")),
    ("STAIR", ("STAIR", "STAIRS", "ESCALATOR", "STEP", "TREAD")),
]
_ID_RE = re.compile(r"[A-Z]{1,3}[_\-]?\d+|[A-Z]{2,}[0-9_]+", re.IGNORECASE)


@dataclass
class SemanticOutput:
    gates: List[dict] = field(default_factory=list)      # graph.build_venue gate schema
    interior: List[dict] = field(default_factory=list)   # interior nodes for the graph
    structures: List[dict] = field(default_factory=list)  # spatial structures (polygons, px)
    walls: List[Tuple[Tuple[float, float], Tuple[float, float], float]] = field(default_factory=list)
    corridors: List[List[Tuple[float, float]]] = field(default_factory=list)  # px polylines
    openings_extra: List[dict] = field(default_factory=list)  # DOOR openings
    warnings: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)  # review-only candidates (kind/id)
    footprint_bbox: Optional[Tuple[float, float, float, float]] = None  # source ink footprint (px)


def _bbox(d: Detection) -> Tuple[float, float, float, float]:
    return d.geometry.bbox if d.geometry.bbox else (0, 0, 0, 0)


def _centroid(d: Detection) -> Tuple[float, float]:
    g = d.geometry
    if g.point is not None:
        return g.point.x, g.point.y
    if g.polygon:
        pts = g.polygon
        return (sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))
    if g.polyline:
        pts = g.polyline
        return (sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))
    b = g.bbox or (0, 0, 0, 0)
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _area_px(d: Detection) -> float:
    b = d.geometry.bbox
    if not b:
        return 0.0
    return max(0.0, (b[2] - b[0]) * (b[3] - b[1]))


def _classify_text(text: str) -> Tuple[Optional[str], float]:
    upper = (text or "").upper()
    for kind, keywords in _KIND_KEYWORDS:
        for kw in keywords:
            if kw in upper:
                return kind, 0.9
    return None, 0.0


def _gate_id(text: str) -> Optional[str]:
    if not text:
        return None
    m = _ID_RE.search(text.upper().strip())
    if m:
        return m.group(0).replace("-", "_")
    return None


def _footprint_dims(
    regions: List[Detection],
    boundaries: List[Detection],
    width_px: float,
    height_px: float,
) -> Tuple[float, float, Optional[Tuple[float, float, float, float]]]:
    """Actual footprint (ink) side lengths in px, falling back to the frame."""
    best = None
    for b in boundaries:
        bb = b.geometry.bbox or (0, 0, 0, 0)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        if w > 0 and h > 0 and (best is None or w * h > best[0] * best[1]):
            best = (w, h, bb)
    if best is None:
        for r in regions:
            bb = r.geometry.bbox or (0, 0, 0, 0)
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            if w > 0 and h > 0 and (best is None or w * h > best[0] * best[1]):
                best = (w, h, bb)
    if best is not None:
        return best[0], best[1], best[2]
    return float(width_px), float(height_px), None


def _gate_state(g: Detection, side_len: float) -> DetectionState:
    """Evidence gate for a perimeter opening candidate (Phase 2C item 3).

    A gap run along the perimeter is only a *credible* opening when its width
    is a sane fraction of the footprint side and it carries supporting evidence
    (real gap geometry + label or tight width). Wide false runs from hatched
    stands / line fragments (the '28 gates' failure) are rejected here and stay
    review candidates only - they never become VenueSpatialModel openings.
    """
    width_px = float(g.metadata.get("width_px", 16))
    conf = g.confidence
    frac = width_px / max(1.0, side_len)
    if width_px < 4.0 or frac > 0.22 or conf < 0.35:
        return DetectionState.REJECTED
    label = str(g.metadata.get("label") or "").strip()
    if frac <= 0.10 or label:
        return DetectionState.CONFIRMED
    return DetectionState.REJECTED


def _region_state(region: Detection, area_frac: float, aspect: float) -> DetectionState:
    """Evidence gate for an enclosed region candidate."""
    if area_frac < 0.005 or aspect > 15.0 or region.confidence < 0.35:
        return DetectionState.REJECTED
    return DetectionState.CONFIRMED


def _polygon_to_np(d: Detection) -> Optional[np.ndarray]:
    if d.geometry.type != GeometryType.POLYGON or not d.geometry.polygon:
        return None
    return np.array([(p.x, p.y) for p in d.geometry.polygon])


def _point_in_polygon(x: float, y: float, poly: np.ndarray) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            inside = not inside
    return inside


def _box_area(box: Tuple[float, float, float, float]) -> float:
    return max(0.0, (box[2] - box[0]) * (box[3] - box[1]))


def _box_intersection_area(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def _box_contained_in_polygon(box: Tuple[float, float, float, float], poly: np.ndarray) -> bool:
    """>= 3 of the 4 corners inside the polygon -> the label sits in the region."""
    corners = ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))
    return sum(1 for x, y in corners if _point_in_polygon(x, y, poly)) >= 3


def _region_evidence(region: Detection, all_dets: List[Detection]) -> Dict[str, float]:
    """Per-region evidence: hatch overlap, fill, aspect, area fraction."""
    b = region.geometry.bbox or (0, 0, 0, 0)
    bw, bh = b[2] - b[0], b[3] - b[1]
    aspect = (bw / max(1.0, bh)) if bh >= bw else (bh / max(1.0, bw))
    area = _area_px(region)
    return {"area": area, "aspect": aspect, "w": bw, "h": bh, "hatch": 0.0, "fill": 0.0}


def interpret(
    detections: List[Detection],
    width_px: int,
    height_px: int,
) -> SemanticOutput:
    out = SemanticOutput()
    footprint_area = width_px * height_px

    regions = [d for d in detections if d.kind == DetectionKind.REGION]
    gates = [d for d in detections if d.kind == DetectionKind.GATE]
    boundaries = [d for d in detections if d.kind == DetectionKind.BOUNDARY]
    foot_w, foot_h, src_foot = _footprint_dims(regions, boundaries, width_px, height_px)
    out.footprint_bbox = src_foot
    doors = [d for d in detections if d.kind == DetectionKind.DOOR]
    walls = [d for d in detections if d.kind == DetectionKind.WALL]
    stairs = [d for d in detections if d.kind == DetectionKind.STAIR]
    corridors = [d for d in detections if d.kind == DetectionKind.CORRIDOR]
    labels = [d for d in detections if d.kind == DetectionKind.TEXT and d.text]

    # Gate labels are allocated FIRST (point-proximity, tight window): a label
    # like "GATE A" must attach to the perimeter opening, not be swallowed by a
    # large interior region. Regions then consume only the unused labels. Each
    # label is bound once (strongest geometric claim wins) so false CV gaps near
    # one opening do not all copy the same gate number.
    gate_label_map: Dict[int, Optional[Detection]] = {}
    if gates and labels:
        candidates = []
        for g in gates:
            scored = _nearest_label_scored(g, labels, max_dist=90)
            if scored:
                candidates.append((scored[1], g, scored[0]))
        used_labels: set = set()
        for score, g, lab in sorted(candidates, key=lambda t: t[0], reverse=True):
            if lab.id in used_labels:
                continue
            used_labels.add(lab.id)
            gate_label_map[id(g)] = lab
    used_label_ids = {lbl.id for lbl in gate_label_map.values() if lbl is not None}
    region_labels = [
        l for l in labels
        if l.id not in used_label_ids and _classify_text(l.text)[0] not in _GATE_KINDS
    ]

    # ------------------------------------------------------------------ #
    #  type enclosed regions using text + geometry + hatching context
    # ------------------------------------------------------------------ #
    for region in regions:
        b = region.geometry.bbox or (0, 0, 0, 0)
        bw, bh = b[2] - b[0], b[3] - b[1]
        area = _area_px(region)
        area_frac = area / max(1.0, footprint_area)
        aspect = (bw / max(1.0, bh)) if bh >= bw else (bh / max(1.0, bw))
        cx, cy = _centroid(region)

        # hatch evidence: fraction of stair detections inside the region
        poly = _polygon_to_np(region)
        hatch = 0
        if poly is not None and stairs:
            for s in stairs:
                sx, sy = _centroid(s)
                if _point_in_polygon(sx, sy, poly):
                    hatch += 1
        hatch_frac = hatch / max(1, len(stairs)) if stairs else 0.0

        label = _nearest_label(region, region_labels, max_dist=160)
        text_kind, text_conf = _classify_text(label.text) if label else (None, 0.0)
        state = _region_state(region, area_frac, aspect)
        region.state = state
        fs = region.metadata.get("fusion") or {}

        kind: str
        graph_kind: str = "INTERSECTION"
        fusion_kind = fs.get("kind_hint")
        fusion_conf = float(fs.get("gemini") or 0.0)
        fusion_used = False
        override_kind = str(region.metadata.get("kind") or "").upper()
        if override_kind in ("FIELD", "SEATING", "CONCOURSE", "ROOM", "ZONE", "STAIR"):
            # human correction from the review overlay wins over geometry/OCR
            kind = override_kind
            confidence = round(max(region.confidence, 0.85), 2)
        elif text_kind and text_kind in ("FIELD", "SEATING", "CONCOURSE", "STAIR", "ZONE"):
            kind = text_kind
            confidence = round(max(region.confidence, text_conf), 2)
        elif text_kind in ("CONCESSION", "CHECKPOINT"):
            kind = "ROOM"
            graph_kind = "CHECKPOINT" if text_kind == "CHECKPOINT" else "CONCESSION"
            confidence = round(max(region.confidence, text_conf), 2)
        elif fusion_kind in ("FIELD", "SEATING", "CONCOURSE", "ZONE", "STAIR", "ROOM") and fusion_conf >= 0.5:
            # Gemini provides architectural semantics; geometry (the region) is
            # already measured by CV. We only re-type, never fabricate geometry.
            kind = fusion_kind
            confidence = round(max(0.5, fusion_conf), 2)
            fusion_used = True
        elif area_frac >= 0.06 and hatch_frac >= 0.4:
            kind = "SEATING"
            confidence = round(region.confidence, 2)
        elif area_frac >= 0.08 and (bw >= 0.45 * width_px or bh >= 0.45 * height_px):
            kind = "FIELD" if hatch_frac < 0.25 else "SEATING"
            confidence = round(region.confidence, 2)
        elif area_frac >= 0.03 and aspect >= 3.0:
            kind = "CONCOURSE"
            confidence = round(max(0.5, region.confidence - 0.05), 2)
        elif area_frac >= 0.03:
            kind = "ZONE"
            confidence = round(region.confidence, 2)
        else:
            kind = "ROOM"
            confidence = round(max(0.45, region.confidence - 0.1), 2)

        polygon_px = [(p.x, p.y) for p in region.geometry.polygon]
        metadata: Dict = {"source": "SEMANTIC", "area_px": round(area, 1)}
        if fusion_used:
            metadata.update({
                "source": "FUSED",
                "kind_evidence": fs.get("provenance") or ["GEMINI"],
                "kind_hint": fusion_kind,
            })
        if fs:
            metadata["fusion"] = fs
        if label:
            metadata["label"] = label.text

        if state == DetectionState.REJECTED:
            out.rejected.append(f"REGION/{region.id} (sliver or degenerate: area_frac={area_frac:.3f})")
            continue

        out.structures.append({
            "kind": kind,
            "graph_kind": graph_kind or _graph_kind(kind),
            "polygon_px": polygon_px,
            "centroid_px": (round(cx, 2), round(cy, 2)),
            "confidence": confidence,
            "label": label.text if label else None,
            "state": state.value,
            "source": "FUSED" if fusion_used else "CV",
            "source_bbox": list(region.geometry.bbox) if region.geometry.bbox else None,
            "metadata": metadata,
        })

    # ------------------------------------------------------------------ #
    #  gates: OCR label + width/side -> kind
    # ------------------------------------------------------------------ #
    gate_by_width = sorted(gates, key=lambda g: -(_area_px(g)))
    labelled_gates: List[dict] = []
    unlabelled: List[dict] = []
    for i, g in enumerate(gates):
        label = gate_label_map.get(id(g))
        label_text = str(g.metadata.get("label") or "").strip() or (label.text if label else None)
        side = g.metadata.get("side", "N")
        side_len = foot_w if side in ("N", "S") else foot_h
        geom_state = _gate_state(g, side_len)
        fs = g.metadata.get("fusion") or {}
        override_kind = str(g.metadata.get("kind") or "").upper()
        if override_kind in _GATE_KINDS:
            state = DetectionState.CONFIRMED  # human correction wins
        elif geom_state == DetectionState.REJECTED:
            state = DetectionState.REJECTED  # geometry is the hard gate
        elif fs:
            try:
                state = DetectionState(fs.get("state", "CONFIRMED"))
            except ValueError:
                state = geom_state
        else:
            state = geom_state
        g.state = state
        kind: str
        conf = g.confidence
        text_kind, text_conf = (None, 0.0)
        if label_text:
            text_kind, text_conf = _classify_text(label_text)
        if override_kind in _GATE_KINDS:
            # human correction from the review overlay wins over OCR/geometry
            kind = override_kind
            conf = round(max(conf, 0.85), 2)
        elif text_kind and text_kind in _GATE_KINDS:
            kind = text_kind
            conf = round(max(conf, text_conf), 2)
        elif fs and fs.get("kind_hint") in _GATE_KINDS and (
            float(fs.get("ocr", 0)) >= 0.4 or float(fs.get("gemini", 0)) >= 0.4
        ):
            kind = fs["kind_hint"]
            conf = round(max(conf, float(fs.get("overall", 0))), 2)
        else:
            kind = "ENTRY"  # provisional; reassigned below by width priority
        b = g.geometry.bbox or (0, 0, 0, 0)
        entry = {
            "id": _gate_id(label_text) if label_text else None,
            "position": _centroid(g),
            "side": side,
            "width_px": g.metadata.get("width_px", 16),
            "kind": kind,
            "confidence": conf,
            "label": label_text,
            "state": state.value,
            "source": "FUSED" if fs else "CV",
            "source_bbox": list(b) if b else None,
            "fusion": fs or {"provenance": ["CV"]},
            "_idx": i,
            "_sort": _area_px(g),
            "_override": bool(override_kind in _GATE_KINDS),
        }
        if label_text or override_kind in _GATE_KINDS:
            labelled_gates.append(entry)
        else:
            unlabelled.append(entry)

    # deterministic assignment for unlabelled gates: widest -> ENTRY, last -> EMERGENCY
    all_gates = sorted(labelled_gates + unlabelled, key=lambda g: -g["_sort"])
    n = len(all_gates)
    for i, g in enumerate(all_gates):
        if g.get("_override") or g["label"] is not None:
            continue
        if i == 0 and n >= 2:
            g["kind"] = "ENTRY"
            g["confidence"] = round(max(0.45, g["confidence"]), 2)
        elif i == n - 1 and n >= 5:
            g["kind"] = "EMERGENCY_EXIT"
            g["confidence"] = round(max(0.4, g["confidence"]), 2)
        else:
            g["kind"] = "EXIT"
            g["confidence"] = round(max(0.45, g["confidence"]), 2)
    for g in all_gates:
        g.pop("_idx", None)
        g.pop("_sort", None)
        g.pop("_override", None)
    rejected_gates = [g for g in all_gates if g["state"] == DetectionState.REJECTED.value]
    confirmed_gates = [g for g in all_gates if g["state"] != DetectionState.REJECTED.value]
    for g in rejected_gates:
        out.rejected.append(f"GATE/{g['id'] or '?'} {g['label'] or ''} side={g['side']} width={g['width_px']}px")
    out.gates = _dedupe_gate_ids(confirmed_gates)

    # ------------------------------------------------------------------ #
    #  interior nodes: one per structure centroid (typed for the graph)
    # ------------------------------------------------------------------ #
    node_seq = 0
    for s in out.structures:
        node_seq += 1
        kind = s.get("graph_kind") or _graph_kind(s["kind"])
        area_m2 = _area_estimate_m2(s, width_px, height_px)
        out.interior.append({
            "id": s.get("label_id") or f"I{node_seq}",
            "position": s["centroid_px"],
            "kind": kind,
            "confidence": s["confidence"],
            "label": s.get("label"),
            "area_m2": area_m2,
        })

    # ------------------------------------------------------------------ #
    #  stairs not enclosed by a region still become STAIR structures
    # ------------------------------------------------------------------ #
    if stairs:
        region_polys = [_polygon_to_np(r) for r in regions]
        for s in stairs:
            b = s.geometry.bbox or (0, 0, 0, 0)
            cx, cy = _centroid(s)
            if any(region_polys and _point_in_polygon(cx, cy, poly) for poly in region_polys if poly is not None):
                continue
            label = _nearest_label(s, labels, max_dist=120)
            text_kind, text_conf = _classify_text(label.text) if label else (None, 0.0)
            out.structures.append({
                "kind": "STAIR",
                "graph_kind": "INTERSECTION",
                "polygon_px": [
                    (b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]),
                ],
                "centroid_px": (round(cx, 2), round(cy, 2)),
                "confidence": round(max(s.confidence, text_conf if text_kind == "STAIR" else 0.0), 2),
                "label": label.text if label else None,
                "metadata": {"source": "SEMANTIC", "hatch": True},
            })

    # ------------------------------------------------------------------ #
    #  walls: dedupe near-identical interior wall segments
    # ------------------------------------------------------------------ #
    for w in walls:
        if w.confidence < 0.5:
            continue
        p0 = (w.geometry.p0.x, w.geometry.p0.y)
        p1 = (w.geometry.p1.x, w.geometry.p1.y)
        if any(_seg_near(p0, p1, e) for e in out.walls):
            continue
        out.walls.append((p0, p1, w.confidence))

    # corridor endpoints enrich the navigation graph when far from regions
    for corr in corridors:
        pts = corr.geometry.polyline
        if not pts:
            continue
        for pt in (pts[0], pts[-1]):
            px, py = pt.x, pt.y
            if any(_dist(px, py, s["centroid_px"]) < 70 for s in out.structures):
                continue
            node_seq += 1
            out.interior.append({
                "id": f"I{node_seq}",
                "position": (round(px, 2), round(py, 2)),
                "kind": "INTERSECTION",
                "confidence": max(0.4, corr.confidence),
                "label": None,
                "area_m2": None,
            })

    # corridors become physical path geometry (metres later)
    for corr in corridors:
        if corr.geometry.polyline and len(corr.geometry.polyline) >= 2:
            out.corridors.append([(p.x, p.y) for p in corr.geometry.polyline])

    # DOOR openings from interior wall gaps
    for d in doors:
        out.openings_extra.append({
            "position": _centroid(d),
            "width_px": d.metadata.get("width_px", 10),
            "confidence": d.confidence,
        })

    if not regions:
        out.warnings.append("no enclosed regions detected; rooms/zones unavailable")
    if not labels:
        out.warnings.append("no OCR text found; gate kinds fall back to geometric heuristics")
    return out


def _nearest_label(
    det: Detection, labels: List[Detection], max_dist: float
) -> Optional[Detection]:
    res = _nearest_label_scored(det, labels, max_dist)
    return res[0] if res else None


def _nearest_label_scored(
    det: Detection, labels: List[Detection], max_dist: float
) -> Optional[Tuple[Detection, float]]:
    """Associate a detection with the best text label (bounding-box aware).

    Priority is geometric, not centroid distance:
      1. label box fully contained in the detection polygon  -> 1.0
      2. strong box overlap with the detection bbox           -> 0.9 / 0.8
      3. otherwise nearest box-centre distance within max_dist

    Binding labels by box geometry (instead of pure centroid distance) is what
    lets Florence/DeepSeek boxed OCR correctly attach rotated, near-touching
    gate numbers that a centroid comparison would mis-couple.
    """
    dbox = det.geometry.bbox or (0, 0, 0, 0)
    if det.geometry.type == GeometryType.POINT and det.geometry.point is not None:
        # point detections (gates) use a point-expanded box: the CV bbox can
        # span a huge false "gap" on stadium sheets and would otherwise swallow
        # unrelated labels through overlap.
        p = det.geometry.point
        dbox = (p.x - 40, p.y - 40, p.x + 40, p.y + 40)
    dcx = (dbox[0] + dbox[2]) / 2.0
    dcy = (dbox[1] + dbox[3]) / 2.0
    poly = _polygon_to_np(det)

    best: Optional[Detection] = None
    best_score = 0.0
    for lab in labels:
        lb = lab.geometry.bbox or (0, 0, 0, 0)
        lcx, lcy = _centroid(lab)
        score: float
        if poly is not None and _box_contained_in_polygon(lb, poly):
            score = 1.0
        else:
            inter = _box_intersection_area(dbox, lb)
            lb_area = _box_area(lb)
            overlap_frac = inter / max(1.0, lb_area) if lb_area else 0.0
            if overlap_frac >= 0.5:
                score = 0.9
            elif overlap_frac > 0.0:
                score = 0.82
            else:
                d2 = (lcx - dcx) ** 2 + (lcy - dcy) ** 2
                if d2 > max_dist * max_dist:
                    continue
                score = 0.6 * (1.0 - (d2 ** 0.5) / max_dist)
        if score > best_score:
            best, best_score = lab, score
    return (best, best_score) if best_score >= 0.35 else None


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dedupe_gate_ids(gates: List[dict]) -> List[dict]:
    """Ensure unique, normalized gate ids (NodeModel ids must be unique)."""
    used: set = set()
    for i, g in enumerate(gates):
        base = (g.get("id") or f"B{i + 1}").strip().upper().replace(" ", "_")
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base}_{n}"
            n += 1
        g["id"] = candidate
        used.add(candidate)
    return gates


def _seg_near(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    existing: Tuple[Tuple[float, float], Tuple[float, float], float],
) -> bool:
    e0, e1, _ = existing
    mid_d = _dist(((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2),
                  ((e0[0] + e1[0]) / 2, (e0[1] + e1[1]) / 2))
    ang = abs(math.degrees(math.atan2(abs((p1[1] - p0[1]) - (e1[1] - e0[1])),
                                      abs((p1[0] - p0[0]) - (e1[0] - e0[0])))))
    return mid_d < 30 and ang < 15


def _graph_kind(structure_kind: str) -> str:
    return {
        "FIELD": "ZONE",
        "ZONE": "ZONE",
        "SEATING": "ZONE",
        "CONCOURSE": "INTERSECTION",
        "ROOM": "CONCESSION",
        "STAIR": "INTERSECTION",
    }.get(structure_kind, "INTERSECTION")


def _area_estimate_m2(s: dict, width_px: int, height_px: int) -> Optional[float]:
    px = s["polygon_px"]
    if len(px) < 3:
        return None
    area_px = abs(sum(px[i][0] * px[(i + 1) % len(px)][1] - px[(i + 1) % len(px)][0] * px[i][1]
                     for i in range(len(px))) / 2.0)
    if area_px <= 0:
        return None
    # area in metres at the same scale the spatial stage will apply (0.6 m/px default)
    scale = min(1.0, width_px / max(1, height_px)) * 0.6
    scale = max(0.05, min(2.0, scale))
    return round(area_px * scale * scale, 1)
