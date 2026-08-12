"""Tests for the VenueSpatialModel layer: schema, storage, API, blueprint, legacy."""
from io import BytesIO
from typing import List

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest
from pydantic import ValidationError

from app.main import app
from app.models import (
    LevelModel,
    NodeType,
    OpeningModel,
    PathGeometryModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueSpatialModel,
)
from app.spatial import derive_spatial_from_venue
from app.storage import storage

client = TestClient(app)


def _synthetic_blueprint() -> bytes:
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 760, 460], outline=(30, 30, 30), width=6)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _triangle() -> Polygon2D:
    return Polygon2D(points=[Point2D(x=0, y=0), Point2D(x=1, y=0), Point2D(x=1, y=1)])


# ---------------------------------------------------------------- schema --- #
def test_polygon_requires_three_points():
    with pytest.raises(ValidationError):
        Polygon2D(points=[Point2D(x=0, y=0), Point2D(x=1, y=1)])


def test_spatial_model_rejects_unknown_level_reference():
    with pytest.raises(ValidationError):
        VenueSpatialModel(
            venue_id="v1",
            levels=[LevelModel(id="L1", name="Ground")],
            structures=[
                StructureModel(id="S1", level_id="L9", type="WALL", polygon=_triangle())
            ],
        )


def test_spatial_model_rejects_unlisted_path_level():
    with pytest.raises(ValidationError):
        VenueSpatialModel(
            venue_id="v1",
            levels=[LevelModel(id="L1", name="Ground")],
            paths=[PathGeometryModel(id="P1", level_id="L2", centerline=[Point2D(x=0, y=0), Point2D(x=1, y=1)])],
        )


# ------------------------------------------------------------- storage ---- #
def test_demo_document_is_versioned_with_spatial():
    doc = storage.get_venue_document("unity_arena")
    assert doc is not None
    assert doc.schema_version == 2
    assert doc.spatial is not None
    assert len(doc.spatial.openings) == 12
    assert len(doc.spatial.paths) == len(doc.venue.edges)
    assert len(doc.spatial.structures) >= 15
    assert doc.spatial.levels[0].id == "L1"


def test_gate_nodes_link_to_openings_and_edges_to_paths():
    doc = storage.get_venue_document("unity_arena")
    gates = [n for n in doc.venue.nodes if n.type in (NodeType.ENTRY, NodeType.EXIT, NodeType.EMERGENCY_EXIT)]
    assert all(n.spatial_ref == f"opening:{n.id}" for n in gates)
    opening_ids = {o.id for o in doc.spatial.openings}
    assert opening_ids == {n.id for n in gates}
    assert all(e.geometry_id for e in doc.venue.edges)
    path_ids = {p.id for p in doc.spatial.paths}
    assert all(e.geometry_id in path_ids for e in doc.venue.edges)


def test_legacy_document_still_readable():
    venue = storage.get_venue("unity_arena")
    assert venue is not None and venue.nodes


# ---------------------------------------------------------------- api ----- #
def test_get_spatial_api():
    r = client.get("/api/venues/unity_arena/spatial")
    assert r.status_code == 200
    body = r.json()
    assert body["venue_id"] == "unity_arena"
    assert len(body["openings"]) == 12
    assert len(body["paths"]) == 32


def test_get_spatial_404():
    assert client.get("/api/venues/does_not_exist/spatial").status_code == 404


