"""Ghi xác nhận tỉ lệ mét vào job đang chờ (CAS, một lần, đúng job/loại artifact)."""

from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry


def _waiting_job(root: Path) -> tuple[ProjectRegistry, object]:
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
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    job = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.RUNNING), expected_checksum=job.job_manifest_checksum
    )
    return registry, registry.record_stage_progress(job, StageId.METRIC_CANONICALIZE)


def _confirmation(
    registry: ProjectRegistry, job_id: str, artifact_type: str = "RGBMetricConfirmation"
) -> ProductArtifactRef:
    payload = b'{"status": "CONFIRMED"}'
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec06/abc/{artifact_type}.json",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    return reference


def test_confirmation_is_recorded_once(tmp_path: Path) -> None:
    registry, job = _waiting_job(tmp_path)
    reference = _confirmation(registry, job.job_id)
    updated = registry.record_metric_confirmation(job, reference)
    assert updated.status == JobStatus.RUNNING and updated.current_stage == StageId.METRIC_CANONICALIZE
    metric = [stage for stage in updated.stage_artifacts if stage.stage_id == StageId.METRIC_CANONICALIZE]
    assert metric[0].artifact_uri == reference.artifact_uri
    progress = job_progress(updated, registry.list_job_attempts(job.job_id), preview_ready=True)
    assert progress.waiting_for is None and progress.stages[-1].state == "succeeded"
    with pytest.raises(RuntimeStateConflictError):
        registry.record_metric_confirmation(updated, reference)


def test_stale_revision_and_foreign_artifacts_are_refused(tmp_path: Path) -> None:
    registry, job = _waiting_job(tmp_path)
    with pytest.raises(ValueError, match="không thuộc job"):
        registry.record_metric_confirmation(job, _confirmation(registry, job.job_id, "SomethingElse"))
    other = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED), expected_checksum=job.job_manifest_checksum
    )
    assert other.status == JobStatus.CANCELLED
    with pytest.raises((RuntimeStateConflictError, ValueError)):
        registry.record_metric_confirmation(job, _confirmation(registry, job.job_id))
