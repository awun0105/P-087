"""Proposed, identity-bound contracts for selectable collision geometry and QA."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, PositiveInt, model_validator

from src.models.contracts.artifacts import ArtifactRef, Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import SceneEnvironment
from src.models.contracts.validation import CollisionObservationState

PositiveFinite = Annotated[FiniteFloat, Field(gt=0)]


class CollisionSourceMode(StrEnum):
    """Geometry producer selected for the collision artifact."""

    RGB_CLEANED = "rgb_cleaned"
    LIDAR_DERIVED = "lidar_derived"


class CollisionInputMode(StrEnum):
    """Source-specific QA route; map registration is not sensor calibration."""

    RGB_METRIC_GEOMETRY = "rgb_metric_geometry"
    LIDAR_SENSOR_PACKAGE = "lidar_sensor_package"
    LIDAR_REGISTERED_MAP = "lidar_registered_map"


class CollisionAlignmentQAKind(StrEnum):
    """QA family bound to the selected LiDAR source mode."""

    SENSOR_CALIBRATION_TIMING = "sensor_calibration_timing"
    REGISTERED_MAP_REGISTRATION = "registered_map_registration"


class CollisionReferenceKind(StrEnum):
    """Origin of a reference used to measure retained obstacles."""

    SAME_INPUT = "same_input"
    INDEPENDENT_SURFACE_SCAN = "independent_surface_scan"
    CAD_REFERENCE = "cad_reference"
    MANUAL_CONTACT_REFERENCE = "manual_contact_reference"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class CollisionPhysicsClaim(StrEnum):
    """Whether the report carries actual, bounded simulator/contact evidence."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class CollisionQualityResult(StrEnum):
    """Result under a versioned/frozen acceptance profile."""

    NOT_EVALUATED = "not_evaluated"
    PASS = "pass"
    FAIL = "fail"


class ClearanceProxyEvidence(ContractModel):
    """Observed free-space proxy; it does not estimate independent obstacle recall."""

    blocked_positions: int = Field(ge=0)
    tested_positions: PositiveInt
    trajectory_origin: Literal["canonical_camera_path", "ground_truth", "estimated"]

    @model_validator(mode="after")
    def _check_counts(self) -> ClearanceProxyEvidence:
        if self.blocked_positions > self.tested_positions:
            raise ValueError("blocked positions cannot exceed tested positions")
        return self


class ObstacleRetentionEvidence(ContractModel):
    """Obstacle retention measured against an explicitly identified reference."""

    reference_ref: ArtifactRef
    reference_kind: CollisionReferenceKind
    expected_obstacles: PositiveInt
    retained_obstacles: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_retained_count(self) -> ObstacleRetentionEvidence:
        if self.retained_obstacles > self.expected_obstacles:
            raise ValueError("retained obstacles cannot exceed reference obstacles")
        return self


class CollisionSupportEvidence(ContractModel):
    """Measured floor/support retention, kept separate from free-space metrics."""

    reference_ref: ArtifactRef
    reference_kind: CollisionReferenceKind
    expected_support_samples: PositiveInt
    retained_support_samples: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_support_count(self) -> CollisionSupportEvidence:
        if self.retained_support_samples > self.expected_support_samples:
            raise ValueError("retained support samples cannot exceed reference samples")
        return self


class CollisionRegionEvidence(ContractModel):
    """Source and observation provenance for one covered or unsupported region."""

    region_id: str = Field(min_length=1)
    state: CollisionObservationState
    source_ref: ProductArtifactRef
    observation_ids: list[str] = Field(default_factory=list)
    coverage_fraction: FiniteFloat = Field(ge=0, le=1)
    diagnostic_ref: ProductArtifactRef | None = None

    @model_validator(mode="after")
    def _observed_region_has_evidence(self) -> CollisionRegionEvidence:
        if self.state == CollisionObservationState.OBSERVED_STATIC:
            if not self.observation_ids or self.coverage_fraction <= 0:
                raise ValueError("observed static region requires observations and measured coverage")
        return self


