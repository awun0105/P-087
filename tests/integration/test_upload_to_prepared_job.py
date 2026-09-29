"""Upload → project → job → worker prepare (REC CLI thật + FFmpeg) → JobManifest.

Fixture proof ở mức L5: prepare chạy qua process boundary thật; preview
COLMAP/Brush được thay bằng stub in-process nên không chứng minh GPU/3DGS.
"""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs import runner, worker_cli
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.dispatch import prepared_frame_reference
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects.models import (
    DataOrigin,
    JobCreateInput,
    SourceRightsAttestation,
    UploadProjectInput,
)
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.uploads import VideoUploadService

ROOT = Path(__file__).resolve().parents[2]


def _attestation(anonymized: bool = True) -> SourceRightsAttestation:
    return SourceRightsAttestation.model_construct(
        data_origin=DataOrigin.SELF_COLLECTED_NO_PII,
        declared_owner="Integration test",
        declared_purpose="Upload pipeline",
        rights_to_use_confirmed=True,
        anonymization_confirmed=anonymized,
        retention_acknowledged=True,
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    config = tmp_path / "processing.json"
    config.write_text(json.dumps({"colmap": {}, "brush": {}}))
    profile = ExecutionProfile(
        config_checksum="sha256:" + hashlib.sha256(config.read_bytes()).hexdigest(),
        runtime_manifest_checksum="sha256:" + "d" * 64,
        seed=None,
    )
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database, execution_profile=profile)
    settings = SimpleNamespace(
        artifact_s3_bucket=None,
        product_processing_config=config,
        product_worker_root=tmp_path / "workers",
        product_upload_quality_profile=ROOT / "configs/product/upload_quality_v1.json",
        product_target_frame_count=5,
        product_prepare_timeout_seconds=120,
        product_preview_timeout_seconds=120,
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_project_registry", lambda: registry)
    previews: list[str] = []

    def fake_preview(attempt: runner._Attempt, frames: object, profile: dict) -> object:
        previews.append(frames.artifact_uri)  # type: ignore[attr-defined]
        return attempt.job

    monkeypatch.setattr(runner, "_execute_preview", fake_preview)
    uploads = VideoUploadService(database, ArtifactResolver(tmp_path / "artifacts"), max_bytes=10_000_000)
    return SimpleNamespace(registry=registry, uploads=uploads, previews=previews, root=tmp_path)


def _queued_job(world: SimpleNamespace, anonymized: bool = True) -> str:
    video = world.root / "walk.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=2:size=64x48:rate=8", "-c:v", "mpeg4", str(video)],
        check=True,
    )  # fmt: skip
    pending = world.uploads.begin("walk.mp4")
    pending.publication.write(video.read_bytes())
    upload = world.uploads.finish(pending)
    request = UploadProjectInput.model_construct(
        upload_id=upload.upload_id, name="Walk", attestation=_attestation(anonymized)
    )
    project = world.registry.create_project_from_upload(upload, request, "self_attested")
    if not anonymized:
        return project.project_id
    return world.registry.create_job(JobCreateInput(project_id=project.project_id)).job_id


def test_worker_prepares_uploaded_video_then_hands_frames_to_preview(world: SimpleNamespace) -> None:
    job_id = _queued_job(world)
    assert worker_cli.dispatch_next(world.registry) is True
    job = world.registry.get_job(job_id)
    assert job.status == JobStatus.RUNNING and job.current_stage == StageId.CAMERA_POSE
    stages = [(stage.stage_id, stage.status) for stage in job.stage_artifacts]
    assert stages == [
        (StageId.INPUT_VALIDATE, "SUCCEEDED"),
        (StageId.PRIVACY_GATE, "SUCCEEDED"),
        (StageId.FRAME_EXTRACT, "SUCCEEDED"),
    ]
    frames = prepared_frame_reference(job)
    assert frames is not None and world.previews == [frames.artifact_uri]
    frame_set = json.loads(world.registry.runtime_resolver.require(frames).read_text())
    assert len(frame_set["frames"]) == 4  # 16 frame, target 5 → stride 4
    # Job RUNNING không bị dispatch lần nữa.
    assert worker_cli.dispatch_next(world.registry) is False


def test_prepare_failure_ends_attempt_with_stage_error(world: SimpleNamespace, monkeypatch) -> None:
    job_id = _queued_job(world)
    # Làm hỏng profile chất lượng → REC CLI trả lỗi setup (exit 2) → runner ghi FAILED.
    broken = world.root / "broken_profile.json"
    broken.write_text("{}")
    runner.get_settings().product_upload_quality_profile = broken
    with pytest.raises(RuntimeError, match="Prepare worker"):
        runner.run_video_job(job_id)
    job = world.registry.get_job(job_id)
    assert job.status == JobStatus.FAILED
    last = world.registry.list_job_attempts(job_id)[-1]
    assert last.error is not None and last.error.error_code == "PREVIEW_RUNNER_FAILED"
    assert world.previews == []


def test_project_without_anonymization_attestation_cannot_queue(world: SimpleNamespace) -> None:
    from src.services.orchestration.projects.errors import PrivacyGateBlockedError

    project_id = _queued_job(world, anonymized=False)
    with pytest.raises(PrivacyGateBlockedError):
        world.registry.create_job(JobCreateInput(project_id=project_id))
