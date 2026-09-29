"""Bản ghi benchmark cho mỗi attempt job (plan Cloud Studio, mục 9).

Chỉ dùng dữ liệu product nhìn thấy được qua contract: journal stage, cấu hình xử lý của
job, máy worker tự đo, kích thước input/SOG. Không đọc manifest nội bộ của EX-REC.
Số liệu chất lượng ảnh (PSNR/SSIM) và sai số metric thuộc evaluation, không nằm ở đây.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.services.orchestration.artifacts import ArtifactStoreError, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.processing import JobProcessingConfig, MachineCapability, job_config_reference
from src.services.orchestration.projects.registry import ProjectRegistry

BENCHMARK_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class StageTiming(BaseModel):
    """Thời gian đo được của một stage (giây); stage chưa có mốc thì bỏ qua."""

    model_config = ConfigDict(extra="forbid")

    stage_id: str
    state: str
    seconds: float | None = Field(default=None, ge=0)


class JobBenchmark(BaseModel):
    """Một bản ghi benchmark bất biến theo job + attempt."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = BENCHMARK_SCHEMA_VERSION
    job_id: str
    project_id: str
    attempt: int
    label: str | None = None
    recorded_at: datetime
    status: str
    stages: list[StageTiming]
    total_seconds: float | None = Field(default=None, ge=0)
    processing: dict[str, int | float | str] | None = None
    config_checksum: str
    machine: MachineCapability | None = None
    input_size_bytes: int | None = None
    sog_size_bytes: int | None = None
    gpu_hourly_usd: float | None = Field(default=None, ge=0)
    estimated_gpu_cost_usd: float | None = Field(default=None, ge=0)


def build_benchmark(
    registry: ProjectRegistry,
    job_id: str,
    *,
    machine: MachineCapability | None = None,
    gpu_hourly_usd: float | None = None,
    label: str | None = None,
) -> JobBenchmark:
    """Dựng bản ghi từ trạng thái hiện tại của job (không ghi gì)."""
    job = registry.get_job(job_id)
    attempts = registry.list_job_attempts(job_id)
    preview_ready = True
    try:
        preview = registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        preview, preview_ready = None, False
    progress = job_progress(job, attempts, preview_ready)

    stages = [
        StageTiming(
            stage_id=stage.stage_id.value,
            state=stage.state,
            seconds=(stage.completed_at - stage.started_at).total_seconds()
            if stage.started_at and stage.completed_at
            else None,
        )
        for stage in progress.stages
    ]
    starts = [stage.started_at for stage in progress.stages if stage.started_at]
    ends = [stage.completed_at for stage in progress.stages if stage.completed_at]
    total = (max(ends) - min(starts)).total_seconds() if starts and ends else None

    processing = None
    try:
        config_path = registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
        processing = JobProcessingConfig.model_validate_json(config_path.read_bytes()).params
    except ArtifactStoreError:
        processing = None  # Job legacy trước khi có file cấu hình chung.

    project = registry.get_project(job.project_id)
    sog_size = None
    if preview is not None:
        try:
            sog_size = registry.runtime_resolver.require(preview.delivery_ref).stat().st_size
        except ArtifactStoreError:
            sog_size = None

    cost = round(total / 3600 * gpu_hourly_usd, 4) if total is not None and gpu_hourly_usd is not None else None
    return JobBenchmark(
        job_id=job.job_id,
        project_id=job.project_id,
        attempt=progress.attempt,
        label=label,
        recorded_at=datetime.now(UTC),
        status=job.status.value,
        stages=stages,
        total_seconds=total,
        processing=processing,
        config_checksum=job.config_checksum,
        machine=machine,
        input_size_bytes=project.input_video.size_bytes if project.input_video else None,
        sog_size_bytes=sog_size,
        gpu_hourly_usd=gpu_hourly_usd,
        estimated_gpu_cost_usd=cost,
    )


def publish_benchmark(registry: ProjectRegistry, benchmark: JobBenchmark) -> ProductArtifactRef:
    """Publish bản ghi thành artifact bất biến cạnh kết quả job (tự đẩy lên kho file nếu có)."""
    payload = benchmark.model_dump_json(indent=2).encode("utf-8") + b"\n"
    reference = ProductArtifactRef(
        artifact_type="JobBenchmark",
        schema_version=BENCHMARK_SCHEMA_VERSION,
        artifact_uri=f"artifact://jobs/{benchmark.job_id}/benchmark/attempt-{benchmark.attempt}.json",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="benchmark",
        job_id=benchmark.job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    return reference
