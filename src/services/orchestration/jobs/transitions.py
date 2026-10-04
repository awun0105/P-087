"""Job lifecycle transition rules (PRODUCT-02).

Luật chuyển trạng thái là hàm thuần, không I/O, nên test được cả bảng chuyển mà
không cần dựng job thật. `FAILED → QUEUED` là cạnh retry duy nhất.
"""

from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs.errors import InvalidTransitionError

#: Bảng chuyển hợp lệ. Trạng thái terminal có tập đích rỗng.
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.CANCELLED: frozenset(),
}

#: Trạng thái không còn đường đi tiếp. Retry job FAILED tạo attempt mới, không
#: mở lại chính attempt đã hỏng.
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.SUCCEEDED, JobStatus.CANCELLED})

#: Trạng thái kết thúc một attempt và phải có `completed_at`.
CLOSING_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


def legal_targets(current: JobStatus) -> frozenset[JobStatus]:
    """Các trạng thái được phép chuyển tới từ `current`."""
    return ALLOWED_TRANSITIONS[current]


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """True only when the transition table allows this edge."""
    return target in ALLOWED_TRANSITIONS[current]


def require_transition(current: JobStatus, target: JobStatus) -> None:
    """Raise InvalidTransitionError when the edge is not on the table."""
    if can_transition(current, target):
        return
    allowed = ", ".join(sorted(ALLOWED_TRANSITIONS[current])) or "không có (trạng thái kết thúc)"
    raise InvalidTransitionError(f"không thể chuyển job từ {current} sang {target}; chỉ cho phép: {allowed}")
