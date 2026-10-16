"""Sự kiện giá trị do trình duyệt gửi: phút công người và phiên Walk (architecture §15.3).

Route không trả dữ liệu; mọi lô bị từ chối 422 trước khi ghi. `actor_id` luôn lấy từ người đăng nhập.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AwareDatetime, BaseModel, Field

from src.api.auth import require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.studio import deps
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import JobNotFoundError
from src.services.orchestration.value.events import list_events, record_event

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


def _authorize(user: UserRecord | None, job_id: str) -> None:
    registry = deps.registry()
    try:
        registry.get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    authorize_job_mutation(user, registry, job_id, operation="ghi thời gian thao tác của")


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
