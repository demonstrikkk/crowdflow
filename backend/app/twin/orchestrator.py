"""Twin generation orchestrator: job lifecycle + provider dispatch.

The HTTP handler only creates the job and returns immediately. A background
asyncio task executes the provider; the WebSocket channel reads the job from
the store, so the application never blocks and Colab being offline never
affects normal CrowdFlow operation.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .providers import (
    Colab3DProvider, ImageTo3DProvider, LocalProceduralProvider,
    SimulatedProvider, _Cancelled,
)
from .schemas import (
    TwinBinding, TwinGenerationJob, TwinJobStatus, TwinProvenance,
    TwinProviderStatus, TwinStage,
)
from .semantic import (
    artifacts_to_job, parse_semantic_text, register_twin_venue,
    save_generation_metadata, semantic_to_venue_document,
)
from .store import TwinJobStore, twin_job_store

_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".svg"}


class TwinOrchestrator:
    def __init__(self, store: TwinJobStore) -> None:
        self.store = store
        self._cancel: Dict[str, asyncio.Event] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._providers: Dict[str, ImageTo3DProvider] = {}

    # ------------------------------------------------------------------ #
    #  Providers
    # ------------------------------------------------------------------ #
    def _provider_factory(self, name: Optional[str]) -> ImageTo3DProvider:
        selected = (name or os.getenv("TWIN_PROVIDER", "auto")).strip().lower()
        if selected in ("colab", "ai"):
            return Colab3DProvider()
        if selected == "simulated":
            return SimulatedProvider()
        if selected == "auto":
            # a configured Colab URL means the user wants the GPU worker
            return Colab3DProvider() if os.getenv("TWIN_COLAB_URL") else LocalProceduralProvider()
        return LocalProceduralProvider()

    def get_provider(self, name: Optional[str] = None) -> ImageTo3DProvider:
        selected = (name or os.getenv("TWIN_PROVIDER", "auto")).strip().lower()
        if selected not in self._providers:
            self._providers[selected] = self._provider_factory(selected)
        return self._providers[selected]

    async def provider_status(self, name: Optional[str] = None) -> TwinProviderStatus:
        provider = self.get_provider(name)
        return await provider.health()

    # ------------------------------------------------------------------ #
    #  Jobs
    # ------------------------------------------------------------------ #
    def create_job(
        self,
        input_data: bytes,
        filename: str,
        provider: Optional[str] = None,
        params: Optional[dict] = None,
    ) -> TwinGenerationJob:
        provider_obj = self.get_provider(provider)
        job_id = f"twg_{uuid.uuid4().hex[:10]}"
        ext = Path(filename).suffix.lower() or ".png"
        if ext not in _ALLOWED_EXT:
            ext = ".png"
        job = TwinGenerationJob(
            id=job_id,
            status=TwinJobStatus.QUEUED,
            stage=TwinStage.QUEUED,
            provider=provider_obj.name,
            model=provider_obj.model,
            provenance=provider_obj.provenance,
            input_name=filename,
            metadata={"params": params or {}},
        )
        self.store.create(job)
        self.store.write_artifact(job_id, f"input{ext}", input_data)
        job.log(f"job created (provider={provider_obj.name}, model={provider_obj.model})")
        self.store.save(job)
        return job

    def get_job(self, job_id: str) -> Optional[TwinGenerationJob]:
        return self.store.get(job_id)

    def list_jobs(self) -> List[TwinGenerationJob]:
        return self.store.list()

    def job_input_path(self, job: TwinGenerationJob) -> Optional[Path]:
        ext = Path(job.input_name or "input.png").suffix.lower() or ".png"
        if ext not in _ALLOWED_EXT:
            ext = ".png"
        return self.store.artifact(job.id, f"input{ext}")

    def dispatch(self, job: TwinGenerationJob) -> None:
        """Start (or restart) background generation for a job."""
        if job.id in self._tasks and not self._tasks[job.id].done():
            return
        self._cancel[job.id] = asyncio.Event()
        self._tasks[job.id] = asyncio.create_task(self._run(job))

    async def _run(self, job: TwinGenerationJob) -> None:
        cancel_event = self._cancel.get(job.id, asyncio.Event())
        try:
            job.status = TwinJobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            job.log(f"generation started (provider={job.provider}, model={job.model})")
            self.store.save(job)

            input_path = self.job_input_path(job)
            if input_path is None or not input_path.exists():
                raise RuntimeError("job input file missing")

            provider = self.get_provider(job.provider)

            def on_progress(stage: TwinStage, progress: int, message: Optional[str] = None) -> None:
                job.set_stage(stage, progress, message)
                self.store.save(job)

            artifacts = await provider.run(job, input_path, on_progress, cancel_event)

            if cancel_event.is_set():
                raise _JobCancelled(job.id)

            # ---- persist artifacts + semantic conversion --------------------
            for filename, data in artifacts.items():
                self.store.write_artifact(job.id, filename, data)
            artifacts_to_job(job, artifacts)

            # Honor the worker's EFFECTIVE provenance: a Colab run that fell back
            # to the deterministic generator is PROCEDURAL, never fabricated as AI.
            meta_artifact = artifacts.get("generation.metadata.json")
            if meta_artifact:
                try:
                    meta = json.loads(meta_artifact.decode("utf-8"))
                    effective = str(meta.get("provenance", "")).upper()
                    if effective in {p.value for p in TwinProvenance} and job.provenance != effective:
                        job.provenance = TwinProvenance(effective)
                        job.log(f"provenance corrected to {effective} from worker metadata")
                except (ValueError, TypeError):
                    pass

            job.log("artifacts stored; converting semantic model to CrowdFlow venue")
            semantic_text = artifacts.get("semantic.json")
            if not semantic_text:
                raise RuntimeError("worker returned no semantic.json")
            semantic = parse_semantic_text(semantic_text.decode("utf-8"))
            venue, spatial, notes = semantic_to_venue_document(
                semantic, job.id.upper(), float(semantic["venue"].get("width_m", 200)),
                float(semantic["venue"].get("height_m", 120)),
            )

            register_twin_venue(job, venue, spatial, notes, job.provenance.value)

            meta = save_generation_metadata(job)
            self.store.write_text_artifact(job.id, "generation.metadata.json", json.dumps(meta, indent=2))

            # refresh bindings from the authoritative spatial model
            job.bindings = [
                TwinBinding(
                    semantic_id=o.id,
                    type=o.type,
                    label=o.id.replace("_", " ").title(),
                    mesh_reference=f"Opening_{o.id}",
                    world_position={"x": o.position.x, "y": o.position.y},
                    simulation_node=o.id,
                )
                for o in spatial.openings
            ]

            job.status = TwinJobStatus.COMPLETED
            job.stage = TwinStage.COMPLETE
            job.progress = 100
            job.completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            job.log(
                f"twin complete: venue={venue.id} ({len(venue.nodes)} nodes, "
                f"{len(venue.edges)} edges, {len(spatial.openings)} openings, "
                f"provenance={job.provenance.value})"
            )
        except (_JobCancelled, _Cancelled) as exc:
            job.status = TwinJobStatus.CANCELLED
            job.stage = TwinStage.QUEUED
            job.log(f"job cancelled ({exc.job_id})")
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to developers
            job.status = TwinJobStatus.FAILED
            job.stage = TwinStage.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.log(f"job failed: {job.error}")
        finally:
            self.store.save(job)
            self._tasks.pop(job.id, None)
            self._cancel.pop(job.id, None)

    def cancel_job(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if job is None:
            return False
        if job.status in (TwinJobStatus.COMPLETED, TwinJobStatus.FAILED, TwinJobStatus.CANCELLED):
            return True
        if job.id in self._cancel:
            self._cancel[job.id].set()
        else:
            job.status = TwinJobStatus.CANCELLED
            job.log("job cancelled before dispatch")
            self.store.save(job)
        return True

    def retry_job(self, job_id: str) -> Optional[TwinGenerationJob]:
        job = self.store.get(job_id)
        if job is None:
            return None
        if job.status in (TwinJobStatus.QUEUED, TwinJobStatus.RUNNING):
            return job
        job.status = TwinJobStatus.QUEUED
        job.stage = TwinStage.QUEUED
        job.progress = 0
        job.error = None
        job.completed_at = None
        job.started_at = None
        job.artifacts = []
        job.bindings = []
        job.log("retry requested; clearing previous result")
        self.store.save(job)
        self.dispatch(job)
        return job


class _JobCancelled(Exception):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"job cancelled: {job_id}")
        self.job_id = job_id


twin_orchestrator = TwinOrchestrator(twin_job_store)