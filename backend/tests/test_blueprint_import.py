"""Blueprint import pipeline tests (deterministic, no optional engines needed)."""
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.blueprint import docclass, geometry, graph, pipeline, semantic
from app.models import (
    Detection,
    DetectionGeometry,
    DetectionKind,
    DetectionState,
    DocumentType,
    GeometryType,
    Point2D,
)
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
    assert result.degradation_level in (0, 1, 2)
    assert "PERCEPTION" in result.steps
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


# ---------------------------------------------------------------------- #
#  Phase 2C reset: detection-state evidence gating + quality gate
# ---------------------------------------------------------------------- #
def _gate_det(id_, x, y, width_px, conf, label=""):
    return Detection(
        id=id_, kind=DetectionKind.GATE,
        geometry=DetectionGeometry(
            type=GeometryType.SEGMENT,
            p0=Point2D(x=x, y=y), p1=Point2D(x=x + width_px, y=y + 20),
            bbox=(x, y, x + width_px, y + 20),
        ),
        confidence=conf, metadata={"width_px": width_px, "label": label},
    )


def test_gate_evidence_rejects_wide_false_openings():
    # the '28 gates' failure: a whole-footprint-side false run must never
    # become a venue opening, while a labelled credible gate is kept
    side_len = 1044.0
    assert semantic._gate_state(_gate_det("g1", 0, 0, 616, 0.72), side_len) == DetectionState.REJECTED
    assert semantic._gate_state(_gate_det("g2", 0, 0, 19, 0.5), side_len) == DetectionState.CONFIRMED
    assert semantic._gate_state(_gate_det("g4", 0, 0, 40, 0.7, "GATE A"), side_len) == DetectionState.CONFIRMED
    assert semantic._gate_state(_gate_det("g5", 0, 0, 3, 0.6), side_len) == DetectionState.REJECTED


def test_import_quality_gate_passes_for_orthographic_plan():
    result = pipeline.import_blueprint(_synthetic_blueprint())
    assert result.image.document_type == DocumentType.ORTHOGRAPHIC_PLAN
    assert result.report is not None and result.report.quality is not None
    assert result.report.quality.passed is True
    assert result.canonical2d is not None
    assert len(result.canonical2d.objects) >= 5  # footprint + 4 gates (+ room)


def test_import_perspective_source_is_blocked_by_quality_gate(monkeypatch):
    # a perspective illustration must NOT be reconstructable as a floor plan:
    # the reconstruction stays a venue preview but the quality gate fails
    monkeypatch.setattr(
        docclass, "classify",
        lambda image: docclass.DocumentTypeResult(DocumentType.PERSPECTIVE_ARCHITECTURAL_DRAWING, 0.75, ["fake"]),
    )
    result = pipeline.import_blueprint(_synthetic_blueprint())
    assert result.report is not None and result.report.quality is not None
    assert result.report.quality.passed is False
    assert any("not an orthographic floor plan" in r for r in result.report.quality.reasons)
