"""Cross-artifact metric verification cho REC-06: kiểm định scale đồng nhất."""

from typing import Literal

from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import MetricScale, MetricScaleStatus
from src.services.reconstruction.rgb.camera_pose import CameraPoseArtifact
from src.services.reconstruction.rgb.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.metric_math import CanonicalCameraPose, canonical_camera_pose
from src.services.reconstruction.rgb.metric_models import DistanceAnchor, MetricConfirmation, independent_distance_error
from src.services.reconstruction.rgb.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.visual_publication import VisualResolver


class CrossArtifactVerificationRequest(ContractModel):
    """Yêu cầu kiểm định chéo metric scale giữa visual, geometry và poses."""

    confirmation_ref: ProductArtifactRef
    visual_ref: ProductArtifactRef
    geometry_ref: ProductArtifactRef
    camera_pose_ref: ProductArtifactRef
    independent_sample: DistanceAnchor | None = None
    tolerance_m: FiniteFloat = Field(default=0.05, gt=0)


class CrossArtifactVerificationReport(ContractModel):
    """Báo cáo nghiệm thu hoàn tất xác nhận metric scale cho scene."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["CONFIRMED"] = "CONFIRMED"
    metric_scale: MetricScale = Field(
        default_factory=lambda: MetricScale(status=MetricScaleStatus.CONFIRMED, meters_per_unit=1.0)
    )
    confirmation_checksum: Checksum
    source_visual_checksum: Checksum
    rgb_geometry_checksum: Checksum
    camera_pose_checksum: Checksum
    scale_m_per_sfm_unit: FiniteFloat
    independent_distance_error_m: FiniteFloat | None = None
    num_canonical_poses: int = Field(ge=0)


class MetricVerificationService:
    """Service kiểm định chéo các artifacts trước khi công bố ReconstructionBundle."""

    def __init__(self, canonicalizer: MetricCanonicalizer, visuals: VisualResolver, poses: CameraPoseResolver) -> None:
        self.canonicalizer = canonicalizer
        self.visuals = visuals
        self.poses = poses

    def verify(self, request: CrossArtifactVerificationRequest) -> CrossArtifactVerificationReport:
        """Kiểm định chéo tính toàn vẹn metric, ngăn double scaling và đối chiếu mẫu độc lập."""
        request = CrossArtifactVerificationRequest.model_validate(request.model_dump())
        confirmation = self.canonicalizer.load(request.confirmation_ref)
        self._verify_geometry(request.geometry_ref, confirmation)
        self._verify_visual(request.visual_ref, confirmation)
        poses = self.poses.load(request.camera_pose_ref)
        canonical_poses = self._canonicalize_poses(poses, confirmation)
        err = self._check_independent_sample(confirmation, request.independent_sample, request.tolerance_m)
        return CrossArtifactVerificationReport(
            confirmation_checksum=confirmation.record_checksum,
            source_visual_checksum=request.visual_ref.artifact_checksum,
            rgb_geometry_checksum=request.geometry_ref.artifact_checksum,
            camera_pose_checksum=request.camera_pose_ref.artifact_checksum,
            scale_m_per_sfm_unit=confirmation.preview.transform.scale_m_per_sfm_unit,
            independent_distance_error_m=err,
            num_canonical_poses=len(canonical_poses),
        )

    def _verify_geometry(self, geometry_ref: ProductArtifactRef, confirmation: MetricConfirmation) -> None:
        if geometry_ref.artifact_type != "RgbGeometry":
            raise ValueError("geometry artifact must be of type RgbGeometry")
        prov = geometry_ref.source_provenance or {}
        if prov.get("applied_confirmation_checksum") != confirmation.record_checksum:
            raise ValueError("geometry was not produced with this confirmed metric record")
        expected_scale = confirmation.preview.transform.scale_m_per_sfm_unit
        if prov.get("scale_applied") != expected_scale:
            raise ValueError("geometry scale does not match confirmation transform scale")

    def _verify_visual(self, visual_ref: ProductArtifactRef, confirmation: MetricConfirmation) -> None:
        visual = self.visuals.load(visual_ref)
        anchor_master = confirmation.preview.request.anchor.source_master
        if visual.master != anchor_master:
            raise ValueError("visual master does not match anchor source master")

    def _canonicalize_poses(
        self, poses: CameraPoseArtifact, confirmation: MetricConfirmation
    ) -> list[CanonicalCameraPose]:
        transform = confirmation.preview.transform
        return [canonical_camera_pose(pose, transform) for pose in poses.poses]

    def _check_independent_sample(
        self, confirmation: MetricConfirmation, sample: DistanceAnchor | None, tolerance_m: float
    ) -> float | None:
        if sample is None:
            return None
        error = independent_distance_error(confirmation, sample)
        if error > tolerance_m:
            raise ValueError(f"independent distance error {error:.4f}m exceeds tolerance {tolerance_m:.4f}m")
        return error
