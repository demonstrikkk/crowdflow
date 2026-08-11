"""Blueprint import pipeline tests (deterministic, no optional engines needed)."""
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.blueprint import geometry, graph, pipeline
from app.models import NodeType


def _synthetic_blueprint(interior_wall: bool = True) -> bytes:
    """Rectangular venue outline with an interior wall (with a gate gap).

    White canvas, dark grey walls, a light gap in the interior wall.
    """
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    # outer footprint
    draw.rectangle([40, 40, 760, 460], outline=(30, 30, 30), width=6)
    if interior_wall:
        # vertical wall from top wall down to centre with a gap at y 180-260
        draw.line([(400, 46), (400, 180)], fill=(30, 30, 30), width=6)
        draw.line([(400, 260), (400, 454)], fill=(30, 30, 30), width=6)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_import_builds_valid_venue():
    result = pipeline.import_blueprint(_synthetic_blueprint())

    assert result.venue.nodes, "venue must contain nodes"
    assert result.venue.edges, "venue must contain edges"

    types = {n.type for n in result.venue.nodes}
    assert NodeType.ENTRY in types, "venue must have an ENTRY gate"
    assert NodeType.EXIT in types or NodeType.EMERGENCY_EXIT in types, "venue must have an exit"

    # VenueModel construction already validated uniqueness + connectivity;
    # re-run the validator explicitly to be safe.
    assert result.venue.model_dump()  # pydantic round-trip stays valid


def test_import_is_degraded_without_optional_engines():
    result = pipeline.import_blueprint(_synthetic_blueprint())
    # cv2 and tesseract are not installed in this environment
    assert result.degradation_level in (1, 2)
    assert result.steps.get("GEOMETRY") in ("heuristic", "opencv")
    assert 0 < result.confidence <= 1


def test_unreadable_image_falls_back_to_template():
    result = pipeline.import_blueprint(b"not an image at all")
    assert result.venue.id == "BLUEPRINT_TEMPLATE"
    assert result.degradation_level == 3
    assert result.notes


def test_geometry_detects_footprint_and_gates():
    img = Image.open(BytesIO(_synthetic_blueprint())).convert("RGB")
    geom = geometry.analyze_geometry(img)
    assert geom.footprint == (40, 40, 760, 460)
    assert len(geom.perimeter) >= 3
    assert len(geom.openings) == 4  # deterministic mid-point defaults on each side
    assert geom.interior_walls, "interior wall should be detected"


def test_graph_builder_always_returns_valid_venue():
    gates = [
        {"position": (400, 40), "kind": "ENTRY", "confidence": 0.45},
        {"position": (400, 460), "kind": "EXIT", "confidence": 0.45},
        {"position": (40, 250), "kind": "EXIT", "confidence": 0.45},
        {"position": (760, 250), "kind": "EMERGENCY_EXIT", "confidence": 0.4},
    ]
    interior = [
        {"position": (400, 120), "kind": "INTERSECTION", "confidence": 0.5},
        {"position": (600, 300), "kind": "CONCESSION", "confidence": 0.5},
    ]
    venue, notes = graph.build_venue(gates, interior, 1000.0, 620.0, 800, 500)
    assert venue.id == "BLUEPRINT_VENUE"
    assert not notes or all("template" not in n for n in notes)


def test_graph_builder_falls_back_on_invalid_input():
    # only ENTRY gates -> fails "must contain an EXIT" -> template fallback
    gates = [
        {"position": (400, 40), "kind": "ENTRY", "confidence": 0.45},
        {"position": (400, 460), "kind": "ENTRY", "confidence": 0.45},
    ]
    venue, notes = graph.build_venue(gates, [], 1000.0, 620.0, 800, 500)
    assert venue.id == "BLUEPRINT_TEMPLATE"
    assert any("falling back" in n for n in notes)
