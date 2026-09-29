"""File cấu hình xử lý chung và bộ thông số của từng job (product-level, không phải shared contract).

`processing_presets_v1.json` là nguồn duy nhất cho: thông số được phép chỉnh,
giới hạn min/max, preset, giá trị cố định và hệ số ước lượng tài nguyên. UI chỉ
hiển thị những gì file này khai báo; worker validate lại trước khi chạy.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.artifacts import Checksum

ParamValue = int | float | str
PresetName = Literal["minimum_quality", "maximum"]


class ParameterChoice(BaseModel):
    """Một lựa chọn của thông số dạng `choice`."""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str


class ParameterSpec(BaseModel):
    """Một thông số chỉnh được: `<nhóm>.<tên>` ánh xạ thẳng vào config của tool."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^(sampling|colmap|brush)\.[a-z_]+$")
    group: Literal["sampling", "colmap", "brush"]
    label: str
    description: str
    kind: Literal["number", "integer", "choice"]
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = Field(default=None, gt=0)
    choices: list[ParameterChoice] | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if not self.key.startswith(f"{self.group}."):
            raise ValueError(f"{self.key}: nhóm không khớp key")
        if self.kind == "choice":
            if not self.choices:
                raise ValueError(f"{self.key}: choice cần danh sách lựa chọn")
        elif self.min is None or self.max is None or self.min > self.max:
            raise ValueError(f"{self.key}: thông số số cần min <= max")
        return self

    def check(self, value: ParamValue) -> ParamValue:
        """Chuẩn hóa kiểu và kiểm giới hạn; ném ValueError có tên thông số."""
        if self.kind == "choice":
            allowed = {choice.value for choice in self.choices or []}
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"{self.key}: giá trị phải thuộc {sorted(allowed)}")
            return value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{self.key}: phải là số")
        if self.kind == "integer":
            if float(value) != int(value):
                raise ValueError(f"{self.key}: phải là số nguyên")
            value = int(value)
        if not (self.min <= value <= self.max):  # type: ignore[operator]
            raise ValueError(f"{self.key}: phải trong khoảng {self.min:g}–{self.max:g}")
        return value


class ResourceModel(BaseModel):
    """Hệ số ước lượng heuristic; UI ghi rõ đây là ước lượng, không phải đo."""

    model_config = ConfigDict(extra="forbid")

    note: str
    vram_base_gb: float = Field(ge=0)
    vram_per_million_splats_gb: float = Field(gt=0)
    vram_per_train_megapixel_gb: float = Field(ge=0)
    ram_base_gb: float = Field(ge=0)
    ram_per_decode_megapixel_gb: float = Field(ge=0)
    ram_feature_bytes: float = Field(gt=0)
    disk_per_frame_megapixel_gb: float = Field(gt=0)
    disk_workspace_factor: float = Field(ge=1)
    disk_per_million_splats_gb: float = Field(ge=0)
    assumed_video_megapixels: float = Field(gt=0)
    viewer_heavy_splats: int = Field(gt=0)
    warn_ratio: float = Field(gt=0, lt=1)
    danger_ratio: float = Field(gt=0, le=1)


class FixedSettings(BaseModel):
    """Giá trị không mở cho người dùng nhưng bắt buộc với COLMAP/Brush."""

    model_config = ConfigDict(extra="forbid")

    colmap: dict[str, ParamValue | bool]
    brush: dict[str, ParamValue | bool]
    colmap_max_threads: int = Field(ge=1, le=256)


class ProcessingPresets(BaseModel):
    """Nội dung file cấu hình chung."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    profile_id: str
    parameters: list[ParameterSpec]
    presets: dict[PresetName, dict[str, ParamValue]]
    fixed: FixedSettings
    resource_model: ResourceModel

    @model_validator(mode="after")
    def _presets_complete(self) -> Self:
        keys = [spec.key for spec in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError("key thông số bị trùng")
        for name, values in self.presets.items():
            if set(values) != set(keys):
                raise ValueError(f"preset {name} phải khai báo đủ và chỉ các thông số trong parameters")
            self.validate_params(values)
        return self

    def spec(self, key: str) -> ParameterSpec:
        """Spec theo key; KeyError nếu không khai báo."""
        return next(spec for spec in self.parameters if spec.key == key)

    def validate_params(self, values: dict[str, ParamValue]) -> dict[str, ParamValue]:
        """Đủ key, không thừa key, mọi giá trị trong giới hạn của file cấu hình chung."""
        keys = {spec.key for spec in self.parameters}
        if set(values) != keys:
            missing, extra = sorted(keys - set(values)), sorted(set(values) - keys)
            raise ValueError(f"thông số không khớp cấu hình chung (thiếu {missing}, thừa {extra})")
        return {spec.key: spec.check(values[spec.key]) for spec in self.parameters}


class MachineCapability(BaseModel):
    """Cấu hình máy worker tự đo (GPU server xử lý job), không phải máy người xem."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str
    measured_at: datetime
    gpu_name: str | None = None
    vram_total_gb: float | None = Field(default=None, ge=0)
    cpu_count: int = Field(ge=1)
    ram_total_gb: float = Field(gt=0)
    disk_free_gb: float = Field(ge=0)


class JobProcessingConfig(BaseModel):
    """Cấu hình đã resolve của một job; bytes của nó là `JobManifest.config_checksum`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    presets_profile_id: str
    presets_checksum: Checksum
    params: dict[str, ParamValue]
    sampling: dict[str, float | int]
    colmap: dict[str, ParamValue | bool]
    brush: dict[str, ParamValue | bool]