class LidarAlignedPointCloudEvidence(ContractModel):
    """Exact metric-world point ordering after applying one confirmed bundle alignment."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["LidarAlignedPointCloudEvidence"] = "LidarAlignedPointCloudEvidence"
    job_id: Identifier
    source_geometry_ref: ProductArtifactRef
    alignment_ref: ProductArtifactRef
    frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"
    point_cloud_checksum: Checksum
    point_count: PositiveInt

    @model_validator(mode="after")
    def _check_binding(self) -> LidarAlignedPointCloudEvidence:
        references = (self.source_geometry_ref, self.alignment_ref)
        if any(
            reference.job_id != self.job_id or not reference.artifact_uri.startswith(f"artifact://jobs/{self.job_id}/")
            for reference in references
        ):
            raise ValueError("aligned point-cloud evidence refs must belong to the same job")
        if (
            self.source_geometry_ref.artifact_type != "LiDARGeometryArtifact"
            or self.source_geometry_ref.producer_stage != StageId.LIDAR_INGEST
        ):
            raise ValueError("aligned point-cloud source must be the job's LiDAR geometry")
        if (
            self.alignment_ref.artifact_type != "AlignmentRecord"
            or self.alignment_ref.producer_stage != StageId.RGB_LIDAR_ALIGN
        ):
            raise ValueError("aligned point-cloud evidence must bind an AlignmentRecord")
        return self


class LidarSelfMaskEvidence(ContractModel):
    """Point-order-bound robot self-mask receipt for one LiDAR package."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["LidarSelfMaskEvidence"] = "LidarSelfMaskEvidence"
    job_id: Identifier
    package_ref: ProductArtifactRef
    source_geometry_ref: ProductArtifactRef
    alignment_ref: ProductArtifactRef
    aligned_point_cloud_ref: ProductArtifactRef
    trajectory_ref: ProductArtifactRef
    robot_profile_ref: ProductArtifactRef
    source_point_checksum: Checksum
    point_count: PositiveInt
    mask_binding_checksum: Checksum
    masked_point_count: int = Field(ge=0, strict=True)
    covered_pose_count: int = Field(ge=0, strict=True)
    total_pose_count: PositiveInt
    algorithm: Literal["sensor_frame_robot_envelope_v1"]

    @model_validator(mode="after")
    def _check_binding(self) -> LidarSelfMaskEvidence:
        references = (
            self.package_ref,
            self.source_geometry_ref,
            self.alignment_ref,
            self.aligned_point_cloud_ref,
            self.trajectory_ref,
            self.robot_profile_ref,
        )
        if any(
            reference.job_id != self.job_id or not reference.artifact_uri.startswith(f"artifact://jobs/{self.job_id}/")
            for reference in references
        ):
            raise ValueError("self-mask evidence refs must belong to the same job")
        if self.package_ref.artifact_type != "LidarPackageRecord":
            raise ValueError("self-mask package_ref must reference a LidarPackageRecord")
        if self.package_ref.producer_stage != StageId.LIDAR_INGEST:
            raise ValueError("self-mask package_ref must be produced by LiDAR ingest")
        if self.source_geometry_ref.artifact_type != "LiDARGeometryArtifact":
            raise ValueError("self-mask source_geometry_ref must reference LiDAR geometry")
        if self.source_geometry_ref.producer_stage != StageId.LIDAR_INGEST:
            raise ValueError("self-mask geometry must be produced by LiDAR ingest")
        if (
            self.alignment_ref.artifact_type != "AlignmentRecord"
            or self.alignment_ref.producer_stage != StageId.RGB_LIDAR_ALIGN
        ):
            raise ValueError("self-mask evidence must bind the exact AlignmentRecord")
        if (
            self.aligned_point_cloud_ref.artifact_type != "LidarAlignedPointCloudEvidence"
            or self.aligned_point_cloud_ref.producer_stage != StageId.COLLIDER
        ):
            raise ValueError("self-mask evidence must bind the aligned point-cloud receipt")
        if self.trajectory_ref.artifact_type != "LidarTrajectory":
            raise ValueError("self-mask trajectory_ref must reference a LiDAR trajectory")
        if self.trajectory_ref.producer_stage != StageId.LIDAR_INGEST:
            raise ValueError("self-mask trajectory must be produced by LiDAR ingest")
        if self.robot_profile_ref.artifact_type != "RobotProfile":
            raise ValueError("self-mask robot_profile_ref must reference a RobotProfile")
        if self.masked_point_count >= self.point_count:
            raise ValueError("self-mask evidence cannot remove every source point")
        if self.covered_pose_count > self.total_pose_count:
            raise ValueError("self-mask covered poses cannot exceed the trajectory inventory")
        return self


