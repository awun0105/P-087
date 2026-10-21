"""Hàng đợi theo từng bước (T-073): job là chuỗi bước, mỗi bước khai loại tài nguyên nó cần.

Nguồn sự thật vẫn là JobManifest. Danh sách bước của một job được **suy ra tất định** từ manifest (`plan_steps`) và
ghi vào `r2s_job_steps` trong cùng transaction với mỗi revision job (`ProjectPersistence.save_job` gọi
`sync_job_steps`), nên bảng bước không bao giờ lệch khỏi manifest. Phần duy nhất bảng bước tự giữ là việc một worker
đã **nhận** bước (`claimed`, CAS `ready → claimed`) trước khi manifest kịp đổi, và bước `view_lod` (chạy sau khi job đã
xong nên manifest không ghi).

Job đang chạy dở từ trước migration v27 chưa có dòng nào: dòng được tạo ở revision kế tiếp của job, hoặc khi worker quét
hàng đợi và nhận bước (`claim_step` đồng bộ trước khi CAS). Không cần chạy backfill riêng.

Các bước của job video (job bộ ảnh không có `prepare`):

    prepare (cpu) → anonymization_review (người dùng, chỉ khi có frame bị che) → pose_visual (gpu: LiDAR nếu có,
    COLMAP, Brush, đề xuất tỉ lệ) → metric_confirm (người dùng) → canonical_geometry (cpu; gpu khi worker đặt
    `product_geometry_gpu_index`) → scene_extract (gpu) → view_lod (gpu, ưu tiên thấp, sau khi job xong)
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.manifests import JobManifest, JobStatus, StageId, StageStatus
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction
from src.services.orchestration.jobs.progress import (
    JobStepView,
    anonymization_acceptance_stage,
    awaiting_anonymization_review,
    awaiting_finalize,
    awaiting_pose_step,
    awaiting_scene_extract,
    metric_confirmation_stage,
    prepared_frame_stage,
    sanitized_frame_stage,
)

logger = logging.getLogger(__name__)

StepId = Literal[
    "prepare",
    "anonymization_review",
    "pose_visual",
    "metric_confirm",
    "canonical_geometry",
    "scene_extract",
    "view_lod",
]
StepKind = Literal["cpu", "gpu", "user"]
StepState = Literal["pending", "ready", "claimed", "running", "done", "failed", "waiting_user", "skipped"]
#: Bước máy (không phải bước người dùng) theo thứ tự pipeline.
MACHINE_STEPS: tuple[StepId, ...] = ("prepare", "pose_visual", "canonical_geometry", "scene_extract", "view_lod")
#: Tool của từng bước, cùng tên với `_run_tool`/`_sampled` (số đo `r2s_resource_usage.tool` dùng lại được).
STEP_TOOL: dict[StepId, str | None] = {
    "prepare": "prepare",
    "anonymization_review": None,
    "pose_visual": "preview",
    "metric_confirm": None,
    "canonical_geometry": "finalize",
    "scene_extract": "scene_extract",
    "view_lod": "lod",
}
STEP_KIND: dict[StepId, StepKind] = {
    "prepare": "cpu",
    "anonymization_review": "user",
    "pose_visual": "gpu",
    "metric_confirm": "user",
    "canonical_geometry": "cpu",
    "scene_extract": "gpu",
    "view_lod": "gpu",
}
#: Số luồng CPU bước CPU khai khi xin chạy (giữ chỗ `cpu_slots`); bước GPU khai theo `gpu_step_cpu_slots`.
STEP_CPU_SLOTS: dict[StepId, int] = {"prepare": 4, "canonical_geometry": 2, "view_lod": 1}
#: Thứ tự ưu tiên khi nhiều bước cùng sẵn sàng (nhỏ trước): người dùng vừa thao tác xong → job đã bắt đầu → job mới →
#: bộ LOD. Bước của cùng hạng xoay vòng theo người yêu cầu (`queue.fair_order`).
RANK_USER_WAITING, RANK_CONTINUATION, RANK_NEW_JOB, RANK_BACKGROUND = 0, 1, 2, 3
#: Bước đã nhận mà quá mức này manifest vẫn chưa đổi (worker chết giữa claim và lượt ghi đầu) thì trả về `ready`.
CLAIM_TTL = timedelta(minutes=10)
#: Bước `view_lod` có thể dài hơn TTL lease: giữ dòng `claimed` lâu hơn (lease job vẫn chặn hai worker cùng chạy).
VIEW_LOD_CLAIM_TTL = timedelta(hours=6)

_PREPARE_STAGES = frozenset({StageId.INPUT_VALIDATE, StageId.PRIVACY_GATE})
_POSE_STAGES = frozenset(
    {
        StageId.LIDAR_INGEST,
        StageId.LIDAR_CALIBRATION_QA,
        StageId.LIDAR_ODOMETRY,
        StageId.CAMERA_POSE,
        StageId.VISUAL_RECON,
    }
)
_TERMINAL: frozenset[StepState] = frozenset({"done", "failed", "skipped"})


class PlannedStep(BaseModel):
    """Một bước suy từ manifest: loại tài nguyên, phụ thuộc và trạng thái hiện tại."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: StepId
    kind: StepKind
    tool: str | None
    state: StepState
    depends_on: tuple[StepId, ...] = ()


