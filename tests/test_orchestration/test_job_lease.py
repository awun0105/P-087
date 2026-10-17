"""T-040 bước 6: lease theo job có fencing; lease hết hạn đưa job RUNNING về FAILED retryable."""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.lease import (
    LEASE_TTL,
    HeldLease,
    acquire,
    expired_job_ids,
    lease_lost,
    leased,
    release,
    renew,
)
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.worker_cli import recover_expired_leases
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_PROJECT = "project-fixture-001"
_T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def _registry(root: Path) -> ProjectRegistry:
    probe = ProjectRegistry(runtime_root=root / "artifacts")
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
    )
    registry.seed_from_fixtures()
    return registry


def _running_job(registry: ProjectRegistry):  # noqa: ANN202
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    return registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))


def test_live_lease_refuses_another_worker_and_an_expired_one_is_taken(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")

    assert acquire(database, "job-a", "worker-1", now=_T0) is not None
    assert acquire(database, "job-a", "worker-2", now=_T0 + timedelta(minutes=5)) is None

    after_expiry = _T0 + LEASE_TTL + timedelta(seconds=1)
    assert acquire(database, "job-a", "worker-2", now=after_expiry) is not None
    assert expired_job_ids(database, now=after_expiry) == []


def test_renew_extends_only_the_holder_token(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    held = acquire(database, "job-a", "worker-1", now=_T0)
    assert held is not None

    assert renew(database, held, now=_T0 + timedelta(minutes=9))
    assert expired_job_ids(database, now=_T0 + timedelta(minutes=11)) == []
    assert expired_job_ids(database, now=_T0 + timedelta(minutes=20)) == ["job-a"]
    assert not renew(database, HeldLease(job_id="job-a", token="someone-else"), now=_T0 + timedelta(minutes=9))


def test_expired_lease_fails_the_running_job_as_retryable_on_another_worker(tmp_path: Path) -> None:
    owner = _registry(tmp_path)
    job = _running_job(owner)
    assert acquire(owner.persistence.database, job.job_id, "worker-a", now=_T0) is not None
    survivor = _registry(tmp_path)

    recovered = recover_expired_leases(survivor, now=_T0 + LEASE_TTL + timedelta(seconds=1))

    assert recovered == 1
    failed = survivor.get_job(job.job_id)
    assert failed.status == JobStatus.FAILED
    error = survivor.list_job_attempts(job.job_id)[-1].error
    assert error is not None and error.retryable is True
    assert recover_expired_leases(survivor, now=_T0 + LEASE_TTL + timedelta(seconds=2)) == 0


def test_worker_that_lost_its_lease_cannot_write_revisions(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    database = registry.persistence.database

    with leased(database, job.job_id, "worker-a") as held:
        assert held is not None
        release(database, held)
        assert acquire(database, job.job_id, "worker-b", now=datetime.now(UTC) + timedelta(hours=1)) is not None
        with pytest.raises(RuntimeStateConflictError, match="Lease"):
            registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
        assert held.lost.is_set()

    assert registry.get_job(job.job_id).status == JobStatus.QUEUED


def test_renewal_keeps_a_running_attempt_alive_past_the_plain_ttl(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")

    with leased(database, "job-a", "worker-a", renew_every=0.05, ttl=timedelta(seconds=1)) as held:
        assert held is not None
        time.sleep(1.5)
        assert not held.lost.is_set()
        assert expired_job_ids(database) == []


def test_lease_is_released_when_the_attempt_ends(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")

    with leased(database, "job-a", "worker-a") as held:
        assert held is not None

    assert acquire(database, "job-a", "worker-b") is not None


def test_lost_flag_is_visible_only_to_the_attempt_holding_that_job(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")

    with leased(database, "job-a", "worker-a") as held:
        assert held is not None
        assert not lease_lost("job-a")
        held.lost.set()  # renewal đã thất bại: vòng theo dõi tool của runner phải thấy điều này
        assert lease_lost("job-a")
        assert not lease_lost("job-b")
