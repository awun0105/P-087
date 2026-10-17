"""Queue for rebuilding scene objects with resource admission and lease fencing.

The queue record lives in the runtime database shared by the API and workers. A
request is bound to the SceneIR revision and ReconstructionBundle visible when it
was accepted. A worker must hold both the queue lease and the matching operation
resource reservation through the atomic scene-head compare-and-swap.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.config import Settings
from src.models.contracts.artifacts import Checksum, JsonObject
from src.models.contracts.floor_model import FloorFitProfile
from src.models.contracts.manifests import JobManifest
from src.models.contracts.object_membership import ObjectMembershipReassignCommand, ObjectRegionCommand
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.artifacts import ArtifactStoreError, sha256_bytes
from src.services.orchestration.jobs.admission import (
    OperationAdmissionRequest,
    OperationAdmissionResult,
    Resource,
    ResourceAdmission,
    WaitReason,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction
from src.services.orchestration.jobs.profile import machine_runtime_checksum
from src.services.orchestration.jobs.stage_results import geometry_surface_note
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.processing.capability import worker_identity
from src.services.orchestration.processing.telemetry import Outcome, ResourceContext, ResourceSampler, sampled_section
from src.services.orchestration.processing.usage_recording import build_sampler, record_usage
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError, SceneRevisionConflictError
from src.services.orchestration.scene.extraction import box_candidates_require_gpu, use_boxes
from src.services.orchestration.scene.membership_regeneration import preview_correction, regenerate_membership
from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError, build_object_geometry
from src.services.orchestration.scene.object_region import rebuild_region_ready, validate_region_rebuild
from src.services.orchestration.scene.objectify import AWAITING_CHOICE, METHOD, ObjectifyError, reobjectify
from src.services.orchestration.value.events import record_event
from src.services.process_control import ProcessCancelledError
from src.services.scene.geometry_state import object_geometry_state

logger = logging.getLogger(__name__)

ObjectifyStatus = Literal["idle", "queued", "running", "done", "failed", "cancelled"]
ObjectifyMode = Literal["objectify", "boxes", "membership", "geometry", "region"]
_LEASE_TTL = timedelta(seconds=90)
_LEASE_HEARTBEAT_SECONDS = 20.0
_CANCEL_POLL_SECONDS = 0.5
# Legacy queue rows predate owner tokens. Keep their prior conservative recovery
# behavior until they have either completed or been explicitly retried.
_LEGACY_STALE_AFTER = timedelta(hours=3)


class ObjectifyRequestError(ValueError):
    """The request cannot be accepted; the message can be shown to the user."""


class ObjectGeometryAlreadyReadyError(ObjectifyRequestError):
    """The full geometry build endpoint requires an awaiting-review scene."""


class ObjectifyResourceWait(BaseModel):
    """Public resource snapshot; deliberately omits worker and lease tokens."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["waiting_resources", "waiting_gpu_affinity", "worker_busy", "identity_conflict"]
    required_gb: dict[Resource, float | None]
    available_gb: dict[Resource, float | None]
    capacity_gb: dict[Resource, float | None]
    waiting_on: list[Resource]
    reasons: dict[Resource, WaitReason]
    needs_exclusive_gpu: bool = False

    @classmethod
    def from_admission(cls, result: OperationAdmissionResult) -> ObjectifyResourceWait:
        if result.status == "admitted":
            raise ValueError("an admitted operation has no resource wait")
        return cls(
            status=result.status,
            required_gb=result.required_gb,
            available_gb=result.available_gb,
            capacity_gb=result.capacity_gb,
            waiting_on=result.waiting_on,
            reasons=result.reasons,
            needs_exclusive_gpu=result.needs_exclusive_gpu,
        )


class ObjectifyState(BaseModel):
    """Latest request state plus derived facts about the current SceneIR."""

    model_config = ConfigDict(extra="forbid")

    status: ObjectifyStatus = "idle"
    mode: ObjectifyMode | None = None
    #: Revision SceneIR hiện tại, để client gửi yêu cầu dựng lại đúng revision mà không phải tải cả scene.
    scene_revision: str | None = None
    awaiting_choice: bool = False
    object_centric: bool = False
    available: bool = False
    note: str | None = None
    base_revision: str | None = None
    result_revision: str | None = None
    error: str | None = None
    retryable: bool | None = None
    floor_fit: JsonObject | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    resource_wait: ObjectifyResourceWait | None = None
    operation_id: str | None = None
    phase: str | None = None
    cancellation_requested: bool = False
    #: Trạng thái hình học theo vật của scene hiện tại; None = scene không có khoá `object_geometry` (luồng cũ).
    object_geometry: Literal["awaiting_review", "ready"] | None = None
    geometry_note: str | None = None


