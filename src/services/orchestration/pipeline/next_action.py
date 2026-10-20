"""Một hàm thuần quyết định "ai đang phải làm gì tiếp" cho một scene (T-058).

Thay cho các chuỗi `if` rải ở chuông, dòng tiến trình, banner, đầu trang và danh sách. Thứ tự quy tắc giữ như chuông cũ
(`NextAction.tsx`): đang dựng → lỗi / hủy → chờ người → scene xong (Draft, chọn cách tách vật, vật chờ xác nhận, gói,
duyệt, phát hành).
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.manifests import JobStatus, StageId
from src.models.contracts.scene import SceneIR
from src.services.orchestration.jobs.progress import WaitingFor
from src.services.scene.geometry_state import ObjectGeometryState

NextActionKind = Literal[
    "wait_system",
    "review_anonymization",
    "confirm_metric",
    "retry_job",
    "job_failed",
    "job_cancelled",
    "retry_geometry",
    "review_objects",
    "choose_object_method",
    "confirm_objects",
    "scene_ready",
    "released",
    "await_review",
    "review_package",
    "fix_preflight",
    "create_package",
]
OperationStatus = Literal["idle", "queued", "running", "done", "failed", "cancelled"]
OperationMode = Literal["objectify", "boxes", "membership", "geometry", "region"]
_BUILD_MODES = frozenset({"geometry", "region", "membership"})


@dataclass(frozen=True)
class SceneOperationFacts:
    status: OperationStatus
    mode: OperationMode
    on_current_revision: bool


@dataclass(frozen=True)
class PackageFacts:
    exists_for_revision: bool
    preflight_failed: bool


@dataclass(frozen=True)
class NextActionFacts:
    job_status: JobStatus
    waiting_for: WaitingFor | None
    #: None = lượt chạy không có lỗi.
    failure_retryable: bool | None
    awaiting_object_choice: bool
    #: Từ `object_geometry_view`: None = scene cũ không có bước duyệt vật.
    object_geometry: ObjectGeometryState | None
    scene_operation: SceneOperationFacts | None
    #: None = không đọc (danh sách scene).
    pending_candidates: int | None
    #: None = không đọc gói / trạng thái duyệt.
    package: PackageFacts | None
    review_status: str | None


class NextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NextActionKind
    step_id: StageId | None = None
    owner: Literal["system", "user"] = "user"
    pending_count: int | None = None


def _user(kind: NextActionKind, step: StageId | None = None, pending: int | None = None) -> NextAction:
    return NextAction(kind=kind, step_id=step, owner="user", pending_count=pending)


def next_action(facts: NextActionFacts) -> NextAction:
    """Quy tắc đầu tiên khớp thắng; `owner="system"` chỉ khi máy đang làm."""
    if facts.job_status == JobStatus.QUEUED:
        return NextAction(kind="wait_system", owner="system")
    if facts.job_status == JobStatus.RUNNING:
        if facts.waiting_for == "anonymization_review":
            return _user("review_anonymization", StageId.ANONYMIZATION_REVIEW)
        if facts.waiting_for == "metric_confirmation":
            return _user("confirm_metric", StageId.METRIC_CANONICALIZE)
        return NextAction(kind="wait_system", owner="system")
    if facts.job_status == JobStatus.FAILED:
        return _user("retry_job" if facts.failure_retryable else "job_failed")
    if facts.job_status == JobStatus.CANCELLED:
        return _user("job_cancelled")
    operation = facts.scene_operation
    if operation is not None and operation.status in {"queued", "running"}:
        step = StageId.SCENE_DECOMPOSE if operation.mode in _BUILD_MODES else StageId.OBJECT_EXTRACT
        return NextAction(kind="wait_system", step_id=step, owner="system")
    if facts.object_geometry == "awaiting_review":
        if (
            operation is not None
            and operation.mode == "geometry"
            and operation.status in {"failed", "cancelled"}
            and operation.on_current_revision
        ):
            return _user("retry_geometry", StageId.SCENE_DECOMPOSE)
        return _user("review_objects", StageId.OBJECT_CONFIRM, facts.pending_candidates)
    if facts.awaiting_object_choice:
        return _user("choose_object_method", StageId.OBJECT_EXTRACT)
    if facts.pending_candidates:
        return _user("confirm_objects", StageId.OBJECT_CONFIRM, facts.pending_candidates)
    if facts.package is None:
        return _user("scene_ready")
    if facts.review_status == "RELEASED":
        return _user("released")
    if facts.review_status == "READY_FOR_REVIEW":
        return _user("await_review")
    if facts.package.exists_for_revision:
        return _user("review_package")
    if facts.package.preflight_failed:
        return _user("fix_preflight")
    return _user("create_package")


def pending_candidates(scene: SceneIR) -> int:
    """Vật ứng viên chưa được xác nhận, bỏ qua vật đã bỏ qua hoặc đã xoá (cùng quy tắc bộ lọc của Studio)."""
    return sum(
        1
        for item in scene.objects
        if item.state == "CANDIDATE" and item.provenance.get("review") not in {"IGNORED", "DELETED"}
    )
