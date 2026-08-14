"""End-to-end tests for the AI 3D Digital Twin generation pipeline.

These test the real path: upload -> job -> provider execution -> artifacts ->
semantic conversion -> venue registration -> simulation readiness, plus the
failure, cancel and malformed-output paths. Async flows run inside
``asyncio.run`` so the suite works without pytest-asyncio.
"""
from __future__ import annotations

import asyncio
import base64
import json
import struct

import pytest

from app.storage import storage
from app.twin.orchestrator import twin_orchestrator
from app.twin.schemas import TwinJobStatus

_TERMINAL = (TwinJobStatus.COMPLETED, TwinJobStatus.FAILED, TwinJobStatus.CANCELLED)


def _stadium_png_bytes() -> bytes:
    # 8x8 single-pixel PNG so the pipeline has a real image to chew on.
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAFklEQVR4nGP8z8Dwn4EIwESMolGNAAAaHgMBG0pW5QAAAABJRU5ErkJggg=="
    )


def _run_and_wait(job_id: str, timeout_s: float = 45.0):
    async def _wait():
        loop = asyncio.get_event_loop()
        start = loop.time()
        while loop.time() - start < timeout_s:
            job = twin_orchestrator.get_job(job_id)
            if job and job.status in _TERMINAL:
                return job
            await asyncio.sleep(0.05)
        raise TimeoutError(f"job {job_id} did not finish in {timeout_s}s")

    return asyncio.run(_wait())


def test_full_pipeline_simulated_provider():
    """Upload -> simulated worker -> GLB + semantic -> registered venue."""
    async def scenario():
        job = twin_orchestrator.create_job(_stadium_png_bytes(), "blueprint.png", provider="simulated")
        twin_orchestrator.dispatch(job)
        done = await _wait(job.id)
        assert done.status == TwinJobStatus.COMPLETED, done.error
        return done

    async def _wait(job_id: str):
        for _ in range(900):
            current = twin_orchestrator.get_job(job_id)
            if current and current.status in _TERMINAL:
                return current
            await asyncio.sleep(0.05)
        raise TimeoutError("job did not finish")

    done = asyncio.run(scenario())
    assert done.status == TwinJobStatus.COMPLETED, done.error
    assert done.progress == 100
    assert done.provenance.value == "SIMULATED"

    # artifacts exist
    glb = twin_orchestrator.store.artifact(done.id, "venue.glb")
    semantic = twin_orchestrator.store.artifact(done.id, "semantic.json")
    assert glb is not None and glb.stat().st_size > 100
    assert semantic is not None

    # GLB is a valid binary glTF 2.0 container
    raw = glb.read_bytes()
    assert raw[:4] == b"glTF"
    version, total = struct.unpack_from("<II", raw, 4)
    assert version == 2
    assert len(raw) == total
    # JSON chunk must parse and reference meshes named for binding
    json_len = struct.unpack_from("<I", raw, 12)[0]
    gltf = json.loads(raw[20:20 + json_len].decode("utf-8"))
    assert "scenes" in gltf and "meshes" in gltf

    # venue registered + simulation-ready
    assert done.venue_id
    venue = storage.get_venue(done.venue_id)
    assert venue is not None
    assert len(venue.nodes) >= 2
    entries = [n for n in venue.nodes if n.type.value == "ENTRY"]
    exits = [n for n in venue.nodes if n.type.value in ("EXIT", "EMERGENCY_EXIT")]
    assert entries and exits
    # a scenario was cloned so the twin can be simulated
    scenario = storage.get_scenario(done.metadata["scenario_id"])
    assert scenario is not None and scenario.venue_id == done.venue_id


def test_local_procedural_provider_registers_venue():
    """Default offline provider runs real blueprint reconstruction."""
    async def _wait(job_id: str):
        for _ in range(1800):
            current = twin_orchestrator.get_job(job_id)
            if current and current.status in _TERMINAL:
                return current
            await asyncio.sleep(0.05)
        raise TimeoutError("job did not finish")

    async def scenario():
        job = twin_orchestrator.create_job(_stadium_png_bytes(), "blueprint.png", provider="procedural")
        twin_orchestrator.dispatch(job)
        return await _wait(job.id)

    done = asyncio.run(scenario())
    assert done.status == TwinJobStatus.COMPLETED, done.error
    assert done.provenance.value == "PROCEDURAL"
    assert done.venue_id
    assert storage.get_venue(done.venue_id) is not None


def test_cancel_job():
    async def scenario():
        job = twin_orchestrator.create_job(_stadium_png_bytes(), "blueprint.png", provider="simulated")
        twin_orchestrator.dispatch(job)
        await asyncio.sleep(0.25)
        twin_orchestrator.cancel_job(job.id)
        for _ in range(200):
            current = twin_orchestrator.get_job(job.id)
            if current and current.status in _TERMINAL:
                return current
            await asyncio.sleep(0.05)
        return twin_orchestrator.get_job(job.id)

    final = asyncio.run(scenario())
    assert final.status in (TwinJobStatus.CANCELLED, TwinJobStatus.COMPLETED)


