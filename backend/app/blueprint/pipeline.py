"""Blueprint import pipeline (brief section 21).

Stages:

  NORMALIZE   -> orientation + scale + footprint          (always runs)
  GEOMETRY    -> walls, openings (OpenCV when present, else numpy heuristic)
  OCR         -> text labels (Tesseract when present; skipped otherwise)
  CLASSIFY    -> semantic kinds (labels first, geometry heuristics next)
  GRAPH       -> validated VenueModel with template fallback

The pipeline never fails hard: unavailable optional engines are reported in
``steps`` and the degradation level, and the graph stage guarantees a valid,
simulation-ready venue.
"""
from __future__ import annotations

import io
from typing import List, Optional

from PIL import Image, ImageOps

from ..models import BlueprintElement, BlueprintResult, WorldPosition
from . import classify, geometry, graph, ocr


def _open_image(data: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1600, 1600))
        return img
    except Exception:
        return None


def import_blueprint(data: bytes) -> BlueprintResult:
    steps: dict = {}

    img = _open_image(data)
    if img is None:
        steps["NORMALIZE"] = "failed: unreadable image"
        steps["GEOMETRY"] = "skipped"
        steps["OCR"] = "skipped"
        steps["CLASSIFY"] = "skipped (template fallback)"
        steps["GRAPH"] = "template venue"
        return BlueprintResult(
            venue=graph._template_venue(1000.0, 620.0),
            confidence=0.2,
            degradation_level=3,
            degraded=True,
            steps=steps,
            notes=["image could not be decoded; template venue returned"],
        )
    steps["NORMALIZE"] = "ok"

    # GEOMETRY
    geom = geometry.analyze_geometry(img)
    steps["GEOMETRY"] = "opencv" if geom.opencv_used else "heuristic"

    # OCR (optional)
    labels = ocr.extract_labels(img)
    steps["OCR"] = f"{len(labels)} label(s)" if labels else "none (tesseract unavailable)"

    # CLASSIFY
    gates = classify.classify_boundary_openings(geom.openings, len(geom.perimeter))
    interior_nodes = classify.assign_interior_kinds(geom.interior_walls)

    # overlay OCR labels onto the nearest gate/interior element
    overlay = _overlay_labels(gates + interior_nodes, labels)

    width_m, height_m = geometry.estimate_dimensions_m(geom)
    venue, notes = graph.build_venue(
        [g for g in overlay if g["kind"] in _gate_kinds()],
        [g for g in overlay if g["kind"] not in _gate_kinds()],
        width_m,
        height_m,
        geom.width_px,
        geom.height_px,
    )
    steps["CLASSIFY"] = f"{len(gates)} gate(s), {len(interior_nodes)} interior node(s)"
    steps["GRAPH"] = "built" if venue.id == "BLUEPRINT_VENUE" else "template fallback"

    confidence = _result_confidence(gates, interior_nodes)
    degraded = not geom.opencv_used or not labels
    level = 1 if geom.opencv_used and not labels else 2 if not geom.opencv_used else 0

    elements = _to_elements(gates + interior_nodes, width_m, height_m, geom.width_px, geom.height_px)

    return BlueprintResult(
        venue=venue,
        elements=elements,
        confidence=confidence,
        degradation_level=level,
        degraded=degraded,
        steps=steps,
        notes=notes,
    )


def _gate_kinds() -> set:
    return {"ENTRY", "EXIT", "EMERGENCY_EXIT"}


def _overlay_labels(elements: List[dict], labels: List[dict]) -> List[dict]:
    """Attach OCR text to the nearest element within 140 px."""
    for label in labels:
        best = None
        best_dist = 141
        for elem in elements:
            d = (elem["position"][0] - label["position"][0]) ** 2 + (
                elem["position"][1] - label["position"][1]
            ) ** 2
            if d < best_dist:
                best_dist = d
                best = elem
        if best is not None:
            kind, conf = classify.classify_text(label["text"])
            if kind in _gate_kinds() or kind in ("CONCESSION", "CHECKPOINT", "ZONE"):
                best["kind"] = kind
                best["confidence"] = max(best.get("confidence", 0.0), conf)
                best["label"] = label["text"]
    return elements


def _result_confidence(gates: List[dict], interior: List[dict]) -> float:
    values = [g.get("confidence", 0.4) for g in gates] + [n.get("confidence", 0.5) for n in interior]
    if not values:
        return 0.2
    return round(sum(values) / len(values), 3)


def _to_elements(
    elements: List[dict], width_m: float, height_m: float, px_w: int, px_h: int
) -> List[BlueprintElement]:
    scale = graph._meters_per_px(width_m, height_m, px_w, px_h)
    out: List[BlueprintElement] = []
    for i, elem in enumerate(elements):
        kind = elem.get("kind", "INTERSECTION")
        pos = elem["position"]
        out.append(
            BlueprintElement(
                id=f"B{i + 1}" if kind in _gate_kinds() else f"I{i + 1}",
                kind=kind,
                position=WorldPosition(x=round(pos[0] * scale, 2), y=round(pos[1] * scale, 2)),
                area_m2=elem.get("area_m2"),
                confidence=elem.get("confidence", 0.4),
                label=elem.get("label"),
                source="OCR" if elem.get("label") else "GEOMETRY",
            )
        )
    return out
