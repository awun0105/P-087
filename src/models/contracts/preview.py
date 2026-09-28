"""Preview trước metric/SceneIR, không được dùng thay canonical VisualArtifact."""

from typing import Literal, Self

from pydantic import model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, StageArtifact


class ReconstructionPreview(ContractModel):
    """Consumer PRODUCT chỉ cần contract này, không parse manifest Brush nội bộ."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["ReconstructionPreview"] = "ReconstructionPreview"
    job_id: Identifier
    attempt_id: Identifier
    source_input_checksum: Checksum
    source_visual_ref: ProductArtifactRef
    camera_pose_ref: ProductArtifactRef
    delivery_ref: ProductArtifactRef
    format: Literal["gaussian_sog"] = "gaussian_sog"
    producer: Literal["brush"] = "brush"
    producer_version: str
    metric_status: Literal["UNCONFIRMED"] = "UNCONFIRMED"
    coordinate_frame: Literal["sfm_world"] = "sfm_world"
    unit: Literal["arbitrary"] = "arbitrary"

    @model_validator(mode="after")
    def _bind_refs(self) -> Self:
        prefix = f"artifact://jobs/{self.job_id}/attempts/{self.attempt_id}/"
        for reference in (self.source_visual_ref, self.camera_pose_ref, self.delivery_ref):
            if reference.job_id != self.job_id or not reference.artifact_uri.startswith(prefix):
                raise ValueError("Preview refs phải cùng job/attempt")
        if self.delivery_ref.artifact_type != "GaussianSOG" or not self.delivery_ref.artifact_uri.endswith(".sog"):
            raise ValueError("Preview delivery cần GaussianSOG đóng gói một file")
        if self.source_visual_ref.artifact_type != "BrushVisualArtifact":
            raise ValueError("Preview source phải là BrushVisualArtifact")
        return self


class PreviewWorkerReceipt(ContractModel):
    """Kết quả port REC đã consumer-verify, dùng để reducer cập nhật JobManifest."""

    job_id: Identifier
    attempt_id: Identifier
    source_input_checksum: Checksum
    result_ref: ProductArtifactRef
    stage_artifacts: list[StageArtifact]
    preview_ref: ProductArtifactRef | None = None
    error: ExecutionError | None = None
