"""Model adapters for the Colab 3D worker.

An adapter is a single 3D-model backend. Every completed job records its TRUE
provenance:

    AI          -> a real 3D model produced the geometry
    PROCEDURAL  -> the deterministic fallback ran (no AI inference available)

An adapter reports ``available()`` and raises ``ModelUnavailable`` when it
cannot run, so the worker never guesses and never fabricates an "AI" label for
a procedural result. TRELLIS / Hunyuan3D are in-process GPU models (must be
installed in the Colab runtime); Tripo / Meshy are hosted REST APIs (require an
API key). ``ProceduralGeometry`` always runs, so the worker is usable on a fresh
Colab instance before any weights or keys are provisioned.
"""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .semantic import build_glb_from_semantic

ProgressCallback = Callable[[str, int, Optional[str]], None]


class ModelUnavailable(Exception):
    """Raised when a requested adapter cannot run in this environment."""


@dataclass
class GeometryResult:
    glb: bytes
    provenance: str  # "AI" | "PROCEDURAL"
    adapter: str
    notes: List[str] = field(default_factory=list)


class GeometryModel(ABC):
    key: str = "base"
    display_name: str = "base"

    @abstractmethod
    def available(self) -> Optional[str]:
        """Return None if usable, else a human-readable reason it is not."""

    @abstractmethod
    async def generate(self, input_path: str, on_progress: ProgressCallback) -> bytes:
        """Produce GLB bytes from the blueprint image. Raises ModelUnavailable."""


# --------------------------------------------------------------------------- #
#  In-process GPU models (must be installed in the Colab runtime)
# --------------------------------------------------------------------------- #
class TrellisGeometry(GeometryModel):
    key = "trellis"
    display_name = "TRELLIS (Microsoft, GPU)"

    def available(self) -> Optional[str]:
        try:
            import trellis  # noqa: F401
            return None
        except Exception as exc:  # noqa: BLE001
            return f"trellis package not installed ({exc.__class__.__name__})"

    async def generate(self, input_path: str, on_progress: ProgressCallback) -> bytes:
        reason = self.available()
        if reason is not None:
            raise ModelUnavailable(reason)
        # TRELLIS on Colab is a dead end as of 2026: it pins torch==2.4.0+cu121,
        # whose nvidia-cudnn-cu12==9.1.0.70 dependency was removed from the PyTorch
        # index, so the runtime keeps a newer torch and Kaolin's _C.so crashes with
        # an ABI mismatch ("undefined symbol: _ZNK3c105Error4whatEv"). Use the
        # Hunyuan3D adapter instead, which pip-installs cleanly on the free T4.
        raise NotImplementedError(
            "TRELLIS install is broken on Colab (torch 2.4.0 wheel chain removed). "
            "Use the 'hunyuan3d' model adapter instead."
        )


class Hunyuan3DGeometry(GeometryModel):
    key = "hunyuan3d"
    display_name = "Hunyuan3D (Tencent, GPU)"

    def available(self) -> Optional[str]:
        try:
            import hy3dgen  # noqa: F401
            import torch
            if not torch.cuda.is_available():
                return "hy3dgen installed but no CUDA GPU in this runtime"
            return None
        except Exception as exc:  # noqa: BLE001
            return f"hy3dgen package not installed ({exc.__class__.__name__})"

    async def generate(self, input_path: str, on_progress: ProgressCallback) -> bytes:
        reason = self.available()
        if reason is not None:
            raise ModelUnavailable(reason)
        # Real Hunyuan3D-2mini inference (hy3dgen). Runs on the free Colab T4
        # (~6 GB VRAM for shape gen). Configurable via env so users can pick the
        # mini/standard/turbo variant or the full Hunyuan3D-2 model.
        model_id = os.getenv("HUNYUAN3D_MODEL", "tencent/Hunyuan3D-2mini")
        subfolder = os.getenv("HUNYUAN3D_SUBFOLDER", "hunyuan3d-dit-v2-mini")
        variant = os.getenv("HUNYUAN3D_VARIANT", "fp16")
        steps = int(os.getenv("HUNYUAN3D_STEPS", "30"))
        octree = int(os.getenv("HUNYUAN3D_OCTREE_RESOLUTION", "320"))
        chunks = int(os.getenv("HUNYUAN3D_NUM_CHUNKS", "8000"))
        device = os.getenv("HUNYUAN3D_DEVICE", "cuda")

        def _prepare() -> Any:
            from PIL import Image
            image = Image.open(input_path).convert("RGB")
            try:
                from hy3dgen.rembg import BackgroundRemover
                return BackgroundRemover()(image)
            except Exception:  # noqa: BLE001 - rembg is optional
                return image

        def _load() -> Any:
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
            return Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                model_id, subfolder=subfolder, variant=variant, device=device,
            )

        def _generate(image: Any) -> Any:
            import torch
            return pipeline(
                image=image,
                num_inference_steps=steps,
                guidance_scale=7.5,
                octree_resolution=octree,
                num_chunks=chunks,
                generator=torch.manual_seed(0),
                output_type="trimesh",
            )[0]

        def _export(mesh: Any) -> bytes:
            import io
            buf = io.BytesIO()
            mesh.export(buf, file_type="glb")
            return buf.getvalue()

        on_progress("ANALYZING", 20, "Hunyuan3D: preparing input image")
        image = await asyncio.to_thread(_prepare)
        on_progress("LOADING_MODEL", 40, f"Hunyuan3D: loading {model_id} ({subfolder})")
        pipeline = await asyncio.to_thread(_load)
        on_progress("GENERATING_GEOMETRY", 55, "Hunyuan3D: reconstructing mesh")
        mesh = await asyncio.to_thread(_generate, image)
        on_progress("EXPORTING", 85, "Hunyuan3D: exporting GLB")
        return await asyncio.to_thread(_export, mesh)


