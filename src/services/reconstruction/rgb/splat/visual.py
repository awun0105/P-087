"""REC-04 raw visual metadata; REC-06 mới xác nhận canonical meter/world."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, JsonObject, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, canonical_json_bytes


class BrushConfig(ContractModel):
    """Các knobs được khóa trước execution; defaults còn lại thuộc runtime pin."""

    schema_version: Literal["1.0"] = "1.0"
    total_train_iters: int = Field(gt=0)
    max_resolution: int = Field(ge=32)
    sh_degree: int = Field(ge=0, le=3)
    seed: int = Field(ge=0)
    max_splats: int = Field(gt=0)
    refine_every: int = Field(gt=0)
    sog_iterations: int = Field(gt=0)

    def checksum(self) -> str:
        """Content identity của config không bao gồm private executable paths."""
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self)).hexdigest()


class SplatInspection(ContractModel):
    """Báo cáo semantic từ upstream reader/stats, không tự viết Gaussian parser."""

    version: Literal["3.6.6"]
    revision: str
    gaussian: Literal[True]
    num_gaussians: int = Field(gt=0)
    sh_bands: int = Field(ge=0, le=3)
    fill_ratio: float = Field(ge=0, allow_inf_nan=False)
    nonfinite_count: Literal[0]
    ply_to_sog: Literal["identity_in_ply_storage_space"]
    info: JsonObject
    stats: JsonObject
    #: Thiết bị thực tế đã nén SOG (`gpu:<adapter>` hoặc `cpu`) và thời gian nén.
    sog_device: str | None = None
    sog_compress_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class BrushVisualArtifact(ContractModel):
    """Manifest nội bộ EX-REC; không gắn nhãn meter cho SfM chưa confirmed."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["BrushVisualArtifact"] = "BrushVisualArtifact"
    source_camera_poses: ProductArtifactRef
    source_frame_set: ProductArtifactRef
    config: BrushConfig
    config_checksum: Checksum
    brush_version: str
    runtime_identity: str
    training_frame_ids: list[int]
    parent_frame: Literal["sfm_world"] = "sfm_world"
    scale_status: Literal["arbitrary_sfm"] = "arbitrary_sfm"
    world_alignment_status: Literal["unconfirmed"] = "unconfirmed"
    format: Literal["gaussian_ply"] = "gaussian_ply"
    master: ProductArtifactRef
    delivery: ProductArtifactRef
    inspection: SplatInspection
    bridge: JsonObject
    logs: dict[str, ProductArtifactRef]
    artifact_checksum: Checksum

    @model_validator(mode="after")
    def _verify(self) -> "BrushVisualArtifact":
        if self.training_frame_ids != sorted(set(self.training_frame_ids)) or len(self.training_frame_ids) < 2:
            raise ValueError("invalid registered training frame inventory")
        if self.config_checksum != self.config.checksum():
            raise ValueError("visual config checksum mismatch")
        if self.inspection.num_gaussians > self.config.max_splats:
            raise ValueError("visual splat count exceeds configured budget")
        if self.inspection.sh_bands != self.config.sh_degree:
            raise ValueError("visual SH degree differs from training config")
        if self.master.artifact_type != "GaussianPLY" or self.delivery.artifact_type != "GaussianSOG":
            raise ValueError("visual representation types mismatch")
        if not self.logs:
            raise ValueError("visual runtime evidence is missing")
        if canonical_content_checksum(self, "artifact_checksum") != self.artifact_checksum:
            raise ValueError("visual content checksum mismatch")
        return self
