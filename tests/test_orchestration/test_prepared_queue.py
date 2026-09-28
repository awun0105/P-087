"""Regression cho basic durable queue: fixture proof, không phải GPU/runtime acceptance.

Runner giả lập thay cho `run_prepared_job` để kiểm policy claim/skip/failure mà
không chạy COLMAP/Brush.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact, StageId, StageStatus
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import prepared_frame_reference, require_profile
from src.services.orchestration.jobs.models import JobAttemptRecord, TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.worker_cli import dispatch_next
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry, with_canonical_checksum

_PROJECT = "project-fixture-001"


def _registry(root: Path, profile: ExecutionProfile | None = None) -> ProjectRegistry:
    """Registry durable với profile khớp fixture project, trừ khi test truyền profile khác."""
    probe = ProjectRegistry(runtime_root=root / "artifacts")
    matching = ExecutionProfile(
        config_checksum=probe._fixture_config_checksum(),
        runtime_manifest_checksum=probe._fixture_runtime_checksum(),
        seed=7,
    )
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=profile or matching,
    )
    registry.seed_from_fixtures()
    return registry


def _frame_stage(job_id: str, suffix: str = "a") -> StageArtifact:
    return StageArtifact(
        stage_id=StageId.FRAME_EXTRACT,
        status=StageStatus.SUCCEEDED,
        artifact_type="NormalizedRGBFrameSet",
        artifact_uri=f"artifact://jobs/{job_id}/rec02a/frame_set.json",
        artifact_checksum="sha256:" + suffix * 64,
        data_class="derived",
        completed_at=datetime.now(UTC),
    )


def _attach_frames(registry: ProjectRegistry, job: JobManifest, *stages: StageArtifact) -> JobManifest:
    """Test seam: publish revision QUEUED có frame set, giống producer prepare-input sau này."""
    updated = with_canonical_checksum(
        job.model_copy(update={"stage_artifacts": [*job.stage_artifacts, *stages]}), "job_manifest_checksum"
    )
    reference = registry.lifecycle.store.publish_manifest(updated)
    event = JobAttemptRecord(
        attempt=1,
        status=updated.status,
        current_stage=updated.current_stage,
        recorded_at=datetime.now(UTC),
        job_manifest_uri=reference.artifact_uri,
        job_manifest_checksum=reference.artifact_checksum,
    )
    assert registry.persistence is not None
    registry.persistence.save_job(updated, reference, event, expected=job)
    return updated


class _Runner:
    """Ghi lại lời gọi; có thể ném lỗi để kiểm failure path trước claim."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.error = error

    def __call__(self, job_id: str, frame_set_uri: str, *, expected_checksum: str) -> JobManifest:
        self.calls.append((job_id, frame_set_uri, expected_checksum))
        if self.error is not None:
            raise self.error
        raise AssertionError("fake runner chỉ dùng cho policy test")


def test_prepared_frame_reference_requires_single_namespaced_frame_set(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    assert prepared_frame_reference(job) is None
    with_frames = job.model_copy(update={"stage_artifacts": [_frame_stage(job.job_id)]})
    reference = prepared_frame_reference(with_frames)
    assert reference is not None and reference.job_id == job.job_id
    duplicate = job.model_copy(update={"stage_artifacts": [_frame_stage(job.job_id), _frame_stage(job.job_id)]})
    assert prepared_frame_reference(duplicate) == reference
    conflicting = job.model_copy(update={"stage_artifacts": [_frame_stage(job.job_id), _frame_stage(job.job_id, "b")]})
    with pytest.raises(ValueError, match="nhiều frame set"):
        prepared_frame_reference(conflicting)
    foreign = job.model_copy(update={"stage_artifacts": [_frame_stage("job-other")]})
    with pytest.raises(ValueError, match="namespace"):
        prepared_frame_reference(foreign)


def test_require_profile_rejects_non_queued_and_foreign_profile(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    assert registry.execution_profile is not None
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    require_profile(job, registry.execution_profile)
    foreign = registry.execution_profile.model_copy(update={"seed": 99})
    with pytest.raises(RuntimeStateConflictError, match="execution profile"):
        require_profile(job, foreign)
    running = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    with pytest.raises(RuntimeStateConflictError, match="QUEUED"):
        require_profile(running, registry.execution_profile)


def test_transition_with_stale_expected_checksum_is_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    running = registry.transition_job(
        job.job_id,
        TransitionRequest(target_status=JobStatus.RUNNING),
        expected_checksum=job.job_manifest_checksum,
    )
    with pytest.raises(RuntimeStateConflictError):
        registry.transition_job(
            job.job_id,
            TransitionRequest(target_status=JobStatus.CANCELLED),
            expected_checksum=job.job_manifest_checksum,
        )
    assert registry.get_job(job.job_id) == running


def test_job_ids_after_pages_in_order(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    for _ in range(3):
        registry.create_job(JobCreateInput(project_id=_PROJECT))
    assert registry.persistence is not None
    every = registry.persistence.job_ids_after(limit=1000)
    assert every == sorted(every) and len(every) >= 3
    assert registry.persistence.job_ids_after(every[0], limit=2) == every[1:3]
    with pytest.raises(ValueError):
        registry.persistence.job_ids_after(limit=0)


def test_dispatch_skips_jobs_without_prepared_frames(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = registry.create_job(JobCreateInput(project_id=_PROJECT))
    runner = _Runner()
    assert dispatch_next(registry, runner) is False
    assert runner.calls == []
    assert registry.get_job(job.job_id).status == JobStatus.QUEUED


def test_dispatch_skips_jobs_of_another_profile(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _attach_frames(registry, registry.create_job(JobCreateInput(project_id=_PROJECT)), _frame_stage("x"))
    assert registry.execution_profile is not None
    other = _registry(tmp_path, registry.execution_profile.model_copy(update={"seed": 99}))
    runner = _Runner()
    assert dispatch_next(other, runner) is False
    assert runner.calls == []
    assert other.get_job(job.job_id).status == JobStatus.QUEUED


def test_dispatch_passes_exact_revision_to_runner(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    created = registry.create_job(JobCreateInput(project_id=_PROJECT))
    job = _attach_frames(registry, created, _frame_stage(created.job_id))
    runner = _Runner(error=RuntimeStateConflictError("runner khác đã claim"))
    assert dispatch_next(registry, runner) is False
    assert runner.calls == [
        (job.job_id, f"artifact://jobs/{job.job_id}/rec02a/frame_set.json", job.job_manifest_checksum)
    ]
    assert registry.get_job(job.job_id).status == JobStatus.QUEUED


def test_dispatch_failure_before_claim_is_recorded_on_job(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    created = registry.create_job(JobCreateInput(project_id=_PROJECT))
    job = _attach_frames(registry, created, _frame_stage(created.job_id))
    assert dispatch_next(registry, _Runner(error=ValueError("frame set thiếu payload"))) is True
    failed = registry.get_job(job.job_id)
    assert failed.status == JobStatus.FAILED
    last = registry.list_job_attempts(job.job_id)[-1]
    assert last.error is not None and last.error.error_code == "PREPARED_DISPATCH_FAILED"
    # Job FAILED không được queue lấy lại khi chưa retry.
    runner = _Runner()
    assert dispatch_next(registry, runner) is False
    assert runner.calls == []
