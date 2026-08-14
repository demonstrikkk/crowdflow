"""Contract tests for the CrowdFlow Colab 3D worker.

Covers: provider registry / honest provenance, semantic contract validity,
GLB validity, and the full HTTP job lifecycle against a live uvicorn server.
"""
from __future__ import annotations

import json
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

# make the worker importable as a package: <repo>/infrastructure on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from colab_3d_worker.providers import (  # noqa: E402
    ADAPTER_BY_KEY, ProceduralGeometry, generate_geometry, registry_status, resolve_adapter,
)
from colab_3d_worker.semantic import analyze_blueprint, generate_stadium_semantic  # noqa: E402


# --------------------------------------------------------------------------- #
#  Semantic contract
# --------------------------------------------------------------------------- #
def test_semantic_payload_matches_contract():
    sem = generate_stadium_semantic(200, 120)
    assert sem["schema"] == "crowdflow.twin.semantic.v1"
    assert sem["venue"]["width_m"] == 200 and sem["venue"]["height_m"] == 120
    assert len(sem["gates"]) >= 2
    assert len(sem["exits"]) >= 1
    assert len(sem["emergency_exits"]) >= 1
    assert sem["structures"] and sem["paths"]
    assert "navigation" in sem and "bindings" in sem


def test_analyze_blueprint_uses_image_proportions(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (400, 200), "white")
    p = tmp_path / "plan.png"
    img.save(p)
    sem = analyze_blueprint(str(p), {})
    assert sem is not None
    assert sem["venue"]["width_m"] == 100.0  # 400px / 4
    assert sem["venue"]["height_m"] == 50.0  # 200px / 4


# --------------------------------------------------------------------------- #
#  Provider registry + honest provenance
# --------------------------------------------------------------------------- #
def test_registry_lists_all_models():
    reg = registry_status()
    for key in ("trellis", "hunyuan3d", "meshy", "tripo", "procedural"):
        assert key in reg
    assert reg["procedural"]["available"] is True


def test_procedural_always_available():
    assert resolve_adapter("procedural").key == "procedural"
    assert ADAPTER_BY_KEY["procedural"].available() is None


def test_unavailable_model_falls_back_to_procedural(tmp_path):
    p = tmp_path / "plan.png"
    from PIL import Image
    Image.new("RGB", (200, 200), "white").save(p)

    async def go():
        result = await generate_geometry("trellis", str(p), lambda *a: None)
        return result

    result = _run_async(go())
    assert result.provenance == "PROCEDURAL"
    assert result.adapter == "procedural"
    assert result.glb
    assert any("unavailable" in n for n in result.notes)


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
#  GLB validity
# --------------------------------------------------------------------------- #
def test_glb_is_valid_binary_gltf():
    from colab_3d_worker.glb import GlbMesh, write_glb
    m = GlbMesh("Structure_TEST", (0.3, 0.3, 0.3))
    m.add_box(0, 0, 0, 2, 2, 2)
    data = write_glb([m])
    magic, version, length = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF"
    assert version == 2
    assert length == len(data)
    jslen, jstype = struct.unpack("<II", data[12:20])
    assert jstype == 0x4E4F534A  # "JSON"
    doc = json.loads(data[20:20 + jslen])
    assert doc["meshes"] and doc["nodes"]
    assert doc["nodes"][0]["name"] == "Structure_TEST"


def test_build_glb_from_semantic():
    from colab_3d_worker.semantic import build_glb_from_semantic
    sem = generate_stadium_semantic(200, 120)
    data = build_glb_from_semantic(sem)
    magic, version, _ = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and version == 2


# --------------------------------------------------------------------------- #
#  Full HTTP lifecycle against a live worker
# --------------------------------------------------------------------------- #
def _start_worker():
    import uvicorn
    from colab_3d_worker.worker import app
    port = 0
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return f"http://127.0.0.1:{port}", server
        time.sleep(0.05)
    raise RuntimeError("worker failed to start")


def test_http_job_lifecycle():
    import httpx
    base, server = _start_worker()
    try:
        with httpx.Client(timeout=60.0) as c:
            h = c.get(f"{base}/health")
            assert h.status_code == 200
            assert h.json()["status"] == "ok"

            from PIL import Image
            import io
            buf = io.BytesIO()
            Image.new("RGB", (320, 160), "white").save(buf, format="PNG")
            jid = f"twg_{uuid.uuid4().hex[:8]}"

            r = c.post(
                f"{base}/jobs",
                data={"job_id": jid, "model": "trellis", "params": "{}"},
                files={"file": ("plan.png", buf.getvalue(), "image/png")},
            )
            assert r.status_code == 200
            assert r.json()["id"] == jid

            final = None
            for _ in range(200):
                st = c.get(f"{base}/jobs/{jid}").json()
                if st["status"] in ("COMPLETE", "FAILED", "CANCELLED"):
                    final = st
                    break
                time.sleep(0.05)
            assert final is not None, "job did not reach a terminal state"
            assert final["status"] == "COMPLETE", final
            # trellis not installed here -> honest PROCEDURAL provenance
            assert final["provenance"] == "PROCEDURAL"
            assert final["adapter"] == "procedural"
            assert final["progress"] == 100

            glb = c.get(f"{base}/jobs/{jid}/artifacts/venue.glb")
            assert glb.status_code == 200
            assert glb.content[:4] == b"glTF"
            sem = c.get(f"{base}/jobs/{jid}/artifacts/semantic.json")
            assert sem.status_code == 200
            assert json.loads(sem.content)["schema"] == "crowdflow.twin.semantic.v1"
            meta = c.get(f"{base}/jobs/{jid}/artifacts/generation.metadata.json")
            assert meta.status_code == 200
            assert json.loads(meta.content)["provenance"] == "PROCEDURAL"
    finally:
        server.should_exit = True


def test_http_cancel():
    import httpx
    base, server = _start_worker()
    try:
        with httpx.Client(timeout=30.0) as c:
            jid = f"twg_{uuid.uuid4().hex[:8]}"
            from PIL import Image
            import io
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
            c.post(f"{base}/jobs", data={"job_id": jid, "model": "procedural"}, files={"file": ("p.png", buf.getvalue(), "image/png")})
            r = c.post(f"{base}/jobs/{jid}/cancel")
            assert r.status_code == 200
            st = c.get(f"{base}/jobs/{jid}").json()
            assert st["status"] in ("CANCELLED", "COMPLETE")
    finally:
        server.should_exit = True


def test_missing_job_404():
    import httpx
    base, server = _start_worker()
    try:
        with httpx.Client(timeout=10.0) as c:
            assert c.get(f"{base}/jobs/nope").status_code == 404
            assert c.get(f"{base}/jobs/nope/artifacts/x").status_code == 404
    finally:
        server.should_exit = True


def test_optional_shared_secret_is_enforced():
    """WORKER_API_KEY set -> X-API-Key required; without it every route 401s."""
    import httpx
    import uvicorn
    from colab_3d_worker import worker as worker_mod

    old = worker_mod.WORKER_API_KEY
    worker_mod.WORKER_API_KEY = "s3cret"
    port = 0
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(worker_mod.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(timeout=10.0) as c:
            assert c.get(f"{base}/health").status_code == 401
            assert c.get(f"{base}/health", headers={"X-API-Key": "wrong"}).status_code == 401
            h = c.get(f"{base}/health", headers={"X-API-Key": "s3cret"})
            assert h.status_code == 200
            assert h.json()["auth_required"] is True
    finally:
        server.should_exit = True
        worker_mod.WORKER_API_KEY = old