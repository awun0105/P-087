"""Hàng đợi xử lý: thứ tự công bằng giữa người dùng, vị trí và thời gian chờ ước tính của một job.

Trạng thái job vẫn là JobManifest; module này chỉ **đọc** journal (cùng transaction với manifest) để biết job
nào đang chờ, không thêm cột hay trạng thái hàng đợi nào. Thứ tự: xoay vòng theo người yêu cầu — job chờ lâu
nhất của mỗi người đi trước, rồi tới job thứ hai của mỗi người, … — để một người gửi nhiều video không chặn
người khác. Deployment không bật đăng nhập thì mọi job cùng một nhóm, tức ai vào trước chạy trước.

Thời gian chờ là ước tính từ thời lượng **đã đo** của các lượt chạy trước trên deployment này
(`r2s_resource_usage`); chưa có lượt nào thì không đưa ra con số.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.auth.models import Actor
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.models import JobAttemptRecord

if TYPE_CHECKING:
    from src.services.orchestration.projects.registry import ProjectRegistry

Phase = Literal["preview", "finalize"]
#: Hành động trong nhật ký gắn một lần xử lý GPU với người yêu cầu (khớp `src/api/auth.py`).
GPU_RUN_ACTION = "gpu.run"
#: Công cụ chạy trong mỗi pha; tổng thời lượng của chúng là thời gian máy của pha đó.
PHASE_TOOLS: dict[Phase, frozenset[str]] = {
    "preview": frozenset({"prepare", "preview", "metric_proposal"}),
    "finalize": frozenset({"finalize", "scene_extract"}),
}
_WORKER_TTL_SECONDS = 15 * 60


class WaitingJob(BaseModel):
    """Một job đang chờ worker: chờ dựng preview, hoặc đã xác nhận tỉ lệ và chờ bước hoàn tất."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    phase: Phase
    queued_at: datetime
    #: Người yêu cầu lần xử lý này; None khi deployment không bật đăng nhập.
    owner: str | None = None
    #: Lần gần nhất worker nhận một job của người này (None = chưa từng): người được phục vụ lâu nhất đi trước.
    owner_served_at: datetime | None = None


