"""Twin generation job schemas.

These models describe an asynchronous "blueprint -> 3D digital twin" job that
is executed by a remote GPU worker (Google Colab by default) or by the local
deterministic reconstruction pipeline (development fallback). The CrowdFlow
backend stays the source of truth: a job only ever produces artifacts plus a
validated, registered venue document through the existing storage layer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TwinJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TwinStage(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    ANALYZING = "ANALYZING"
    GENERATING_GEOMETRY = "GENERATING_GEOMETRY"
    GENERATING_TEXTURE = "GENERATING_TEXTURE"
    SEMANTIC_PROCESSING = "SEMANTIC_PROCESSING"
    EXPORTING = "EXPORTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class TwinProvenance(str, Enum):
    """Truthful provenance for a generated twin.

    - AI         : geometry produced by a remote GPU AI model (Colab worker).
    - PROCEDURAL : geometry produced by deterministic local reconstruction.
    - SIMULATED  : a fake worker that only emulates the pipeline (tests/demo).
    """

    AI = "AI"
    PROCEDURAL = "PROCEDURAL"
    SIMULATED = "SIMULATED"


class TwinArtifact(BaseModel):
    kind: str = Field(description="GLB | SEMANTIC | METADATA | PREVIEW | INPUT")
    name: str
    path: str = Field(description="relative path inside the job directory")
    size_bytes: int = 0
    mime: str = "application/octet-stream"


class TwinBinding(BaseModel):
    """GLB <-> semantic <-> simulation binding for one selectable element."""

    semantic_id: str = Field(description="semantic id, e.g. 'G01'")
    type: str = Field(description="ENTRY_GATE | EXIT_GATE | EMERGENCY_EXIT | DOOR | ZONE ...")
    label: str = Field(description="human label, e.g. 'Gate A'")
    mesh_reference: str = Field(description="node name inside venue.glb")
    world_position: Dict[str, float] = Field(description="{x, y} in venue metres")
    simulation_node: str = Field(description="node id in the CrowdFlow VenueModel")


class TwinGenerationJob(BaseModel):
    id: str = Field(min_length=1)
    status: TwinJobStatus = TwinJobStatus.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    stage: TwinStage = TwinStage.QUEUED
    provider: str = "colab"
    model: str = "configured-model"
    provenance: TwinProvenance = TwinProvenance.PROCEDURAL
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    input_name: Optional[str] = None
    output_asset: Optional[str] = None
    venue_id: Optional[str] = None
    artifacts: List[TwinArtifact] = Field(default_factory=list)
    bindings: List[TwinBinding] = Field(default_factory=list)
    error: Optional[str] = None
    logs: List[str] = Field(default_factory=list, description="append-only job log")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def log(self, message: str) -> None:
        self.logs.append(f"[{_now_iso()}] {message}")
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]
        self.touch()

    def set_stage(self, stage: TwinStage, progress: int, message: Optional[str] = None) -> None:
        self.stage = stage
        self.progress = max(0, min(100, int(progress)))
        if message:
            self.log(message)
        else:
            self.touch()

    def model_dump_public(self) -> dict:
        return self.model_dump(mode="json")


class TwinProviderStatus(BaseModel):
    provider: str
    model: str
    online: bool
    provenance: TwinProvenance
    reason: Optional[str] = None