class StepRow(BaseModel):
    """Một dòng `r2s_job_steps`."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    step_id: str
    kind: StepKind
    tool: str | None
    state: StepState
    depends_on: list[str]
    required_gb: dict[str, float] | None = None
    attempt: int
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    job_manifest_checksum: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


def _has_bundle(job: JobManifest) -> bool:
    return any(
        stage.artifact_type == "ReconstructionBundle" and stage.status == StageStatus.SUCCEEDED
        for stage in job.stage_artifacts
    )


def _stage_step(job: JobManifest, stage: StageId) -> StepId:
    """Bước chứa stage này (dùng cho job đang chạy, lỗi hoặc đã hủy)."""
    if stage in _PREPARE_STAGES:
        return "prepare"
    if stage == StageId.FRAME_EXTRACT:
        return "pose_visual" if prepared_frame_stage(job) is not None else "prepare"
    if stage in _POSE_STAGES:
        return "pose_visual"
    if stage == StageId.METRIC_CANONICALIZE:
        return "canonical_geometry" if metric_confirmation_stage(job) is not None else "metric_confirm"
    if stage == StageId.RGB_GEOMETRY:
        return "scene_extract" if _has_bundle(job) else "canonical_geometry"
    if stage in {StageId.OBJECT_EXTRACT, StageId.VIEW_LOD}:
        return "scene_extract"
    # Stage ngoài pipeline chính (vd đăng ký RGB-LiDAR sau khi job xong) không thuộc bước nào của hàng đợi.
    return "pose_visual"


def active_step(job: JobManifest) -> tuple[StepId, StepState] | None:
    """Bước job đang ở và trạng thái của nó; None khi job đã xong toàn bộ pipeline (SUCCEEDED)."""
    status, stage = job.status, job.current_stage
    if status == JobStatus.SUCCEEDED:
        return None
    if status in {JobStatus.QUEUED, JobStatus.RUNNING} and awaiting_anonymization_review(job):
        return "anonymization_review", "waiting_user"
    if status == JobStatus.QUEUED:
        if awaiting_scene_extract(job):
            return "scene_extract", "ready"
        if awaiting_finalize(job):
            return "canonical_geometry", "ready"
        if prepared_frame_stage(job) is not None:
            return "pose_visual", "ready"
        return "prepare", "ready"
    if status == JobStatus.RUNNING:
        if awaiting_pose_step(job):
            return "pose_visual", "ready"
        if awaiting_finalize(job):
            return "canonical_geometry", "ready"
        if awaiting_scene_extract(job):
            return "scene_extract", "ready"
        if stage == StageId.METRIC_CANONICALIZE and metric_confirmation_stage(job) is None:
            return "metric_confirm", "waiting_user"
        return _stage_step(job, stage), "running"
    return _stage_step(job, stage), "failed" if status == JobStatus.FAILED else "skipped"


def runnable_step(job: JobManifest) -> StepId | None:
    """Bước máy job đang chờ worker nhận; None khi job đang chạy, chờ người dùng hoặc đã kết thúc."""
    active = active_step(job)
    if active is None or active[1] != "ready":
        return None
    return active[0]


def step_rank(job: JobManifest, step: StepId) -> int:
    """Hạng ưu tiên của bước sẵn sàng (xem `RANK_*`)."""
    if step == "view_lod":
        return RANK_BACKGROUND
    if step == "canonical_geometry":
        return RANK_USER_WAITING  # người dùng vừa xác nhận tỉ lệ và đang chờ kết quả
    if step == "pose_visual" and job.status == JobStatus.RUNNING and anonymization_acceptance_stage(job) is not None:
        return RANK_USER_WAITING  # vừa có bản đã che được chấp nhận (người dùng thường đang mở trang chờ)
    if job.status == JobStatus.RUNNING or step == "scene_extract":
        return RANK_CONTINUATION
    return RANK_NEW_JOB


def plan_steps(job: JobManifest) -> list[PlannedStep]:
    """Danh sách bước tất định của job, suy từ manifest (không đọc DB)."""
    frames = prepared_frame_stage(job) is not None
    active = active_step(job)
    included: list[StepId] = []
    ran_prepare = any(stage.stage_id == StageId.INPUT_VALIDATE for stage in job.stage_artifacts)
    if not frames or ran_prepare or (active is not None and active[0] == "prepare"):
        included.append("prepare")
    if sanitized_frame_stage(job) is not None:
        included.append("anonymization_review")
    included += ["pose_visual", "metric_confirm", "canonical_geometry", "scene_extract"]
    if active is not None and active[0] not in included:
        active = None
    # Job đã xong (hoặc manifest lạ): mọi bước trước con trỏ đều xong.
    position = included.index(active[0]) if active is not None else len(included)
    planned: list[PlannedStep] = []
    previous: StepId | None = None
    for index, step in enumerate(included):
        if index < position:
            state: StepState = "done"
        elif index == position and active is not None:
            state = active[1]
        else:
            state = "skipped" if job.status == JobStatus.CANCELLED else "pending"
        planned.append(
            PlannedStep(
                step_id=step,
                kind=STEP_KIND[step],
                tool=STEP_TOOL[step],
                state=state,
                depends_on=(previous,) if previous is not None else (),
            )
        )
        previous = step
    return planned


def gpu_step_cpu_slots() -> int:
    """Luồng CPU một bước GPU khai: chia đều cho các worker GPU trên máy và chừa chỗ cho một bước CPU chạy song song."""
    try:
        workers = max(1, int(os.environ.get("R2S_GPU_WORKERS", "1")))
    except ValueError:
        workers = 1
    return max(1, (os.cpu_count() or 1) // (workers + 1))


def step_cpu_slots(step: StepId, kind: StepKind) -> int:
    if kind == "gpu":
        return gpu_step_cpu_slots()
    return STEP_CPU_SLOTS.get(step, 1)


# --- Bảng r2s_job_steps --------------------------------------------------------------------------------------------

_COLUMNS = (
    "job_id",
    "step_id",
    "kind",
    "tool",
    "state",
    "depends_on",
    "required_gb",
    "attempt",
    "worker_id",
    "lease_expires_at",
    "job_manifest_checksum",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
)


def _stamp(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat(timespec="microseconds") if moment is not None else None


def _parse_time(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    moment = datetime.fromisoformat(str(value))
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _row(values: tuple) -> StepRow:
    record = dict(zip(_COLUMNS, values, strict=True))
    return StepRow(
        job_id=str(record["job_id"]),
        step_id=str(record["step_id"]),
        kind=record["kind"],
        tool=record["tool"],
        state=record["state"],
        depends_on=json.loads(record["depends_on"] or "[]"),
        required_gb=json.loads(record["required_gb"]) if record["required_gb"] else None,
        attempt=int(record["attempt"]),
        worker_id=record["worker_id"],
        lease_expires_at=_parse_time(record["lease_expires_at"]),
        job_manifest_checksum=str(record["job_manifest_checksum"]),
        started_at=_parse_time(record["started_at"]),
        finished_at=_parse_time(record["finished_at"]),
        created_at=_parse_time(record["created_at"]) or datetime.now(UTC),
        updated_at=_parse_time(record["updated_at"]) or datetime.now(UTC),
    )


def _values(row: StepRow) -> tuple:
    return (
        row.job_id,
        row.step_id,
        row.kind,
        row.tool,
        row.state,
        json.dumps(row.depends_on),
        json.dumps(row.required_gb, sort_keys=True) if row.required_gb is not None else None,
        row.attempt,
        row.worker_id,
        _stamp(row.lease_expires_at),
        row.job_manifest_checksum,
        _stamp(row.started_at),
        _stamp(row.finished_at),
        _stamp(row.created_at),
        _stamp(row.updated_at),
    )


def read_rows(tx: RuntimeTransaction, job_id: str) -> dict[str, StepRow]:
    rows = tx.execute(f"SELECT {','.join(_COLUMNS)} FROM r2s_job_steps WHERE job_id=?", (job_id,)).fetchall()
    result: dict[str, StepRow] = {}
    for values in rows:
        try:
            row = _row(tuple(values))
        except (ValueError, TypeError) as error:
            logger.warning("Bỏ qua dòng bước hỏng job=%s cause=%s", job_id, type(error).__name__)
            continue
        result[row.step_id] = row
    return result


def _upsert(tx: RuntimeTransaction, rows: Iterable[StepRow]) -> None:
    rows = list(rows)
    if not rows:
        return
    placeholders = ",".join("(" + ",".join("?" for _ in _COLUMNS) + ")" for _ in rows)
    updates = ",".join(f"{column}=excluded.{column}" for column in _COLUMNS[2:])
    parameters: tuple = tuple(value for row in rows for value in _values(row))
    tx.execute(
        f"INSERT INTO r2s_job_steps({','.join(_COLUMNS)}) VALUES {placeholders} "
        f"ON CONFLICT(job_id, step_id) DO UPDATE SET {updates}",
        parameters,
    )


def _claim_live(row: StepRow, now: datetime) -> bool:
    return row.state == "claimed" and row.lease_expires_at is not None and row.lease_expires_at > now


def _merge(planned: PlannedStep, row: StepRow | None, job: JobManifest, now: datetime) -> StepRow:
    """Dòng mới cho một bước theo kế hoạch, giữ phần chỉ bảng bước biết (đã nhận, thời điểm, số lần chạy, kind)."""
    state: StepState = planned.state
    previous: StepState | None = row.state if row is not None else None
    if row is not None and planned.state == "ready" and _claim_live(row, now):
        state = "claimed"  # worker đã nhận, manifest chưa kịp đổi
    attempt = row.attempt if row is not None else 1
    if previous in _TERMINAL and state in {"ready", "claimed", "running"}:
        attempt += 1  # retry: chỉ bước lỗi chạy lại, các bước trước giữ `done`
    started: datetime | None
    finished: datetime | None
    if state in {"running", "waiting_user"}:
        started = row.started_at if row is not None and previous == state else now
        finished = None
    elif state in _TERMINAL:
        started = row.started_at if row is not None else None
        # Dòng tạo lần đầu cho bước đã xong từ trước (job cũ) không có mốc thật: để trống thay vì ghi giờ hiện tại.
        finished = row.finished_at if previous in _TERMINAL else (now if row is not None else None)
    else:
        started, finished = None, None
    keep_worker = row is not None and state in {"claimed", "running"} and previous in {"claimed", "running"}
    # Worker có thể ghi `kind` thật lúc nhận (vd hình học chạy trên GPU khi máy đặt geometry_gpu_index).
    kind = row.kind if row is not None and planned.kind != "user" and row.kind != "user" else planned.kind
    merged = StepRow(
        job_id=job.job_id,
        step_id=planned.step_id,
        kind=kind,
        tool=planned.tool,
        state=state,
        depends_on=list(planned.depends_on),
        required_gb=row.required_gb if row is not None else None,
        attempt=attempt,
        worker_id=row.worker_id if keep_worker and row is not None else None,
        lease_expires_at=row.lease_expires_at if keep_worker and row is not None else None,
        job_manifest_checksum=job.job_manifest_checksum,
        started_at=started,
        finished_at=finished,
        created_at=row.created_at if row is not None else now,
        updated_at=row.updated_at if row is not None else now,
    )
    if row is not None and _values(merged)[:-1] != _values(row)[:-1]:
        merged = merged.model_copy(update={"updated_at": now})
    return merged


def sync_job_steps(tx: RuntimeTransaction, job: JobManifest, *, now: datetime | None = None) -> list[StepRow]:
    """Ghi các bước suy từ revision `job` vào bảng (chỉ dòng đổi); gọi trong transaction đã commit revision đó."""
    current = now or datetime.now(UTC)
    rows = read_rows(tx, job.job_id)
    merged = [_merge(planned, rows.get(planned.step_id), job, current) for planned in plan_steps(job)]
    changed = [row for row in merged if rows.get(row.step_id) is None or _values(rows[row.step_id]) != _values(row)]
    _upsert(tx, changed)
    by_id = {**rows, **{row.step_id: row for row in merged}}
    return list(by_id.values())


def sync_in_commit(tx: RuntimeTransaction, job: JobManifest) -> None:
    """Gọi từ `save_job`: lỗi của bảng bước không được làm hỏng commit của job (bảng bước tự đồng bộ lại sau)."""
    tx.execute("SAVEPOINT r2s_job_steps_sync")
    try:
        sync_job_steps(tx, job)
    except Exception as error:  # noqa: BLE001 - bảng bước là phần chiếu; revision job vẫn phải commit được
        tx.execute("ROLLBACK TO SAVEPOINT r2s_job_steps_sync")
        logger.warning("Không đồng bộ được bảng bước job=%s cause=%s", job.job_id, type(error).__name__)
    tx.execute("RELEASE SAVEPOINT r2s_job_steps_sync")


#: Đọc manifest từ giá trị `r2s_jobs.manifest_ref` (`ProjectPersistence.job_from_pointer`).
JobLoader = Callable[[str], JobManifest]


def _is_latest(tx: RuntimeTransaction, job: JobManifest, load_job: JobLoader) -> bool:
    """`job` là revision mới nhất đã commit; khoá dòng job (PostgreSQL) để `save_job` song song chờ transaction này."""
    row = tx.execute("SELECT manifest_ref FROM r2s_jobs WHERE job_id=?" + tx.lock_suffix(), (job.job_id,)).fetchone()
    if row is None:
        return False
    try:
        return load_job(str(row[0])).job_manifest_checksum == job.job_manifest_checksum
    except Exception as error:  # noqa: BLE001 - manifest không đọc được: không nhận bước của job đó
        logger.warning("Không đọc được manifest mới nhất job=%s cause=%s", job.job_id, type(error).__name__)
        return False


@dataclass(frozen=True)
class Claim:
    job_id: str
    step_id: str
    worker_id: str


def claim_step(
    database: RuntimeDatabase,
    job: JobManifest,
    step_id: StepId,
    worker_id: str,
    *,
    load_job: JobLoader,
    kind: StepKind | None = None,
    required_gb: dict[str, float] | None = None,
    now: datetime | None = None,
) -> Claim | None:
    """CAS `ready → claimed` cho bước của đúng revision `job`; None khi worker khác đã nhận hoặc job đã đổi.

    Đồng bộ bảng bước từ manifest trước (job cũ chưa có dòng nào), nhưng chỉ khi `job` là revision mới nhất.
    """
    current = now or datetime.now(UTC)
    ttl = VIEW_LOD_CLAIM_TTL if step_id == "view_lod" else CLAIM_TTL
    with database.transaction(write=True) as tx:
        if step_id != "view_lod":
            if not _is_latest(tx, job, load_job):
                return None
            sync_job_steps(tx, job, now=current)
            condition, parameters = "AND job_manifest_checksum=?", (job.job_manifest_checksum,)
        else:
            # Job đã xong có thể có revision mới (vd đăng ký LiDAR); bộ LOD không phụ thuộc revision.
            condition, parameters = "", ()
            tx.execute(
                "UPDATE r2s_job_steps SET state='ready', worker_id=NULL, lease_expires_at=NULL "
                "WHERE job_id=? AND step_id='view_lod' AND state IN ('claimed','running') AND lease_expires_at <= ?",
                (job.job_id, _stamp(current)),
            )
        changed = tx.execute(
            "UPDATE r2s_job_steps SET state='claimed', worker_id=?, lease_expires_at=?, updated_at=?, "
            "kind=COALESCE(?, kind), required_gb=COALESCE(?, required_gb) "
            f"WHERE job_id=? AND step_id=? AND state='ready' {condition}",
            (
                worker_id,
                _stamp(current + ttl),
                _stamp(current),
                kind,
                json.dumps(required_gb, sort_keys=True) if required_gb is not None else None,
                job.job_id,
                step_id,
                *parameters,
            ),
        ).rowcount
    return Claim(job.job_id, step_id, worker_id) if changed == 1 else None


def release_claim(database: RuntimeDatabase, claim: Claim) -> None:
    """Bước đã nhận nhưng không chạy (mất lease, lỗi trước lượt ghi đầu): trả về `ready` nếu vẫn là của mình."""
    with database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_job_steps SET state='ready', worker_id=NULL, lease_expires_at=NULL, updated_at=? "
            "WHERE job_id=? AND step_id=? AND state='claimed' AND worker_id=?",
            (_stamp(datetime.now(UTC)), claim.job_id, claim.step_id, claim.worker_id),
        )


def finish_claim(database: RuntimeDatabase, claim: Claim, outcome: Literal["done", "failed"]) -> None:
    """Kết thúc bước không suy được từ manifest (`view_lod`)."""
    now = _stamp(datetime.now(UTC))
    with database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_job_steps SET state=?, worker_id=NULL, lease_expires_at=NULL, finished_at=?, updated_at=? "
            "WHERE job_id=? AND step_id=? AND state IN ('claimed','running') AND worker_id=?",
            (outcome, now, now, claim.job_id, claim.step_id, claim.worker_id),
        )


def mark_running(database: RuntimeDatabase, claim: Claim) -> None:
    now = _stamp(datetime.now(UTC))
    with database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_job_steps SET state='running', started_at=?, updated_at=? "
            "WHERE job_id=? AND step_id=? AND state='claimed' AND worker_id=?",
            (now, now, claim.job_id, claim.step_id, claim.worker_id),
        )


def resync(database: RuntimeDatabase, job_id: str, load_job: JobLoader) -> None:
    """Đồng bộ lại bảng bước theo revision mới nhất (sau khi một bước chạy xong hoặc bị bỏ)."""
    try:
        with database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT manifest_ref FROM r2s_jobs WHERE job_id=?" + tx.lock_suffix(), (job_id,)
            ).fetchone()
            if row is not None:
                sync_job_steps(tx, load_job(str(row[0])))
    except Exception as error:  # noqa: BLE001 - bảng bước là phần chiếu; lượt sau đồng bộ lại
        logger.warning("Không đồng bộ lại được bảng bước job=%s cause=%s", job_id, type(error).__name__)


def enqueue_view_lod(database: RuntimeDatabase, job: JobManifest) -> None:
    """Sau khi job xong: thêm bước `view_lod` (GPU, ưu tiên thấp) nếu job chưa có."""
    now = datetime.now(UTC)
    row = StepRow(
        job_id=job.job_id,
        step_id="view_lod",
        kind="gpu",
        tool=STEP_TOOL["view_lod"],
        state="ready",
        depends_on=["scene_extract"],
        attempt=1,
        job_manifest_checksum=job.job_manifest_checksum,
        created_at=now,
        updated_at=now,
    )
    with database.transaction(write=True) as tx:
        tx.execute(
            f"INSERT INTO r2s_job_steps({','.join(_COLUMNS)}) VALUES ({','.join('?' for _ in _COLUMNS)}) "
            "ON CONFLICT(job_id, step_id) DO NOTHING",
            _values(row),
        )


def ready_view_lods(database: RuntimeDatabase, *, now: datetime | None = None) -> list[str]:
    """Job có bước `view_lod` chờ chạy (gồm dòng đã nhận nhưng quá hạn), cũ nhất trước."""
    current = _stamp(now or datetime.now(UTC))
    with database.transaction() as tx:
        rows = tx.execute(
            "SELECT job_id FROM r2s_job_steps WHERE step_id='view_lod' AND "
            "(state='ready' OR (state IN ('claimed','running') AND lease_expires_at <= ?)) ORDER BY created_at, job_id",
            (current,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def pending_step_counts(database: RuntimeDatabase, *, now: datetime | None = None) -> dict[str, int]:
    """Số bước máy của pipeline (không gồm `view_lod`) đang chờ hoặc vừa được nhận, theo loại tài nguyên."""
    current = now or datetime.now(UTC)
    counts = {"gpu": 0, "cpu": 0}
    with database.transaction() as tx:
        rows = tx.execute(
            "SELECT kind, state, lease_expires_at FROM r2s_job_steps WHERE step_id<>'view_lod' "
            "AND state IN ('ready','claimed')"
        ).fetchall()
    for kind, state, lease in rows:
        if kind not in counts:
            continue
        if state == "claimed":
            expires = _parse_time(lease)
            if expires is None or expires <= current:
                continue
        counts[str(kind)] += 1
    return counts


def _waiting_on(row: StepRow | PlannedStep) -> Literal["gpu", "cpu", "user"] | None:
    if row.state == "waiting_user":
        return "user"
    if row.state == "ready" and row.kind in {"gpu", "cpu"}:
        return row.kind  # type: ignore[return-value]
    return None


def job_step_views(database: RuntimeDatabase | None, job: JobManifest) -> list[JobStepView]:
    """Các bước của job cho UI: trạng thái của dòng trong bảng nếu đã đồng bộ với đúng revision này (gồm `claimed`),
    không thì suy từ manifest; thời điểm bắt đầu/kết thúc lấy từ bảng (job cũ chưa có dòng thì để trống)."""
    rows: dict[str, StepRow] = {}
    if database is not None:
        try:
            with database.transaction() as tx:
                rows = read_rows(tx, job.job_id)
        except Exception as error:  # noqa: BLE001 - lỗi đọc bảng bước không được làm hỏng màn tiến trình
            logger.debug("Không đọc được bảng bước job=%s cause=%s", job.job_id, type(error).__name__)
    views: list[JobStepView] = []
    for planned in plan_steps(job):
        row = rows.get(planned.step_id)
        synced = row is not None and row.job_manifest_checksum == job.job_manifest_checksum
        source: StepRow | PlannedStep = row if synced and row is not None else planned
        views.append(
            JobStepView(
                step_id=planned.step_id,
                kind=source.kind,
                state=source.state,
                waiting_on=_waiting_on(source),
                attempt=row.attempt if row is not None else 1,
                started_at=row.started_at if synced and row is not None else None,
                finished_at=row.finished_at if synced and row is not None else None,
            )
        )
    lod = rows.get("view_lod")
    if lod is not None:
        views.append(
            JobStepView(
                step_id="view_lod",
                kind=lod.kind,
                state=lod.state,
                waiting_on=_waiting_on(lod),
                attempt=lod.attempt,
                started_at=lod.started_at,
                finished_at=lod.finished_at,
            )
        )
    return views