def test_generate_and_update_spatial_for_new_venue():
    venue = {
        "id": "TEST_ARENA_SP",
        "name": "Test Arena",
        "width": 100.0,
        "height": 80.0,
        "nodes": [
            {"id": "G1", "position": {"x": 10, "y": 10}, "type": "ENTRY", "area_m2": 60},
            {"id": "X1", "position": {"x": 90, "y": 70}, "type": "EXIT", "area_m2": 60},
            {"id": "N1", "position": {"x": 50, "y": 40}, "type": "INTERSECTION", "area_m2": 40},
        ],
        "edges": [
            {"id": "E1", "source": "G1", "destination": "N1", "length_m": 50, "width_m": 4, "capacity": 500},
            {"id": "E2", "source": "N1", "destination": "X1", "length_m": 50, "width_m": 4, "capacity": 500},
        ],
    }
    r = client.post("/api/venues", json=venue)
    assert r.status_code == 201
    try:
        r = client.post("/api/venues/TEST_ARENA_SP/spatial/generate")
        assert r.status_code == 200
        body = r.json()
        assert len(body["openings"]) == 2
        assert len(body["paths"]) == 2
        # generated links persisted with the venue
        v = client.get("/api/venues/TEST_ARENA_SP").json()
        by_id = {n["id"]: n for n in v["nodes"]}
        assert by_id["G1"]["spatial_ref"] == "opening:G1"
        assert v["edges"][0]["geometry_id"] == "PATH_E1"
        # updating the venue preserves the derived spatial model
        r = client.put("/api/venues/TEST_ARENA_SP", json={**venue, "name": "Renamed Arena"})
        assert r.status_code == 200
        r = client.get("/api/venues/TEST_ARENA_SP/spatial")
        assert r.status_code == 200
        assert r.json()["venue_id"] == "TEST_ARENA_SP"
    finally:
        client.delete("/api/venues/TEST_ARENA_SP")


def test_put_spatial_api():
    spatial = {
        "venue_id": "unity_arena",
        "coordinate_system": "LOCAL_METRIC",
        "levels": [{"id": "L1", "name": "Ground", "elevation_m": 0.0, "height_m": 5.0}],
        "structures": [
            {"id": "WALL_X", "level_id": "L1", "type": "WALL",
             "polygon": {"points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}, {"x": 0, "y": 10}]},
             "height_m": 5.0}
        ],
        "openings": [],
        "paths": [],
        "metadata": {},
    }
    r = client.put("/api/venues/unity_arena/spatial", json=spatial)
    assert r.status_code == 200
    assert r.json()["structures"][0]["id"] == "WALL_X"
    # restore the authored demo spatial
    client.post("/api/venues/unity_arena/spatial/generate")


# ------------------------------------------------------------ blueprint ---- #
def test_blueprint_import_returns_spatial():
    from app.blueprint import pipeline

    result = pipeline.import_blueprint(_synthetic_blueprint())
    assert result.spatial is not None
    assert result.spatial.openings, "imported spatial must contain gate openings"
    assert result.spatial.structures, "imported spatial must contain structures"
    assert result.spatial.paths, "imported spatial must contain generated paths"
    assert any(n.spatial_ref for n in result.venue.nodes)
    assert any(e.geometry_id for e in result.venue.edges)


def test_blueprint_import_api_returns_spatial():
    r = client.post(
        "/api/blueprint/import",
        files={"file": ("venue.png", _synthetic_blueprint(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["spatial"] is not None
    assert body["spatial"]["venue_id"] == "BLUEPRINT_VENUE"
    assert body["spatial"]["openings"]


def test_blueprint_import_persists_spatial():
    r = client.post(
        "/api/blueprint/import",
        files={"file": ("venue.png", _synthetic_blueprint(), "image/png")},
    )
    assert r.status_code == 200
    r = client.get("/api/venues/BLUEPRINT_VENUE/spatial")
    assert r.status_code == 200
    assert r.json()["openings"]


# ------------------------------------------------------------ legacy ------ #
def test_derive_spatial_from_venue():
    venue = storage.get_venue("unity_arena")
    spatial = derive_spatial_from_venue(venue)
    assert spatial.venue_id == "unity_arena"
    assert len(spatial.openings) == 12
    assert len(spatial.paths) == len(venue.edges)
    assert len(spatial.structures) == 5  # floor + 4 walls
    assert venue.nodes[0].spatial_ref is not None
    assert venue.edges[0].geometry_id is not None
