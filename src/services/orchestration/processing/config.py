"""Đọc file cấu hình chung và dựng cấu hình đầy đủ cho một job."""

import json
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import sha256_bytes
from src.services.orchestration.processing.models import (
    JobProcessingConfig,
    MachineCapability,
    ParamValue,
    PresetName,
    ProcessingPresets,
)


class ProcessingConfigError(ValueError):
    """File cấu hình chung thiếu/sai hoặc thông số của job vượt giới hạn."""


def load_presets(path: Path) -> tuple[ProcessingPresets, str]:
    """Đọc bytes một lần: checksum và nội dung không lệch nhau."""
    try:
        payload = path.read_bytes()
        presets = ProcessingPresets.model_validate(json.loads(payload))
    except (OSError, ValueError) as error:
        raise ProcessingConfigError(f"File cấu hình xử lý không hợp lệ: {path.name}") from error
    return presets, sha256_bytes(payload)


def is_presets_file(path: Path) -> bool:
    """File chung có `parameters`; file legacy chỉ có `colmap` + `brush`."""
    try:
        return "parameters" in json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False


def preset_values(presets: ProcessingPresets, name: PresetName) -> dict[str, ParamValue]:
    """Bản sao preset để caller chỉnh mà không sửa file đã nạp."""
    return dict(presets.presets[name])


def build_job_config(
    presets: ProcessingPresets,
    presets_checksum: str,
    params: dict[str, ParamValue],
    capability: MachineCapability | None,
) -> JobProcessingConfig:
    """Validate thông số người dùng rồi ghép với giá trị cố định thành config của tool.

    `num_threads` của COLMAP lấy theo số nhân CPU của máy worker (chặn trên bởi
    file chung); chưa có worker đo thì dùng 4 luồng.
    """
    try:
        values = presets.validate_params(params)
    except ValueError as error:
        raise ProcessingConfigError(str(error)) from error
    grouped: dict[str, dict[str, ParamValue]] = {"sampling": {}, "colmap": {}, "brush": {}}
    for key, value in values.items():
        group, name = key.split(".", 1)
        grouped[group][name] = value
    threads = min(presets.fixed.colmap_max_threads, capability.cpu_count if capability else 4)
    return JobProcessingConfig(
        presets_profile_id=presets.profile_id,
        presets_checksum=presets_checksum,
        params=values,
        sampling={key: value for key, value in grouped["sampling"].items() if not isinstance(value, str)},
        colmap={**presets.fixed.colmap, **grouped["colmap"], "num_threads": threads},
        brush={**presets.fixed.brush, **grouped["brush"]},
    )


def config_bytes(config: JobProcessingConfig) -> bytes:
    """Bytes xác định (sort key) để checksum ổn định giữa các lần publish."""
    return json.dumps(config.model_dump(mode="json"), sort_keys=True, indent=2).encode("utf-8") + b"\n"


def job_config_reference(job_id: str, checksum: str) -> ProductArtifactRef:
    """Vị trí cố định của cấu hình xử lý riêng của job; checksum = `JobManifest.config_checksum`."""
    return ProductArtifactRef(
        artifact_type="JobProcessingConfig",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/config/processing.json",
        artifact_checksum=checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=job_id,
    )
