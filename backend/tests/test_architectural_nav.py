"""Unit tests for Phase 7: Spatial-derived Navigation Graph Builder."""
from __future__ import annotations

from app.blueprint.navigation import build_venue_from_spatial
from app.models import (
    LevelModel,
    OpeningModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueSpatialModel,
)


def test_build_venue_from_spatial_success():
    spatial = VenueSpatialModel(
        venue_id="test_arch_venue",
        levels=[
            LevelModel(id="L0", name="Ground Floor", elevation_m=0.0, height_m=4.0),
            LevelModel(id="L1", name="First Floor", elevation_m=4.0, height_m=4.0),
        ],
        structures=[
            StructureModel(
                id="BOWL_L0",
                type="SEATING",
                level_id="L0",
                polygon=Polygon2D(
                    points=[
                        Point2D(x=10, y=10),
                        Point2D(x=20, y=10),
                        Point2D(x=20, y=20),
                        Point2D(x=10, y=20),
                    ]
                ),
            ),
            StructureModel(
                id="CONCOURSE_L1",
                type="CONCOURSE",
                level_id="L1",
                polygon=Polygon2D(
                    points=[
                        Point2D(x=30, y=30),
                        Point2D(x=40, y=30),
                        Point2D(x=40, y=40),
                        Point2D(x=30, y=40),
                    ]
                ),
            ),
        ],
        openings=[
            OpeningModel(
                id="GATE_1",
                type="ENTRY_GATE",
                level_id="L0",
                position=Point2D(x=15, y=5),
                width_m=4.0,
                metadata={"capacity_ppm": 150.0},
            ),
            OpeningModel(
                id="EMG_1",
                type="EMERGENCY_EXIT",
                level_id="L1",
                position=Point2D(x=35, y=25),
                width_m=2.5,
            ),
        ],
        paths=[],
    )

    venue, notes = build_venue_from_spatial(spatial, width_m=100.0, height_m=100.0)

    # 2 openings + 2 level hubs = 4 nodes total
    assert len(venue.nodes) == 4
    node_ids = {n.id for n in venue.nodes}
    assert "GATE_1" in node_ids
    assert "EMG_1" in node_ids
    assert "HUB_L0" in node_ids
    assert "HUB_L1" in node_ids

    # Nodes linked back to spatial ref
    gate_node = next(n for n in venue.nodes if n.id == "GATE_1")
    assert gate_node.spatial_ref == "opening:GATE_1"
    assert gate_node.capacity == 150.0

    # Verify edges (GATE_1 -> HUB_L0, EMG_1 -> HUB_L1, HUB_L0 -> HUB_L1)
    assert len(venue.edges) == 3

    # Check emergency exit propagation
    emg_edge = next(e for e in venue.edges if e.source == "EMG_1" or e.destination == "EMG_1")
    assert emg_edge.is_emergency is True

    # Check back-population of paths
    assert len(spatial.paths) == 3
    # Check centerline points mapped correctly
    path = spatial.paths[0]
    assert len(path.centerline) == 2
    assert path.level_id in ("L0", "L1")
