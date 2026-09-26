"""Camera-derived navigation proposal không phải chứng nhận capsule walkable."""

from typing import Literal

from pydantic import Field

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.services.reconstruction.rgb.camera_pose import Vector3
from src.services.reconstruction.rgb.metric_models import EvidenceKind


class CameraSeedProposal(ContractModel):
    """Giữ source identity/frame ID thật; không tự bịa offset camera-to-ground."""

    confirmation_ref: ProductArtifactRef
    confirmation_checksum: Checksum
    source_camera_poses: ProductArtifactRef
    frame_id: int = Field(ge=0)
    position_world: Vector3
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    method: Literal["first_registered_camera"] = "first_registered_camera"
    validation_status: Literal["UNVALIDATED"] = "UNVALIDATED"
    capsule_clearance_verified: Literal[False] = False
    evidence_kind: EvidenceKind
