"""Unit tests for the job transition table (PRODUCT-02).

The table is pure data, so every edge can be asserted exhaustively.
"""

import pytest

from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs.errors import InvalidTransitionError
from src.services.orchestration.jobs.transitions import (
    ALLOWED_TRANSITIONS,
    CLOSING_STATUSES,
    TERMINAL_STATUSES,
    can_transition,
    legal_targets,
    require_transition,
)

ALL_STATUSES = list(JobStatus)

#: Bảng hợp lệ, viết tay để test không tự suy ra từ chính implementation.
EXPECTED_EDGES: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: {JobStatus.QUEUED},
    JobStatus.CANCELLED: set(),
}


def test_transition_table_covers_every_status() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(ALL_STATUSES)


@pytest.mark.parametrize("current", ALL_STATUSES)
def test_allowed_edges_match_expected(current: JobStatus) -> None:
    assert set(ALLOWED_TRANSITIONS[current]) == EXPECTED_EDGES[current]


@pytest.mark.parametrize("current", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_can_transition_matches_expected(current: JobStatus, target: JobStatus) -> None:
    assert can_transition(current, target) is (target in EXPECTED_EDGES[current])


@pytest.mark.parametrize("current", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_require_transition_raises_exactly_on_forbidden_edges(current: JobStatus, target: JobStatus) -> None:
    if target in EXPECTED_EDGES[current]:
        require_transition(current, target)  # must not raise
    else:
        with pytest.raises(InvalidTransitionError):
            require_transition(current, target)


def test_legal_targets_exposes_the_same_table() -> None:
    for status in ALL_STATUSES:
        assert legal_targets(status) == ALLOWED_TRANSITIONS[status]


def test_terminal_statuses_have_no_exit() -> None:
    for status in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_retry_is_the_only_exit_from_failed() -> None:
    assert ALLOWED_TRANSITIONS[JobStatus.FAILED] == frozenset({JobStatus.QUEUED})


def test_succeeded_cannot_be_undone() -> None:
    """Thành công không được rollback thành trạng thái khác."""
    for target in ALL_STATUSES:
        assert can_transition(JobStatus.SUCCEEDED, target) is False


def test_closing_statuses_require_completed_at() -> None:
    assert CLOSING_STATUSES == frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


def test_error_message_names_the_allowed_targets() -> None:
    with pytest.raises(InvalidTransitionError, match="RUNNING"):
        require_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED)


def test_error_message_marks_terminal_state() -> None:
    with pytest.raises(InvalidTransitionError, match="trạng thái kết thúc"):
        require_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
