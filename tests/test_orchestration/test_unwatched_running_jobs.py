"""T-048: a RUNNING job that no worker holds a lease for is failed as retryable after one lease TTL."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.jobs import worker_cli
from src.services.orchestration.jobs.lease import LEASE_TTL, acquire, has_lease
from src.services.orchestration.jobs.worker_cli import intentionally_unleased, recover_unwatched_running_jobs
from tests.test_orchestration.test_job_lease import _registry, _running_job


def _later() -> datetime:
    """One lease TTL after now, computed when the test runs (not at import)."""
    return datetime.now(UTC) + LEASE_TTL + timedelta(minutes=1)


def test_running_job_without_lease_older_than_ttl_is_failed_retryable(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _running_job(registry)

    assert recover_unwatched_running_jobs(registry, now=_later()) == 1

    failed = registry.get_job(job.job_id)
    error = registry.list_job_attempts(job.job_id)[-1].error
    assert failed.status == JobStatus.FAILED
    assert error is not None and error.error_code == "INTERRUPTED_SHUTDOWN" and error.retryable is True
    assert error.details == {"job_id": job.job_id, "stage": job.current_stage, "reason": "no_lease"}


def test_running_job_with_lease_is_untouched(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _running_job(registry)
    assert acquire(registry.persistence.database, job.job_id, "worker-a", now=_later()) is not None
    assert has_lease(registry.persistence.database, job.job_id)

    assert recover_unwatched_running_jobs(registry, now=_later()) == 0
    assert registry.get_job(job.job_id).status == JobStatus.RUNNING


def test_recent_running_job_without_lease_is_untouched(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _running_job(registry)

    assert recover_unwatched_running_jobs(registry, now=datetime.now(UTC) + timedelta(minutes=1)) == 0
    assert registry.get_job(job.job_id).status == JobStatus.RUNNING


def test_job_waiting_for_metric_confirmation_is_intentionally_unleased(tmp_path: Path) -> None:
    job = _running_job(_registry(tmp_path)).model_copy(update={"current_stage": StageId.METRIC_CANONICALIZE})
    assert intentionally_unleased(job) is True


@pytest.mark.parametrize(
    "wait", ["awaiting_anonymization_review", "awaiting_finalize", "awaiting_pose_step", "awaiting_scene_extract"]
)
def test_jobs_waiting_on_purpose_are_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wait: str) -> None:
    registry = _registry(tmp_path)
    job = _running_job(registry)
    monkeypatch.setattr(worker_cli, wait, lambda candidate: candidate.job_id == job.job_id)

    assert recover_unwatched_running_jobs(registry, now=_later()) == 0
    assert registry.get_job(job.job_id).status == JobStatus.RUNNING


def test_sweep_runs_at_most_once_per_interval() -> None:
    """Review fix: the unwatched-job scan reads the whole event journal; once per half lease TTL is enough."""
    from src.services.orchestration.jobs.worker_cli import Periodic

    sweep = Periodic(300.0)
    assert sweep.due(1000.0) is True
    assert sweep.due(1003.0) is False
    assert sweep.due(1299.0) is False
    assert sweep.due(1300.0) is True
    assert sweep.due(1301.0) is False
