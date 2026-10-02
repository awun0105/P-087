"""Yêu cầu dựng lại tập vật của một scene: API ghi yêu cầu, worker (máy có GPU) thực hiện.

Hai kiểu yêu cầu, đều do người dùng chọn trên Studio:

- `objectify`: chạy lại tách theo vật (pipeline v2), tự thử tối đa `product_objectify_attempts` lần;
- `boxes`: dùng hộp ứng viên (ADR 0006) — lựa chọn lùi khi tách theo vật không thành công.

Job đã `SUCCEEDED` là trạng thái kết thúc (PRODUCT-02) nên việc này **không** đổi vòng đời job: nó là
một thao tác trên scene, kết quả là revision SceneIR kế tiếp. Trạng thái yêu cầu nằm trong bảng
`r2s_scene_requests` của DB runtime — cùng DB mà API và worker đã dùng chung cho hàng đợi job — nên chạy được
cả khi API và worker ở hai máy khác nhau. Mỗi job giữ yêu cầu gần nhất; không phải artifact, không nằm trong
SceneIR.
"""

import logging
import socket
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.config import Settings
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError, SceneRevisionConflictError
from src.services.orchestration.scene.extraction import use_boxes
from src.services.orchestration.scene.objectify import AWAITING_CHOICE, METHOD, ObjectifyError, reobjectify

logger = logging.getLogger(__name__)

ObjectifyStatus = Literal["idle", "queued", "running", "done", "failed"]
ObjectifyMode = Literal["objectify", "boxes"]


class ObjectifyRequestError(ValueError):
    """Không nhận được yêu cầu; message hiển thị được cho người dùng."""


class ObjectifyState(BaseModel):
    """Trạng thái yêu cầu gần nhất của một job + scene hiện có phải scene theo vật không."""

    model_config = ConfigDict(extra="forbid")

    status: ObjectifyStatus = "idle"
    mode: ObjectifyMode | None = None
    #: Tách theo vật đã lỗi hết số lần thử; scene chỉ có môi trường, chờ người dùng chọn.
    awaiting_choice: bool = False
    #: Scene hiện tại được dựng bằng tách theo vật (pipeline v2) hay đang là đường hộp.
    object_centric: bool = False
    #: Máy này có cấu hình runtime tách theo vật không (không có thì nút chạy lại vô nghĩa).
    available: bool = False
    #: Ghi chú của lần dựng scene (vd lý do lùi về đường hộp).
    note: str | None = None
    base_revision: str | None = None
    result_revision: str | None = None
    error: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class _Record(BaseModel):
    """Phần ghi xuống đĩa (không gồm các trường suy ra từ scene/cấu hình)."""

    model_config = ConfigDict(extra="forbid")

    status: ObjectifyStatus
    mode: ObjectifyMode
    base_revision: str
    result_revision: str | None = None
    error: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: Máy của worker đã nhận yêu cầu (để nhận ra yêu cầu mồ côi khi worker máy đó khởi động lại).
    worker_host: str | None = None


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


def runtime_available(settings: Settings) -> bool:
    """Runtime tách theo vật đã cấu hình và file tồn tại trên máy này."""
    python, checkpoint = settings.product_scene_runtime_python, settings.product_sam2_checkpoint
    return bool(settings.product_objectify and python and checkpoint and python.is_file() and checkpoint.is_file())


def state(registry: ProjectRegistry, settings: Settings, job_id: str) -> ObjectifyState:
    """Trạng thái cho UI: scene đang là đường nào, có chạy lại được không, yêu cầu gần nhất ra sao.

    `available` phản ánh máy đang trả lời (API). Khi worker ở máy khác, API không biết runtime của worker:
    đặt `PRODUCT_OBJECTIFY_REMOTE_WORKER=true` trên API để báo "có worker lo việc này".
    """
    provenance = registry.scene.current(job_id).scene.provenance
    with _database(settings).transaction() as tx:
        record = _read(tx, job_id)
    note = provenance.get("note")
    return ObjectifyState(
        **(record.model_dump(exclude={"worker_host"}) if record is not None else {}),
        object_centric=provenance.get("object_extraction") == METHOD,
        awaiting_choice=provenance.get("object_extraction") == AWAITING_CHOICE,
        available=runtime_available(settings) or settings.product_objectify_remote_worker,
        note=str(note) if note else None,
    )


