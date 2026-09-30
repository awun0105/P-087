"""Bước hoàn tất EX-REC phía PRODUCT: điều kiện nhận job, định tuyến queue, ghi kết quả (CAS)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, JobStatus, StageArtifact, StageId, StageStatus
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.progress import awaiting_finalize, job_progress
from src.services.orchestration.jobs.worker_cli import dispatch_next
from src.services.reconstruction import FinalizeResult
from tests.test_orchestration.test_metric_confirmation_record import _confirmation, _waiting_job


def _publish(registry, job_id: str, name: str, artifact_type: str, stage: StageId) -> ProductArtifactRef:  # noqa: ANN001
    payload = f'{{"name": "{name}"}}'.encode()
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/finalize-test/{name}",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    return reference


def _confirmed(tmp_path: Path):  # noqa: ANN202
    registry, job = _waiting_job(tmp_path)
    confirmation = _confirmation(registry, job.job_id)
    return registry, registry.record_metric_confirmation(job, confirmation), confirmation


def _stage(reference: ProductArtifactRef, stage: StageId) -> StageArtifact:
    return StageArtifact(
        stage_id=stage,
        status=StageStatus.SUCCEEDED,
        completed_at=datetime.now(UTC),
        artifact_type=reference.artifact_type,
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        data_class=reference.data_class,
    )


def test_confirmed_job_waits_for_finalize_and_not_before(tmp_path: Path) -> None:
    registry, waiting = _waiting_job(tmp_path)
    assert not awaiting_finalize(waiting)  # chưa xác nhận
    confirmed = registry.record_metric_confirmation(waiting, _confirmation(registry, waiting.job_id))
    assert awaiting_finalize(confirmed)
    claimed = registry.record_stage_progress(confirmed, StageId.RGB_GEOMETRY)
    assert not awaiting_finalize(claimed)  # đã có worker nhận


def test_success_records_geometry_and_bundle_and_closes_job(tmp_path: Path) -> None:
    registry, job, confirmation = _confirmed(tmp_path)
    job = registry.record_stage_progress(job, StageId.RGB_GEOMETRY)
    geometry = _publish(registry, job.job_id, "collision.glb", "RgbGeometry", StageId.RGB_GEOMETRY)
    bundle = _publish(registry, job.job_id, "bundle.json", "ReconstructionBundle", StageId.METRIC_CANONICALIZE)
    result_ref = _publish(registry, job.job_id, "result.json", "RecFinalizeResult", StageId.METRIC_CANONICALIZE)
    result = FinalizeResult(
        job_id=job.job_id,
        attempt_id="finalize-1",
        confirmation_ref=confirmation,
        geometry_ref=geometry,
        bundle_ref=bundle,
        stage_artifacts=[_stage(geometry, StageId.RGB_GEOMETRY), _stage(bundle, StageId.METRIC_CANONICALIZE)],
    )
    done = registry.record_finalize(job, result, result_ref)
    assert done.status == JobStatus.SUCCEEDED and done.completed_at is not None
    assert not awaiting_finalize(done)
    progress = job_progress(done, registry.list_job_attempts(job.job_id), preview_ready=True)
    states = {stage.stage_id: stage.state for stage in progress.stages}
    assert states[StageId.RGB_GEOMETRY] == "succeeded"
    # Không có artifact tách vật thể → stage đó không được báo xong.
    assert states[StageId.OBJECT_EXTRACT] == "pending"
    with pytest.raises((RuntimeStateConflictError, ValueError)):
        registry.record_finalize(job, result, result_ref)  # revision cũ: CAS từ chối


def test_failure_then_retry_resumes_finalize_only(tmp_path: Path) -> None:
    registry, job, confirmation = _confirmed(tmp_path)
    job = registry.record_stage_progress(job, StageId.RGB_GEOMETRY)
    result_ref = _publish(registry, job.job_id, "result.json", "RecFinalizeResult", StageId.METRIC_CANONICALIZE)
    error = ExecutionError(
        stage_id=StageId.RGB_GEOMETRY, error_code="REC_FINALIZE_FAILED", human_message="lỗi", retryable=False
    )
    result = FinalizeResult(job_id=job.job_id, attempt_id="finalize-1", confirmation_ref=confirmation, error=error)
    failed = registry.record_finalize(job, result, result_ref)
    assert failed.status == JobStatus.FAILED and failed.current_stage == StageId.RGB_GEOMETRY
    queued = registry.transition_job(
        failed.job_id, TransitionRequest(target_status=JobStatus.QUEUED), expected_checksum=failed.job_manifest_checksum
    )
    assert awaiting_finalize(queued)  # retry: chỉ chạy lại bước hoàn tất, giữ preview + xác nhận

    calls: list[str] = []

    def unexpected(*_: object, **__: object) -> None:
        raise AssertionError("retry sau lỗi hoàn tất không được dựng lại preview")

    def finalize(job_id: str, *, expected_checksum: str) -> None:
        calls.append(job_id)

    assert dispatch_next(registry, runner=unexpected, video_runner=unexpected, finalize_runner=finalize)
    assert calls == [queued.job_id]

    # Worker nhận lại (QUEUED → RUNNING ở hình học): các bước trước vẫn hiện đã xong.
    resumed = registry.transition_job(
        queued.job_id,
        TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.RGB_GEOMETRY),
        expected_checksum=queued.job_manifest_checksum,
    )
    progress = job_progress(resumed, registry.list_job_attempts(resumed.job_id), preview_ready=True)
    states = {stage.stage_id: stage.state for stage in progress.stages}
    assert states[StageId.METRIC_CANONICALIZE] == "succeeded" and states[StageId.RGB_GEOMETRY] == "running"


def test_dispatch_routes_confirmed_running_job_to_finalize(tmp_path: Path) -> None:
    registry, job, confirmation = _confirmed(tmp_path)
    calls: list[tuple[str, str]] = []

    def finalize(job_id: str, *, expected_checksum: str) -> None:
        calls.append((job_id, expected_checksum))

    def unexpected(*_: object, **__: object) -> None:
        raise AssertionError("job đã xác nhận không được đi vào preview/prepare")

    assert dispatch_next(registry, runner=unexpected, video_runner=unexpected, finalize_runner=finalize)
    assert calls == [(job.job_id, job.job_manifest_checksum)]