class QueuePosition(BaseModel):
    """Vị trí của một job trong hàng đợi và thời gian chờ ước tính (None khi chưa có số đo)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    #: 1 = job kế tiếp được nhận.
    position: int = Field(ge=1)
    waiting: int = Field(ge=1)
    running: int = Field(ge=0)
    workers: int = Field(ge=1)
    estimated_wait_seconds: float | None = Field(default=None, ge=0)
    #: Số lượt chạy đã đo mà ước tính dựa vào (0 = chưa có số đo, không ước tính).
    estimate_samples: int = Field(ge=0)


def job_requesters(database: RuntimeDatabase) -> dict[str, str]:
    """ID người yêu cầu gần nhất, ưu tiên snapshot journal rồi fallback audit legacy."""
    owners, _ = _job_requester_data(database)
    return owners


def job_requester_actors(database: RuntimeDatabase, legacy_actors: dict[str, Actor]) -> dict[str, Actor]:
    """Actor của lượt chạy gần nhất; job cũ dùng tên và role hiện tại của tài khoản (không ghi ngược vào bản ghi)."""
    owners, snapshots = _job_requester_data(database)
    return {
        job_id: snapshots.get(job_id) or legacy_actors[user_id]
        for job_id, user_id in owners.items()
        if job_id in snapshots or user_id in legacy_actors
    }


def _job_requester_data(database: RuntimeDatabase) -> tuple[dict[str, str], dict[str, Actor]]:
    """Batch-load legacy audit identities and immutable actor snapshots from job events."""
    with database.transaction() as tx:
        audit_rows = tx.execute(
            "SELECT user_id, payload, at FROM r2s_audit_log WHERE action=? AND user_id IS NOT NULL ORDER BY at",
            (GPU_RUN_ACTION,),
        ).fetchall()
        # Only run-starting events carry an actor; the key is omitted otherwise, so skip every other event
        # instead of parsing the whole journal on each Scenes poll.
        event_rows = tx.execute(
            "SELECT job_id, payload FROM r2s_job_events WHERE payload LIKE ? ORDER BY job_id, version",
            ('%"requested_by"%',),
        ).fetchall()
    owners: dict[str, str] = {}
    audit_times: dict[str, datetime] = {}
    for user_id, payload, at in audit_rows:
        target = json.loads(payload).get("target")
        if isinstance(target, str):
            recorded_at = datetime.fromisoformat(at)
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=UTC)
            owners[target] = user_id
            audit_times[target] = recorded_at
    snapshots: dict[str, Actor] = {}
    snapshot_times: dict[str, datetime] = {}
    for job_id, payload in event_rows:
        event = JobAttemptRecord.model_validate_json(payload)
        actor = event.requested_by
        if actor is not None:
            recorded_at = event.recorded_at
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=UTC)
            snapshots[job_id] = actor
            snapshot_times[job_id] = recorded_at
    for job_id, actor in list(snapshots.items()):
        audit_at = audit_times.get(job_id)
        if owners.get(job_id) == actor.user_id or audit_at is None or snapshot_times[job_id] >= audit_at:
            owners[job_id] = actor.user_id
        else:
            snapshots.pop(job_id)
    return owners, snapshots


def waiting_jobs(registry: ProjectRegistry) -> list[WaitingJob]:
    """Mọi job đang chờ worker nhận bước kế tiếp, chưa xếp thứ tự.

    Ứng viên lấy từ event mới nhất của từng job trong journal (một truy vấn); chỉ job RUNNING ở một điểm dừng giữa
    hai bước (tách frame, tỉ lệ, hình học — T-073) mới phải mở manifest để phân biệt "chờ người dùng" / "đang chạy"
    với "chờ worker nhận bước sau".
    """
    from src.services.orchestration.jobs.progress import (
        anonymization_acceptance_stage,
        awaiting_anonymization_review,
        awaiting_finalize,
        awaiting_pose_step,
        awaiting_scene_extract,
        metric_confirmation_stage,
        prepared_frame_stage,
    )

    if registry.persistence is None:
        return []
    database = registry.persistence.database
    with database.transaction() as tx:
        rows = tx.execute(
            "SELECT e.job_id, e.payload FROM r2s_job_events e JOIN "
            "(SELECT job_id, MAX(version) AS version FROM r2s_job_events GROUP BY job_id) latest "
            "ON e.job_id=latest.job_id AND e.version=latest.version ORDER BY e.job_id"
        ).fetchall()
    waiting: list[WaitingJob] = []
    #: Job đã rời hàng đợi (đang chạy hoặc đã kết thúc) và thời điểm hoạt động gần nhất của nó.
    served: dict[str, datetime] = {}
    pause_stages = {StageId.FRAME_EXTRACT, StageId.METRIC_CANONICALIZE, StageId.RGB_GEOMETRY}
    for job_id, payload in rows:
        event = JobAttemptRecord.model_validate_json(payload)
        if event.status != JobStatus.QUEUED:
            served[job_id] = event.recorded_at
        if event.status == JobStatus.QUEUED:
            waiting.append(WaitingJob(job_id=job_id, phase="preview", queued_at=event.recorded_at))
            continue
        if event.status != JobStatus.RUNNING or event.current_stage not in pause_stages:
            continue
        try:
            job = registry.get_job(job_id)
        except Exception:  # noqa: BLE001, S112 - một manifest hỏng không được chặn hàng đợi của job khác
            continue
        if awaiting_pose_step(job):
            # Bước chuẩn bị xong (job chọn che frame: sau khi người dùng chấp nhận bản đã che).
            accepted = anonymization_acceptance_stage(job)
            frames = prepared_frame_stage(job)
            since = (accepted.completed_at if accepted is not None else None) or (
                frames.completed_at if frames is not None else None
            )
            waiting.append(WaitingJob(job_id=job_id, phase="preview", queued_at=since or event.recorded_at))
        elif awaiting_finalize(job):
            stage = metric_confirmation_stage(job)
            confirmed = stage.completed_at if stage is not None and stage.completed_at is not None else None
            waiting.append(WaitingJob(job_id=job_id, phase="finalize", queued_at=confirmed or event.recorded_at))
        elif awaiting_scene_extract(job):
            waiting.append(WaitingJob(job_id=job_id, phase="finalize", queued_at=event.recorded_at))
        elif awaiting_anonymization_review(job):
            continue  # chờ người dùng xem bản đã che
    if not waiting:
        return []
    owners = job_requesters(database)
    last_served: dict[str, datetime] = {}
    waiting_ids = {item.job_id for item in waiting}
    for job_id, at in served.items():
        owner = owners.get(job_id)
        if owner is not None and job_id not in waiting_ids:
            last_served[owner] = max(at, last_served.get(owner, at))
    return [
        item.model_copy(
            update={"owner": owners.get(item.job_id), "owner_served_at": last_served.get(owners.get(item.job_id, ""))}
        )
        for item in waiting
    ]


def fair_order(jobs: list[WaitingJob]) -> list[WaitingJob]:
    """Xoay vòng theo người yêu cầu: job thứ n của mỗi người đứng trước job thứ n+1 của bất kỳ ai.

    Trong cùng một vòng, người lâu chưa được phục vụ nhất đi trước (chưa từng được phục vụ thì trước cả), rồi
    mới tới thời điểm vào hàng. Nhờ vậy khi worker chạy tuần tự, người vừa có job chạy xong không được nhận tiếp
    trước người đang chờ lượt đầu.
    """
    never = datetime.min.replace(tzinfo=UTC)
    groups: dict[str | None, list[WaitingJob]] = defaultdict(list)
    for job in sorted(jobs, key=lambda item: (item.queued_at, item.job_id)):
        groups[job.owner].append(job)
    ranked = [(rank, job) for group in groups.values() for rank, job in enumerate(group)]
    return [
        job
        for _, job in sorted(
            ranked, key=lambda item: (item[0], item[1].owner_served_at or never, item[1].queued_at, item[1].job_id)
        )
    ]


def _phase_durations(database: RuntimeDatabase) -> dict[Phase, list[float]]:
    """Thời gian máy của từng pha ở các lượt đã hoàn tất: tổng thời lượng các công cụ của pha, theo từng attempt."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_resource_usage").fetchall()
    totals: dict[tuple[Phase, str, str], float] = defaultdict(float)
    complete: dict[tuple[Phase, str, str], bool] = {}
    for (payload,) in rows:
        try:
            record = json.loads(payload)
            tool, outcome = record["tool"], record["outcome"]
            key_tail = (str(record["job_id"]), str(record["attempt_id"]))
            duration = float(record["duration_seconds"])
        except (ValueError, KeyError, TypeError):
            continue
        for phase, tools in PHASE_TOOLS.items():
            if tool in tools:
                key = (phase, *key_tail)
                totals[key] += duration
                complete[key] = complete.get(key, True) and outcome == "completed"
    durations: dict[Phase, list[float]] = {"preview": [], "finalize": []}
    for key, total in totals.items():
        if complete[key]:
            durations[key[0]].append(total)
    return durations


