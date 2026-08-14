"""Artifact storage for twin generation jobs.

Jobs and their artifacts live under ``backend/generated/twins/{job_id}/``:

    job.json            # current job state (persisted on every change)
    input.<ext>         # uploaded blueprint
    venue.glb           # visual 3D model
    semantic.json       # semantic venue description + bindings
    generation.metadata.json  # generation metadata
    preview.png         # optional preview

The storage layer is behind a small interface so it can later move to S3 /
R2 / Supabase without changing the application architecture.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .schemas import TwinGenerationJob

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "generated"
TWINS_DIR = GENERATED_DIR / "twins"


class TwinJobStore:
    """Persistent job registry backed by ``job.json`` files on disk."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else TWINS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, TwinGenerationJob] = {}
        self._load()

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        for job_json in sorted(self.root.glob("*/job.json")):
            try:
                job = TwinGenerationJob.model_validate(json.loads(job_json.read_text(encoding="utf-8")))
                self._jobs[job.id] = job
            except Exception:
                continue

    def job_dir(self, job_id: str) -> Path:
        d = self.root / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ #
    def create(self, job: TwinGenerationJob) -> TwinGenerationJob:
        self._jobs[job.id] = job
        self.save(job)
        return job

    def get(self, job_id: str) -> Optional[TwinGenerationJob]:
        return self._jobs.get(job_id)

    def list(self) -> List[TwinGenerationJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def save(self, job: TwinGenerationJob) -> None:
        self._jobs[job.id] = job
        (self.job_dir(job.id) / "job.json").write_text(
            job.model_dump_json(indent=2), encoding="utf-8"
        )

    def write_artifact(self, job_id: str, filename: str, data: bytes) -> Path:
        p = self.job_dir(job_id) / filename
        p.write_bytes(data)
        return p

    def write_text_artifact(self, job_id: str, filename: str, text: str) -> Path:
        p = self.job_dir(job_id) / filename
        p.write_text(text, encoding="utf-8")
        return p

    def artifact(self, job_id: str, filename: str) -> Optional[Path]:
        p = self.job_dir(job_id) / filename
        return p if p.exists() else None


twin_job_store = TwinJobStore()