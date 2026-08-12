"""Regenerate backend/data/venue_demo_stadium.json as a v2 venue document.

Adds an authored VenueSpatialModel (walls, field, seating tiers, concourses,
openings, paths) and links nodes/edges to it. Deterministic; run once.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\asus\Downloads\crowdflow\backend")

from app.models import (  # noqa: E402
    LevelModel,
    NodeType,
    OpeningModel,
    PathGeometryModel,
    Point2D,
    Polygon2D,
    StructureModel,
    VenueModel,
    VenueSpatialModel,
)

SRC = OUT = Path(r"C:\Users\asus\Downloads\crowdflow\backend\data\venue_demo_stadium.json")
L1 = "L1"


def rect(x0, y0, x1, y1):
    return Polygon2D(points=[Point2D(x=x0, y=y0), Point2D(x=x1, y=y0), Point2D(x=x1, y=y1), Point2D(x=x0, y=y1)])


def struct(sid, stype, poly, height, **meta):
    return StructureModel(id=sid, level_id=L1, type=stype, polygon=poly, height_m=height, metadata=meta)


def build_spatial(venue: VenueModel) -> VenueSpatialModel:
    W, H = venue.width, venue.height
    structures = [
        # footprint floor
        struct("FLR", "FLOOR", rect(0, 0, W, H), 0.3, source="AUTHORED"),
        # perimeter walls
        struct("WALL_N", "WALL", rect(0, 0, W, 6), 5.0, source="AUTHORED"),
        struct("WALL_S", "WALL", rect(0, H - 6, W, H), 5.0, source="AUTHORED"),
        struct("WALL_E", "WALL", rect(W - 6, 0, W, H), 5.0, source="AUTHORED"),
        struct("WALL_W", "WALL", rect(0, 0, 6, H), 5.0, source="AUTHORED"),
        # pitch
        struct("FIELD", "FIELD", rect(420, 250, 580, 370), 0.3, source="AUTHORED"),
        # seating tiers (north/south split so checkpoint kiosks stay clear)
        struct("SEAT_N_A", "SEATING", rect(380, 225, 494, 265), 2.5, source="AUTHORED", tiers=4),
        struct("SEAT_N_B", "SEATING", rect(506, 225, 620, 265), 2.5, source="AUTHORED", tiers=4),
        struct("SEAT_E", "SEATING", rect(585, 255, 655, 345), 2.5, source="AUTHORED", tiers=4),
        struct("SEAT_S_A", "SEATING", rect(380, 355, 494, 395), 2.5, source="AUTHORED", tiers=4),
        struct("SEAT_S_B", "SEATING", rect(506, 355, 620, 395), 2.5, source="AUTHORED", tiers=4),
        struct("SEAT_W", "SEATING", rect(345, 255, 415, 345), 2.5, source="AUTHORED", tiers=4),
        # concourse ring slabs
        struct("CONCOURSE_N", "CONCOURSE", rect(140, 110, 860, 150), 0.4, source="AUTHORED"),
        struct("CONCOURSE_E", "CONCOURSE", rect(800, 110, 860, 510), 0.4, source="AUTHORED"),
        struct("CONCOURSE_S", "CONCOURSE", rect(140, 470, 860, 510), 0.4, source="AUTHORED"),
        struct("CONCOURSE_W", "CONCOURSE", rect(140, 110, 200, 510), 0.4, source="AUTHORED"),
        # concessions
        struct("CONCESSION_N", "ROOM", rect(495, 180, 505, 190), 3.0, source="AUTHORED"),
        struct("CONCESSION_S", "ROOM", rect(495, 430, 505, 440), 3.0, source="AUTHORED"),
        # checkpoints (sit in the gaps left between seating blocks)
        struct("CHECKPOINT_N", "ROOM", rect(496, 236, 504, 244), 3.0, source="AUTHORED"),
        struct("CHECKPOINT_E", "ROOM", rect(766, 296, 774, 304), 3.0, source="AUTHORED"),
        struct("CHECKPOINT_S", "ROOM", rect(496, 376, 504, 384), 3.0, source="AUTHORED"),
        struct("CHECKPOINT_W", "ROOM", rect(226, 296, 234, 304), 3.0, source="AUTHORED"),
    ]

    node_pos = {n.id: n.position for n in venue.nodes}
    opening = []
    side_rot = {
        "GATE_A": 0, "GATE_B": 0, "EXIT_N": 0,
        "GATE_E": 180, "GATE_F": 180, "EXIT_S": 180, "EMERGENCY_2": 180,
        "GATE_C": 90, "GATE_D": 90, "EXIT_E": 90,
        "EXIT_W": 270, "EMERGENCY_1": 270,
    }
    widths = {
        "GATE_A": 7, "GATE_B": 7, "GATE_C": 7, "GATE_D": 7, "GATE_E": 7, "GATE_F": 7,
        "EXIT_N": 8, "EXIT_E": 8, "EXIT_S": 8, "EXIT_W": 8,
        "EMERGENCY_1": 14, "EMERGENCY_2": 14,
    }
    for n in venue.nodes:
        if n.type == NodeType.ENTRY:
            otype = "ENTRY_GATE"
        elif n.type == NodeType.EXIT:
            otype = "EXIT_GATE"
        elif n.type == NodeType.EMERGENCY_EXIT:
            otype = "EMERGENCY_EXIT"
        else:
            continue
        opening.append(
            OpeningModel(
                id=n.id,
                level_id=L1,
                type=otype,
                position=Point2D(x=n.position.x, y=n.position.y),
                width_m=widths.get(n.id, 8.0),
                rotation_deg=side_rot.get(n.id, 0.0),
                metadata={"source": "AUTHORED", "node": n.id},
            )
        )

    # ring corridors follow the concourse rectangle; everything else is straight
    ring_waypoints = {
        "E_CN_CE": [(500, 140), (830, 140), (830, 300)],
        "E_CE_CS": [(830, 300), (830, 480), (500, 480)],
        "E_CS_CW": [(500, 480), (170, 480), (170, 300)],
        "E_CW_CN": [(170, 300), (170, 140), (500, 140)],
    }
    paths = []
    for e in venue.edges:
        wp = ring_waypoints.get(e.id)
        if wp is None:
            a, b = node_pos[e.source], node_pos[e.destination]
            wp = [(a.x, a.y), (b.x, b.y)]
        pid = f"PATH_{e.id}"
        paths.append(
            PathGeometryModel(
                id=pid,
                level_id=L1,
                centerline=[Point2D(x=round(x, 2), y=round(y, 2)) for x, y in wp],
                width_m=e.width_m,
                metadata={"source": "AUTHORED", "edge": e.id},
            )
        )
        e.geometry_id = pid

    for n in venue.nodes:
        if n.type in (NodeType.ENTRY, NodeType.EXIT, NodeType.EMERGENCY_EXIT):
            n.spatial_ref = f"opening:{n.id}"

    return VenueSpatialModel(
        venue_id=venue.id,
        levels=[LevelModel(id=L1, name="Ground", elevation_m=0.0, height_m=5.0)],
        structures=structures,
        openings=opening,
        paths=paths,
        metadata={
            "source": "AUTHORED",
            "notes": [
                "Hand-authored architectural model for the Unity Arena demo.",
                "Seating rendered as tiered slabs; concourse ring as four slabs.",
                "Every edge has a linked PathGeometryModel (geometry_id).",
            ],
        },
    )


def main():
    doc = json.loads(SRC.read_text(encoding="utf-8"))
    venue = VenueModel.model_validate(doc.get("venue", doc))
    spatial = build_spatial(venue)
    out = {
        "schema_version": 2,
        "venue": venue.model_dump(mode="json"),
        "spatial": spatial.model_dump(mode="json"),
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        f"wrote {OUT}  nodes={len(venue.nodes)} edges={len(venue.edges)} "
        f"structures={len(spatial.structures)} openings={len(spatial.openings)} paths={len(spatial.paths)}"
    )


if __name__ == "__main__":
    main()
