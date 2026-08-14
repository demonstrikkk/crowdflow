"""CrowdFlow Colab 3D worker service (FastAPI).

Runs standalone on a Colab GPU runtime (or locally for development). The
CrowdFlow backend polls this service; it never pushes state back, so network
failures between the two only affect the current twin job, never the app.

Run locally:
    pip install -r requirements.txt
    uvicorn worker:app --port 8097

In Colab, see colab_worker.ipynb (starts this server behind a tunnel).
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from . import __doc__ as PACKAGE_DOC
from .providers import DEFAULT_MODEL, generate_geometry, registry_status
from .semantic import analyze_blueprint, build_glb_from_semantic, build_metadata, generate_stadium_semantic

DATA_DIR = Path(os.getenv("WORKER_DATA_DIR", Path(__file__).resolve().parent / "_data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Optional shared secret. If unset (the common case — the ngrok tunnel URL is
# the only credential), every caller is accepted. Set it on the Colab side and
# mirror it as TWIN_COLAB_API_KEY on the backend to require X-API-Key auth.
WORKER_API_KEY = os.getenv("WORKER_API_KEY", "")

app = FastAPI(title="CrowdFlow Colab 3D Worker", version="1.0.0")

_JOBS: Dict[str, dict] = {}
_TASKS: Dict[str, asyncio.Task] = {}
_CANCEL: Dict[str, asyncio.Event] = {}

_TERMINAL = {"COMPLETE", "FAILED", "CANCELLED"}


def _require_auth(request) -> None:
    if WORKER_API_KEY and request.headers.get("X-API-Key") != WORKER_API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_payload(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job.get("message"),
        "error": job.get("error"),
        "provenance": job.get("provenance"),
        "model": job.get("model"),
        "adapter": job.get("adapter"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "artifacts": sorted(p.name for p in Path(job["dir"]).iterdir() if p.is_file() and p.name != "input"),
    }


def _persist(job: dict) -> None:
    payload = _job_payload(job)
    with open(Path(job["dir"]) / "job.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


@app.get("/health")
def health(request: Request) -> dict:
    _require_auth(request)
    return {
        "status": "ok",
        "service": "crowdflow-colab-3d-worker",
        "version": "1.0.0",
        "default_model": DEFAULT_MODEL,
        "auth_required": bool(WORKER_API_KEY),
        "models": registry_status(),
        "active_jobs": len([j for j in _JOBS.values() if j["status"] not in _TERMINAL]),
    }


@app.post("/jobs")
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    job_id: str = Form(...),
    model: str = Form(default=""),
    params: str = Form(default="{}"),
) -> dict:
    _require_auth(request)
    job_uid = (job_id or f"twg_{uuid.uuid4().hex[:10]}").strip()
    if job_uid in _JOBS and _JOBS[job_uid]["status"] not in _TERMINAL:
        raise HTTPException(409, f"job {job_uid} already running")
    try:
        extra = json.loads(params or "{}")
    except json.JSONDecodeError:
        extra = {}

    job_dir = DATA_DIR / job_uid
    job_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "input.png").suffix.lower() or ".png"
    input_path = job_dir / f"input{ext}"
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty input file")
    input_path.write_bytes(data)

    job = {
        "id": job_uid,
        "status": "QUEUED",
        "stage": "QUEUED",
        "progress": 0,
        "message": "queued",
        "error": None,
        "provenance": None,
        "model": model.strip() or DEFAULT_MODEL,
        "adapter": None,
        "params": extra,
        "input_path": str(input_path),
        "dir": str(job_dir),
        "created_at": _now(),
        "updated_at": _now(),
    }
    _JOBS[job_uid] = job
    _persist(job)

    cancel = asyncio.Event()
    _CANCEL[job_uid] = cancel
    _TASKS[job_uid] = asyncio.create_task(_run(job, cancel))
    return {"id": job_uid, "status": "QUEUED", "model": job["model"]}


async def _run(job: dict, cancel: asyncio.Event) -> None:
    def on_progress(stage: str, progress: int, message: Optional[str] = None) -> None:
        job["status"] = "RUNNING"
        job["stage"] = stage
        job["progress"] = min(100, max(0, int(progress)))
        if message:
            job["message"] = message
        job["updated_at"] = _now()
        _persist(job)

    try:
        on_progress("ANALYZING", 10, "analyzing blueprint")

        def _analyze() -> Optional[Dict[str, Any]]:
            return analyze_blueprint(job["input_path"], job.get("params", {}))

        semantic = await asyncio.to_thread(_analyze)
        if semantic is None:
            semantic = generate_stadium_semantic()

        if cancel.is_set():
            raise _Cancelled()
        on_progress("GENERATING_GEOMETRY", 40, f"generating geometry ({job['model']})")

        result = await generate_geometry(job["model"], job["input_path"], on_progress)

        if cancel.is_set():
            raise _Cancelled()
        on_progress("SEMANTIC_PROCESSING", 70, "finalizing semantic venue")

        job["provenance"] = result.provenance
        job["adapter"] = result.adapter
        semantic["metadata"]["source"] = "AI_TWIN"
        semantic["metadata"]["model"] = job["model"]
        semantic["metadata"]["adapter"] = result.adapter
        semantic["metadata"]["notes"] = list(semantic.get("metadata", {}).get("notes", [])) + result.notes

        if cancel.is_set():
            raise _Cancelled()
        on_progress("EXPORTING", 88, "exporting artifacts")

        job_dir = Path(job["dir"])
        (job_dir / "venue.glb").write_bytes(result.glb)
        (job_dir / "semantic.json").write_text(json.dumps(semantic, indent=2), encoding="utf-8")
        meta = build_metadata(job["id"], job["model"], result.provenance, result.adapter, result.notes)
        (job_dir / "generation.metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        job["status"] = "COMPLETE"
        job["stage"] = "COMPLETE"
        job["progress"] = 100
        job["message"] = f"twin generated ({result.provenance}, {result.adapter})"
        job["updated_at"] = _now()
        _persist(job)
    except _Cancelled:
        job["status"] = "CANCELLED"
        job["message"] = "cancelled by operator"
        job["updated_at"] = _now()
        _persist(job)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the backend
        job["status"] = "FAILED"
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["message"] = "generation failed"
        job["updated_at"] = _now()
        _persist(job)
    finally:
        _TASKS.pop(job["id"], None)
        _CANCEL.pop(job["id"], None)


class _Cancelled(Exception):
    pass


@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    _require_auth(request)
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _job_payload(job)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict:
    _require_auth(request)
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job["status"] in _TERMINAL:
        return _job_payload(job)
    if job_id in _CANCEL:
        _CANCEL[job_id].set()
    task = _TASKS.get(job_id)
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    return _job_payload(job)


@app.get("/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: str, name: str, request: Request) -> FileResponse:
    _require_auth(request)
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    path = Path(job["dir"]) / name
    if not path.is_file():
        raise HTTPException(404, "artifact not found")
    return FileResponse(path)