# --------------------------------------------------------------------------- #
#  Hosted REST APIs (require an API key; run regardless of local GPU)
# --------------------------------------------------------------------------- #
class MeshyGeometry(GeometryModel):
    key = "meshy"
    display_name = "Meshy (hosted API)"

    def __init__(self) -> None:
        self.api_key = os.getenv("MESHY_API_KEY", "").strip()
        self.base = "https://api.meshy.ai/v2"

    def available(self) -> Optional[str]:
        if not self.api_key:
            return "MESHY_API_KEY not configured"
        return None

    async def generate(self, input_path: str, on_progress: ProgressCallback) -> bytes:
        import httpx
        if not self.api_key:
            raise ModelUnavailable(self.available())
        data_url = _to_data_url(input_path)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        on_progress("ANALYZING", 15, "Meshy: submitting image-to-3d task")
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self.base}/image-to-3d",
                headers=headers,
                json={"image_url": data_url, "model_name": "meshy-4", "enable_pbr": False, "texture": False},
            )
            r.raise_for_status()
            task_id = r.json()["result"]
            while True:
                await asyncio.sleep(4)
                st = await client.get(f"{self.base}/image-to-3d/{task_id}", headers=headers)
                st.raise_for_status()
                data = st.json()
                status = data.get("status")
                on_progress("GENERATING_GEOMETRY", 50, f"Meshy: {status}")
                if status == "SUCCEEDED":
                    break
                if status == "FAILED":
                    raise RuntimeError(f"Meshy task failed: {data.get('error', '')}")
            model_url = (data.get("model_urls") or {}).get("glb")
            if not model_url:
                raise RuntimeError("Meshy returned no GLB")
            on_progress("EXPORTING", 85, "Meshy: downloading GLB")
            dl = await client.get(model_url)
            dl.raise_for_status()
            return dl.content


