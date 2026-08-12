import pytest
from app.blueprint.architecture.models import (
    ArchitecturalScene,
    ArchitecturalDocument,
    ArchitecturalVenue,
    ArchitecturalLevel,
    ArchitecturalRegion,
    EntitySource,
    EntityType,
    Evidence
)

def test_architectural_scene_serialization():
    scene = ArchitecturalScene(
        document=ArchitecturalDocument(
            drawing_type="ORTHOGRAPHIC_PLAN",
            projection="2D",
            venue_type="STADIUM",
            image_quality="HIGH",
            confidence=0.9
        ),
        venue=ArchitecturalVenue(
            overall_footprint_shape="OVAL",
        ),
        levels=[
            ArchitecturalLevel(id="L0", name="Level 0")
        ],
        regions=[
            ArchitecturalRegion(
                id="R1",
                type=EntityType.SEATING_BOWL,
                source=EntitySource.GEMINI,
                evidence=[Evidence(source=EntitySource.GEMINI, confidence=0.85)]
            )
        ]
    )

    # Test serialization to dict
    scene_dict = scene.model_dump()
    assert scene_dict["document"]["drawing_type"] == "ORTHOGRAPHIC_PLAN"
    assert len(scene_dict["regions"]) == 1
    assert scene_dict["regions"][0]["type"] == "SEATING_BOWL"

    # Test deserialization from dict
    scene_parsed = ArchitecturalScene.model_validate(scene_dict)
    assert scene_parsed.document.venue_type == "STADIUM"
    assert scene_parsed.levels[0].id == "L0"
    assert scene_parsed.regions[0].evidence[0].confidence == 0.85

def test_architectural_scene_invalid_confidence():
    with pytest.raises(ValueError):
        ArchitecturalScene(
            document=ArchitecturalDocument(
                drawing_type="ORTHOGRAPHIC_PLAN",
                projection="2D",
                venue_type="STADIUM",
                image_quality="HIGH",
                confidence=1.5 # Invalid
            ),
            venue=ArchitecturalVenue()
        )
