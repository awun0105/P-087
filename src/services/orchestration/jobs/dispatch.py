"""Prepared RGB dispatch policy, dùng chung cho CLI và basic queue consumer."""

import json
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, JobStatus, StageId, StageStatus
from src.services.orchestration.artifacts import ArtifactNotFoundError, ArtifactResolver, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.processing import (
    JobProcessingConfig,
    is_presets_file,
    job_config_reference,
    load_presets,
)


def prepared_frame_reference(job: JobManifest) -> ProductArtifactRef | None:
    """Chỉ dùng một frame set thành công; không tùy tiện chọn giữa nhiều input."""
    references: dict[tuple[str, str], ProductArtifactRef] = {}
    for stage in job.stage_artifacts:
        if stage.stage_id != StageId.FRAME_EXTRACT or stage.artifact_type != "NormalizedRGBFrameSet":
            continue
        if stage.status != StageStatus.SUCCEEDED:
            continue
        reference = ProductArtifactRef(
            artifact_type=stage.artifact_type,
            schema_version="1.0",
            artifact_uri=stage.artifact_uri,
            artifact_checksum=stage.artifact_checksum,
            data_class=stage.data_class,
            producer_stage=stage.stage_id,
            job_id=job.job_id,
        )
        if not reference.artifact_uri.startswith(f"artifact://jobs/{job.job_id}/"):
            raise ValueError("Prepared frames phải thuộc namespace của job")
        references[(reference.artifact_uri, reference.artifact_checksum)] = reference
    if len(references) > 1:
        raise ValueError("Job có nhiều frame set khác nhau; cần khóa input trước dispatch")
    return next(iter(references.values()), None)


def load_prepared_profile(path: Path, expected: ExecutionProfile) -> dict:
    """Đọc bytes một lần: checksum và config không lệch vì file đổi giữa chừng."""
    payload = path.read_bytes()
    if sha256_bytes(payload) != expected.config_checksum:
        raise ValueError("Processing config khác profile đã khóa")
    profile = json.loads(payload)
    if not isinstance(profile, dict) or set(profile) != {"colmap", "brush"}:
        raise ValueError("Prepared preview profile cần đúng hai object colmap và brush")
    if not all(isinstance(value, dict) for value in profile.values()):
        raise ValueError("COLMAP/Brush config phải là object")
    return profile


def require_profile(job: JobManifest, profile: ExecutionProfile) -> None:
    """Worker không claim job thuộc runtime/seed khác.

    Cấu hình xử lý có thể riêng từng job (Studio); nó được kiểm ở
    `resolve_job_processing` theo giới hạn của file cấu hình chung.
    """
    if job.status != JobStatus.QUEUED:
        raise RuntimeStateConflictError("Chỉ claim job QUEUED; không tự chạy lại attempt đang RUNNING")
    if job.runtime_manifest_checksum != profile.runtime_manifest_checksum or job.seed != profile.seed:
        raise RuntimeStateConflictError("Job cần worker có execution profile tương ứng")


@dataclass(frozen=True)
class ResolvedProcessing:
    """Cấu hình tool cho một attempt: COLMAP/Brush + lấy mẫu frame."""

    colmap: dict
    brush: dict
    sample_fps: float
    max_frames: int


def resolve_job_processing(
    job: JobManifest,
    profile: ExecutionProfile,
    config_path: Path,
    resolver: ArtifactResolver,
    legacy_max_frames: int,
) -> ResolvedProcessing:
    """Cấu hình của job: artifact riêng (Studio) hoặc file profile legacy.

    Artifact riêng được verify checksum rồi validate lại theo giới hạn hiện hành của
    file cấu hình chung — client không thể lách giới hạn bằng cách tự ghi config.
    """
    if job.config_checksum == profile.config_checksum:
        if is_presets_file(config_path):
            raise RuntimeStateConflictError("Job dùng config chung nhưng không có bộ thông số riêng")
        legacy = load_prepared_profile(config_path, profile)
        return ResolvedProcessing(legacy["colmap"], legacy["brush"], 3.0, legacy_max_frames)
    try:
        path = resolver.require(job_config_reference(job.job_id, job.config_checksum))
    except ArtifactNotFoundError as error:
        raise RuntimeStateConflictError("Job cần worker có execution profile tương ứng") from error
    config = JobProcessingConfig.model_validate_json(path.read_bytes())
    if not is_presets_file(config_path):
        raise RuntimeStateConflictError("Worker chưa cấu hình file thông số chung cho job Studio")
    presets, _ = load_presets(config_path)
    presets.validate_params(config.params)
    return ResolvedProcessing(
        dict(config.colmap),
        dict(config.brush),
        float(config.sampling["sample_fps"]),
        int(config.sampling["max_frames"]),
    )
