"""Regression persistence: fixture proof, không phải worker/GPU acceptance."""

from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus
from src.services.orchestration.artifacts import ArtifactChecksumError
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord, TransitionRequest
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry


def registry_at(root: Path) -> ProjectRegistry:
    """Mỗi instance có connection mới, dùng chung durable state."""
    return ProjectRegistry(
        runtime_root=root / "artifacts", database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}")
    )


def test_restart_retains_jobs_and_retry_history(tmp_path: Path) -> None:
    first = registry_at(tmp_path)
    first.seed_from_fixtures()
    job = first.create_job(JobCreateInput(project_id="project-fixture-001"))
    first.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    first.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.FAILED))
    second = registry_at(tmp_path)
    second.seed_from_fixtures()
    assert second.get_job(job.job_id).status == JobStatus.FAILED
    old_history = second.list_job_attempts(job.job_id)
    second.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.QUEUED))
    assert first.list_job_attempts(job.job_id)[:-1] == old_history
    assert first.list_job_attempts(job.job_id)[-1].attempt == 2
    assert len(second.list_jobs(job.project_id)) == 2


def test_stale_writer_cannot_replace_committed_job(tmp_path: Path) -> None:
    registry = registry_at(tmp_path)
    registry.seed_from_fixtures()
    initial = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    stale = registry.lifecycle.prepare(initial, TransitionRequest(target_status=JobStatus.CANCELLED))
    reference = registry.lifecycle.store.publish_manifest(stale)
    running = registry.transition_job(initial.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    event = JobAttemptRecord(
        attempt=1,
        status=stale.status,
        current_stage=stale.current_stage,
        recorded_at=stale.completed_at,
        job_manifest_uri=reference.artifact_uri,
        job_manifest_checksum=reference.artifact_checksum,
    )
    assert registry.persistence is not None
    with pytest.raises(RuntimeStateConflictError):
        registry.persistence.save_job(stale, reference, event, expected=initial)
    assert registry.get_job(initial.job_id) == running
    assert len(registry.list_job_attempts(initial.job_id)) == 2


def test_corrupt_manifest_is_not_replaced_with_fixture(tmp_path: Path) -> None:
    registry = registry_at(tmp_path)
    registry.seed_from_fixtures()
    history = registry.list_job_attempts("job-fixture-001")
    # Cố tình sửa payload test; production writer vẫn create-only.
    path = next((tmp_path / "artifacts").rglob("manifests/*.json"))
    path.write_bytes(b"{}")
    with pytest.raises(ArtifactChecksumError):
        registry_at(tmp_path).get_job("job-fixture-001")
    assert history[0].job_manifest_checksum is not None


def test_failed_transaction_rolls_back(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    with pytest.raises(RuntimeError, match="abort"):
        with database.transaction(write=True) as tx:
            tx.execute("INSERT INTO r2s_projects(project_id,payload) VALUES (?,?)", ("uncommitted", "{}"))
            raise RuntimeError("abort")
    with database.transaction() as tx:
        assert tx.execute("SELECT payload FROM r2s_projects").fetchall() == []
