"""Demo bundle: output thật của một lần chạy pipeline, đóng gói để phát lại nhanh.

Bundle không phải artifact contract của pipeline; nó là bản export read-only phục
vụ kịch bản demo. Mọi file có checksum; thời lượng stage lấy từ journal của job
gốc (null khi nguồn không ghi được), UI không được bịa số.
"""

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.contracts.artifacts import Checksum
from src.models.contracts.manifests import StageId
from src.services.orchestration.jobs.progress import STUDIO_PIPELINE

_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class DemoFile(BaseModel):
    """Một file trong `files/` của bundle, tham chiếu bằng tên phẳng + checksum."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=128)
    media_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    checksum: Checksum

    @field_validator("name")
    @classmethod
    def _flat_name(cls, value: str) -> str:
        if _FILE_NAME.fullmatch(value) is None:
            raise ValueError("demo file name phải là tên phẳng an toàn")
        return value


class DemoStage(BaseModel):
    """Evidence của stage; `duration_seconds` null khi chưa có mốc thời gian."""

    model_config = ConfigDict(extra="forbid")

    stage_id: StageId
    #: Bundle cũ chỉ liệt kê stage đã chạy; field mới phân biệt bước chưa có evidence.
    state: Literal["succeeded", "pending", "failed"] = "succeeded"
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    summary: str = Field(default="", max_length=300)


class DemoSource(BaseModel):
    """Nguồn dữ liệu của demo (dataset công khai, traversal) để hiển thị trung thực."""

    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(min_length=1, max_length=200)
    sequence: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=500)


class DemoManifest(BaseModel):
    """`manifest.json` của bundle; `origin` phân biệt job thật với bản smoke tạm."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    demo_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    origin: Literal["pipeline_job", "smoke_run"]
    source: DemoSource
    produced_at: datetime
    provenance: dict[str, str] = Field(default_factory=dict)
    stages: list[DemoStage]
    video: DemoFile | None = None
    frames: list[DemoFile] = Field(default_factory=list, max_length=48)
    frame_count: int | None = Field(default=None, ge=0)
    splat: DemoFile
    #: Thông số xử lý thật của job (theo file cấu hình chung); None với bundle cũ/smoke.
    processing: dict[str, int | float | str] | None = None
    #: Máy đã xử lý (từ RuntimeManifest), ví dụ {"gpu_model": "RTX 4090", "vram": "24564 MiB"}.
    machine: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        names = [file.name for file in self.files()]
        if len(names) != len(set(names)):
            raise ValueError("demo file names phải duy nhất")
        if not self.splat.name.endswith((".sog", ".ply")):
            raise ValueError("splat phải là .sog hoặc .ply")
        records = {stage.stage_id: stage for stage in self.stages}
        if len(records) != len(self.stages):
            raise ValueError("demo stage IDs phải duy nhất")
        # Adapter read-only: bundle preview cũ hiện đủ pipeline mới, không ghi success giả.
        self.stages = [
            records.get(stage_id)
            or DemoStage(stage_id=stage_id, state="pending", summary="Mẫu này chưa ghi kết quả của bước này.")
            for stage_id in STUDIO_PIPELINE
        ]
        return self

    def files(self) -> list[DemoFile]:
        """Allow-list duy nhất của file được phục vụ qua API."""
        return [*([self.video] if self.video else []), *self.frames, self.splat]
