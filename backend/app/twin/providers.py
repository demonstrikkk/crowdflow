"""ImageTo3D provider abstraction.

The backend never hard-codes a single 3D model. A job is executed by a
provider; the first real one is the Colab GPU worker (``Colab3DProvider``),
with a local deterministic reconstruction (``LocalProceduralProvider``) as the
development fallback and a ``SimulatedProvider`` for tests/demo. Swapping
TRELLIS / Hunyuan3D / Tripo / Meshy later means adding a new provider or
configuring the worker's model — never rewriting CrowdFlow.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from ..twin.schemas import TwinJobStatus, TwinProvenance, TwinProviderStatus, TwinStage
from .semantic import build_semantic_output, build_venue_glb

ProgressCallback = Callable[[TwinStage, int, Optional[str]], None]

_ENV_PACE_S = float(os.getenv("TWIN_STAGE_PACE_S", "0.6"))
_ENV_POLL_S = float(os.getenv("TWIN_COLAB_POLL_S", "2.0"))
_ENV_COLAB_TIMEOUT_S = float(os.getenv("TWIN_COLAB_TIMEOUT_S", "60.0"))


class ImageTo3DProvider(ABC):
    name: str = "base"
    provenance: TwinProvenance = TwinProvenance.PROCEDURAL
    model: str = "configured-model"

    @abstractmethod
    async def health(self) -> TwinProviderStatus:
        """Report whether the provider can run a job right now."""

    @abstractmethod
    async def run(
        self,
        job: Any,
        input_path: Path,
        on_progress: ProgressCallback,
        cancel_event: asyncio.Event,
    ) -> Dict[str, bytes]:
        """Execute the generation and return artifact bytes.

        Keys use the output contract: ``venue.glb``, ``semantic.json``,
        ``generation.metadata.json``, optional ``preview.png``.
        """


# --------------------------------------------------------------------------- #
#  Deterministic stadium generator (shared fallback / simulated provider)
# --------------------------------------------------------------------------- #
def generate_stadium_semantic(width: float = 200.0, height: float = 120.0) -> Dict[str, Any]:
    """Build a canonical stadium semantic payload without any AI or CV.

    Used by the simulated provider and as a hard fallback when local
    blueprint reconstruction is unavailable.
    """
    cx, cy = width / 2.0, height / 2.0
    rx, ry = width * 0.34, height * 0.40
    def ellipse(n: int) -> List[Dict[str, float]]:
        return [{"x": round(cx + rx * math.cos(2 * math.pi * i / n), 2),
                 "y": round(cy + ry * math.sin(2 * math.pi * i / n), 2)} for i in range(n)]

    pitch = [{"x": round(cx - width * 0.20, 2), "y": round(cy - height * 0.16, 2)},
             {"x": round(cx + width * 0.20, 2), "y": round(cy - height * 0.16, 2)},
             {"x": round(cx + width * 0.20, 2), "y": round(cy + height * 0.16, 2)},
             {"x": round(cx - width * 0.20, 2), "y": round(cy + height * 0.16, 2)}]
    outer = ellipse(16)

    gates = [
        {"id": "GATE_A", "label": "Gate A", "type": "ENTRY_GATE",
         "position": {"x": round(cx - width * 0.30, 2), "y": 12.0}, "width_m": 8.0, "capacity": 180},
        {"id": "GATE_B", "label": "Gate B", "type": "ENTRY_GATE",
         "position": {"x": round(cx + width * 0.30, 2), "y": 12.0}, "width_m": 8.0, "capacity": 180},
        {"id": "GATE_C", "label": "Gate C", "type": "ENTRY_GATE",
         "position": {"x": 12.0, "y": round(cy, 2)}, "width_m": 8.0, "capacity": 180},
        {"id": "GATE_D", "label": "Gate D", "type": "ENTRY_GATE",
         "position": {"x": round(width - 12.0, 2), "y": round(cy, 2)}, "width_m": 8.0, "capacity": 180},
        {"id": "EXIT_N", "label": "Exit North", "type": "EXIT_GATE",
         "position": {"x": round(cx, 2), "y": round(height - 12.0, 2)}, "width_m": 10.0, "capacity": 220},
        {"id": "EXIT_S", "label": "Exit South", "type": "EXIT_GATE",
         "position": {"x": round(cx, 2), "y": 12.0}, "width_m": 10.0, "capacity": 220},
        {"id": "EMERGENCY_1", "label": "Emergency Exit 1", "type": "EMERGENCY_EXIT",
         "position": {"x": round(cx - width * 0.28, 2), "y": round(height - 12.0, 2)}, "width_m": 6.0, "capacity": 140},
        {"id": "EMERGENCY_2", "label": "Emergency Exit 2", "type": "EMERGENCY_EXIT",
         "position": {"x": round(cx + width * 0.28, 2), "y": round(height - 12.0, 2)}, "width_m": 6.0, "capacity": 140},
    ]

    structures = [
        {"id": "PITCH", "type": "FIELD", "level_id": "L0", "polygon": {"points": pitch}, "height_m": 0.15},
        {"id": "STAND_N", "type": "SEATING", "level_id": "L0", "polygon": {"points": ellipse(10)}, "height_m": 1.6},
        {"id": "CONCOURSE_1", "type": "CONCOURSE", "level_id": "L0",
         "polygon": {"points": [{"x": round(cx - width * 0.42, 2), "y": round(cy - height * 0.3, 2)},
                                 {"x": round(cx + width * 0.42, 2), "y": round(cy - height * 0.3, 2)},
                                 {"x": round(cx + width * 0.42, 2), "y": round(cy + height * 0.3, 2)},
                                 {"x": round(cx - width * 0.42, 2), "y": round(cy + height * 0.3, 2)}]},
         "height_m": 0.25},
    ]
    for i, (x, y) in enumerate(((10, 10), (width - 10, 10), (10, height - 10), (width - 10, height - 10))):
        structures.append({"id": f"WALL_CORNER_{i}", "type": "WALL", "level_id": "L0",
                           "polygon": {"points": [{"x": x, "y": y}, {"x": x + 6, "y": y},
                                                  {"x": x + 6, "y": y + 6}, {"x": x, "y": y + 6}]},
                           "height_m": 3.0})

    paths = []
    for g in gates:
        if g["type"] == "ENTRY_GATE":
            paths.append({"id": f"PATH_{g['id']}_PITCH", "level_id": "L0",
                          "centerline": [g["position"], {"x": round(cx, 2), "y": round(cy, 2)}],
                          "width_m": 5.0})
    for e in ("EMERGENCY_1", "EMERGENCY_2"):
        paths.append({"id": f"PATH_{e}_EXIT", "level_id": "L0",
                      "centerline": [{"x": round(cx, 2), "y": round(cy, 2)},
                                     {"x": round(cx, 2), "y": round(height - 12.0, 2)}],
                      "width_m": 6.0})

    return {
        "schema": "crowdflow.twin.semantic.v1",
        "venue": {"id": "GENERATED", "name": "Generated Stadium", "type": "stadium",
                  "width_m": width, "height_m": height},
        "levels": [{"id": "L0", "name": "Ground", "elevation_m": 0.0, "height_m": 5.0}],
        "structures": structures,
        "gates": [g for g in gates if g["type"] == "ENTRY_GATE"],
        "exits": [g for g in gates if g["type"] == "EXIT_GATE"],
        "emergency_exits": [g for g in gates if g["type"] == "EMERGENCY_EXIT"],
        "zones": [],
        "paths": paths,
        "navigation": {"nodes": [], "edges": []},
        "bindings": [],
        "metadata": {"source": "SIMULATED", "model": "deterministic-stadium-v1", "notes": []},
    }


import math  # noqa: E402


# --------------------------------------------------------------------------- #
#  Local deterministic reconstruction (DEVELOPMENT FALLBACK, provenance = PROCEDURAL)
# --------------------------------------------------------------------------- #
class LocalProceduralProvider(ImageTo3DProvider):
    name = "procedural"
    provenance = TwinProvenance.PROCEDURAL
    model = os.getenv("TWIN_PROCEDURAL_MODEL", "blueprint-cv-v1")

    async def health(self) -> TwinProviderStatus:
        return TwinProviderStatus(provider=self.name, model=self.model, online=True, provenance=self.provenance)

    async def run(self, job, input_path, on_progress, cancel_event) -> Dict[str, bytes]:
        on_progress(TwinStage.ANALYZING, 8, "Analyzing blueprint with local reconstruction")

        def _reconstruct() -> Optional[Dict[str, Any]]:
            from ..blueprint.pipeline import import_blueprint
            data = input_path.read_bytes()
            result = import_blueprint(data, job.input_name or input_path.name)
            if result.venue is not None and result.spatial is not None:
                return {
                    "venue": result.venue,
                    "spatial": result.spatial,
                    "notes": list(result.notes or []) + [f"confidence {round(result.confidence, 3)}"],
                }
            return None

        result = await asyncio.to_thread(_reconstruct)
        if result is None:
            semantic = generate_stadium_semantic()
            notes = ["blueprint CV reconstruction unavailable; deterministic stadium used"]
        else:
            semantic, _bindings = build_semantic_output(
                result["venue"], result["spatial"], "PROCEDURAL", self.model, result.get("notes")
            )
            notes = result.get("notes", [])

        if cancel_event.is_set():
            raise _Cancelled()

        on_progress(TwinStage.GENERATING_GEOMETRY, 45, "Generating 3D geometry (GLB)")
        glb_bytes = _glb_from_semantic(semantic)

        if cancel_event.is_set():
            raise _Cancelled()

        on_progress(TwinStage.SEMANTIC_PROCESSING, 68, "Extracting semantic venue structure")
        semantic_bytes = json.dumps(semantic, indent=2).encode("utf-8")

        on_progress(TwinStage.EXPORTING, 88, "Exporting generation metadata")
        meta = {"provenance": "PROCEDURAL", "model": self.model, "notes": notes}
        meta_bytes = json.dumps(meta, indent=2).encode("utf-8")

        await asyncio.sleep(max(0.0, _ENV_PACE_S))
        on_progress(TwinStage.COMPLETE, 100, "Twin generated")
        return {
            "venue.glb": glb_bytes,
            "semantic.json": semantic_bytes,
            "generation.metadata.json": meta_bytes,
        }


# --------------------------------------------------------------------------- #
#  Simulated worker (tests / offline demo, provenance = SIMULATED)
# --------------------------------------------------------------------------- #
class SimulatedProvider(ImageTo3DProvider):
    name = "simulated"
    provenance = TwinProvenance.SIMULATED
    model = os.getenv("TWIN_SIMULATED_MODEL", "sim-worker-v1")
    total_s = float(os.getenv("TWIN_SIMULATED_SECONDS", "3.0"))

    async def health(self) -> TwinProviderStatus:
        return TwinProviderStatus(provider=self.name, model=self.model, online=True, provenance=self.provenance)

    async def run(self, job, input_path, on_progress, cancel_event) -> Dict[str, bytes]:
        steps: List[tuple] = [
            (TwinStage.DOWNLOADING, 5, "Worker downloading input"),
            (TwinStage.ANALYZING, 22, "Worker analyzing blueprint"),
            (TwinStage.GENERATING_GEOMETRY, 48, "Worker generating 3D geometry"),
            (TwinStage.GENERATING_TEXTURE, 62, "Worker generating textures"),
            (TwinStage.SEMANTIC_PROCESSING, 78, "Worker extracting semantic venue"),
            (TwinStage.EXPORTING, 92, "Worker exporting GLB + semantic JSON"),
        ]
        for stage, progress, msg in steps:
            if cancel_event.is_set():
                raise _Cancelled()
            on_progress(stage, progress, msg)
            await asyncio.sleep(self.total_s / len(steps))

        semantic = generate_stadium_semantic()
        glb_bytes = _glb_from_semantic(semantic)
        if cancel_event.is_set():
            raise _Cancelled()
        meta = {"provenance": "SIMULATED", "model": self.model, "notes": ["emulated worker, no AI inference"]}
        on_progress(TwinStage.COMPLETE, 100, "Twin generated (simulated)")
        return {
            "venue.glb": glb_bytes,
            "semantic.json": json.dumps(semantic, indent=2).encode("utf-8"),
            "generation.metadata.json": json.dumps(meta, indent=2).encode("utf-8"),
        }


# --------------------------------------------------------------------------- #
#  Colab GPU worker (real AI, provenance = AI)
# --------------------------------------------------------------------------- #
# ngrok free tunnels answer every request without this header with an HTML
# browser-warning interstitial instead of JSON, which breaks the worker API.
_NGROK_SKIP_HEADER = {"ngrok-skip-browser-warning": "true"}

# Preference order for picking a real AI geometry model the worker actually has,
# when TWIN_COLAB_MODEL is unset or points at an unavailable model.
_MODEL_PRIORITY = ["hunyuan3d", "trellis", "meshy", "tripo"]


def _pick_model(models: Dict[str, Any], configured: str) -> str:
    """Choose the model to run from the worker's /health ``models`` map.

    Honors the configured model when available; otherwise picks the first
    available real-AI model; returns ``procedural`` when none is available so
    the result is never mislabelled.
    """
    cfg = (configured or "").strip().lower()
    if cfg == "procedural":
        return "procedural"
    if cfg and models.get(cfg, {}).get("available"):
        return cfg
    for name in _MODEL_PRIORITY:
        if models.get(name, {}).get("available"):
            return name
    return "procedural"


class Colab3DProvider(ImageTo3DProvider):
    name = "colab"
    provenance = TwinProvenance.AI
    model = os.getenv("TWIN_COLAB_MODEL", "trellis")

    def __init__(self) -> None:
        self.base_url = os.getenv("TWIN_COLAB_URL", "").rstrip("/")
        self.api_key = os.getenv("TWIN_COLAB_API_KEY", "")
        if not self.base_url:
            self.base_url = os.getenv("TWIN_COLAB_OVERRIDE_URL", "").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        headers = dict(_NGROK_SKIP_HEADER)
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def _worker_model(self) -> str:
        """Resolve the model the worker can actually run.

        Honors TWIN_COLAB_MODEL when that model is available; otherwise picks the
        first available real-AI model (hunyuan3d > trellis > meshy > tripo);
        returns ``procedural`` when no AI model is available so the result is
        never mislabelled.
        """
        configured = (self.model or "").strip().lower()
        if configured == "procedural":
            return "procedural"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{self.base_url}/health", headers=self._headers())
            if r.status_code != 200:
                return configured or "procedural"
            models = r.json().get("models", {})
        except Exception:
            return configured or "procedural"
        return _pick_model(models, configured)

    async def health(self) -> TwinProviderStatus:
        if not self.base_url:
            return TwinProviderStatus(
                provider=self.name, model=self.model, online=False,
                provenance=self.provenance,
                reason="TWIN_COLAB_URL not configured",
            )
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{self.base_url}/health", headers=self._headers())
            if r.status_code == 200:
                return TwinProviderStatus(provider=self.name, model=await self._worker_model(), online=True, provenance=self.provenance)
            return TwinProviderStatus(provider=self.name, model=self.model, online=False, provenance=self.provenance, reason=f"worker health {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            return TwinProviderStatus(provider=self.name, model=self.model, online=False, provenance=self.provenance, reason=str(exc))

    async def run(self, job, input_path, on_progress, cancel_event) -> Dict[str, bytes]:
        if not self.base_url:
            raise RuntimeError("Colab worker not configured (set TWIN_COLAB_URL)")
        import httpx

        on_progress(TwinStage.DOWNLOADING, 5, "Submitting job to Colab GPU worker")
        async with httpx.AsyncClient(timeout=_ENV_COLAB_TIMEOUT_S) as client:
            headers = self._headers()
            resolved_model = await self._worker_model()
            if job.model != resolved_model:
                job.model = resolved_model  # reflect what will actually run
            with open(input_path, "rb") as fh:
                r = await client.post(
                    f"{self.base_url}/jobs",
                    headers=headers,
                    data={"job_id": job.id, "model": resolved_model,
                          "params": json.dumps(job.metadata.get("params", {}))},
                    files={"file": (job.input_name or "input.png", fh,
                                    "image/png" if str(input_path).lower().endswith((".png", ".jpg", ".jpeg")) else "application/octet-stream")},
                )
            if r.status_code not in (200, 202):
                raise RuntimeError(f"worker submit failed ({r.status_code}): {r.text[:300]}")
            provider_job = r.json().get("id") or job.id

            while True:
                if cancel_event.is_set():
                    await client.post(f"{self.base_url}/jobs/{provider_job}/cancel", headers=headers)
                    raise _Cancelled()
                await asyncio.sleep(_ENV_POLL_S)
                st = await client.get(f"{self.base_url}/jobs/{provider_job}", headers=headers)
                if st.status_code != 200:
                    raise RuntimeError(f"worker status failed ({st.status_code})")
                data = st.json()
                status = str(data.get("status", "RUNNING")).upper()
                stage = _map_worker_stage(str(data.get("stage", "")).upper())
                progress = int(data.get("progress", 20))
                on_progress(stage, max(5, min(90, progress)), data.get("message") or "worker generating")
                if status in ("COMPLETE", "COMPLETED"):
                    break
                if status in ("FAILED", "ERROR"):
                    raise RuntimeError(data.get("error") or "worker reported failure")
                if status in ("CANCELLED",):
                    raise _Cancelled()

            artifacts: Dict[str, bytes] = {}
            for name in ("venue.glb", "semantic.json", "generation.metadata.json", "preview.png"):
                ar = await client.get(f"{self.base_url}/jobs/{provider_job}/artifacts/{name}", headers=headers)
                if ar.status_code == 200:
                    artifacts[name] = ar.content
            if "venue.glb" not in artifacts or "semantic.json" not in artifacts:
                raise RuntimeError("worker completed without venue.glb/semantic.json artifacts")
            on_progress(TwinStage.COMPLETE, 100, "Twin generated by Colab worker")
            return artifacts


def _map_worker_stage(stage: str) -> TwinStage:
    mapping = {
        "QUEUED": TwinStage.QUEUED,
        "DOWNLOADING": TwinStage.DOWNLOADING,
        "ANALYZING": TwinStage.ANALYZING,
        "GENERATING_GEOMETRY": TwinStage.GENERATING_GEOMETRY,
        "GENERATING_TEXTURE": TwinStage.GENERATING_TEXTURE,
        "SEMANTIC_PROCESSING": TwinStage.SEMANTIC_PROCESSING,
        "EXPORTING": TwinStage.EXPORTING,
        "COMPLETE": TwinStage.COMPLETE,
    }
    return mapping.get(stage, TwinStage.RUNNING if stage in ("RUNNING",) else TwinStage.ANALYZING)


def _glb_from_semantic(semantic: Dict[str, Any]) -> bytes:
    """Render a semantic payload into GLB bytes (shared by local/simulated)."""
    from .semantic import semantic_to_venue_document
    venue, spatial, _ = semantic_to_venue_document(
        semantic, "GENERATED", float(semantic.get("venue", {}).get("width_m", 200)),
        float(semantic.get("venue", {}).get("height_m", 120)),
    )
    return build_venue_glb(venue, spatial)


class _Cancelled(Exception):
    pass


class ProviderError(Exception):
    """Raised when a provider fails (job marked FAILED with the reason)."""