ObjectGeometry = Literal["awaiting_review", "ready"]


def object_geometry_status(provenance: JsonObject) -> ObjectGeometry | None:
    """Khoá thiếu → None; giá trị lạ → "awaiting_review", khớp quy tắc khoá lại của Studio."""
    if "object_geometry" not in provenance or provenance["object_geometry"] is None:
        return None
    return "ready" if provenance["object_geometry"] == "ready" else "awaiting_review"


GeometryReview = Literal["waiting", "running", "failed"]
#: Các chế độ là việc dựng hình học theo vật (khớp `BUILD_MODES` của Studio, T-021).
_BUILD_MODES = frozenset({"geometry", "region", "membership"})


def geometry_review(
    settings: Settings,
    job_id: str,
    object_geometry: ObjectGeometry | None,
    scene_revision: str,
) -> GeometryReview | None:
    """Việc còn lại của bước "Duyệt vật & Tạo mesh" cho danh sách scene; cùng quy tắc với hàng tiến trình của Studio.

    `running`: đang dựng (Tạo mesh hoặc dựng lại vùng). Draft: `failed` khi Tạo mesh lỗi trên đúng revision này, ngược lại
    `waiting`. Scene Ready không còn việc chờ người dùng nên trả None, kể cả khi lần dựng lại vùng gần nhất lỗi.
    """
    if object_geometry is None:
        return None
    with _database(settings).transaction() as tx:
        record = _read(tx, job_id)
    if record is not None and record.status in {"queued", "running"} and record.mode in _BUILD_MODES:
        return "running"
    if object_geometry != "awaiting_review":
        return None
    if (
        record is not None
        and record.status in {"failed", "cancelled"}
        and record.mode == "geometry"
        and record.base_revision == scene_revision
    ):
        return "failed"
    return "waiting"


class _Record(BaseModel):
    """Durable queue record; optional additions preserve older JSON payloads."""

    model_config = ConfigDict(extra="forbid")

    status: ObjectifyStatus
    mode: ObjectifyMode
    base_revision: str
    result_revision: str | None = None
    error: str | None = None
    retryable: bool | None = None
    floor_fit: JsonObject | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    operation_id: str | None = None
    input_checksum: Checksum | None = None
    config_checksum: Checksum | None = None
    resource_wait: ObjectifyResourceWait | None = None
    correction_command: ObjectMembershipReassignCommand | None = None
    region_object_id: str | None = None
    region_command: ObjectRegionCommand | None = None
    actor_id: str | None = None
    lease_generation: int = 0
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    worker_id: str | None = None
    worker_host: str | None = None
    worker_pid: int | None = None
    phase: str | None = None
    cancellation_requested: bool = False


def _database(settings: Settings) -> RuntimeDatabase:
    return RuntimeDatabase(settings.database_url)


def _read(tx: RuntimeTransaction, job_id: str, *, lock: bool = False) -> _Record | None:
    suffix = tx.lock_suffix() if lock else ""
    row = tx.execute("SELECT payload FROM r2s_scene_requests WHERE job_id=?" + suffix, (job_id,)).fetchone()
    return _Record.model_validate_json(row[0]) if row is not None else None


def _write(tx: RuntimeTransaction, job_id: str, record: _Record) -> None:
    tx.execute(
        "INSERT INTO r2s_scene_requests(job_id,status,payload) VALUES (?,?,?) "
        "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, payload=excluded.payload",
        (job_id, record.status, record.model_dump_json()),
    )


def _digest(value: object) -> Checksum:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(encoded)


def _input_checksum(
    job_id: str, base_revision: str, scene_checksum: Checksum, bundle: ReconstructionBundle
) -> Checksum:
    return _digest(
        {
            "job_id": job_id,
            "base_revision": base_revision,
            "base_scene_checksum": scene_checksum,
            "bundle": bundle.model_dump(mode="json"),
        }
    )


