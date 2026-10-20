"""Mốc bắt đầu / kết thúc của từng bước, ghi lúc xảy ra (T-056).

Thay cho việc suy "bước trước xong vì bước sau đã bắt đầu" (progress.py) và đoán theo mốc thời gian (benchmark.py).
Mốc của pipeline job được suy ra từ chính mỗi revision job ở chỗ commit duy nhất (`ProjectPersistence.save_job`) và ghi
trong cùng transaction; runner ghi thêm mốc kết thúc trực tiếp khi worker báo xong một stage. Hàng đợi tách vật ghi mốc
`scene_operation` (T-057). Job cũ không có mốc: nơi đọc giữ cách suy luận cũ.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact, StageId, StageStatus
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.progress import (
    ANONYMIZATION_ACCEPTANCE_TYPE,
    awaiting_anonymization_review,
    sanitized_frame_stage,
)

logger = logging.getLogger(__name__)

RunKind = Literal["pipeline", "scene_operation"]
MarkOutcome = Literal["succeeded", "failed", "cancelled"]
_OUTCOMES: dict[StageStatus, MarkOutcome] = {
    StageStatus.SUCCEEDED: "succeeded",
    StageStatus.FAILED: "failed",
    StageStatus.CANCELLED: "cancelled",
}
_TERMINAL: dict[JobStatus, MarkOutcome] = {JobStatus.FAILED: "failed", JobStatus.CANCELLED: "cancelled"}


class StepMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    run_kind: RunKind
    run_id: str
    step_id: str
    started_at: datetime | None
    completed_at: datetime | None
    outcome: MarkOutcome | None


@dataclass(frozen=True)
class MarkWrite:
    kind: Literal["start", "finish", "close"]
    step_id: str | None
    at: datetime
    outcome: MarkOutcome | None = None


def _identity(stage: StageArtifact) -> tuple:
    return (stage.stage_id, stage.artifact_type, stage.artifact_uri, stage.status, stage.completed_at)


def marks_for_revision(previous: JobManifest | None, current: JobManifest, event: JobAttemptRecord) -> list[MarkWrite]:
    """Mốc bước mà revision `current` (so với `previous`) thể hiện; hàm thuần."""
    writes: list[MarkWrite] = []
    # R1: job vừa chạy, hoặc chuyển sang stage khác, hoặc worker báo mốc bắt đầu chính xác của stage hiện tại.
    if event.status == JobStatus.RUNNING and (
        previous is None
        or previous.status != JobStatus.RUNNING
        or previous.current_stage != current.current_stage
        or event.stage_started_at is not None
    ):
        writes.append(MarkWrite("start", current.current_stage.value, event.stage_started_at or event.recorded_at))
    # R2: StageArtifact mới mang mốc do worker quan sát.
    known = {_identity(stage) for stage in previous.stage_artifacts} if previous is not None else set()
    for stage in current.stage_artifacts:
        if _identity(stage) in known:
            continue
        outcome = _OUTCOMES.get(stage.status)
        if stage.artifact_type == ANONYMIZATION_ACCEPTANCE_TYPE:
            if stage.completed_at is not None:
                writes.append(MarkWrite("finish", StageId.ANONYMIZATION_REVIEW.value, stage.completed_at, "succeeded"))
            continue
        if stage.started_at is not None:
            writes.append(MarkWrite("start", stage.stage_id.value, stage.started_at))
        if stage.completed_at is not None and outcome is not None:
            writes.append(MarkWrite("finish", stage.stage_id.value, stage.completed_at, outcome))
    # R3: bắt đầu chờ người xem bản đã che, tính từ lúc frame đã che xong.
    if awaiting_anonymization_review(current) and (previous is None or not awaiting_anonymization_review(previous)):
        frames = sanitized_frame_stage(current)
        started = frames.completed_at if frames is not None and frames.completed_at is not None else event.recorded_at
        writes.append(MarkWrite("start", StageId.ANONYMIZATION_REVIEW.value, started))
    # R4: lượt chạy kết thúc không thành công → đóng các mốc còn mở.
    outcome = _TERMINAL.get(current.status)
    if outcome is not None and (previous is None or previous.status != current.status):
        writes.append(MarkWrite("close", None, event.recorded_at, outcome))
    return writes


def apply_marks(
    tx: RuntimeTransaction, job_id: str, run_kind: RunKind, run_id: str, writes: Iterable[MarkWrite]
) -> None:
    """Ghi mốc trong transaction có sẵn. Mốc bắt đầu sớm nhất và mốc kết thúc đầu tiên được giữ."""
    for write in writes:
        at = write.at.isoformat()
        if write.kind == "start":
            tx.execute(
                "INSERT INTO r2s_step_marks(job_id, run_kind, run_id, step_id, started_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(job_id, run_kind, run_id, step_id) DO UPDATE SET started_at="
                "COALESCE(r2s_step_marks.started_at, excluded.started_at)",
                (job_id, run_kind, run_id, write.step_id, at),
            )
        elif write.kind == "finish":
            tx.execute(
                "INSERT INTO r2s_step_marks(job_id, run_kind, run_id, step_id, completed_at, outcome) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(job_id, run_kind, run_id, step_id) DO UPDATE SET "
                "completed_at=COALESCE(r2s_step_marks.completed_at, excluded.completed_at), "
                "outcome=COALESCE(r2s_step_marks.outcome, excluded.outcome)",
                (job_id, run_kind, run_id, write.step_id, at, write.outcome),
            )
        else:
            tx.execute(
                "UPDATE r2s_step_marks SET completed_at=?, outcome=? WHERE job_id=? AND run_kind=? AND run_id=? "
                "AND completed_at IS NULL AND started_at IS NOT NULL",
                (at, write.outcome, job_id, run_kind, run_id),
            )


def record_marks(
    database: RuntimeDatabase, job_id: str, run_kind: RunKind, run_id: str, writes: Iterable[MarkWrite]
) -> None:
    """Ghi mốc trong transaction riêng; lỗi chỉ ghi cảnh báo (ranh giới đo, không làm hỏng việc chính)."""
    pending = list(writes)
    if not pending:
        return
    try:
        with database.transaction(write=True) as tx:
            apply_marks(tx, job_id, run_kind, run_id, pending)
    except Exception as error:  # noqa: BLE001 - mốc bước là đo đạc, không được làm hỏng job
        logger.warning("Không ghi được mốc bước job=%s cause=%s", job_id, type(error).__name__)


def list_marks(database: RuntimeDatabase, job_id: str) -> list[StepMark]:
    with database.transaction() as tx:
        rows = tx.execute(
            "SELECT job_id, run_kind, run_id, step_id, started_at, completed_at, outcome FROM r2s_step_marks "
            "WHERE job_id=? ORDER BY run_kind, run_id, started_at",
            (job_id,),
        ).fetchall()
    return [
        StepMark(
            job_id=row[0],
            run_kind=row[1],
            run_id=row[2],
            step_id=row[3],
            started_at=row[4],
            completed_at=row[5],
            outcome=row[6],
        )
        for row in rows
    ]
