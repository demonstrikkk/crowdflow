"""Tests for the VenueDigitalTwin canonical semantic model.

Covers the schema, document<->twin conversion round-trips, the deterministic
validation engine, and the /twin API endpoints (edit -> regenerate -> validate).
"""
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.main import app
from app.models import (
    Point2D,
    Polygon2D,
    TwinNavigationGraph,
    TwinNavigationNode,
    TwinStructure,
    VenueDigitalTwin,
    digital_twin_to_document,
    document_to_digital_twin,
    validate_digital_twin,
)
from app.storage import storage

client = TestClient(app)


def _demo_twin() -> VenueDigitalTwin:
    doc = storage.get_venue_document("unity_arena")
    assert doc is not None
    return document_to_digital_twin(doc)


# ---------------------------------------------------------------- schema ---- #
def test_twin_rejects_unknown_level_reference():
    with pytest.raises(ValidationError):
        VenueDigitalTwin(
            venue_id="v1",
            name="V",
            dimensions={"width_m": 100, "height_m": 80},
            levels=[{"id": "L1", "name": "Ground"}],
            structures=[
                TwinStructure(
                    id="S1",
                    level_id="L9",
                    type="WALL",
                    polygon=Polygon2D(points=[Point2D(x=0, y=0), Point2D(x=1, y=0), Point2D(x=1, y=1)]),
                )
            ],
        )


def test_twin_rejects_nav_edge_to_unknown_node():
    with pytest.raises(ValidationError):
        TwinNavigationGraph(
            nodes=[TwinNavigationNode(id="A", type="ENTRY", position=Point2D(x=0, y=0))],
            edges=[{"id": "E1", "source": "A", "destination": "MISSING"}],
        )


# ---------------------------------------------------------- derivation ----- #
def test_demo_document_projects_to_twin():
    tw = _demo_twin()
    assert tw.venue_id == "unity_arena"
    assert tw.dimensions.width_m == 1000.0
    assert tw.dimensions.height_m == 620.0
    assert tw.coordinate_system.name == "LOCAL_METRIC"
    assert len(tw.levels) == 1
    assert len(tw.structures) == 22
    assert len(tw.openings) == 12
    assert len(tw.paths) == 32
    assert len(tw.navigation.nodes) == 27
    assert len(tw.navigation.edges) == 32
    # emergency exits tagged correctly
    emg = [o for o in tw.openings if o.type == "EMERGENCY_EXIT"]
    assert emg and all(o.is_emergency for o in emg)
    # authored structures recovered with high confidence
    walls = [s for s in tw.structures if s.id.startswith("WALL")]
    assert walls and all(s.confidence >= 0.9 for s in walls)


def test_demo_twin_validates_clean():
    issues = _demo_twin().validation
    assert not [i for i in issues if i.severity == "ERROR"], [i.message for i in issues]


# ----------------------------------------------------------- validation ---- #
def test_validation_detects_duplicate_structure_ids():
    tw = _demo_twin()
    tw.structures[0].id = tw.structures[1].id
    issues = validate_digital_twin(tw)
    dup = [i for i in issues if i.severity == "ERROR" and "duplicate" in i.message]
    assert dup and tw.structures[0].id in dup[0].element_ids


def test_validation_detects_out_of_bounds_structure():
    tw = _demo_twin()
    s = tw.structures[0]
    s.polygon = Polygon2D(points=[
        Point2D(x=0, y=0), Point2D(x=0, y=5000), Point2D(x=100, y=0),
    ])
    issues = validate_digital_twin(tw)
    assert any(i.severity == "ERROR" and "outside the venue" in i.message for i in issues)


def test_validation_detects_disconnected_navigation():
    tw = _demo_twin()
    tw.navigation.nodes.append(
        TwinNavigationNode(id="ISOLATED_NODE", type="INTERSECTION", position=Point2D(x=50, y=50))
    )
    # no edge connects the new node => disconnected
    tw.navigation = TwinNavigationGraph(nodes=tw.navigation.nodes, edges=tw.navigation.edges)
    issues = validate_digital_twin(tw)
    assert any(i.severity == "ERROR" and "cannot be reached" in i.message for i in issues)
    assert any("ISOLATED_NODE" in i.element_ids for i in issues)