def _config_checksum(
    job: JobManifest,
    settings: Settings,
    mode: ObjectifyMode,
    correction: ObjectMembershipReassignCommand | None = None,
    region: tuple[str, ObjectRegionCommand] | None = None,
) -> Checksum:
    """Bind the user's mode and shared runtime knobs without persisting local paths."""
    return _digest(
        {
            **({"correction": correction.model_dump(mode="json")} if correction else {}),
            **({"region": {"object_id": region[0], "command": region[1].model_dump(mode="json")}} if region else {}),
            "operation": "reobjectify",
            "mode": mode,
            "runtime_manifest_checksum": job.runtime_manifest_checksum,
            "job_config_checksum": job.config_checksum,
            "objectify_attempts": settings.product_objectify_attempts,
            "scene_timeout_seconds": settings.product_scene_timeout_seconds,
            "floor_profile_checksum": FloorFitProfile().checksum(),
        }
    )


def runtime_available(settings: Settings) -> bool:
    """The API's local SAM2 runtime is configured and present."""
    python, checkpoint = settings.product_scene_runtime_python, settings.product_sam2_checkpoint
    return bool(settings.product_objectify and python and checkpoint and python.is_file() and checkpoint.is_file())


def _public_record(record: _Record) -> dict[str, object]:
    names = (
        "status",
        "mode",
        "base_revision",
        "result_revision",
        "error",
        "retryable",
        "floor_fit",
        "requested_at",
        "started_at",
        "finished_at",
        "resource_wait",
        "cancellation_requested",
        "phase",
        "operation_id",
    )
    return {name: getattr(record, name) for name in names}


def state(registry: ProjectRegistry, settings: Settings, job_id: str) -> ObjectifyState:
    """Project current-scene facts and the latest durable request for Studio/API."""
    scene = registry.scene.current(job_id).scene
    provenance = scene.provenance
    with _database(settings).transaction() as tx:
        record = _read(tx, job_id)
    note = provenance.get("note")
    public = _public_record(record) if record is not None else {}
    fit = provenance.get("floor_fit")
    public["floor_fit"] = fit if isinstance(fit, dict) else None
    public["retryable"] = provenance.get("objectify_retryable")
    if isinstance(fit, dict) and fit.get("profile_checksum") != FloorFitProfile().checksum():
        public["retryable"] = None
    if record is not None and record.status == "failed" and record.base_revision == scene.scene_revision:
        public["floor_fit"] = record.floor_fit or public["floor_fit"]
        region = (
            (record.region_object_id, record.region_command)
            if record.region_object_id is not None and record.region_command is not None
            else None
        )
        if record.config_checksum == _config_checksum(
            registry.get_job(job_id), settings, record.mode, record.correction_command, region
        ):
            public["retryable"] = record.retryable
    return ObjectifyState(
        **public,
        scene_revision=scene.scene_revision,
        object_centric=provenance.get("object_extraction") == METHOD or provenance.get("geometry_method") == "objectgs",
        awaiting_choice=provenance.get("object_extraction") == AWAITING_CHOICE,
        object_geometry=object_geometry_status(provenance),
        geometry_note=geometry_surface_note(scene.objects),
        available=runtime_available(settings) or settings.product_objectify_remote_worker,
        note=str(note) if note else None,
    )