class _CollisionSourceSelectionFields(ContractModel):
    """Validated selection payload before it is sealed with a checksum."""

    schema_version: Literal["1.0"] = "1.0"
    mode: CollisionSourceMode
    input_mode: CollisionInputMode
    alignment_qa_kind: CollisionAlignmentQAKind | None = None
    source_geometry_ref: ProductArtifactRef
    source_qa_ref: ProductArtifactRef
    alignment_qa_ref: ProductArtifactRef | None = None
    profile_checksum: Checksum
    config_checksum: Checksum
    effective_resolution_m: PositiveFinite
    output_collision_ref: ProductArtifactRef

    @model_validator(mode="after")
    def _check_mode(self) -> _CollisionSourceSelectionFields:
        if self.mode == CollisionSourceMode.RGB_CLEANED:
            if (
                self.input_mode != CollisionInputMode.RGB_METRIC_GEOMETRY
                or self.alignment_qa_ref is not None
                or self.alignment_qa_kind is not None
            ):
                raise ValueError("RGB collision selection requires metric RGB geometry without LiDAR alignment QA")
        else:
            if self.input_mode == CollisionInputMode.RGB_METRIC_GEOMETRY:
                raise ValueError("LiDAR collision selection requires a LiDAR input mode and alignment QA")
            expected_qa_kind = {
                CollisionInputMode.LIDAR_SENSOR_PACKAGE: CollisionAlignmentQAKind.SENSOR_CALIBRATION_TIMING,
                CollisionInputMode.LIDAR_REGISTERED_MAP: CollisionAlignmentQAKind.REGISTERED_MAP_REGISTRATION,
            }[self.input_mode]
            if self.alignment_qa_ref is None or self.alignment_qa_kind != expected_qa_kind:
                raise ValueError("LiDAR collision selection requires alignment QA bound to its input mode")
        return self


class CollisionSourceSelection(_CollisionSourceSelectionFields):
    """Immutable proposed selection bound to its source, config and output bytes."""

    selection_checksum: Checksum

    @model_validator(mode="after")
    def _check_selection_checksum(self) -> CollisionSourceSelection:
        expected = f"sha256:{hashlib.sha256(canonical_json_bytes(self, 'selection_checksum')).hexdigest()}"
        if self.selection_checksum != expected:
            raise ValueError("collision source selection checksum mismatch")
        return self


class _CollisionQualityReportFields(ContractModel):
    """Validated quality payload before it is sealed with a checksum."""

    schema_version: Literal["1.0"] = "1.0"
    source_selection_checksum: Checksum
    source_geometry_ref: ProductArtifactRef
    config_checksum: Checksum
    output_collision_ref: ProductArtifactRef
    candidate_checksum: Checksum | None = Field(default=None, exclude_if=lambda value: value is None)
    effective_collision_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    hardware_profile_ref: ProductArtifactRef
    robot_profile_ref: ProductArtifactRef
    effective_resolution_m: PositiveFinite
    robot_radius_m: PositiveFinite
    robot_height_m: PositiveFinite
    acceptance_profile_ref: ProductArtifactRef | None = None
    quality_result: CollisionQualityResult = CollisionQualityResult.NOT_EVALUATED
    free_space_proxy: ClearanceProxyEvidence | None = None
    obstacle_retention: ObstacleRetentionEvidence | None = None
    support_retention: CollisionSupportEvidence | None = None
    regions: list[CollisionRegionEvidence] = Field(default_factory=list)
    isaac_contact_ref: ProductArtifactRef | None = None
    physics_claim: CollisionPhysicsClaim = CollisionPhysicsClaim.UNVERIFIED

    @model_validator(mode="after")
    def _check_physics_claim(self) -> _CollisionQualityReportFields:
        if self.quality_result == CollisionQualityResult.NOT_EVALUATED and self.acceptance_profile_ref is not None:
            raise ValueError("unevaluated collision quality cannot bind an acceptance profile")
        if self.quality_result != CollisionQualityResult.NOT_EVALUATED and self.acceptance_profile_ref is None:
            raise ValueError("evaluated collision quality requires a frozen acceptance profile ref")
        if self.physics_claim == CollisionPhysicsClaim.VERIFIED:
            self._require_physics_evidence()
        return self

    def _require_physics_evidence(self) -> None:
        if self.quality_result != CollisionQualityResult.PASS or self.acceptance_profile_ref is None:
            raise ValueError("verified physics requires a PASS under a bound acceptance profile")
        if self.candidate_checksum is None or self.effective_collision_ref is None:
            raise ValueError("verified physics must bind the exact candidate and effective collider")
        if not self.regions or any(
            region.state != CollisionObservationState.OBSERVED_STATIC or region.coverage_fraction != 1.0
            for region in self.regions
        ):
            raise ValueError("verified physics requires fully observed static coverage for every claimed region")
        if (
            self.obstacle_retention is None
            or self.obstacle_retention.retained_obstacles != self.obstacle_retention.expected_obstacles
        ):
            raise ValueError("verified physics requires retained obstacles from an independent reference")
        if self.obstacle_retention.reference_kind in {
            CollisionReferenceKind.SAME_INPUT,
            CollisionReferenceKind.SYNTHETIC_FIXTURE,
        }:
            raise ValueError("verified physics cannot use same-input or synthetic obstacle evidence")
        if self.obstacle_retention.reference_ref.artifact_checksum == self.source_geometry_ref.artifact_checksum:
            raise ValueError("obstacle reference checksum must differ from the selected source")
        if self.support_retention is None or (
            self.support_retention.retained_support_samples != self.support_retention.expected_support_samples
        ):
            raise ValueError("verified physics requires measured floor/support retention")
        if self.support_retention.reference_kind in {
            CollisionReferenceKind.SAME_INPUT,
            CollisionReferenceKind.SYNTHETIC_FIXTURE,
        }:
            raise ValueError("verified physics cannot use same-input or synthetic support evidence")
        if self.support_retention.reference_ref.artifact_checksum == self.source_geometry_ref.artifact_checksum:
            raise ValueError("support reference checksum must differ from the selected source")
        if self.isaac_contact_ref is None:
            raise ValueError("verified physics requires exact-candidate Isaac contact evidence")
        contact_provenance = self.isaac_contact_ref.source_provenance or {}
        if (
            contact_provenance.get("candidate_checksum") != self.candidate_checksum
            or contact_provenance.get("effective_collision_checksum") != self.effective_collision_ref.artifact_checksum
        ):
            raise ValueError("Isaac contact evidence must bind the exact candidate and effective collider")