def _running(database: RuntimeDatabase, now: datetime) -> list[tuple[Phase | None, float]]:
    """(pha, số giây đã chạy) của các job worker đang giữ chỗ."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_resource_reservations").fetchall()
    running: list[tuple[Phase | None, float]] = []
    for (payload,) in rows:
        try:
            record = json.loads(payload)
            started = datetime.fromisoformat(record["reserved_at"])
        except (ValueError, KeyError, TypeError):
            continue
        phase = record.get("phase")
        running.append((phase if phase in PHASE_TOOLS else None, max(0.0, (now - started).total_seconds())))
    return running


def _workers(database: RuntimeDatabase, now: datetime) -> int:
    """Số worker còn báo số đo máy trong TTL; tối thiểu 1 để phép chia có nghĩa."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_workers").fetchall()
    alive = 0
    for (payload,) in rows:
        try:
            measured = datetime.fromisoformat(json.loads(payload)["measured_at"])
        except (ValueError, KeyError, TypeError):
            continue
        alive += (now - measured).total_seconds() <= _WORKER_TTL_SECONDS
    return max(1, alive)


def queue_position(registry: ProjectRegistry, job_id: str, now: datetime | None = None) -> QueuePosition | None:
    """Vị trí của `job_id` theo đúng thứ tự worker sẽ nhận; None khi job không ở trong hàng đợi."""
    if registry.persistence is None:
        return None
    database = registry.persistence.database
    now = now or datetime.now(UTC)
    ordered = fair_order(waiting_jobs(registry))
    index = next((position for position, item in enumerate(ordered) if item.job_id == job_id), None)
    if index is None:
        return None
    durations = _phase_durations(database)
    running = _running(database, now)
    workers = _workers(database, now)
    typical = {phase: statistics.median(values) for phase, values in durations.items() if values}
    ahead = ordered[:index]
    estimate: float | None = None
    needed = {item.phase for item in ahead} | {phase for phase, _ in running if phase is not None}
    if needed <= typical.keys() and all(phase is not None for phase, _ in running):
        remaining = sum(max(0.0, typical[phase] - elapsed) for phase, elapsed in running if phase is not None)
        estimate = (remaining + sum(typical[item.phase] for item in ahead)) / workers
    return QueuePosition(
        position=index + 1,
        waiting=len(ordered),
        running=len(running),
        workers=workers,
        estimated_wait_seconds=estimate,
        estimate_samples=min((len(durations[phase]) for phase in needed), default=0),
    )
