"""REC-06 diagnostic preflight, KHÔNG phải final metric/bundle authorization.

Canonical visual publication và production measurement authority chưa nối vào đây.
Kiểm đúng dependency bytes/distance math không được nâng thành scene CONFIRMED.
"""

from typing import Literal

from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.manifests import StageId
from src.services.reconstruction.adapters.collision_glb import read_collision_glb
from src.services.reconstruction.rgb.canonical_poses import CanonicalPoseService
from src.services.reconstruction.rgb.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.metric_models import (
    DistanceAnchor,
    EvidenceKind,
    MetricConfirmation,
    independent_distance_error,
)


class CrossArtifactVerificationRequest(ContractModel):
    """Raw visual + published canonical poses; tolerance do caller khóa trước run."""

    schema_version: Literal["1.1"] = "1.1"
    confirmation_ref: ProductArtifactRef
    visual_ref: ProductArtifactRef
    geometry_ref: ProductArtifactRef
    camera_pose_ref: ProductArtifactRef
    independent_sample: DistanceAnchor
    tolerance_m: FiniteFloat = Field(gt=0)


class CrossArtifactVerificationReport(ContractModel):
    """Kết quả có scope hẹp; không dùng thay verification_ref cho REC-10."""

    schema_version: Literal["1.1"] = "1.1"
    status: Literal["PENDING_FINAL_VERIFICATION"] = "PENDING_FINAL_VERIFICATION"
    scope: Literal["canonical_poses_geometry_lineage_distance_math"] = "canonical_poses_geometry_lineage_distance_math"
    evidence_kind: EvidenceKind
    request: CrossArtifactVerificationRequest
    confirmation_checksum: Checksum
    source_visual_checksum: Checksum
    rgb_geometry_checksum: Checksum
    camera_pose_checksum: Checksum
    scale_m_per_sfm_unit: FiniteFloat
    independent_distance_error_m: FiniteFloat = Field(ge=0)
    num_canonical_poses: int = Field(gt=0)


class MetricVerificationService:
    """Kiểm payload/lineage đã có, không che các proof còn thiếu ở final boundary."""

    def __init__(self, canonicalizer: MetricCanonicalizer) -> None:
        self.canonicalizer = canonicalizer
        self.visuals = canonicalizer.deps.visuals
        self.poses = CanonicalPoseService(canonicalizer)

    def verify(self, request: CrossArtifactVerificationRequest) -> CrossArtifactVerificationReport:
        """Raw poses hoặc metadata-only geometry không được xem là canonical proof."""
        request = CrossArtifactVerificationRequest.model_validate(request.model_dump())
        confirmation = self.canonicalizer.load(request.confirmation_ref)
        self._verify_geometry(request, confirmation)
        self._verify_visual(request.visual_ref, confirmation)
        poses = self.poses.load(request.camera_pose_ref)
        if poses.confirmation_ref != request.confirmation_ref:
            raise ValueError("canonical poses belong to a different metric confirmation")
        self.visuals.require(request.independent_sample.measurement_ref)
        err = self._check_independent_sample(confirmation, request.independent_sample, request.tolerance_m)
        return CrossArtifactVerificationReport(
            evidence_kind=confirmation.preview.request.evidence_kind,
            request=request,
            confirmation_checksum=confirmation.record_checksum,
            source_visual_checksum=request.visual_ref.artifact_checksum,
            rgb_geometry_checksum=request.geometry_ref.artifact_checksum,
            camera_pose_checksum=request.camera_pose_ref.artifact_checksum,
            scale_m_per_sfm_unit=confirmation.preview.transform.scale_m_per_sfm_unit,
            independent_distance_error_m=err,
            num_canonical_poses=len(poses.poses),
        )

    def _verify_geometry(self, request: CrossArtifactVerificationRequest, confirmation: MetricConfirmation) -> None:
        geometry_ref = request.geometry_ref
        if geometry_ref.artifact_type != "RgbGeometry" or geometry_ref.producer_stage != StageId.RGB_GEOMETRY:
            raise ValueError("geometry artifact type/stage mismatch")
        if geometry_ref.job_id != request.confirmation_ref.job_id:
            raise ValueError("geometry belongs to a different confirmation job")
        if not geometry_ref.artifact_uri.startswith(f"artifact://jobs/{geometry_ref.job_id}/"):
            raise ValueError("geometry URI belongs to a different job")
        read_collision_glb(self.visuals.require(geometry_ref))
        prov = geometry_ref.source_provenance or {}
        if prov.get("applied_confirmation_checksum") != confirmation.record_checksum:
            raise ValueError("geometry was not produced with this confirmed metric record")
        expected_scale = confirmation.preview.transform.scale_m_per_sfm_unit
        if prov.get("scale_applied") != expected_scale:
            raise ValueError("geometry scale does not match confirmation transform scale")
        expected = dict(
            applied_transform=confirmation.preview.transform.model_dump(mode="json"),
            evidence_kind=confirmation.preview.request.evidence_kind,
            source_checksum=confirmation.preview.request.anchor.source_master.artifact_checksum,
            metric_confirmation_ref=request.confirmation_ref.model_dump(mode="json"),
            coordinate_system=CoordinateSystem().model_dump(mode="json"),
        )
        if any(prov.get(key) != value for key, value in expected.items()):
            raise ValueError("geometry full transform/source lineage does not match confirmation")

    def _verify_visual(self, visual_ref: ProductArtifactRef, confirmation: MetricConfirmation) -> None:
        if visual_ref != confirmation.preview.request.source_visual:
            raise ValueError("raw visual differs from the exact confirmed source")
        visual = self.visuals.load(visual_ref)
        anchor_master = confirmation.preview.request.anchor.source_master
        if visual.master != anchor_master:
            raise ValueError("visual master does not match anchor source master")

    def _check_independent_sample(
        self, confirmation: MetricConfirmation, sample: DistanceAnchor, tolerance_m: float
    ) -> float:
        error = independent_distance_error(confirmation, sample)
        if error > tolerance_m:
            raise ValueError(f"independent distance error {error:.4f}m exceeds tolerance {tolerance_m:.4f}m")
        return error