def request(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    expected_revision: str,
    mode: ObjectifyMode,
    *,
    correction: ObjectMembershipReassignCommand | None = None,
    region: tuple[str, ObjectRegionCommand] | None = None,
    actor_id: str | None = None,
    origin: Literal["human", "system"] = "human",
) -> ObjectifyState:
    """Accept a request only for the current scene and freeze its input/config identity."""
    job = registry.get_job(job_id)
    current = registry.scene.current(job_id).scene
    if current.scene_revision != expected_revision:
        raise SceneRevisionConflictError(
            f"scene đã ở {current.scene_revision}, không phải {expected_revision}; tải lại rồi thử lại"
        )
    if mode == "geometry" and object_geometry_state(current) != "awaiting_review":
        raise ObjectGeometryAlreadyReadyError("Scene đã có hình học; dùng chỉnh vùng để dựng lại vật.")
    if mode == "objectify" and not (runtime_available(settings) or settings.product_objectify_remote_worker):
        raise ObjectifyRequestError("Máy xử lý chưa cài runtime tách theo vật (xem scripts/gpu/README.md)")
    if mode == "objectify" and state(registry, settings, job_id).retryable is False:
        raise ObjectifyRequestError("Dữ liệu tách vật chưa đạt điều kiện; cần sửa dữ liệu hoặc dùng hộp ứng viên")
    if mode == "membership":
        if correction is None or not actor_id or correction.expected_scene_revision != expected_revision:
            raise ObjectifyRequestError("membership request requires an actor and matching correction command")
        if object_geometry_state(current) != "ready":
            raise ObjectifyRequestError("queued membership regeneration requires a Ready scene")
        preview_correction(registry.scene, job_id, correction)
    elif correction is not None:
        raise ObjectifyRequestError("correction command requires membership mode")
    if mode == "region":
        if region is None or not actor_id or region[1].expected_scene_revision != expected_revision:
            raise ObjectifyRequestError("region request requires an actor and matching region command")
        validate_region_rebuild(registry, job_id, region[0], region[1])
    elif region is not None:
        raise ObjectifyRequestError("region command requires region mode")
    bundle = job_bundle(registry, job)
    if bundle is None:
        raise ObjectifyRequestError("Job chưa có kết quả dựng hình hệ mét nên chưa dựng được tập vật")
    record = _Record(
        status="queued",
        mode=mode,
        base_revision=current.scene_revision,
        requested_at=datetime.now(UTC),
        operation_id=uuid4().hex,
        input_checksum=_input_checksum(job_id, current.scene_revision, current.scene_ir_checksum, bundle),
        config_checksum=_config_checksum(job, settings, mode, correction, region),
        correction_command=correction,
        region_object_id=region[0] if region else None,
        region_command=region[1] if region else None,
        actor_id=actor_id,
        phase=None if mode == "geometry" else "queued",
    )
    with _database(settings).transaction(write=True) as tx:
        previous = _read(tx, job_id, lock=True)
        if previous is not None and previous.status in ("queued", "running"):
            raise ObjectifyRequestError("Đang có một yêu cầu dựng lại tập vật cho scene này")
        if previous is not None:
            record = record.model_copy(update={"lease_generation": previous.lease_generation})
        _write(tx, job_id, record)
    # Ý định của người dùng được ghi sau khi yêu cầu đã nhận; từ chối ở trên thì không tới đây.
    intent = {
        "mode": mode,
        "base_revision": expected_revision,
        "operation_id": record.operation_id,
        "origin": origin,
    }
    if record.region_object_id is not None:
        intent["region_object_id"] = record.region_object_id
    record_event(_database(settings), job_id, "scene_request", intent, actor_id=actor_id)
    return state(registry, settings, job_id)


def cancel(
    registry: ProjectRegistry, settings: Settings, job_id: str, *, expected_operation_id: str | None = None
) -> ObjectifyState:
    """Request cancellation; queued work stops immediately and running work waits for child reap."""
    now = datetime.now(UTC)
    with _database(settings).transaction(write=True) as tx:
        record = _read(tx, job_id, lock=True)
        if record is None:
            raise ObjectifyRequestError("Không có yêu cầu dựng lại tập vật để hủy")
        if expected_operation_id is not None and record.operation_id != expected_operation_id:
            raise ObjectifyRequestError("operation changed; reload before cancelling")
        if record.status == "queued":
            _write(
                tx,
                job_id,
                record.model_copy(
                    update={
                        "status": "cancelled",
                        "cancellation_requested": True,
                        "error": "Đã hủy trước khi worker bắt đầu.",
                        "finished_at": now,
                        "resource_wait": None,
                    }
                ),
            )
        elif record.status == "running" and not record.cancellation_requested:
            _write(
                tx,
                job_id,
                record.model_copy(update={"cancellation_requested": True, "error": "Đang dừng tiến trình…"}),
            )
    return state(registry, settings, job_id)


def _same_lease(record: _Record | None, token: str, generation: int) -> bool:
    return bool(
        record is not None
        and record.status == "running"
        and record.lease_token == token
        and record.lease_generation == generation
    )


def _active_lease(record: _Record | None, token: str, generation: int, now: datetime) -> bool:
    return bool(
        _same_lease(record, token, generation)
        and record is not None
        and record.lease_expires_at is not None
        and record.lease_expires_at > now
    )


def _lease_is_current(
    tx: RuntimeTransaction,
    job_id: str,
    token: str,
    generation: int,
    request: OperationAdmissionRequest | None = None,
) -> bool:
    record = _read(tx, job_id, lock=True)
    if not _active_lease(record, token, generation, datetime.now(UTC)):
        return False
    if request is None:
        return True
    return bool(
        record is not None
        and record.operation_id == request.operation_id
        and request.parent_id == job_id
        and request.parent_kind == "job"
        and record.input_checksum == request.input_checksum
        and record.config_checksum == request.config_checksum
    )


