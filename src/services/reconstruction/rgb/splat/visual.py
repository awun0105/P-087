"""REC-04 raw visual metadata; REC-06 mới xác nhận canonical meter/world."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, JsonObject, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, canonical_json_bytes


def _absent(value: object) -> bool:
    """Trường thêm sau schema 1.0 không xuất hiện trong JSON khi chưa dùng (giữ nguyên checksum cũ)."""
    return value is None


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
    #: Giữ lại mỗi ảnh thứ N (theo thứ tự tên) không train, để chấm PSNR/SSIM/LPIPS ở bước cuối. None = train trên
    #: mọi ảnh như trước. Trường bị bỏ khỏi JSON khi None nên checksum của cấu hình và artifact cũ không đổi.
    eval_split_every: int | None = Field(default=None, ge=2, exclude_if=_absent)

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


class HoldoutQuality(ContractModel):
    """Chất lượng ảnh render ở camera của ảnh giữ lại (không train), do Brush chấm ở bước train cuối.

    PSNR/SSIM là số Brush in ra (render nền đen, làm tròn 8-bit); LPIPS chấm riêng trên ảnh Brush lưu ra đĩa và chỉ
    có khi worker cấu hình runtime LPIPS. Giao thức: `eval/protocols/recon_visual_quality.md`.
    """

    eval_split_every: int = Field(ge=2)
    iteration: int = Field(gt=0)
    views: int = Field(gt=0)
    psnr: float = Field(allow_inf_nan=False)
    ssim: float = Field(allow_inf_nan=False)
    lpips: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    lpips_net: Literal["vgg"] | None = None


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
    #: Ảnh đã đăng ký pose nhưng không đưa vào train (config.eval_split_every). Không có trường = train mọi ảnh.
    held_out_frame_ids: list[int] | None = Field(default=None, exclude_if=_absent)
    #: None khi có giữ ảnh nhưng runtime không in kết quả chấm (vd. train tiếp từ checkpoint của đúng bước cuối).
    holdout_quality: HoldoutQuality | None = Field(default=None, exclude_if=_absent)
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
        held_out = self.held_out_frame_ids
        if (held_out is None) != (self.config.eval_split_every is None):
            raise ValueError("held-out inventory must match the configured eval split")
        if held_out is not None and (
            not held_out or held_out != sorted(set(held_out)) or set(held_out) & set(self.training_frame_ids)
        ):
            raise ValueError("invalid held-out frame inventory")
        quality = self.holdout_quality
        if quality is not None and (
            held_out is None
            or quality.views != len(held_out)
            or quality.eval_split_every != self.config.eval_split_every
        ):
            raise ValueError("held-out quality does not describe the held-out inventory")
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