class TripoGeometry(GeometryModel):
    key = "tripo"
    display_name = "Tripo (hosted API)"

    def __init__(self) -> None:
        self.api_key = os.getenv("TRIPO_API_KEY", "").strip()
        self.base = "https://api.tripo3d.ai/v2/openapi"

    def available(self) -> Optional[str]:
        if not self.api_key:
            return "TRIPO_API_KEY not configured"
        return None

    async def generate(self, input_path: str, on_progress: ProgressCallback) -> bytes:
        import httpx
        if not self.api_key:
            raise ModelUnavailable(self.available())
        headers = {"Authorization": f"Bearer {self.api_key}"}
        on_progress("ANALYZING", 15, "Tripo: uploading input")
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(input_path, "rb") as fh:
                up = await client.post(
                    f"{self.base}/image-to-model/upload",
                    headers=headers,
                    files={"file": (os.path.basename(input_path), fh)},
                )
            up.raise_for_status()
            image_id = up.json()["data"]["id"]
            task = await client.post(
                f"{self.base}/task",
                headers=headers,
                json={"type": "image_to_model", "model": {"image_id": image_id}},
            )
            task.raise_for_status()
            task_id = task.json()["data"]["task_id"]
            while True:
                await asyncio.sleep(5)
                st = await client.get(f"{self.base}/task/{task_id}", headers=headers)
                st.raise_for_status()
                data = st.json()["data"]
                status = data.get("status")
                on_progress("GENERATING_GEOMETRY", 50, f"Tripo: {status}")
                if status == "success":
                    break
                if status in ("failed", "cancelled"):
                    raise RuntimeError(f"Tripo task {status}: {data.get('error', '')}")
            model_url = (data.get("output") or {}).get("model")
            if not model_url:
                raise RuntimeError("Tripo returned no model")
            on_progress("EXPORTING", 85, "Tripo: downloading GLB")
            dl = await client.get(model_url)
            dl.raise_for_status()
            return dl.content


# --------------------------------------------------------------------------- #
#  Deterministic fallback (always available)
# --------------------------------------------------------------------------- #
class ProceduralGeometry(GeometryModel):
    key = "procedural"
    display_name = "Deterministic fallback"

    def available(self) -> Optional[str]:
        return None

    async def generate(self, input_path: str, on_progress: ProgressCallback) -> bytes:
        on_progress("GENERATING_GEOMETRY", 45, "Procedural fallback: building GLB")
        from .semantic import analyze_blueprint, generate_stadium_semantic

        semantic = analyze_blueprint(input_path, {}) or generate_stadium_semantic()
        glb = await asyncio.to_thread(build_glb_from_semantic, semantic)
        return glb


# --------------------------------------------------------------------------- #
#  Registry + orchestration
# --------------------------------------------------------------------------- #
ADAPTERS: List[GeometryModel] = [
    TrellisGeometry(),
    Hunyuan3DGeometry(),
    MeshyGeometry(),
    TripoGeometry(),
    ProceduralGeometry(),
]

ADAPTER_BY_KEY = {a.key: a for a in ADAPTERS}

DEFAULT_MODEL = os.getenv("COLAB_MODEL", "hunyuan3d")


def resolve_adapter(model: Optional[str]) -> GeometryModel:
    """Pick the requested adapter, falling back to ProceduralGeometry."""
    key = (model or DEFAULT_MODEL).strip().lower()
    adapter = ADAPTER_BY_KEY.get(key)
    if adapter is not None and adapter.available() is None:
        return adapter
    return ADAPTER_BY_KEY["procedural"]


async def generate_geometry(model: Optional[str], input_path: str, on_progress: ProgressCallback) -> GeometryResult:
    """Run the best available adapter for the requested model.

    Returns a GeometryResult whose ``provenance`` is AI only when a real model
    produced the geometry; otherwise the result is marked PROCEDURAL.
    """
    requested = (model or DEFAULT_MODEL).strip().lower()
    adapter = resolve_adapter(requested)
    if adapter.key == "procedural":
        glb = await adapter.generate(input_path, on_progress)
        return GeometryResult(
            glb=glb,
            provenance="PROCEDURAL",
            adapter=adapter.key,
            notes=[f"requested model '{requested}' unavailable; deterministic fallback used"],
        )
    try:
        glb = await adapter.generate(input_path, on_progress)
        return GeometryResult(
            glb=glb,
            provenance="AI",
            adapter=adapter.key,
            notes=[f"geometry generated by {adapter.display_name}"],
        )
    except (ModelUnavailable, NotImplementedError) as exc:  # noqa: BLE001
        glb = await ADAPTER_BY_KEY["procedural"].generate(input_path, on_progress)
        return GeometryResult(
            glb=glb,
            provenance="PROCEDURAL",
            adapter="procedural",
            notes=[f"requested model '{requested}' unavailable ({exc}); deterministic fallback used"],
        )


def registry_status() -> Dict[str, Any]:
    return {
        key: {
            "display": a.display_name,
            "available": a.available() is None,
            "reason": a.available(),
        }
        for key, a in ADAPTER_BY_KEY.items()
    }


def _to_data_url(path: str) -> str:
    import base64
    with open(path, "rb") as f:
        raw = f.read()
    ext = os.path.splitext(path)[1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext.lstrip("."), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
