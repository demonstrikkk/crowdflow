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
