"""Twin generation job endpoints.

Flow: upload blueprint -> job created (202) -> background GPU worker ->
progress over WebSocket -> GLB + semantic artifacts available -> the generated
venue is registered and selectable. The application never blocks on GPU
inference and keeps working when the Colab worker is offline.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..twin.orchestrator import twin_orchestrator
from ..twin.schemas import TwinGenerationJob, TwinJobStatus, TwinProviderStatus

router = APIRouter()

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_WS_POLL_S = 0.2


@router.get("/jobs", response_model=list[TwinGenerationJob])
async def list_jobs():
    return twin_orchestrator.list_jobs()


@router.post("/jobs", response_model=TwinGenerationJob, status_code=202)
async def create_job(
    file: UploadFile = File(..., description="Blueprint / venue image (PNG, JPG, WebP, PDF, SVG)"),
    provider: str = Form("auto"),
    params: str = Form("{}"),
):
    """Upload a blueprint and start twin generation. Returns immediately."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload too large (max 25 MB)")
    try:
        parsed = json.loads(params) if params.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid params JSON: {exc}") from exc
    provider_name = None if provider in ("auto", "") else provider
    job = twin_orchestrator.create_job(data, file.filename or "blueprint.png", provider=provider_name, params=parsed)
    twin_orchestrator.dispatch(job)
    return job


@router.get("/jobs/{job_id}", response_model=TwinGenerationJob)
async def get_job(job_id: str):
    job = twin_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Twin generation job not found")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=TwinGenerationJob)
async def cancel_job(job_id: str):
    job = twin_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Twin generation job not found")
    twin_orchestrator.cancel_job(job_id)
    job = twin_orchestrator.get_job(job_id)
    return job


@router.post("/jobs/{job_id}/retry", response_model=TwinGenerationJob)
async def retry_job(job_id: str):
    job = twin_orchestrator.retry_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Twin generation job not found")
    return job


@router.get("/jobs/{job_id}/artifacts/{filename}")
async def get_artifact(job_id: str, filename: str):
    job = twin_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Twin generation job not found")
    safe = Path(filename).name
    artifact = twin_orchestrator.store.artifact(job_id, safe)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(artifact, media_type=_mime(safe), filename=safe)


@router.get("/provider", response_model=TwinProviderStatus)
async def provider_status(provider: str = Query("auto")):
    provider_name = None if provider in ("auto", "") else provider
    return await twin_orchestrator.provider_status(provider_name)


@router.websocket("/jobs/{job_id}/live")
async def job_live(websocket: WebSocket, job_id: str):
    """Push job snapshots; close when the job reaches a terminal state."""
    await websocket.accept()
    job = twin_orchestrator.get_job(job_id)
    if job is None:
        await websocket.send_json({"error": "Job not found", "job_id": job_id})
        await websocket.close()
        return

    last_payload: str | None = None
    try:
        while True:
            job = twin_orchestrator.get_job(job_id)
            if job is None:
                break
            payload = job.model_dump_json()
            if payload != last_payload:
                await websocket.send_text(payload)
                last_payload = payload
            if job.status in (TwinJobStatus.COMPLETED, TwinJobStatus.FAILED, TwinJobStatus.CANCELLED):
                break
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=_WS_POLL_S)
            except asyncio.TimeoutError:
                msg = None
            except WebSocketDisconnect:
                break
            if msg:
                try:
                    action = json.loads(msg).get("action")
                except json.JSONDecodeError:
                    action = None
                if action == "cancel":
                    twin_orchestrator.cancel_job(job_id)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _mime(filename: str) -> str:
    if filename.endswith(".glb"):
        return "model/gltf-binary"
    if filename.endswith(".json"):
        return "application/json"
    if filename.endswith(".png"):
        return "image/png"
    if filename.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "application/octet-stream"