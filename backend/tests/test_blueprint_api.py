"""Blueprint import API tests."""
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app

client = TestClient(app)


def _png_bytes() -> bytes:
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 760, 460], outline=(30, 30, 30), width=6)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_import_blueprint_endpoint():
    r = client.post(
        "/api/blueprint/import",
        files={"file": ("venue.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["venue"]["id"] == "BLUEPRINT_VENUE"
    assert body["confidence"] > 0
    assert "steps" in body
    # the imported venue is persisted and retrievable
    assert client.get("/api/venues/BLUEPRINT_VENUE").status_code == 200


def test_import_blueprint_rejects_non_image():
    r = client.post(
        "/api/blueprint/import",
        files={"file": ("venue.png", b"not an image", "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["venue"]["id"] == "BLUEPRINT_TEMPLATE"


def test_detect_returns_detections_and_image_meta():
    r = client.post(
        "/api/blueprint/detect",
        files={"file": ("venue.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["image"]["width_px"] > 0 and body["image"]["height_px"] > 0
    kinds = {d["kind"] for d in body["detections"]}
    assert kinds.issuperset({"BOUNDARY", "GATE"}), f"expected boundary+gate, got {kinds}"
    # the correction round trip can consume the response directly
    assert client.post("/api/blueprint/reconstruct", json=body).status_code == 200


def test_reconstruct_applies_human_corrections():
    det = client.post(
        "/api/blueprint/detect",
        files={"file": ("venue.png", _png_bytes(), "image/png")},
    ).json()
    gates = [d for d in det["detections"] if d["kind"] == "GATE"]
    assert gates, "detection stage must produce gates"
    original_x = gates[0]["geometry"]["point"]["x"]
    gates[0]["geometry"]["point"]["x"] += 25
    gates[0]["metadata"]["kind"] = "EXIT_GATE"

    body = {"image": det["image"], "detections": det["detections"]}
    r = client.post("/api/blueprint/reconstruct", json=body)
    assert r.status_code == 200
    res = r.json()
    assert res["venue"]["id"] == "BLUEPRINT_VENUE"
    # the corrected gate is used by the venue
    openings = {o["id"]: o for o in res["spatial"]["openings"]}
    corrected = [o for o in openings.values() if round(o["position"]["x"]) != round(original_x)]
    assert corrected, "expected at least one opening to reflect the corrected position"


def test_reconstruct_persists_corrected_venue():
    det = client.post(
        "/api/blueprint/detect",
        files={"file": ("venue.png", _png_bytes(), "image/png")},
    ).json()
    r = client.post(
        "/api/blueprint/reconstruct",
        json={"image": det["image"], "detections": det["detections"]},
    )
    assert r.status_code == 200
    # persisted and retrievable under the deterministic id
    assert client.get("/api/venues/BLUEPRINT_VENUE").status_code == 200


def test_detect_rejects_non_image():
    r = client.post(
        "/api/blueprint/detect",
        files={"file": ("venue.png", b"not an image", "image/png")},
    )
    assert r.status_code == 422


def test_reconstruct_accepts_zone_structure_kind():
    det = client.post(
        "/api/blueprint/detect",
        files={"file": ("venue.png", _png_bytes(), "image/png")},
    ).json()
    # a region the review overlay typed as ZONE must reconstruct (not 500)
    det["detections"].append({
        "id": "REGION_ZONE",
        "kind": "REGION",
        "geometry": {
            "type": "POLYGON",
            "polygon": [
                {"x": 110, "y": 110}, {"x": 290, "y": 110},
                {"x": 290, "y": 240}, {"x": 110, "y": 240},
            ],
            "bbox": [110, 110, 290, 240],
        },
        "text": None,
        "confidence": 0.9,
        "source": "USER",
        "level_id": "L1",
        "metadata": {"kind": "ZONE"},
    })
    r = client.post("/api/blueprint/reconstruct", json=det)
    assert r.status_code == 200
    types = {s["type"] for s in r.json()["spatial"]["structures"]}
    assert "ZONE" in types, f"expected a ZONE structure, got {types}"


def test_reconstruction_atomic_commit_blocks_failed_quality(monkeypatch):
    """A quality-failing reconstruction is returned but never persisted."""
    import app.blueprint.docclass as docclass
    import app.routers.blueprint as bp
    from app.models import DocumentType

    calls: list = []
    orig = bp.storage.save_venue_document

    def spy(venue, spatial=None):
        calls.append(venue.id)
        return orig(venue, spatial)

    monkeypatch.setattr(bp.storage, "save_venue_document", spy)
    monkeypatch.setattr(
        docclass, "classify",
        lambda image: docclass.DocumentTypeResult(DocumentType.PERSPECTIVE_ARCHITECTURAL_DRAWING, 0.75, ["fake"]),
    )

    r = client.post(
        "/api/blueprint/import",
        files={"file": ("venue.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["quality"]["pass"] is False
    assert calls == [], "a quality-failing reconstruction must never be committed"
