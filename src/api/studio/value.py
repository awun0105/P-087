"""Sự kiện giá trị do trình duyệt gửi (architecture §15.3) và ground truth benchmark (§15.2).

Route ghi sự kiện không trả dữ liệu; mọi lô bị từ chối 422 trước khi ghi. `actor_id` luôn lấy từ người đăng nhập.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import JobNotFoundError
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.value.events import list_events, record_event
from src.services.orchestration.value.ground_truth import (
    BenchmarkTruth,
    StoredTruth,
    TruthVersionConflictError,
    read_truth,
    write_truth,
)

router = APIRouter()
_ERRORS = {404: {"description": "Job không tồn tại"}, 422: {"description": "Lô sự kiện vi phạm luật ghi nhận"}}
#: Một lô thời gian thao tác không được dài quá 5 phút; phiên Walk tối đa 2 giờ.
_OPERATOR_BATCH_MAX = timedelta(seconds=300)
_WALK_SESSION_MAX = timedelta(hours=2)
#: Đồng hồ trình duyệt được phép lệch về phía tương lai tối đa 60 giây.
_FUTURE_TOLERANCE = timedelta(seconds=60)


class OperatorTimeBatch(BaseModel):
    session_key: str = Field(min_length=8, max_length=64)
    surface: Literal["studio", "progress", "evaluation", "other"]
    started_at: AwareDatetime
    ended_at: AwareDatetime
    active_seconds: float = Field(ge=0)


class WalkSessionBatch(BaseModel):
    scene_revision: str = Field(min_length=1, max_length=64)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    outcome: Literal["completed", "aborted"]


def _reject(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _check_clock(started_at: datetime, ended_at: datetime) -> timedelta:
    """Luật chung: kết thúc sau bắt đầu và không lệch tương lai quá 60 giây."""
    if ended_at <= started_at:
        raise _reject("ended_at phải sau started_at")
    if max(started_at, ended_at) > datetime.now(UTC) + _FUTURE_TOLERANCE:
        raise _reject("thời điểm lô nằm ở tương lai")
    return ended_at - started_at


def _job_exists(job_id: str) -> None:
    try:
        deps.registry().get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _authorize(user: UserRecord | None, job_id: str, *, operation: str = "ghi thời gian thao tác của") -> None:
    _job_exists(job_id)
    authorize_job_mutation(user, deps.registry(), job_id, operation=operation)


def _database() -> RuntimeDatabase:
    return RuntimeDatabase(deps.settings().database_url)


def _previous_batch_end(database: RuntimeDatabase, job_id: str, session_key: str) -> datetime | None:
    """Thời điểm kết thúc lớn nhất trong các lô trước của cùng phiên trình duyệt."""
    ends = [
        datetime.fromisoformat(event.payload["ended_at"])
        for event in list_events(database, job_id, {"operator_time"})
        if event.payload.get("session_key") == session_key
    ]
    return max(ends, default=None)


@router.post(
    "/jobs/{job_id}/value-events/operator-time",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
)
def record_operator_time(
    job_id: str,
    batch: OperatorTimeBatch,
    user: UserRecord | None = Depends(require_contributor),
) -> None:
    """Một lô thời gian người dùng thật sự thao tác (đã được trình duyệt lọc theo quy tắc §15.3)."""
    _authorize(user, job_id)
    duration = _check_clock(batch.started_at, batch.ended_at)
    if duration > _OPERATOR_BATCH_MAX:
        raise _reject("một lô thời gian thao tác dài tối đa 300 giây")
    if batch.active_seconds > duration.total_seconds():
        raise _reject("active_seconds lớn hơn khoảng thời gian của lô")
    database = _database()
    previous_end = _previous_batch_end(database, job_id, batch.session_key)
    if previous_end is not None and batch.started_at < previous_end:
        raise _reject("lô thời gian chồng lên lô trước của cùng phiên")
    record_event(
        database,
        job_id,
        "operator_time",
        {
            "session_key": batch.session_key,
            "surface": batch.surface,
            "started_at": batch.started_at.isoformat(),
            "ended_at": batch.ended_at.isoformat(),
            "active_seconds": batch.active_seconds,
        },
        actor_id=user.user_id if user is not None else None,
    )


@router.post(
    "/jobs/{job_id}/value-events/walk-session",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
)
def record_walk_session(
    job_id: str,
    session: WalkSessionBatch,
    user: UserRecord | None = Depends(require_contributor),
) -> None:
    """Một phiên Walk đã chạy trên một revision; hoàn tất hoặc bị huỷ."""
    _authorize(user, job_id)
    duration = _check_clock(session.started_at, session.ended_at)
    if duration > _WALK_SESSION_MAX:
        raise _reject("phiên Walk dài tối đa 2 giờ")
    record_event(
        _database(),
        job_id,
        "walk_session",
        {
            "scene_revision": session.scene_revision,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat(),
            "outcome": session.outcome,
        },
        actor_id=user.user_id if user is not None else None,
    )


class BenchmarkTruthResponse(BaseModel):
    version: int
    truth: BenchmarkTruth
    updated_at: datetime | None


class BenchmarkTruthWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    truth: BenchmarkTruth


def _truth_response(stored: StoredTruth) -> BenchmarkTruthResponse:
    return BenchmarkTruthResponse(version=stored.version, truth=stored.truth, updated_at=stored.updated_at)


def _with_server_tag_times(truth: BenchmarkTruth, previous: BenchmarkTruth) -> BenchmarkTruth:
    """`tagged_at` do máy chủ đặt: giữ mốc đã lưu khi layout vẫn trỏ cùng revision, ngược lại lấy giờ máy chủ.

    P3 (đổi → thử lại) so mốc này với thời điểm sự kiện do máy chủ ghi, nên không được tin đồng hồ trình duyệt.
    """
    now = datetime.now(UTC)
    layouts = {}
    for key, layout in truth.layouts.items():
        kept = previous.layouts.get(key)
        tagged_at = kept.tagged_at if kept is not None and kept.scene_revision == layout.scene_revision else now
        layouts[key] = layout.model_copy(update={"tagged_at": tagged_at})
    return truth.model_copy(update={"layouts": layouts})


def _reference_problems(job_id: str, truth: BenchmarkTruth, previous: BenchmarkTruth) -> list[str]:
    """Revision của layout và vật cản chính phải có thật trong job; trả danh sách lỗi tiếng Việt.

    Chỉ kiểm phần mới hoặc đổi so với tài liệu đã lưu: một vật cản chính sau này rời khỏi scene không được chặn mọi lần lưu khác.
    """
    problems: list[str] = []
    layout_a, layout_b = truth.layouts.get("A"), truth.layouts.get("B")
    if layout_a is not None and layout_b is not None and layout_a.scene_revision == layout_b.scene_revision:
        problems.append("layout A và B phải là hai revision khác nhau")
    changed_layouts = {
        key: layout
        for key, layout in truth.layouts.items()
        if (kept := previous.layouts.get(key)) is None or kept.scene_revision != layout.scene_revision
    }
    new_obstacles = [item for item in truth.key_obstacle_ids if item not in set(previous.key_obstacle_ids)]
    if not changed_layouts and not new_obstacles:
        return problems
    registry = deps.registry()
    try:
        for key in sorted(changed_layouts):
            revision = changed_layouts[key].scene_revision
            if registry.scene.revision(job_id, revision) is None:
                problems.append(f"layout {key}: revision {revision} không phải revision của job này")
        if new_obstacles:
            objects = {item.id for item in registry.scene.current(job_id).scene.objects}
            missing = [item for item in new_obstacles if item not in objects]
            if missing:
                problems.append("vật cản chính không có trong scene hiện tại: " + ", ".join(missing))
    except SceneError:
        problems.append("job chưa có scene đọc được nên chưa đối chiếu được revision và vật cản chính")
    return problems


@router.get("/jobs/{job_id}/benchmark-truth", response_model=BenchmarkTruthResponse, responses=_ERRORS)
def read_benchmark_truth(job_id: str, user: UserRecord | None = Depends(require_contributor)) -> BenchmarkTruthResponse:
    """Ground truth của job; job chưa có tài liệu thì version 0 và giá trị mặc định, không 404."""
    _job_exists(job_id)
    return _truth_response(read_truth(_database(), job_id))


@router.put(
    "/jobs/{job_id}/benchmark-truth",
    response_model=BenchmarkTruthResponse,
    responses={**_ERRORS, 409: {"description": "Tài liệu đã đổi so với expected_version"}},
)
def write_benchmark_truth(
    job_id: str,
    body: BenchmarkTruthWrite,
    user: UserRecord | None = Depends(require_contributor),
) -> BenchmarkTruthResponse:
    """Ghi ground truth với kiểm version (CAS): lệch version thì 409, sai tham chiếu thì 422."""
    _authorize(user, job_id, operation="sửa ground truth benchmark của")
    database = _database()
    previous = read_truth(database, job_id).truth
    problems = _reference_problems(job_id, body.truth, previous)
    if problems:
        raise _reject("; ".join(problems))
    try:
        stored = write_truth(database, job_id, body.expected_version, _with_server_tag_times(body.truth, previous))
    except TruthVersionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _truth_response(stored)