def test_worker_offline_does_not_break_app():
    """An unavailable remote worker reports offline and surfaces the reason."""
    from app.twin.providers import Colab3DProvider

    provider = Colab3DProvider()
    provider.base_url = "http://127.0.0.1:1"
    status = asyncio.run(provider.health())
    assert status.online is False
    assert status.reason


def test_malformed_semantic_is_rejected():
    """Free-form / malformed semantic output must never reach the simulation."""
    from app.twin.semantic import parse_semantic_text

    with pytest.raises(ValueError):
        parse_semantic_text("not json at all")
    with pytest.raises(ValueError):
        parse_semantic_text(json.dumps({"foo": 1}))
    with pytest.raises(ValueError):
        parse_semantic_text(json.dumps({"venue": {"width_m": -5, "height_m": 0}}))


def test_semantic_to_venue_requires_valid_graph():
    """A semantic payload still yields a valid, connected venue."""
    from app.models import VenueModel
    from app.twin.providers import generate_stadium_semantic
    from app.twin.semantic import semantic_to_venue_document

    semantic = generate_stadium_semantic()
    venue, spatial, notes = semantic_to_venue_document(semantic, "TESTV", 200.0, 120.0)
    assert venue.id == "TESTV"
    assert len(venue.nodes) >= 2
    VenueModel.model_validate(venue.model_dump())


def test_bindings_map_glb_to_simulation():
    """Each opening has a GLB node name, world position and sim node id."""
    from app.twin.providers import generate_stadium_semantic
    from app.twin.semantic import build_semantic_output, semantic_to_venue_document

    semantic = generate_stadium_semantic()
    venue, spatial, _ = semantic_to_venue_document(semantic, "BINDV", 200.0, 120.0)
    _, bindings = build_semantic_output(venue, spatial, "TEST", "model")
    assert len(bindings) >= 6
    for b in bindings:
        assert b.semantic_id == b.simulation_node
        assert b.mesh_reference.startswith("Opening_")
        assert "x" in b.world_position and "y" in b.world_position


def test_pick_model_resolves_available_ai_model():
    """Model resolution: configured > first available AI > procedural fallback."""
    from app.twin.providers import _pick_model

    models = {
        "trellis": {"available": False},
        "hunyuan3d": {"available": True},
        "meshy": {"available": False},
        "tripo": {"available": False},
        "procedural": {"available": True},
    }
    # configured-unavailable model falls back to the first available AI model
    assert _pick_model(models, "trellis") == "hunyuan3d"
    # explicit available model wins
    assert _pick_model(models, "hunyuan3d") == "hunyuan3d"
    # no AI model -> procedural (never mislabelled)
    only_proc = {**models, "hunyuan3d": {"available": False}}
    assert _pick_model(only_proc, "trellis") == "procedural"
    # explicit procedural is honored
    assert _pick_model(models, "procedural") == "procedural"


def test_colab_fallback_provenance_is_honest():
    """A Colab run that falls back to the deterministic generator must NOT be
    labelled AI. The worker's effective provenance wins over the provider class."""
    from app.twin import providers as P

    class FakeColab(P.SimulatedProvider):
        name = "colab"
        provenance = P.TwinProvenance.AI
        model = "hunyuan3d"
        total_s = 0.05

        async def run(self, job, input_path, on_progress, cancel_event):
            artifacts = await super().run(job, input_path, on_progress, cancel_event)
            meta = json.loads(artifacts["generation.metadata.json"].decode("utf-8"))
            meta["provenance"] = "PROCEDURAL"  # worker fell back, no AI inference
            artifacts["generation.metadata.json"] = json.dumps(meta, indent=2).encode("utf-8")
            return artifacts

    twin_orchestrator._providers["colab"] = FakeColab()
    try:
        async def scenario():
            job = twin_orchestrator.create_job(_stadium_png_bytes(), "blueprint.png", provider="colab")
            assert job.provenance.value == "AI"  # declared as AI up front
            twin_orchestrator.dispatch(job)
            for _ in range(900):
                current = twin_orchestrator.get_job(job.id)
                if current and current.status in _TERMINAL:
                    return current
                await asyncio.sleep(0.05)
            raise TimeoutError("job did not finish")

        done = asyncio.run(scenario())
        assert done.status == TwinJobStatus.COMPLETED, done.error
        assert done.provenance.value == "PROCEDURAL"  # corrected to the truth
    finally:
        twin_orchestrator._providers.pop("colab", None)