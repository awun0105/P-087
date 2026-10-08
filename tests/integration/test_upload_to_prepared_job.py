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
        product_upload_quality_profile=ROOT / "configs/product/upload_quality_v2.json",
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


# ── Job có gói LiDAR (ADR 0009) ─────────────────────────────────────────────────────────────────


def _lidar_package(root, floor_offset: float = 0.0) -> bytes:  # noqa: ANN001
    """Gói đám mây đã đăng ký: sàn 6 × 6 m ngay dưới quỹ đạo (hoặc lệch xa `floor_offset` mét để gói hỏng)."""
    import io
    import zipfile

    import numpy as np

    from src.services.reconstruction.lidar.fusion import ply_bytes

    grid = np.stack(np.meshgrid(np.arange(-3, 3, 0.05), np.arange(-3, 3, 0.05)), axis=-1).reshape(-1, 2)
    cloud = np.column_stack([grid + floor_offset, np.zeros(len(grid))])
    calibration = "".join(
        f"T_cam1_os.{key}: {value}\n"
        for key, value in zip("px py pz qx qy qz qw".split(), "0 0 0 0 0 0 1".split(), strict=True)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("map.ply", ply_bytes(cloud))
        archive.writestr("traj.txt", "".join(f"{i * 0.125} {i * 0.1} 0 1.0 0 0 0 1\n" for i in range(16)))
        archive.writestr("calibrations.txt", calibration)
        archive.writestr("frame_times.txt", "".join(f"{i * 0.125}\n" for i in range(16)))
    return buffer.getvalue()


def _queued_lidar_job(world: SimpleNamespace, package: bytes) -> str:
    from src.services.orchestration.projects.models import LidarAttachment

    video = world.root / "walk.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=2:size=64x48:rate=8", "-c:v", "mpeg4", str(video)],
        check=True,
    )  # fmt: skip
    records = []
    for name, payload in (("walk.mp4", video.read_bytes()), ("lidar.zip", package)):
        pending = world.uploads.begin(name)
        pending.publication.write(payload)
        records.append(world.uploads.finish(pending))
    upload, lidar = records
    assert lidar.input_kind == "registered_lidar"
    request = UploadProjectInput.model_construct(
        upload_id=upload.upload_id,
        name="Walk + LiDAR",
        attestation=_attestation(True),
        lidar=LidarAttachment(upload_id=lidar.upload_id, trajectory_origin="estimated", same_scene_confirmed=True),
    )
    project = world.registry.create_project_from_upload(upload, request, "self_attested", lidar)
    return world.registry.create_job(JobCreateInput(project_id=project.project_id)).job_id


def test_worker_ingests_the_lidar_package_before_camera_pose(world: SimpleNamespace) -> None:
    from src.services.orchestration.jobs.progress import job_progress
    from src.services.reconstruction import LidarPackageRecord

    job_id = _queued_lidar_job(world, _lidar_package(world.root))
    assert worker_cli.dispatch_next(world.registry) is True
    job = world.registry.get_job(job_id)
    assert job.status == JobStatus.RUNNING and job.current_stage == StageId.CAMERA_POSE
    assert [(stage.stage_id, stage.status) for stage in job.stage_artifacts][-1] == (StageId.LIDAR_INGEST, "SUCCEEDED")
    stage = job.stage_artifacts[-1]
    resolver = world.registry.runtime_resolver
    record = LidarPackageRecord.model_validate_json(
        resolver.require_uri(stage.artifact_uri, stage.artifact_checksum).read_bytes()
    )
    assert record.kind == "registered_lidar" and record.trajectory_origin == "estimated"
    assert record.floor_z_m == pytest.approx(0.0, abs=0.02) and record.pose_count == 16
    assert len(world.previews) == 1  # LiDAR xong mới sang dựng pose camera
    progress = job_progress(job, world.registry.list_job_attempts(job_id), preview_ready=False)
    ids = [item.stage_id for item in progress.stages]
    assert ids.index(StageId.LIDAR_INGEST) == ids.index(StageId.FRAME_EXTRACT) + 1
    assert next(item for item in progress.stages if item.stage_id == StageId.LIDAR_INGEST).state == "succeeded"


def test_broken_lidar_package_stops_the_job_before_gpu_work(world: SimpleNamespace) -> None:
    """Quỹ đạo không nằm trên đám mây: job dừng ở bước LiDAR với lý do rõ, không chạy tiếp như job chỉ có video."""
    job_id = _queued_lidar_job(world, _lidar_package(world.root, floor_offset=500.0))
    assert worker_cli.dispatch_next(world.registry) is True
    job = world.registry.get_job(job_id)
    assert job.status == JobStatus.FAILED and job.current_stage == StageId.LIDAR_INGEST
    failed = job.stage_artifacts[-1]
    assert failed.error is not None and failed.error.error_code == "LIDAR_PACKAGE_INVALID"
    assert "Không tìm thấy mặt sàn dưới quỹ đạo" in failed.error.human_message
    assert world.previews == []


def test_video_only_job_has_no_lidar_stage(world: SimpleNamespace) -> None:
    from src.services.orchestration.jobs.progress import job_progress

    job_id = _queued_job(world)
    assert worker_cli.dispatch_next(world.registry) is True
    job = world.registry.get_job(job_id)
    assert all(stage.stage_id != StageId.LIDAR_INGEST for stage in job.stage_artifacts)
    progress = job_progress(job, world.registry.list_job_attempts(job_id), preview_ready=False)
    assert StageId.LIDAR_INGEST not in [item.stage_id for item in progress.stages]