def _legacy_record_is_stale(record: _Record, now: datetime) -> bool:
    age = now - (record.started_at or record.requested_at)
    # Old rows lack heartbeats and fencing tokens. Do not use the old 60-second
    # same-host startup heuristic; only the long stale bound can recover them.
    return age > _LEGACY_STALE_AFTER


def recover_interrupted(settings: Settings) -> int:
    """Recover expired leases; live stale workers remain fenced and keep their resource reservation."""
    now = datetime.now(UTC)
    recovered = 0
    with _database(settings).transaction(write=True) as tx:
        rows = tx.execute("SELECT job_id FROM r2s_scene_requests WHERE status=?", ("running",)).fetchall()
        for row in rows:
            job_id = str(row[0])
            record = _read(tx, job_id, lock=True)
            if record is None or record.status != "running":
                continue
            if record.lease_token is None:
                recoverable = _legacy_record_is_stale(record, now)
            else:
                # Expiry is the ownership boundary. A live but partitioned worker may
                # finish computation, but the commit guard will reject its old token.
                recoverable = record.lease_expires_at is not None and record.lease_expires_at <= now
            if not recoverable:
                continue
            update = {
                "status": "cancelled" if record.cancellation_requested else "failed",
                "error": (
                    "Đã hủy sau khi worker mất lease."
                    if record.cancellation_requested
                    else "Worker lease expired; bấm chạy lại để thử tiếp."
                ),
                "finished_at": now,
            }
            _write(tx, job_id, record.model_copy(update=update))
            recovered += 1
    return recovered


def _claim(settings: Settings) -> tuple[str, _Record] | None:
    """Claim a queued row with a monotonically increasing generation and fresh token."""
    worker_id, host, pid = worker_identity()
    now = datetime.now(UTC)
    with _database(settings).transaction(write=True) as tx:
        row = tx.execute(
            "SELECT job_id FROM r2s_scene_requests WHERE status=? ORDER BY job_id LIMIT 1", ("queued",)
        ).fetchone()
        if row is None:
            return None
        job_id = str(row[0])
        record = _read(tx, job_id, lock=True)
        if record is None or record.status != "queued":
            return None
        running = record.model_copy(
            update={
                "status": "running",
                "operation_id": record.operation_id or uuid4().hex,
                "started_at": now,
                "finished_at": None,
                "error": None,
                "resource_wait": None,
                "lease_generation": record.lease_generation + 1,
                "lease_token": uuid4().hex,
                "lease_expires_at": now + _LEASE_TTL,
                "heartbeat_at": now,
                "worker_id": worker_id,
                "worker_host": host,
                "worker_pid": pid,
            }
        )
        _write(tx, job_id, running)
    return job_id, running


def _heartbeat(settings: Settings, job_id: str, token: str, generation: int) -> bool:
    now = datetime.now(UTC)
    with _database(settings).transaction(write=True) as tx:
        record = _read(tx, job_id, lock=True)
        if not _active_lease(record, token, generation, now):
            return False
        assert record is not None
        _write(
            tx,
            job_id,
            record.model_copy(update={"heartbeat_at": now, "lease_expires_at": now + _LEASE_TTL}),
        )
    return True


def _cancel_reason(settings: Settings, job_id: str, token: str, generation: int) -> str | None:
    with _database(settings).transaction() as tx:
        record = _read(tx, job_id)
    if not _active_lease(record, token, generation, datetime.now(UTC)):
        return "lease_lost"
    return "user_cancel" if record is not None and record.cancellation_requested else None