def request(
    registry: ProjectRegistry, settings: Settings, job_id: str, expected_revision: str, mode: ObjectifyMode
) -> ObjectifyState:
    """Xếp hàng một yêu cầu; từ chối khi đang có yêu cầu dở, scene đã đổi, hoặc không máy nào làm được."""
    job = registry.get_job(job_id)
    current = registry.scene.current(job_id).scene.scene_revision
    if current != expected_revision:
        raise SceneRevisionConflictError(f"scene đã ở {current}, không phải {expected_revision}; tải lại rồi thử lại")
    if mode == "objectify" and not (runtime_available(settings) or settings.product_objectify_remote_worker):
        raise ObjectifyRequestError("Máy xử lý chưa cài runtime tách theo vật (xem scripts/gpu/README.md)")
    if job_bundle(registry, job) is None:
        raise ObjectifyRequestError("Job chưa có kết quả dựng hình hệ mét nên chưa dựng được tập vật")
    with _database(settings).transaction(write=True) as tx:
        previous = _read(tx, job_id, lock=True)
        if previous is not None and previous.status in ("queued", "running"):
            raise ObjectifyRequestError("Đang có một yêu cầu dựng lại tập vật cho scene này")
        _write(tx, job_id, _Record(status="queued", mode=mode, base_revision=current, requested_at=datetime.now(UTC)))
    return state(registry, settings, job_id)


#: Yêu cầu "running" lâu hơn mức này coi như worker đã chết, dù ở máy nào (dài hơn nhiều so với 3 lần thử).
_STALE_AFTER = timedelta(hours=3)
#: Lúc worker khởi động, yêu cầu "running" của chính máy này mà cũ hơn mức này là của lần chạy trước đã chết.
#: Không lấy 0: các worker cùng nhóm khởi động lệch nhau vài giây, worker khởi động sau không được huỷ việc
#: worker khởi động trước vừa nhận.
_OWN_HOST_GRACE = timedelta(seconds=60)


def recover_interrupted(settings: Settings, host: str | None = None) -> int:
    """Lúc worker khởi động: đánh dấu lỗi các yêu cầu "running" mồ côi để người dùng chạy lại được.

    Mồ côi = do máy `host` (mặc định: máy này) nhận từ trước khi nhóm worker hiện tại khởi động, hoặc đã
    "running" quá `_STALE_AFTER` ở bất kỳ máy nào (máy đó đã bị tắt/trả).
    """
    host = host or socket.gethostname()
    now = datetime.now(UTC)
    recovered = 0
    with _database(settings).transaction(write=True) as tx:
        rows = tx.execute("SELECT job_id, payload FROM r2s_scene_requests WHERE status=?", ("running",)).fetchall()
        for job_id, payload in rows:
            record = _Record.model_validate_json(payload)
            age = now - (record.started_at or record.requested_at)
            if not (age > _STALE_AFTER or (record.worker_host == host and age > _OWN_HOST_GRACE)):
                continue
            update = {"status": "failed", "error": "Worker dừng giữa chừng; bấm chạy lại.", "finished_at": now}
            _write(tx, str(job_id), record.model_copy(update=update))
            recovered += 1
    return recovered


def _claim(settings: Settings) -> tuple[str, _Record] | None:
    """Nhận một yêu cầu đang chờ: đọc có khoá rồi ghi `running` trong cùng transaction, nên chỉ một worker nhận."""
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
            update={"status": "running", "started_at": datetime.now(UTC), "worker_host": socket.gethostname()}
        )
        _write(tx, job_id, running)
    return job_id, running


def process_next(registry: ProjectRegistry, settings: Settings) -> bool:
    """Worker: thực hiện tối đa một yêu cầu đang chờ; trả True nếu đã xử lý một yêu cầu."""
    claimed = _claim(settings)
    if claimed is None:
        return False
    job_id, running = claimed
    outcome: dict[str, object]
    try:
        # Worker ở máy khác: lấy về artifact mới nhất của job (kể cả revision scene do API ghi khi người dùng sửa).
        registry.runtime_resolver.sync_down(job_id)
        current = registry.scene.current(job_id).scene.scene_revision
        if current != running.base_revision:
            raise ObjectifyError(f"scene đã đổi sang {current} sau khi yêu cầu; yêu cầu lại nếu vẫn cần")
        root = settings.product_worker_root.expanduser().resolve() / job_id
        operation = reobjectify if running.mode == "objectify" else use_boxes
        revision = operation(registry, job_id, settings, root / f"{running.mode}-{uuid4().hex}")
        outcome = {"status": "done", "result_revision": revision}
    except (ObjectifyError, ArtifactStoreError, SceneError, ValueError, OSError) as error:
        logger.warning("Dựng lại tập vật (%s) lỗi job=%s cause=%s", running.mode, job_id, error)
        outcome = {"status": "failed", "error": str(error)[:500]}
    with _database(settings).transaction(write=True) as tx:
        _write(tx, job_id, running.model_copy(update={**outcome, "finished_at": datetime.now(UTC)}))
    return True
