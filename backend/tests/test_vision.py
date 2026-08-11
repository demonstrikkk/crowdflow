"""Vision (crowd sensing) tests with a mocked HF client - no network needed."""

import os

import pytest
from fastapi import HTTPException

from app.engine.vision import CrowdVisionService, _detections_to_count
from app.routers.vision import vision_service


class FakeClient:
    def __init__(self, detections=None, fail=False):
        self._detections = detections or []
        self._fail = fail
        self.calls = []

    def object_detection(self, image_path, model=None):
        assert os.path.exists(image_path), "expected a real temp file path"
        self.calls.append(model)
        if self._fail:
            raise RuntimeError("model exploded")
        return list(self._detections)


def test_detection_count_labels():
    detections = [
        {"label": "person", "score": 0.9},
        {"label": "Person", "score": 0.8},
        {"label": "pedestrian", "score": 0.7},
        {"label": "chair", "score": 0.6},
        {"label": "person-walking", "score": 0.5},
    ]
    assert _detections_to_count(detections) == 4


def test_estimate_crowd_happy_path(monkeypatch):
    svc = CrowdVisionService(token="fake", model_id="m1")
    dets = [{"label": "person", "score": 0.92}, {"label": "person", "score": 0.71}]
    client = FakeClient(dets)
    monkeypatch.setattr(svc, "_ensure_client", lambda: client)

    result = svc.estimate_crowd(b"fake-jpeg-bytes")
    assert result["estimated_count"] == 2
    assert result["density_score"] == pytest.approx(round(2 / 150.0, 3))
    assert result["mean_confidence"] == pytest.approx(0.815)
    assert result["model_id"] == "m1"
    assert len(result["detections"]) == 2


def test_estimate_falls_back_to_second_model(monkeypatch):
    svc = CrowdVisionService(token="fake", model_id="m1", fallback_models=["m2"])
    dets = [{"label": "person", "score": 0.8}]

    class FallbackClient(FakeClient):
        def object_detection(self, image_path, model=None):
            self.calls.append(model)
            if model == "m1":
                raise RuntimeError("m1 failed")
            return list(dets)

    client = FallbackClient()
    monkeypatch.setattr(svc, "_ensure_client", lambda: client)
    result = svc.estimate_crowd(b"bytes")
    assert result["model_id"] == "m2"
    assert result["estimated_count"] == 1
    assert client.calls == ["m1", "m2"]


def test_estimate_raises_503_without_token(monkeypatch):
    svc = CrowdVisionService(token=None, model_id="m1")
    client = FakeClient(fail=True)
    monkeypatch.setattr(svc, "_ensure_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        svc.estimate_crowd(b"bytes")
    assert exc.value.status_code == 503
    assert "HF_API_TOKEN" in exc.value.detail


def test_estimate_all_models_fail(monkeypatch):
    svc = CrowdVisionService(token="fake", model_id="m1")
    client = FakeClient(fail=True)
    monkeypatch.setattr(svc, "_ensure_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        svc.estimate_crowd(b"bytes")
    assert exc.value.status_code == 503


def test_empty_payload_rejected():
    svc = CrowdVisionService(token="fake")
    with pytest.raises(HTTPException) as exc:
        svc.estimate_crowd(b"")
    assert exc.value.status_code == 400


def test_api_crowd_estimate_requires_image():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/crowd-estimate",
        files={"file": ("crowd.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400


def test_api_crowd_estimate_mocked_service(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    dets = [{"label": "person", "score": 0.9}]

    def fake_estimate(image_bytes, content_type=None):
        return {
            "model_id": "mocked",
            "estimated_count": 1,
            "detections": [{"label": "person", "score": 0.9}],
            "density_score": 0.007,
            "mean_confidence": 0.9,
            "frame_area_m2": None,
        }

    monkeypatch.setattr(vision_service, "estimate_crowd", fake_estimate)
    client = TestClient(app)
    r = client.post(
        "/api/crowd-estimate",
        files={"file": ("crowd.png", b"fake-image-bytes", "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["estimated_count"] == 1
    assert body["density_score"] == pytest.approx(0.007)
