"""T-040 bước 5: rebind job QUEUED chưa có stage sang runtime đang sống; finalize chỉ chạy trên đúng runtime."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import (
    JobManifest,
    JobStatus,
    RuntimeComponent,
    RuntimeComponentStatus,
    RuntimeManifest,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import JobAttemptRecord, RuntimeRebound
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.jobs.worker_cli import dispatch_next
from src.services.orchestration.jobs.worker_runtimes import publish
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry

_PROJECT = "project-fixture-001"
_CONFIG = "sha256:" + "c" * 64
_PLACEHOLDER = "sha256:" + "0" * 64
_NOW = datetime.now(UTC)


def _manifest(colmap: str) -> RuntimeManifest:
    draft = RuntimeManifest(
        schema_version="1.0",
        components={"colmap": RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=colmap)},
        runtime_manifest_checksum=_PLACEHOLDER,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum")


def _profile(manifest: RuntimeManifest) -> ExecutionProfile:
    return ExecutionProfile(
        config_checksum=_CONFIG,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=7,
    )


def _registry(root: Path, profile: ExecutionProfile) -> ProjectRegistry:
    registry = ProjectRegistry(
        runtime_root=root / "artifacts",
        database=RuntimeDatabase(f"sqlite:///{root / 'runtime.db'}"),
        execution_profile=profile,
    )
    registry.seed_from_fixtures()
    return registry


def _forbidden(*args: object, **kwargs: object) -> None:
    raise AssertionError("runner không được gọi")


def _stage(stage_id: StageId, artifact_type: str) -> StageArtifact:
    return StageArtifact(
        stage_id=stage_id,
        status=StageStatus.SUCCEEDED,
        artifact_type=artifact_type,
        artifact_uri=f"artifact://jobs/job-x/{stage_id.value.lower()}.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        completed_at=_NOW,
    )


def _publish_revision(registry: ProjectRegistry, job: JobManifest, **update: object) -> JobManifest:
    """Test seam: publish một revision QUEUED mới (giống producer thật ghi stage artifact)."""
    updated = with_canonical_checksum(job.model_copy(update=update), "job_manifest_checksum")
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


def _stale_runtime_and_live_worker(tmp_path: Path) -> tuple[ExecutionProfile, ExecutionProfile, RuntimeDatabase]:
    """Job tạo trên runtime X (đã mất worker); máy W đang sống và chạy được."""
    old = _manifest("3.8.0")
    new = _manifest("3.9.1")
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    publish(database, _profile(old), old, now=_NOW - timedelta(hours=2))
    publish(database, _profile(new), new)
    return _profile(old), _profile(new), database


def test_orphaned_queued_job_moves_to_the_live_worker_runtime(tmp_path: Path) -> None:
    old_profile, new_profile, _ = _stale_runtime_and_live_worker(tmp_path)
    job = _registry(tmp_path, old_profile).create_job(JobCreateInput(project_id=_PROJECT))
    worker = _registry(tmp_path, new_profile)

    assert dispatch_next(worker, runner=_forbidden, video_runner=_forbidden, finalize_runner=_forbidden) is True

    rebound = worker.get_job(job.job_id)
    assert rebound.runtime_manifest_checksum == new_profile.job_runtime_checksum
    assert rebound.job_manifest_checksum != job.job_manifest_checksum
    last = worker.list_job_attempts(job.job_id)[-1]
    assert last.runtime_rebound == RuntimeRebound(
        from_checksum=old_profile.job_runtime_checksum,
        to_checksum=new_profile.job_runtime_checksum,
        reason="no_live_worker",
    )


def test_job_is_left_alone_while_its_own_runtime_still_has_a_live_worker(tmp_path: Path) -> None:
    old_profile = _profile(_manifest("3.8.0"))
    job = _registry(tmp_path, old_profile).create_job(JobCreateInput(project_id=_PROJECT))
    new_profile = _profile(_manifest("3.9.1"))
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    publish(database, old_profile, _manifest("3.8.0"))
    publish(database, new_profile, _manifest("3.9.1"))
    worker = _registry(tmp_path, new_profile)

    assert dispatch_next(worker, runner=_forbidden, video_runner=_forbidden, finalize_runner=_forbidden) is False

    assert worker.get_job(job.job_id).runtime_manifest_checksum == old_profile.job_runtime_checksum


def test_job_with_stage_artifacts_is_never_rebound(tmp_path: Path) -> None:
    old_profile, new_profile, _ = _stale_runtime_and_live_worker(tmp_path)
    api = _registry(tmp_path, old_profile)
    job = api.create_job(JobCreateInput(project_id=_PROJECT))
    frames = _stage(StageId.FRAME_EXTRACT, "NormalizedRGBFrameSet")
    with_frames = _publish_revision(api, job, stage_artifacts=[frames])
    worker = _registry(tmp_path, new_profile)

    assert dispatch_next(worker, runner=_forbidden, video_runner=_forbidden, finalize_runner=_forbidden) is False

    assert worker.get_job(job.job_id).runtime_manifest_checksum == old_profile.job_runtime_checksum
    with pytest.raises(RuntimeStateConflictError, match="chưa có stage"):
        worker.rebind_job_runtime(with_frames, new_profile.job_runtime_checksum, reason="no_live_worker")


def test_rebind_uses_revision_cas(tmp_path: Path) -> None:
    old_profile, new_profile, _ = _stale_runtime_and_live_worker(tmp_path)
    job = _registry(tmp_path, old_profile).create_job(JobCreateInput(project_id=_PROJECT))
    worker = _registry(tmp_path, new_profile)

    worker.rebind_job_runtime(job, new_profile.job_runtime_checksum, reason="no_live_worker")
    with pytest.raises(RuntimeStateConflictError):
        worker.rebind_job_runtime(job, new_profile.job_runtime_checksum, reason="no_live_worker")


def test_persistence_refuses_a_runtime_change_without_a_rebind_event(tmp_path: Path) -> None:
    old_profile, new_profile, _ = _stale_runtime_and_live_worker(tmp_path)
    api = _registry(tmp_path, old_profile)
    job = api.create_job(JobCreateInput(project_id=_PROJECT))
    changed = with_canonical_checksum(
        job.model_copy(update={"runtime_manifest_checksum": new_profile.job_runtime_checksum}),
        "job_manifest_checksum",
    )
    reference = api.lifecycle.store.publish_manifest(changed)
    event = JobAttemptRecord(
        attempt=1,
        status=JobStatus.QUEUED,
        current_stage=changed.current_stage,
        recorded_at=datetime.now(UTC),
        job_manifest_uri=reference.artifact_uri,
        job_manifest_checksum=reference.artifact_checksum,
    )
    assert api.persistence is not None
    with pytest.raises(ValueError, match="không được thay"):
        api.persistence.save_job(changed, reference, event, expected=job)


def test_finalize_runs_only_on_a_worker_with_the_job_runtime(tmp_path: Path) -> None:
    old_profile, new_profile, _ = _stale_runtime_and_live_worker(tmp_path)
    api = _registry(tmp_path, old_profile)
    job = api.create_job(JobCreateInput(project_id=_PROJECT))
    confirmed = _stage(StageId.METRIC_CANONICALIZE, "RGBMetricConfirmation")
    _publish_revision(api, job, current_stage=StageId.METRIC_CANONICALIZE, stage_artifacts=[confirmed])
    finalized: list[str] = []

    def record_finalize(job_id: str, **_: object) -> None:
        finalized.append(job_id)

    other_worker = _registry(tmp_path, new_profile)
    assert dispatch_next(other_worker, finalize_runner=record_finalize) is False
    assert finalized == []

    matching_worker = _registry(tmp_path, old_profile)
    assert dispatch_next(matching_worker, finalize_runner=record_finalize) is True
    assert finalized == [job.job_id]
