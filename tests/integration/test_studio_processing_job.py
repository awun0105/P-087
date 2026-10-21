"""Job Studio mang cấu hình riêng: worker đọc artifact config, validate theo file chung.

Prepare chạy REC CLI thật (FFmpeg) qua subprocess; preview COLMAP/Brush là stub.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import JobStatus
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs import runner, worker_cli
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.processing import build_job_config, job_config_reference, load_presets, preset_values
from src.services.orchestration.projects.models import (
    DataOrigin,
    JobCreateInput,
    SourceRightsAttestation,
    UploadProjectInput,
)
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.uploads import VideoUploadService

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ROOT / "configs/product/processing_presets_v1.json"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    presets, presets_checksum = load_presets(PRESETS)
    profile = ExecutionProfile(
        config_checksum=presets_checksum, runtime_manifest_checksum="sha256:" + "d" * 64, seed=None
    )
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database, execution_profile=profile)
    settings = SimpleNamespace(
        artifact_s3_bucket=None,
        product_processing_config=PRESETS,
        product_worker_root=tmp_path / "workers",
        product_upload_quality_profile=ROOT / "configs/product/upload_quality_v2.json",
        product_target_frame_count=240,
        product_prepare_timeout_seconds=120,
        product_preview_timeout_seconds=120,
    )
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_project_registry", lambda: registry)
    calls: list[dict] = []

    def fake_preview(attempt: runner._Attempt, frames: object, resolved: object) -> object:
        calls.append({"frames": frames, "resolved": resolved})
        return attempt.job

    monkeypatch.setattr(runner, "_execute_preview", fake_preview)
    video = tmp_path / "walk.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=4:size=64x48:rate=10", "-c:v", "mpeg4", str(video)],
        check=True,
    )  # fmt: skip
    uploads = VideoUploadService(database, ArtifactResolver(tmp_path / "artifacts"), max_bytes=10_000_000)
    pending = uploads.begin("walk.mp4")
    pending.publication.write(video.read_bytes())
    upload = uploads.finish(pending)
    attestation = SourceRightsAttestation(
        data_origin=DataOrigin.SELF_COLLECTED_NO_PII,
        declared_owner="Integration",
        declared_purpose="Studio processing",
        rights_to_use_confirmed=True,
        anonymization_confirmed=True,
        retention_acknowledged=True,
    )
    project = registry.create_project_from_upload(
        upload, UploadProjectInput(upload_id=upload.upload_id, name="Walk", attestation=attestation), "self_attested"
    )
    return SimpleNamespace(
        registry=registry, presets=presets, checksum=presets_checksum, project=project, calls=calls, root=tmp_path
    )


def test_job_config_drives_sampling_and_tool_configs(world: SimpleNamespace) -> None:
    params = preset_values(world.presets, "minimum_quality")
    params.update({"sampling.sample_fps": 1.0, "sampling.max_frames": 30, "brush.total_train_iters": 5000})
    config = build_job_config(world.presets, world.checksum, params, None)
    job = world.registry.create_job(JobCreateInput(project_id=world.project.project_id), config)
    stored = world.registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
    assert json.loads(stored.read_text())["params"]["brush.total_train_iters"] == 5000
    assert worker_cli.dispatch_next(world.registry) is True
    running = world.registry.get_job(job.job_id)
    assert running.status == JobStatus.RUNNING
    frame_set = next(stage for stage in running.stage_artifacts if stage.stage_id == "ST-FRAME-EXTRACT")
    frames = json.loads(world.registry.runtime_resolver.resolve(frame_set.artifact_uri).read_text())["frames"]
    assert len(frames) == 4  # 40 frame, 3,9 s × 1 fps → 4 frame
    assert world.calls == []  # T-073: bước chuẩn bị xong; bước dựng camera là lượt nhận riêng
    assert worker_cli.dispatch_next(world.registry) is True
    resolved = world.calls[0]["resolved"]
    assert (
        resolved.brush["total_train_iters"] == 5000 and resolved.colmap["max_image_size"] == 1280
    )  # sàn mới của bảng A5 (T-071)
    assert resolved.sample_fps == 1.0 and resolved.max_frames == 30


def test_tampered_or_out_of_bounds_config_is_not_run(world: SimpleNamespace) -> None:
    params = preset_values(world.presets, "minimum_quality")
    config = build_job_config(world.presets, world.checksum, params, None)
    job = world.registry.create_job(JobCreateInput(project_id=world.project.project_id), config)
    # Ghi đè artifact (mô phỏng sửa tay): checksum khác JobManifest → không resolve.
    path = world.registry.runtime_resolver.resolve(f"artifact://jobs/{job.job_id}/config/processing.json")
    tampered = json.loads(path.read_text())
    tampered["params"]["brush.max_splats"] = 999_000_000
    path.write_text(json.dumps(tampered))
    assert worker_cli.dispatch_next(world.registry) is True
    failed = world.registry.get_job(job.job_id)
    assert failed.status == JobStatus.FAILED
    assert world.calls == []


def test_benchmark_record_from_real_prepare(world: SimpleNamespace) -> None:
    """Benchmark lấy thông số thật của job, kích thước input và thời gian stage đo được."""
    from src.services.orchestration.benchmark import PipelineRuntimeBenchmark, build_benchmark, publish_benchmark

    params = preset_values(world.presets, "minimum_quality")
    config = build_job_config(world.presets, world.checksum, params, None)
    job = world.registry.create_job(JobCreateInput(project_id=world.project.project_id), config)
    assert worker_cli.dispatch_next(world.registry) is True

    benchmark = build_benchmark(world.registry, job.job_id, gpu_hourly_usd=1.0, label="integration")
    assert benchmark.processing == params and benchmark.config_checksum == job.config_checksum
    assert benchmark.input_size_bytes == world.project.input_video.size_bytes
    assert benchmark.sog_size_bytes is None  # preview giả, chưa có SOG
    assert [stage.stage_id for stage in benchmark.stages][0] == "ST-INPUT-VALIDATE"
    measured = [stage.seconds for stage in benchmark.stages if stage.seconds is not None]
    assert measured and all(seconds >= 0 for seconds in measured)
    assert benchmark.actual_frame_count == 10  # 30 is a cap; source fixture extracts ten frames.
    assert benchmark.snapshot_phase == "partial"
    assert benchmark.total_seconds is None
    assert benchmark.estimated_gpu_cost_usd is None  # no measured GPU allocation interval

    reference = publish_benchmark(world.registry, benchmark)
    assert reference.artifact_uri == (f"artifact://jobs/{job.job_id}/benchmark/pipeline_runtime/attempt-1-partial.json")
    stored = PipelineRuntimeBenchmark.model_validate_json(
        world.registry.runtime_resolver.require(reference).read_bytes()
    )
    assert reference.schema_version == "1.1"
    assert stored.label == "integration" and stored.benchmark_kind == "pipeline_runtime"