def test_validation_flags_estimated_scale():
    tw = _demo_twin()
    tw.coordinate_system.scale_estimated = True
    issues = validate_digital_twin(tw)
    assert any(i.severity == "INFERENCE" and "scale is estimated" in i.message for i in issues)


# ---------------------------------------------------------- round-trip ----- #
def test_geometry_round_trip_is_stable():
    tw = _demo_twin()
    doc = digital_twin_to_document(tw)
    assert doc.venue.id == "unity_arena"
    assert doc.spatial is not None
    tw2 = document_to_digital_twin(doc)

    def key(target):
        return [(s.id, s.level_id, s.height_m, [(p.x, p.y) for p in s.polygon.points]) for s in target.structures]

    assert key(tw2) == key(tw)
    assert [(o.id, o.position.x, o.position.y, o.width_m) for o in tw2.openings] == [
        (o.id, o.position.x, o.position.y, o.width_m) for o in tw.openings
    ]
    assert [(lv.id, lv.elevation_m, lv.height_m) for lv in tw2.levels] == [
        (lv.id, lv.elevation_m, lv.height_m) for lv in tw.levels
    ]


def test_round_trip_regenerates_navigation_graph():
    tw = _demo_twin()
    doc = digital_twin_to_document(tw)
    # the regenerated graph is derived from geometry (hubs + openings) and is
    # fully connected and validated
    assert len(doc.venue.nodes) == len(tw.navigation.nodes) or len(doc.venue.nodes) >= len(tw.openings)
    assert doc.venue.edges
    from app.engine.venue import VenueGraph

    graph = VenueGraph(doc.venue)
    graph.set_emergency(True)
    entries = [n.id for n in doc.venue.nodes if n.type.value == "ENTRY"]
    assert len(graph.reachable_from(entries)) == len(doc.venue.nodes)


# ------------------------------------------------------------------ api ---- #
def test_get_twin_api():
    r = client.get("/api/venues/unity_arena/twin")
    assert r.status_code == 200
    body = r.json()
    assert body["venue_id"] == "unity_arena"
    assert len(body["openings"]) == 12
    assert body["navigation"]["nodes"]
    assert "validation" in body


def test_get_twin_404():
    assert client.get("/api/venues/does_not_exist/twin").status_code == 404


def test_put_twin_edits_geometry_regenerates_graph_and_persists():
    venue = {
        "id": "TWIN_TEST_ARENA",
        "name": "Twin Test Arena",
        "width": 200.0,
        "height": 160.0,
        "nodes": [
            {"id": "G1", "position": {"x": 20, "y": 20}, "type": "ENTRY", "area_m2": 60},
            {"id": "G2", "position": {"x": 180, "y": 140}, "type": "EXIT", "area_m2": 60},
            {"id": "N1", "position": {"x": 100, "y": 80}, "type": "INTERSECTION", "area_m2": 40},
        ],
        "edges": [
            {"id": "E1", "source": "G1", "destination": "N1", "length_m": 100, "width_m": 4, "capacity": 500},
            {"id": "E2", "source": "N1", "destination": "G2", "length_m": 100, "width_m": 4, "capacity": 500},
        ],
    }
    assert client.post("/api/venues", json=venue).status_code == 201
    try:
        r = client.get("/api/venues/TWIN_TEST_ARENA/twin")
        assert r.status_code == 200
        twin = r.json()
        assert len(twin["openings"]) == 2

        # edit: move one gate and widen another
        by_id = {o["id"]: o for o in twin["openings"]}
        by_id["G1"]["position"] = {"x": 40, "y": 40}
        by_id["G2"]["width_m"] = 12.0

        r = client.put("/api/venues/TWIN_TEST_ARENA/twin", json=twin)
        assert r.status_code == 200
        saved = r.json()
        assert saved["venue_id"] == "TWIN_TEST_ARENA"

        updated = {o["id"]: o for o in saved["openings"]}
        assert updated["G1"]["position"] == {"x": 40, "y": 40}
        assert updated["G2"]["width_m"] == 12.0
        assert saved["navigation"]["nodes"], "navigation graph must be regenerated"
        assert saved["navigation"]["edges"]

        # persisted: the stored venue now mirrors the regenerated geometry graph
        v = client.get("/api/venues/TWIN_TEST_ARENA").json()
        assert v["id"] == "TWIN_TEST_ARENA"
        assert len(v["nodes"]) >= len(saved["openings"])
    finally:
        client.delete("/api/venues/TWIN_TEST_ARENA")