def _start_heartbeat(
    settings: Settings,
    job_id: str,
    record: _Record,
    admission: ResourceAdmission,
    operation_request: list[OperationAdmissionRequest | None],
    cancel_event: Event,
    abort_reason: list[str | None],
) -> tuple[Event, Thread]:
    stop = Event()

    def beat() -> None:
        last_heartbeat = time.monotonic()
        while not stop.wait(_CANCEL_POLL_SECONDS):
            try:
                reason = _cancel_reason(settings, job_id, record.lease_token or "", record.lease_generation)
                if reason is not None:
                    abort_reason[0] = reason
                    cancel_event.set()
                    if reason == "lease_lost":
                        logger.warning(
                            "Objectify lease mất quyền job=%s generation=%s", job_id, record.lease_generation
                        )
                    return
                if time.monotonic() - last_heartbeat < _LEASE_HEARTBEAT_SECONDS:
                    continue
                if not _heartbeat(settings, job_id, record.lease_token or "", record.lease_generation):
                    abort_reason[0] = "lease_lost"
                    cancel_event.set()
                    logger.warning("Objectify lease mất quyền job=%s generation=%s", job_id, record.lease_generation)
                    return
                request = operation_request[0]
                if request is not None and not admission.touch_operation(request):
                    abort_reason[0] = "reservation_lost"
                    cancel_event.set()
                    logger.warning(
                        "Objectify reservation mất quyền job=%s generation=%s", job_id, record.lease_generation
                    )
                    return
                last_heartbeat = time.monotonic()
            except Exception as error:  # noqa: BLE001 - expiry plus commit fencing handles DB outages
                logger.warning("Objectify heartbeat lỗi job=%s cause=%s", job_id, type(error).__name__)
                abort_reason[0] = "lease_lost"
                cancel_event.set()
                return

    thread = Thread(target=beat, name=f"objectify-lease-{job_id[:8]}", daemon=True)
    thread.start()
    return stop, thread


def _bind_checksums(
    settings: Settings,
    job_id: str,
    running: _Record,
    input_checksum: Checksum,
    config_checksum: Checksum,
) -> tuple[_Record | None, str | None]:
    with _database(settings).transaction(write=True) as tx:
        current = _read(tx, job_id, lock=True)
        if not _active_lease(current, running.lease_token or "", running.lease_generation, datetime.now(UTC)):
            return None, "worker lease changed before operation admission"
        assert current is not None
        if current.input_checksum is not None and current.input_checksum != input_checksum:
            return None, "operation input changed after request acceptance"
        if current.config_checksum is not None and current.config_checksum != config_checksum:
            return None, "operation configuration changed after request acceptance"
        updated = current.model_copy(update={"input_checksum": input_checksum, "config_checksum": config_checksum})
        _write(tx, job_id, updated)
    return updated, None


def _requeue_wait(
    settings: Settings,
    job_id: str,
    running: _Record,
    result: OperationAdmissionResult,
) -> bool:
    with _database(settings).transaction(write=True) as tx:
        current = _read(tx, job_id, lock=True)
        if not _active_lease(current, running.lease_token or "", running.lease_generation, datetime.now(UTC)):
            return False
        assert current is not None
        if current.cancellation_requested:
            _write(
                tx,
                job_id,
                current.model_copy(
                    update={
                        "status": "cancelled",
                        "error": "Đã hủy theo yêu cầu.",
                        "finished_at": datetime.now(UTC),
                        "lease_expires_at": datetime.now(UTC),
                        "resource_wait": None,
                    }
                ),
            )
            return True
        _write(
            tx,
            job_id,
            current.model_copy(
                update={
                    "status": "queued",
                    "resource_wait": ObjectifyResourceWait.from_admission(result),
                    "lease_token": None,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                    "worker_id": None,
                    "worker_host": None,
                    "worker_pid": None,
                }
            ),
        )
    return True


def _finish(settings: Settings, job_id: str, running: _Record, outcome: dict[str, object]) -> bool:
    now = datetime.now(UTC)
    with _database(settings).transaction(write=True) as tx:
        current = _read(tx, job_id, lock=True)
        if not _lease_is_current(tx, job_id, running.lease_token or "", running.lease_generation):
            return False
        assert current is not None
        final = dict(outcome)
        if current.cancellation_requested and final.get("status") != "done":
            final.update(status="cancelled", error="Đã hủy theo yêu cầu.", result_revision=None, resource_wait=None)
        elif final.get("status") == "done":
            final["cancellation_requested"] = False
        _write(tx, job_id, current.model_copy(update={**final, "finished_at": now, "lease_expires_at": now}))
    return True


def _commit_guard(
    job_id: str,
    running: _Record,
    admission: ResourceAdmission,
    request: OperationAdmissionRequest,
) -> Callable[[RuntimeTransaction], bool]:
    def guard(tx: RuntimeTransaction) -> bool:
        current = _read(tx, job_id, lock=True)
        return bool(
            current is not None
            and not current.cancellation_requested
            and _lease_is_current(tx, job_id, running.lease_token or "", running.lease_generation, request)
            and admission.operation_lease_is_current(tx, request)
        )

    return guard


#: Kết quả của lượt tách vật → outcome của bản ghi đo; chỉ `completed` được cộng vào thời gian máy.
_SCENE_OUTCOMES: dict[str, Outcome] = {"done": "completed", "cancelled": "cancelled", "failed": "failed"}


