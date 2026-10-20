"""T-047: a worker shutdown during a run is recorded as an interrupted, retryable attempt."""

from pathlib import Path

from src.models.contracts.manifests import JobStatus
from src.models.contracts.retryability import is_execution_error_retryable
from src.services.orchestration.jobs import runner
from tests.test_orchestration.test_runner_expected_deadline import _attempt


def _record(tmp_path: Path, error: BaseException):  # noqa: ANN202
    attempt = _attempt(tmp_path)
    runner._record_runner_failure(attempt, error)
    job = attempt.registry.get_job(attempt.job.job_id)
    failure = attempt.registry.list_job_attempts(job.job_id)[-1].error
    return job, failure


def test_keyboard_interrupt_records_interrupted_shutdown(tmp_path: Path) -> None:
    job, failure = _record(tmp_path, KeyboardInterrupt())
    assert job.status == JobStatus.FAILED
    assert failure is not None and failure.error_code == "INTERRUPTED_SHUTDOWN"
    assert failure.retryable is True and is_execution_error_retryable(failure)
    assert "Thử lại" in failure.human_message


def test_ordinary_runner_error_keeps_runner_failed_code(tmp_path: Path) -> None:
    _, failure = _record(tmp_path, ValueError("bad"))
    assert failure is not None and failure.error_code == "PREVIEW_RUNNER_FAILED"
    assert failure.retryable is False
