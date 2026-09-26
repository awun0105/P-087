"""REC-09 declarations không tự trở thành confirmation hoặc same-scene proof."""

from pydantic import Field

from src.models.contracts.artifacts import ContractModel, Identifier, JsonObject, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.reconstruction import AlignmentStatus


class AlignmentRequest(ContractModel):
    """Verifier kiểm same-scene/frame/transform và authorization bằng evidence đã bind."""

    job_id: Identifier
    rgb_geometry_ref: ProductArtifactRef
    lidar_geometry_ref: ProductArtifactRef
    transform_target_from_source: Transform
    method: Identifier = "calibration_known_transform"
    status: AlignmentStatus = AlignmentStatus.DECLARED
    evidence_refs: list[ProductArtifactRef] = Field(default_factory=list)
    same_scene_attestation: bool = False
    provenance: JsonObject = Field(default_factory=dict)