def _scene_sampler(
    settings: Settings,
    admission: ResourceAdmission,
    job: JobManifest,
    mode: str,
    operation_id: str,
    config_checksum: Checksum,
    workspace: Path,
) -> ResourceSampler | None:
    """Sampler cho một lượt tách vật (tool `scene.<mode>`); lỗi đo trả None, không làm hỏng việc dựng."""
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        context = ResourceContext(
            job_id=job.job_id,
            attempt_id=operation_id,
            tool=f"scene.{mode}",
            config_checksum=config_checksum,
            runtime_manifest_checksum=machine_runtime_checksum(
                admission.registry.execution_profile, job.runtime_manifest_checksum
            ),
            shared_gpu=admission.shares_gpu(),
        )
    except Exception as error:  # noqa: BLE001 - measurement boundary must not change objectify
        logger.warning("Không tạo được resource sampler cause=%s", type(error).__name__)
        return None
    return build_sampler(settings, context, workspace)


def _record_scene_usage(settings: Settings, sampler: ResourceSampler | None, outcome: dict[str, object] | None) -> None:
    """Ghi bản ghi đo của lượt vừa xong; lỗi ghi chỉ log, không đổi kết quả job."""
    if sampler is None:
        return
    status = outcome.get("status") if outcome is not None else None
    try:
        usage = sampler.finish(_SCENE_OUTCOMES.get(str(status), "interrupted"), None)
        record_usage(_database(settings), usage)
    except Exception as error:  # noqa: BLE001 - telemetry boundary: keep the operation result
        logger.warning("Không ghi được resource telemetry cause=%s", type(error).__name__)


