"""Checkpoint REC-11 trước HITL metric; không thay JobManifest hoặc final bundle."""

from typing import Literal, Self

from pydantic import model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId
from src.services.reconstruction.attempt import PathSegment
from src.services.reconstruction.rgb.camera_pose import ColmapConfig
from src.services.reconstruction.rgb.visual import BrushConfig


class PreparedPreviewRequest(ContractModel):
    """Chỉ nhận output REC-02A sau privacy gate, không nhận raw video bỏ qua QA."""

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["prepared_rgb_preview"] = "prepared_rgb_preview"
    job_id: PathSegment
    attempt_id: PathSegment
    source_input_checksum: Checksum
    frame_set_ref: ProductArtifactRef
    colmap: ColmapConfig
    brush: BrushConfig

    @model_validator(mode="after")
    def _source(self) -> Self:
        ref = self.frame_set_ref
        if ref.job_id != self.job_id or not ref.artifact_uri.startswith(f"artifact://jobs/{self.job_id}/"):
            raise ValueError("prepared frames must belong to the requested job")
        if ref.artifact_type != "NormalizedRGBFrameSet" or ref.producer_stage != StageId.FRAME_EXTRACT:
            raise ValueError("preview requires a published REC-02A frame set")
        return self


class PreparedPreviewResult(ContractModel):
    """preview_complete không đồng nghĩa toàn job hoặc reconstruction đã SUCCEEDED."""

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["prepared_rgb_preview"] = "prepared_rgb_preview"
    job_id: PathSegment
    attempt_id: PathSegment
    source_input_checksum: Checksum
    request_ref: ProductArtifactRef
    preview_complete: bool
    job_status: Literal["RUNNING", "FAILED"]
    metric_status: Literal["UNCONFIRMED"] = "UNCONFIRMED"
    stage_artifacts: list[StageArtifact]
    camera_pose_ref: ProductArtifactRef | None = None
    raw_visual_ref: ProductArtifactRef | None = None
    delivery_ref: ProductArtifactRef | None = None
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def _completion(self) -> Self:
        if self.preview_complete:
            if self.job_status != "RUNNING" or self.error is not None:
                raise ValueError("preview completion must keep the overall job running")
            if any(ref is None for ref in (self.camera_pose_ref, self.raw_visual_ref, self.delivery_ref)):
                raise ValueError("complete preview requires published poses, visual and delivery")
        elif self.job_status != "FAILED" or self.error is None:
            raise ValueError("incomplete preview requires a structured failure")
        return self
