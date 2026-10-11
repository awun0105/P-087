"""Request/result của bước chuẩn bị input video (REC-02 → REC-02A) cho PRODUCT worker."""

from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId
from src.services.reconstruction.attempt import PathSegment
from src.services.reconstruction.rgb.preflight.quality_models import RGBQualityProfile


class PrepareInputRequest(ContractModel):
    """Một video upload đã publish kèm InputManifest; privacy chỉ có chế độ tự khai MVP.

    Lấy mẫu theo thời lượng: số frame mong muốn = thời lượng video × `sample_fps`,
    chặn trên bởi `max_frames`; trong mỗi cửa sổ giữ frame nét nhất. Video dài
    vì vậy tự có nhiều frame hơn, không bị một trần cố định làm thưa đi.
    """

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["rgb_video_prepare"] = "rgb_video_prepare"
    job_id: PathSegment
    input_manifest_ref: ProductArtifactRef
    quality_profile: RGBQualityProfile
    privacy_mode: Literal["self_attested"] = "self_attested"
    sample_fps: float = Field(default=3.0, gt=0, le=30, allow_inf_nan=False)
    max_frames: int = Field(default=300, ge=2, le=5000)
    #: Che khuôn mặt/biển số trên frame trước khi dựng 3D (AUD-18). Bật mà worker không có anonymizer thì job lỗi,
    #: không lùi về frame gốc.
    anonymize: bool = False

    @model_validator(mode="after")
    def _manifest_ref(self) -> Self:
        if self.input_manifest_ref.artifact_type != "InputManifest":
            raise ValueError("prepare input requires a published InputManifest reference")
        return self


class PrepareInputResult(ContractModel):
    """Stage records cho JobManifest; `frame_set_ref` chỉ có khi mọi stage SUCCEEDED."""

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["rgb_video_prepare"] = "rgb_video_prepare"
    job_id: PathSegment
    input_manifest_checksum: Checksum
    stage_artifacts: list[StageArtifact]
    frame_set_ref: ProductArtifactRef | None = None
    frame_stride: int | None = Field(default=None, ge=1)
    video_duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    selected_frame_count: int | None = Field(default=None, ge=0)
    extracted_frame_count: int | None = Field(default=None, ge=0)
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def _outcome(self) -> Self:
        if (self.error is None) == (self.frame_set_ref is None):
            raise ValueError("prepare result needs exactly one of frame_set_ref or error")
        if self.frame_set_ref is not None:
            succeeded = {stage.stage_id for stage in self.stage_artifacts if stage.status == "SUCCEEDED"}
            if StageId.FRAME_EXTRACT not in succeeded:
                raise ValueError("frame_set_ref requires a succeeded ST-FRAME-EXTRACT stage")
        return self