def process_next(registry: ProjectRegistry, settings: Settings) -> bool:
    """Handle at most one request; resource waits are requeued and let the worker sleep."""
    recover_interrupted(settings)
    # Build the admission gate before claiming work so a setup error cannot strand a row.
    admission = ResourceAdmission(registry, settings)
    claimed = _claim(settings)
    if claimed is None:
        return False
    job_id, running = claimed
    operation_request: list[OperationAdmissionRequest | None] = [None]
    cancel_event = Event()
    abort_reason: list[str | None] = [None]
    heartbeat_stop, heartbeat_thread = _start_heartbeat(
        settings, job_id, running, admission, operation_request, cancel_event, abort_reason
    )
    outcome: dict[str, object] | None = None
    reserved = False
    sampler: ResourceSampler | None = None
    try:
        # The remote resolver may update local artifacts, but it cannot change the captured base revision.
        registry.runtime_resolver.sync_down(job_id)
        if cancel_event.is_set():
            raise ProcessCancelledError("Objectify operation was cancelled")
        current = registry.scene.current(job_id).scene
        if current.scene_revision != running.base_revision:
            raise SceneRevisionConflictError(
                f"scene đã đổi sang {current.scene_revision} sau khi yêu cầu; yêu cầu lại nếu vẫn cần"
            )
        job = registry.get_job(job_id)
        bundle = job_bundle(registry, job)
        if bundle is None:
            raise ObjectifyError("job chưa có ReconstructionBundle hệ mét")
        input_checksum = _input_checksum(job_id, current.scene_revision, current.scene_ir_checksum, bundle)
        region = (
            (running.region_object_id, running.region_command)
            if running.region_object_id is not None and running.region_command is not None
            else None
        )
        config_checksum = _config_checksum(job, settings, running.mode, running.correction_command, region)
        bound, bind_error = _bind_checksums(settings, job_id, running, input_checksum, config_checksum)
        if bound is None:
            raise ObjectifyError(bind_error or "không thể giữ snapshot operation")
        running = bound

        uses_gpu = running.mode in {"objectify", "membership", "geometry", "region"} or box_candidates_require_gpu(
            settings
        )
        profile = admission.operation_profile_for_job(job, gpu_required=uses_gpu)
        request = OperationAdmissionRequest(
            operation_kind="reobjectify",
            operation_id=running.operation_id or uuid4().hex,
            parent_kind="job",
            parent_id=job_id,
            input_checksum=input_checksum,
            config_checksum=config_checksum,
            resources=profile,
            lease_token=running.lease_token,
            lease_generation=running.lease_generation,
        )
        admitted = admission.admit_operation(request)
        if admitted.status != "admitted":
            if admitted.status == "identity_conflict":
                raise ObjectifyError("operation identity trùng với input/config khác; yêu cầu bị chặn")
            _requeue_wait(settings, job_id, running, admitted)
            return False
        operation_request[0] = request
        reserved = True
        if cancel_event.is_set():
            raise ProcessCancelledError("Objectify operation was cancelled")

        root = settings.product_worker_root.expanduser().resolve() / job_id
        workspace = root / f"{running.mode}-{uuid4().hex}"
        sampler = _scene_sampler(
            settings, admission, job, running.mode, request.operation_id, config_checksum, workspace
        )
        arguments = dict(
            expected_revision=running.base_revision,
            commit_guard=_commit_guard(job_id, running, admission, request),
            cancel_event=cancel_event,
        )
        with sampled_section(
            sampler,
            on_error=lambda error: logger.warning("Không lấy được resource sample cause=%s", type(error).__name__),
        ):
            if running.mode in {"membership", "geometry", "region"}:

                def progress(phase: str) -> None:
                    with _database(settings).transaction(write=True) as tx:
                        record = _read(tx, job_id, lock=True)
                        if not _active_lease(
                            record, running.lease_token or "", running.lease_generation, datetime.now(UTC)
                        ):
                            cancel_event.set()
                            raise ProcessCancelledError(f"{running.mode} progress lost worker lease")
                        _write(tx, job_id, record.model_copy(update={"phase": phase}))

                if running.mode == "geometry":
                    revision = build_object_geometry(
                        registry, settings, job_id, workspace=workspace, progress=progress, **arguments
                    )
                elif running.mode == "region":
                    if running.region_command is None or running.region_object_id is None or running.actor_id is None:
                        raise ObjectifyRequestError("queued region payload is missing")
                    revision = rebuild_region_ready(
                        registry,
                        settings,
                        job_id,
                        workspace,
                        object_id=running.region_object_id,
                        command=running.region_command,
                        actor_id=running.actor_id,
                        progress=progress,
                        **arguments,
                    )
                else:
                    if running.correction_command is None or running.actor_id is None:
                        raise ObjectifyRequestError("queued correction payload is missing")
                    revision = regenerate_membership(
                        registry,
                        job_id,
                        settings,
                        workspace,
                        command=running.correction_command,
                        actor_id=running.actor_id,
                        progress=progress,
                        **arguments,
                    )
            else:
                operation = reobjectify if running.mode == "objectify" else use_boxes
                revision = operation(registry, job_id, settings, workspace, **arguments)
        outcome = {
            "status": "done",
            "phase": "done",
            "result_revision": revision,
            "error": None,
            "resource_wait": None,
            "retryable": None,
            "floor_fit": None,
        }
    except ProcessCancelledError:
        if abort_reason[0] == "lease_lost":
            logger.warning("Objectify cancellation after lease loss job=%s", job_id)
            outcome = {"status": "failed", "error": "Worker lease expired; result was fenced.", "result_revision": None}
        elif abort_reason[0] == "reservation_lost":
            outcome = {
                "status": "failed",
                "error": "Resource reservation expired; result was fenced.",
                "result_revision": None,
            }
        else:
            outcome = {"status": "cancelled", "error": "Đã hủy theo yêu cầu.", "result_revision": None}
    except (ObjectifyError, ObjectGeometryBuildError, ArtifactStoreError, SceneError, ValueError, OSError) as error:
        logger.warning("Dựng lại tập vật (%s) lỗi job=%s cause=%s", running.mode, job_id, error)
        outcome = {"status": "failed", "error": str(error)[:500], "result_revision": None}
        if isinstance(error, ObjectifyError):
            outcome.update(retryable=error.retryable, floor_fit=error.floor_fit)
        elif isinstance(error, ObjectGeometryBuildError):
            outcome["retryable"] = error.retryable
    except Exception as error:  # noqa: BLE001 - durable operation boundary must record unexpected failure
        logger.exception("Dựng lại tập vật (%s) lỗi ngoài dự kiến job=%s", running.mode, job_id)
        outcome = {"status": "failed", "error": str(error)[:500], "result_revision": None}
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=_LEASE_HEARTBEAT_SECONDS + 1)
        _record_scene_usage(settings, sampler, outcome)
        if reserved and operation_request[0] is not None:
            admission.release_operation(operation_request[0])

    if outcome is not None:
        if not _finish(settings, job_id, running, outcome):
            logger.warning(
                "Objectify outcome fenced after lease change job=%s generation=%s", job_id, running.lease_generation
            )
    return True
