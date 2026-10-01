"""Yêu cầu dựng lại tập vật của một scene: API ghi yêu cầu, worker (máy có GPU) thực hiện.

Hai kiểu yêu cầu, đều do người dùng chọn trên Studio:

- `objectify`: chạy lại tách theo vật (pipeline v2), tự thử tối đa `product_objectify_attempts` lần;
- `boxes`: dùng hộp ứng viên (ADR 0006) — lựa chọn lùi khi tách theo vật không thành công.

Job đã `SUCCEEDED` là trạng thái kết thúc (PRODUCT-02) nên việc này **không** đổi vòng đời job: nó là
một thao tác trên scene, kết quả là revision SceneIR kế tiếp do `reobjectify` ghi. Trạng thái yêu cầu là
một file JSON nhỏ trong workspace của worker (`PRODUCT_WORKER_ROOT/<job_id>/objectify_request.json`),
không phải artifact và không nằm trong SceneIR.

Giới hạn: API và worker phải nhìn thấy cùng `PRODUCT_WORKER_ROOT` (triển khai một máy / một volume).
Triển khai tách API và worker ở hai máy cần chuyển trạng thái này sang DB — chưa làm.
"""

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.config import Settings
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import SceneError, SceneRevisionConflictError
from src.services.orchestration.scene_extraction import use_boxes
from src.services.orchestration.scene_objectify import AWAITING_CHOICE, METHOD, ObjectifyError, reobjectify
from src.services.orchestration.stage_views import job_bundle

logger = logging.getLogger(__name__)

_FILE = "objectify_request.json"
_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
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


def _path(settings: Settings, job_id: str) -> Path:
    if _JOB_ID.fullmatch(job_id) is None:
        raise ObjectifyRequestError("job_id không hợp lệ")
    return settings.product_worker_root.expanduser().resolve() / job_id / _FILE


def _read(path: Path) -> _Record | None:
    if not path.is_file():
        return None
    return _Record.model_validate_json(path.read_text(encoding="utf-8"))


def _write(path: Path, record: _Record) -> None:
    """Ghi qua file tạm rồi đổi tên để bên đọc không bao giờ thấy file dở."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(record.model_dump_json(), encoding="utf-8")
    os.replace(temporary, path)


def runtime_available(settings: Settings) -> bool:
    """Runtime tách theo vật đã cấu hình và file tồn tại trên máy này."""
    python, checkpoint = settings.product_scene_runtime_python, settings.product_sam2_checkpoint
    return bool(settings.product_objectify and python and checkpoint and python.is_file() and checkpoint.is_file())


def state(registry: ProjectRegistry, settings: Settings, job_id: str) -> ObjectifyState:
    """Trạng thái cho UI: scene đang là đường nào, có chạy lại được không, yêu cầu gần nhất ra sao."""
    provenance = registry.scene.current(job_id).scene.provenance
    record = _read(_path(settings, job_id))
    note = provenance.get("note")
    return ObjectifyState(
        **(record.model_dump() if record is not None else {}),
        object_centric=provenance.get("object_extraction") == METHOD,
        awaiting_choice=provenance.get("object_extraction") == AWAITING_CHOICE,
        available=runtime_available(settings),
        note=str(note) if note else None,
    )


def request(
    registry: ProjectRegistry, settings: Settings, job_id: str, expected_revision: str, mode: ObjectifyMode
) -> ObjectifyState:
    """Xếp hàng một yêu cầu; từ chối khi đang có yêu cầu dở, scene đã đổi, hoặc máy thiếu điều kiện."""
    job = registry.get_job(job_id)
    current = registry.scene.current(job_id).scene.scene_revision
    if current != expected_revision:
        raise SceneRevisionConflictError(f"scene đã ở {current}, không phải {expected_revision}; tải lại rồi thử lại")
    if mode == "objectify" and not runtime_available(settings):
        raise ObjectifyRequestError("Máy xử lý chưa cài runtime tách theo vật (xem scripts/gpu/README.md)")
    if job_bundle(registry, job) is None:
        raise ObjectifyRequestError("Job chưa có kết quả dựng hình hệ mét nên chưa dựng được tập vật")
    path = _path(settings, job_id)
    previous = _read(path)
    if previous is not None and previous.status in ("queued", "running"):
        raise ObjectifyRequestError("Đang có một yêu cầu dựng lại tập vật cho scene này")
    _write(path, _Record(status="queued", mode=mode, base_revision=current, requested_at=datetime.now(UTC)))
    return state(registry, settings, job_id)


def recover_interrupted(settings: Settings) -> int:
    """Lúc worker khởi động: yêu cầu còn ghi "running" là của lần chạy đã chết → đánh dấu lỗi để chạy lại được."""
    root = settings.product_worker_root.expanduser().resolve()
    recovered = 0
    for path in sorted(root.glob(f"*/{_FILE}")):
        record = _read(path)
        path.with_suffix(".lock").unlink(missing_ok=True)
        if record is not None and record.status == "running":
            _write(
                path,
                record.model_copy(
                    update={
                        "status": "failed",
                        "error": "Worker dừng giữa chừng; bấm chạy lại.",
                        "finished_at": datetime.now(UTC),
                    }
                ),
            )
            recovered += 1
    return recovered


def process_next(registry: ProjectRegistry, settings: Settings) -> bool:
    """Worker: thực hiện tối đa một yêu cầu đang chờ; trả True nếu đã xử lý một yêu cầu."""
    root = settings.product_worker_root.expanduser().resolve()
    for path in sorted(root.glob(f"*/{_FILE}")):
        record = _read(path)
        if record is None or record.status != "queued":
            continue
        job_id = path.parent.name
        lock = path.with_suffix(".lock")
        try:
            # Nhiều worker cùng quét: tạo file khoá kiểu "chỉ tạo mới" để chỉ một worker nhận yêu cầu này.
            lock.open("x").close()
        except FileExistsError:
            continue
        running = record.model_copy(update={"status": "running", "started_at": datetime.now(UTC)})
        _write(path, running)
        outcome: dict[str, object]
        try:
            current = registry.scene.current(job_id).scene.scene_revision
            if current != record.base_revision:
                raise ObjectifyError(f"scene đã đổi sang {current} sau khi yêu cầu; yêu cầu lại nếu vẫn cần")
            workspace = path.parent / f"{record.mode}-{uuid4().hex}"
            operation = reobjectify if record.mode == "objectify" else use_boxes
            revision = operation(registry, job_id, settings, workspace)
            outcome = {"status": "done", "result_revision": revision}
        except (ObjectifyError, ArtifactStoreError, SceneError, ValueError, OSError) as error:
            logger.warning("Dựng lại tập vật (%s) lỗi job=%s cause=%s", record.mode, job_id, error)
            outcome = {"status": "failed", "error": str(error)[:500]}
        _write(path, running.model_copy(update={**outcome, "finished_at": datetime.now(UTC)}))
        lock.unlink(missing_ok=True)
        return True
    return False