class CollisionQualityReport(_CollisionQualityReportFields):
    """Quality evidence bound to the exact selected source, config and collision output."""

    report_checksum: Checksum

    @model_validator(mode="after")
    def _check_report_checksum(self) -> CollisionQualityReport:
        expected = f"sha256:{hashlib.sha256(canonical_json_bytes(self, 'report_checksum')).hexdigest()}"
        if self.report_checksum != expected:
            raise ValueError("collision quality report checksum mismatch")
        return self


def _sealed_payload(
    model_type: type[CollisionSourceSelection] | type[CollisionQualityReport],
    draft_type: type[_CollisionSourceSelectionFields] | type[_CollisionQualityReportFields],
    checksum_field: str,
    payload: dict,
) -> CollisionSourceSelection | CollisionQualityReport:
    """Create a validated model after calculating its canonical logical checksum."""
    draft = draft_type.model_validate(payload)
    checksum = f"sha256:{hashlib.sha256(canonical_json_bytes(draft)).hexdigest()}"
    return model_type.model_validate({**draft.model_dump(mode="python"), checksum_field: checksum})


def seal_collision_source_selection(**payload: object) -> CollisionSourceSelection:
    """Validate and checksum a versioned collision source selection."""
    result = _sealed_payload(
        CollisionSourceSelection,
        _CollisionSourceSelectionFields,
        "selection_checksum",
        payload,
    )
    assert isinstance(result, CollisionSourceSelection)
    return result


def seal_collision_quality_report(**payload: object) -> CollisionQualityReport:
    """Validate and checksum a source-bound collision quality report."""
    result = _sealed_payload(
        CollisionQualityReport,
        _CollisionQualityReportFields,
        "report_checksum",
        payload,
    )
    assert isinstance(result, CollisionQualityReport)
    return result


def validate_collision_source_binding(
    environment: SceneEnvironment,
    selection: CollisionSourceSelection,
    report: CollisionQualityReport,
    *,
    selection_ref: ProductArtifactRef | None = None,
) -> None:
    """Check selected-source identity without confusing it with a carved effective collider."""
    if environment.collision_source_ref is None:
        if environment.collider_ref != selection.output_collision_ref:
            raise ValueError("SceneEnvironment collider_ref differs from selected collision output")
    else:
        if environment.collision_source_ref != selection.output_collision_ref:
            raise ValueError("SceneEnvironment collision_source_ref differs from selected collision output")
        if selection_ref is None or environment.collision_selection_ref != selection_ref:
            raise ValueError("SceneEnvironment collision_selection_ref differs from selected source record")
    if report.source_selection_checksum != selection.selection_checksum:
        raise ValueError("collision quality report belongs to a different source selection")
    if report.source_geometry_ref != selection.source_geometry_ref:
        raise ValueError("collision quality report source checksum differs from selection")
    if report.config_checksum != selection.config_checksum:
        raise ValueError("collision quality report config checksum differs from selection")
    if report.output_collision_ref != selection.output_collision_ref:
        raise ValueError("collision quality report output checksum differs from selection")
    if report.effective_collision_ref is not None and report.effective_collision_ref != environment.collider_ref:
        raise ValueError("collision quality report effective collider differs from SceneEnvironment")
