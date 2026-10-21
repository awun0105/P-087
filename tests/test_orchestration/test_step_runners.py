"""T-073: bước hình học và bước tách vật là hai lượt chạy riêng; bước chuẩn bị dừng đúng chỗ cho bước sau."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.config import Settings
from src.models.contracts.manifests import ExecutionError, JobStatus, StageArtifact, StageId, StageStatus
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.models import PreparedInputReceipt, TransitionRequest
from src.services.orchestration.jobs.progress import (
    awaiting_anonymization_review,
    awaiting_pose_step,
    awaiting_scene_extract,
)
from src.services.orchestration.jobs.steps import ready_view_lods
from src.services.orchestration.projects.models import JobCreateInput
from src.services.reconstruction import FinalizeResult
from tests.test_orchestration.test_anonymization_review import _publish as _publish_frames
from tests.test_orchestration.test_finalize_flow import _confirmed, _publish, _stage
from tests.test_orchestration.test_prepared_queue import _registry


def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, failed: bool = False):  # noqa: ANN202
    """Job đã xác nhận tỉ lệ; `finalize_cli` giả trả kết quả REC thật (đi qua reducer thật của registry)."""
    registry, job, confirmation = _confirmed(tmp_path / "runtime")
    settings = Settings(product_worker_root=tmp_path / "workers")
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_project_registry", lambda: registry)
    monkeypatch.setattr(runner, "_authorized_decision", lambda *args: (confirmation, "sha256:" + "a" * 64))
    monkeypatch.setattr(runner, "_record_benchmark", lambda attempt: None)
    geometry = _publish(registry, job.job_id, "collision.glb", "RgbGeometry", StageId.RGB_GEOMETRY)
    bundle = _publish(registry, job.job_id, "bundle.json", "ReconstructionBundle", StageId.METRIC_CANONICALIZE)
    result_ref = _publish(registry, job.job_id, "result.json", "RecFinalizeResult", StageId.METRIC_CANONICALIZE)
    monkeypatch.setattr(
        runner, "_run_tool", lambda *args: (int(failed), {"result_ref": result_ref.model_dump(mode="json")})
    )

    def result(*args: object) -> FinalizeResult:
        attempt_id = next((tmp_path / "workers" / job.job_id).glob("finalize-*")).name
        if failed:
            error = ExecutionError(
                stage_id=StageId.RGB_GEOMETRY, error_code="REC_FINALIZE_FAILED", human_message="lỗi", retryable=True
            )
            return FinalizeResult(job_id=job.job_id, attempt_id=attempt_id, confirmation_ref=confirmation, error=error)
        return FinalizeResult(
            job_id=job.job_id,
            attempt_id=attempt_id,
            confirmation_ref=confirmation,
            geometry_ref=geometry,
            bundle_ref=bundle,
            stage_artifacts=[_stage(geometry, StageId.RGB_GEOMETRY), _stage(bundle, StageId.METRIC_CANONICALIZE)],
        )

    monkeypatch.setattr(runner, "load_finalize_result", result)
    return registry, job, bundle


def test_geometry_step_stops_with_the_bundle_and_the_scene_step_closes_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, bundle = _world(tmp_path, monkeypatch)

    def unexpected(*args: object) -> list:
        raise AssertionError("bước hình học không được tách vật (đó là bước GPU riêng)")

    monkeypatch.setattr(runner, "_extract_scene_stage", unexpected)
    geometry = runner.run_geometry_step(job.job_id, expected_checksum=job.job_manifest_checksum)
    assert geometry.status == JobStatus.RUNNING and geometry.current_stage == StageId.RGB_GEOMETRY
    assert awaiting_scene_extract(geometry) and registry.get_job(job.job_id) == geometry

    seen: list[str] = []

    def scene(attempt: runner._Attempt, workspace: Path, reference: object) -> list[StageArtifact]:
        assert attempt.job.current_stage == StageId.OBJECT_EXTRACT  # đã claim bằng CAS
        seen.append(reference.artifact_uri)  # type: ignore[attr-defined]
        return [_stage(bundle, StageId.OBJECT_EXTRACT)]

    monkeypatch.setattr(runner, "_extract_scene_stage", scene)
    done = runner.run_scene_step(job.job_id, expected_checksum=geometry.job_manifest_checksum)
    assert done.status == JobStatus.SUCCEEDED and done.current_stage == StageId.OBJECT_EXTRACT
    assert seen == [bundle.artifact_uri]
    assert registry.persistence is not None and ready_view_lods(registry.persistence.database) == [job.job_id]
    with pytest.raises(runner.RuntimeStateConflictError):
        runner.run_scene_step(job.job_id)  # job đã xong: không ai nhận lại bước tách vật


def test_failed_scene_extraction_still_finishes_the_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, _ = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_extract_scene_stage", lambda *args: [])
    runner.run_geometry_step(job.job_id)
    done = runner.run_scene_step(job.job_id)
    assert done.status == JobStatus.SUCCEEDED and done.current_stage == StageId.RGB_GEOMETRY


def test_geometry_failure_fails_the_job_like_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, _ = _world(tmp_path, monkeypatch, failed=True)
    failed = runner.run_geometry_step(job.job_id)
    assert failed.status == JobStatus.FAILED and not awaiting_scene_extract(failed)


def test_interrupted_scene_step_retries_only_object_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, bundle = _world(tmp_path, monkeypatch)
    geometry = runner.run_geometry_step(job.job_id)

    def interrupted(*args: object) -> list:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_extract_scene_stage", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run_scene_step(job.job_id, expected_checksum=geometry.job_manifest_checksum)
    failed = registry.get_job(job.job_id)
    assert failed.status == JobStatus.FAILED and failed.current_stage == StageId.OBJECT_EXTRACT
    queued = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.QUEUED), expected_checksum=failed.job_manifest_checksum
    )
    assert awaiting_scene_extract(queued)
    monkeypatch.setattr(runner, "_extract_scene_stage", lambda *args: [_stage(bundle, StageId.OBJECT_EXTRACT)])
    done = runner.run_scene_step(job.job_id, expected_checksum=queued.job_manifest_checksum)
    assert done.status == JobStatus.SUCCEEDED


def test_geometry_failure_right_after_claim_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, _ = _world(tmp_path, monkeypatch)

    def broken(*args: object) -> str:
        raise OSError("disk unavailable")

    monkeypatch.setattr(runner, "_attempt_log_id", broken)
    with pytest.raises(OSError):
        runner.run_geometry_step(job.job_id)
    error = registry.list_job_attempts(job.job_id)[-1].error
    assert registry.get_job(job.job_id).status == JobStatus.FAILED
    assert error is not None and error.stage_id == StageId.RGB_GEOMETRY


def test_successful_prepare_stops_at_frame_extract_and_redacted_frames_wait_for_review(tmp_path: Path) -> None:
    """Trước đây job dừng ở ST-CAMERA-POSE nên bước chờ người dùng duyệt bản đã che bị bỏ qua (AUD-18)."""
    for sanitized in (False, True):
        registry = _registry(tmp_path / str(sanitized))
        job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
        job = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
        path = "rec02a/sanitized/frame_set.json" if sanitized else "rec02a/frame_set.json"
        frames = _publish_frames(registry, job.job_id, path, "NormalizedRGBFrameSet", StageId.FRAME_EXTRACT)
        stage = StageArtifact(
            stage_id=StageId.FRAME_EXTRACT,
            status=StageStatus.SUCCEEDED,
            completed_at=datetime.now(UTC),
            artifact_type=frames.artifact_type,
            artifact_uri=frames.artifact_uri,
            artifact_checksum=frames.artifact_checksum,
            data_class=frames.data_class,
        )
        receipt = PreparedInputReceipt(
            job_id=job.job_id,
            input_manifest_checksum=job.input_manifest_checksum,
            stage_artifacts=[stage],
            frame_set_ref=frames,
            extracted_frame_count=4,
        )
        prepared = registry.record_prepared_input(job, receipt)
        assert prepared.status == JobStatus.RUNNING and prepared.current_stage == StageId.FRAME_EXTRACT
        assert awaiting_anonymization_review(prepared) is sanitized
        assert awaiting_pose_step(prepared) is not sanitized
