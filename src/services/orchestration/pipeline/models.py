"""Kiểu dữ liệu của mô hình tiến trình hợp nhất (T-059)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.manifests import ExecutionError, StageId
from src.services.orchestration.pipeline.next_action import NextAction

StepActor = Literal["system", "user"]
#: `waiting` chỉ dùng khi chờ người; chờ máy (hàng đợi, tài nguyên, GPU) là `queued`.
StepState = Literal["pending", "queued", "running", "waiting", "succeeded", "failed", "cancelled", "skipped"]
#: `recorded`: từ r2s_step_marks; `inferred`: suy từ journal như trước (job cũ); `none`: chưa có mốc.
TimingSource = Literal["recorded", "inferred", "none"]


class PipelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: StageId
    actor: StepActor
    state: StepState
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timing_source: TimingSource = "none"
    phase: str | None = None
    error: ExecutionError | None = None
    note: str | None = None


class PipelineWait(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "queue", "resources", "runtime", "scene_operation"]
    step_id: StageId | None = None
    since: datetime | None = None


class PipelineView(BaseModel):
    """Phần dùng chung của endpoint `/pipeline`; lớp API thêm `progress`, `objectify`, `gpu`."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    scene_revision: str | None = None
    usable: bool
    steps: list[PipelineStep]
    current_step: StageId | None = None
    wait: PipelineWait | None = None
    next_action: NextAction
    version: str
