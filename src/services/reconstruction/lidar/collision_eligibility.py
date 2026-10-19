"""Fail-closed source eligibility before any LiDAR collision candidate is built."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionInputMode,
    LidarAlignedPointCloudEvidence,
    LidarSelfMaskEvidence,
)
from src.models.contracts.coordinates import MetricScaleStatus
from src.models.contracts.floor_model import FloorFitEvidence
from src.models.contracts.lidar_calibration_qa import (
    LidarCalibrationObservability,
    LidarCalibrationQAReport,
    LidarCalibrationQAResult,
)
from src.models.contracts.lidar_projection_qa import LidarCalibrationProjectionEvidence
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    AlignmentRecord,
    AlignmentStatus,
    ReconstructionBundle,
)
from src.services.reconstruction.adapters.lidar_collision import LidarCollisionProfile
from src.services.reconstruction.lidar.calibration_qa import is_sensor_package_collision_eligible
from src.services.reconstruction.lidar.package import LidarPackageRecord


class CollisionEligibilityBlockerCode(StrEnum):
    """Stable reasons why the source cannot reach candidate construction."""

    INPUT_MODE_UNSUPPORTED = "INPUT_MODE_UNSUPPORTED"
    REGISTERED_MAP_QA_UNAVAILABLE = "REGISTERED_MAP_QA_UNAVAILABLE"
    BUNDLE_MISSING = "BUNDLE_MISSING"
    BUNDLE_SOURCE_MISMATCH = "BUNDLE_SOURCE_MISMATCH"
    ALIGNMENT_UNCONFIRMED = "ALIGNMENT_UNCONFIRMED"
    PACKAGE_MISSING = "PACKAGE_MISSING"
    PACKAGE_REFERENCE_INVALID = "PACKAGE_REFERENCE_INVALID"
    PACKAGE_RECORD_INVALID = "PACKAGE_RECORD_INVALID"
    PACKAGE_MODE_MISMATCH = "PACKAGE_MODE_MISMATCH"
    CALIBRATION_QA_MISSING = "CALIBRATION_QA_MISSING"
    CALIBRATION_QA_REFERENCE_INVALID = "CALIBRATION_QA_REFERENCE_INVALID"
    CALIBRATION_QA_SOURCE_MISMATCH = "CALIBRATION_QA_SOURCE_MISMATCH"
    CALIBRATION_QA_NOT_PASS = "CALIBRATION_QA_NOT_PASS"
    PROJECTION_EVIDENCE_MISSING = "PROJECTION_EVIDENCE_MISSING"
    PROJECTION_EVIDENCE_REFERENCE_INVALID = "PROJECTION_EVIDENCE_REFERENCE_INVALID"
    PROJECTION_EVIDENCE_SOURCE_MISMATCH = "PROJECTION_EVIDENCE_SOURCE_MISMATCH"
    PROJECTION_EVIDENCE_NOT_SCORED = "PROJECTION_EVIDENCE_NOT_SCORED"
    PROJECTION_EVIDENCE_DIAGNOSTIC_ONLY = "PROJECTION_EVIDENCE_DIAGNOSTIC_ONLY"
    FLOOR_EVIDENCE_MISSING = "FLOOR_EVIDENCE_MISSING"
    FLOOR_EVIDENCE_REFERENCE_INVALID = "FLOOR_EVIDENCE_REFERENCE_INVALID"
    FLOOR_EVIDENCE_SOURCE_MISMATCH = "FLOOR_EVIDENCE_SOURCE_MISMATCH"
    FLOOR_MODEL_UNSUPPORTED = "FLOOR_MODEL_UNSUPPORTED"
    SELF_MASK_EVIDENCE_MISSING = "SELF_MASK_EVIDENCE_MISSING"
    SELF_MASK_EVIDENCE_REFERENCE_INVALID = "SELF_MASK_EVIDENCE_REFERENCE_INVALID"
    SELF_MASK_EVIDENCE_SOURCE_MISMATCH = "SELF_MASK_EVIDENCE_SOURCE_MISMATCH"
    ALIGNED_POINT_CLOUD_EVIDENCE_MISSING = "ALIGNED_POINT_CLOUD_EVIDENCE_MISSING"
    ALIGNED_POINT_CLOUD_EVIDENCE_REFERENCE_INVALID = "ALIGNED_POINT_CLOUD_EVIDENCE_REFERENCE_INVALID"
    ALIGNED_POINT_CLOUD_EVIDENCE_SOURCE_MISMATCH = "ALIGNED_POINT_CLOUD_EVIDENCE_SOURCE_MISMATCH"
    COLLISION_PROFILE_MISSING = "COLLISION_PROFILE_MISSING"


class CollisionEligibilityBlocker(ContractModel):
    code: CollisionEligibilityBlockerCode
    detail: str = Field(min_length=1)
    evidence_ref: ProductArtifactRef | None = None


class LidarCollisionEligibilityAssessment(ContractModel):
    """Pure decision record; an eligible assessment still does not publish/select a source."""

    state: Literal["eligible", "blocked"]
    input_mode: CollisionInputMode
    source_geometry_ref: ProductArtifactRef | None = None
    profile_checksum: Checksum | None = None
    evidence_refs: list[ProductArtifactRef] = Field(default_factory=list)
    blockers: list[CollisionEligibilityBlocker] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_state(self) -> Self:
        if self.state == "eligible" and (
            self.blockers or self.source_geometry_ref is None or self.profile_checksum is None
        ):
            raise ValueError("eligible collision assessment requires exact source/profile refs and no blockers")
        if self.state == "blocked" and not self.blockers:
            raise ValueError("blocked collision assessment requires at least one blocker")
        return self


@dataclass(frozen=True)
class LidarCollisionEligibilityInputs:
    """Resolved records plus a receipt for the exact aligned point-cloud identity."""

    input_mode: CollisionInputMode
    bundle: ReconstructionBundle | None
    package_ref: ProductArtifactRef | None
    package: LidarPackageRecord | None
    calibration_qa_ref: ProductArtifactRef | None
    calibration_qa: LidarCalibrationQAReport | None
    projection_evidence_ref: ProductArtifactRef | None
    projection_evidence: LidarCalibrationProjectionEvidence | None
    aligned_point_cloud_ref: ProductArtifactRef | None
    aligned_point_cloud: LidarAlignedPointCloudEvidence | None
    floor_evidence_ref: ProductArtifactRef | None
    floor_evidence: FloorFitEvidence | None
    self_mask_evidence_ref: ProductArtifactRef | None
    self_mask_evidence: LidarSelfMaskEvidence | None
    profile: LidarCollisionProfile | None


def evaluate_lidar_collision_eligibility(
    inputs: LidarCollisionEligibilityInputs,
) -> LidarCollisionEligibilityAssessment:
    """Cross-bind source QA and geometry before candidate allocation or source selection.

    The resolver must supply checksum-verified records. This function checks their
    serialized identity and cross-references; it does not read point clouds, build a
    mesh, publish artifacts, rewrite trajectories, or fall back to RGB.
    """
    blockers: list[CollisionEligibilityBlocker] = []
    evidence_refs: list[ProductArtifactRef] = []

    def block(
        code: CollisionEligibilityBlockerCode,
        detail: str,
        reference: ProductArtifactRef | None = None,
    ) -> None:
        if not any(item.code == code and item.evidence_ref == reference for item in blockers):
            blockers.append(CollisionEligibilityBlocker(code=code, detail=detail, evidence_ref=reference))

    def keep(reference: ProductArtifactRef | None) -> None:
        if reference is not None and reference not in evidence_refs:
            evidence_refs.append(reference)

    bundle = inputs.bundle
    package = inputs.package
    package_ref = inputs.package_ref
    geometry_ref = bundle.lidar_geometry_ref if bundle is not None else None
    keep(bundle_ref(bundle))
    keep(geometry_ref)
    keep(package_ref)
    keep(inputs.calibration_qa_ref)
    keep(inputs.projection_evidence_ref)
    keep(inputs.aligned_point_cloud_ref)
    keep(inputs.floor_evidence_ref)
    keep(inputs.self_mask_evidence_ref)

    if inputs.input_mode == CollisionInputMode.LIDAR_REGISTERED_MAP:
        block(
            CollisionEligibilityBlockerCode.REGISTERED_MAP_QA_UNAVAILABLE,
            "Registered-map registration QA is not production-qualified; AUD-19 must supply the mode-specific receipt.",
        )
    elif inputs.input_mode != CollisionInputMode.LIDAR_SENSOR_PACKAGE:
        block(
            CollisionEligibilityBlockerCode.INPUT_MODE_UNSUPPORTED,
            "This gate only assesses LiDAR source modes; RGB collision cleanup uses its own quality route.",
        )

    confirmed_alignment_ref: ProductArtifactRef | None = None
    if bundle is None:
        block(CollisionEligibilityBlockerCode.BUNDLE_MISSING, "No checksum-verified ReconstructionBundle was supplied.")
    elif (
        not bundle.input_configuration.rgb_present
        or not bundle.input_configuration.registered_lidar_present
        or bundle.rgb_geometry_ref is None
        or bundle.lidar_geometry_ref is None
        or bundle.canonical_geometry_ref != bundle.rgb_geometry_ref
        or bundle.metric_scale.status != MetricScaleStatus.CONFIRMED
        or bundle.metric_scale.meters_per_unit != 1.0
        or not _valid_ref(bundle.rgb_geometry_ref, "RgbGeometry", StageId.RGB_GEOMETRY, bundle.job_id)
        or not _valid_ref(bundle.lidar_geometry_ref, "LiDARGeometryArtifact", StageId.LIDAR_INGEST, bundle.job_id)
    ):
        block(
            CollisionEligibilityBlockerCode.BUNDLE_SOURCE_MISMATCH,
            "The bundle must bind RGB canonical geometry and the exact LiDAR geometry without replacing the RGB source.",
            geometry_ref,
        )
    else:
        alignment = bundle.alignment_record
        if (
            alignment is None
            or alignment.status != AlignmentStatus.CONFIRMED
            or alignment.job_id != bundle.job_id
            or not _valid_ref(alignment_reference(alignment), "AlignmentRecord", StageId.RGB_LIDAR_ALIGN, bundle.job_id)
            or alignment.source_lidar_checksum != bundle.lidar_geometry_ref.artifact_checksum
            or alignment.target_rgb_geometry_checksum != bundle.rgb_geometry_ref.artifact_checksum
            or alignment.transform_target_from_source.parent_frame != "world"
            or not alignment.evidence_refs
            or any(
                reference.job_id != bundle.job_id
                or not reference.artifact_uri.startswith(f"artifact://jobs/{bundle.job_id}/")
                for reference in alignment.evidence_refs
            )
        ):
            block(
                CollisionEligibilityBlockerCode.ALIGNMENT_UNCONFIRMED,
                "The bundle lacks a confirmed same-job transform for its exact LiDAR and RGB geometry checksums.",
                geometry_ref,
            )
        else:
            confirmed_alignment_ref = alignment_reference(alignment)
            keep(confirmed_alignment_ref)

    if package is None or package_ref is None:
        block(
            CollisionEligibilityBlockerCode.PACKAGE_MISSING,
            "A resolved LidarPackageRecord and its exact ref are required.",
        )
    else:
        package_payload = package.model_dump_json(indent=2).encode("utf-8") + b"\n"
        package_valid = (
            _valid_ref(
                package_ref,
                "LidarPackageRecord",
                StageId.LIDAR_INGEST,
                package.job_id,
                package.schema_version,
            )
            and package_ref.artifact_checksum == _sha256(package_payload)
            and package.record_checksum == _canonical_record_checksum(package)
        )
        if not package_valid:
            block(
                CollisionEligibilityBlockerCode.PACKAGE_REFERENCE_INVALID,
                "Package ref, serialized bytes, or record checksum do not identify the supplied package record.",
                package_ref,
            )
        if (
            bundle is None
            or bundle.job_id != package.job_id
            or bundle.lidar_geometry_ref != package.lidar_geometry_ref
            or not _valid_ref(package.lidar_geometry_ref, "LiDARGeometryArtifact", StageId.LIDAR_INGEST, package.job_id)
            or not _valid_ref(package.trajectory_ref, "LidarTrajectory", StageId.LIDAR_INGEST, package.job_id)
            or not _valid_ref(package.frame_times_ref, "LidarFrameTimes", StageId.LIDAR_INGEST, package.job_id)
        ):
            block(
                CollisionEligibilityBlockerCode.PACKAGE_RECORD_INVALID,
                "Package and bundle must bind the same job and exact LiDAR geometry artifact.",
                package_ref,
            )
        if package.kind != "lidar_scan_sequence":
            block(
                CollisionEligibilityBlockerCode.PACKAGE_MODE_MISMATCH,
                "Sensor calibration/timing QA requires per-pose scan data; registered maps must use the AUD-19 route.",
                package_ref,
            )

    aligned_points = inputs.aligned_point_cloud
    aligned_points_ref = inputs.aligned_point_cloud_ref
    point_checksum: Checksum | None = None
    point_count: int | None = None
    if aligned_points is None or aligned_points_ref is None:
        block(
            CollisionEligibilityBlockerCode.ALIGNED_POINT_CLOUD_EVIDENCE_MISSING,
            "A point-cloud receipt binding the exact source and confirmed world alignment is required.",
        )
    elif package is not None and geometry_ref is not None:
        aligned_payload = aligned_points.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if not _valid_ref(
            aligned_points_ref,
            "LidarAlignedPointCloudEvidence",
            StageId.COLLIDER,
            package.job_id,
            aligned_points.schema_version,
        ) or aligned_points_ref.artifact_checksum != _sha256(aligned_payload):
            block(
                CollisionEligibilityBlockerCode.ALIGNED_POINT_CLOUD_EVIDENCE_REFERENCE_INVALID,
                "Aligned point-cloud ref does not identify its exact serialized evidence receipt.",
                aligned_points_ref,
            )
        if (
            aligned_points.job_id != package.job_id
            or aligned_points.source_geometry_ref != geometry_ref
            or aligned_points.alignment_ref != confirmed_alignment_ref
            or aligned_points.point_count != package.point_count
            or aligned_points.frame != "world"
            or aligned_points.distance_unit != "m"
        ):
            block(
                CollisionEligibilityBlockerCode.ALIGNED_POINT_CLOUD_EVIDENCE_SOURCE_MISMATCH,
                "Aligned points must retain every package point and bind its exact geometry/alignment in world meters.",
                aligned_points_ref,
            )
        point_checksum = aligned_points.point_cloud_checksum
        point_count = aligned_points.point_count

    if inputs.calibration_qa is None or inputs.calibration_qa_ref is None:
        block(
            CollisionEligibilityBlockerCode.CALIBRATION_QA_MISSING,
            "A resolved calibration/timing QA report and exact artifact ref are required.",
        )
    elif package is not None and package_ref is not None:
        report = inputs.calibration_qa
        report_ref = inputs.calibration_qa_ref
        report_payload = report.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if not _valid_ref(
            report_ref,
            "LidarCalibrationQAReport",
            StageId.LIDAR_CALIBRATION_QA,
            package.job_id,
            report.schema_version,
        ) or report_ref.artifact_checksum != _sha256(report_payload):
            block(
                CollisionEligibilityBlockerCode.CALIBRATION_QA_REFERENCE_INVALID,
                "Calibration QA ref does not identify the exact serialized report for this package job.",
                report_ref,
            )
        if (
            report.package_ref != package_ref
            or report.input_checksum != package_ref.artifact_checksum
            or report.calibration_ref != package.calibration_ref
            or report.trajectory_ref != package.trajectory_ref
            or report.timing_ref != package.frame_times_ref
            or (report.intrinsics_ref is not None and report.intrinsics_ref.job_id != package.job_id)
            or (report.rgb_frame_set_ref is not None and report.rgb_frame_set_ref.job_id != package.job_id)
            or report.timestamp_unit != "seconds"
            or report.coordinate_unit != "m"
            or report.clock_relation in {None, "unknown"}
            or report.clock_offset_seconds is None
            or report.maximum_timestamp_residual_sec is None
            or report.maximum_timestamp_residual_sec > report.profile.maximum_timestamp_residual_sec
        ):
            block(
                CollisionEligibilityBlockerCode.CALIBRATION_QA_SOURCE_MISMATCH,
                "Calibration/timing QA must bind this package, calibration, trajectory, and timing artifact exactly.",
                report_ref,
            )
        if (
            report.result != LidarCalibrationQAResult.PASS
            or report.observability != LidarCalibrationObservability.READY_FOR_SCORING
            or report.projection_evidence_ref is None
        ):
            block(
                CollisionEligibilityBlockerCode.CALIBRATION_QA_NOT_PASS,
                "Calibration/timing QA is not a scored PASS with a qualified projection receipt.",
                report_ref,
            )

    if inputs.projection_evidence is None or inputs.projection_evidence_ref is None:
        block(
            CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_MISSING,
            "A resolved projection receipt is required; the diagnostic overlay ref is not a qualification receipt.",
            inputs.calibration_qa_ref,
        )
    elif inputs.calibration_qa is not None and package is not None:
        projection = inputs.projection_evidence
        projection_ref = inputs.projection_evidence_ref
        projection_payload = projection.model_dump_json(indent=2).encode("utf-8") + b"\n"
        expected_ref = inputs.calibration_qa.projection_evidence_ref
        if (
            not _valid_ref(
                projection_ref,
                "LidarCalibrationProjectionEvidence",
                StageId.LIDAR_CALIBRATION_QA,
                package.job_id,
                projection.schema_version,
            )
            or projection_ref.artifact_checksum != _sha256(projection_payload)
            or projection_ref != expected_ref
        ):
            block(
                CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_REFERENCE_INVALID,
                "The supplied projection receipt is not the exact projection ref bound by the QA report.",
                projection_ref,
            )
        if (
            projection.package_ref != inputs.calibration_qa.package_ref
            or projection.calibration_ref != package.calibration_ref
            or projection.trajectory_ref != package.trajectory_ref
            or projection.timing_ref != package.frame_times_ref
            or projection.intrinsics_ref != inputs.calibration_qa.intrinsics_ref
            or projection.rgb_frame_set_ref != inputs.calibration_qa.rgb_frame_set_ref
            or projection.qa_profile.config_checksum != inputs.calibration_qa.config_checksum
        ):
            block(
                CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_SOURCE_MISMATCH,
                "Projection evidence must bind the exact package, calibration, trajectory, timing, and QA profile.",
                projection_ref,
            )
        if projection.scoring_status != "SCORED":
            block(
                CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_NOT_SCORED,
                "Projection evidence is inconclusive and cannot qualify calibration for collision use.",
                projection_ref,
            )
        if projection.qualification_status != "production_qualified":
            block(
                CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_DIAGNOSTIC_ONLY,
                "Current projection evidence is diagnostic-only; production thresholds and held-out capture qualification are absent.",
                projection_ref,
            )
        if not is_sensor_package_collision_eligible(report, projection_ref, projection):
            block(
                CollisionEligibilityBlockerCode.CALIBRATION_QA_NOT_PASS,
                "The calibration report is not linked to this exact scored, production-qualified projection receipt.",
                report_ref,
            )

    if inputs.floor_evidence is None or inputs.floor_evidence_ref is None:
        block(
            CollisionEligibilityBlockerCode.FLOOR_EVIDENCE_MISSING,
            "A resolved FloorFitEvidence record bound to the LiDAR point ordering is required.",
        )
    elif (
        package is not None
        and aligned_points_ref is not None
        and point_checksum is not None
        and point_count is not None
    ):
        floor = inputs.floor_evidence
        floor_ref = inputs.floor_evidence_ref
        floor_payload = floor.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if not _valid_ref(
            floor_ref, "FloorFitEvidence", StageId.OBJECT_EXTRACT, package.job_id, floor.schema_version
        ) or floor_ref.artifact_checksum != _sha256(floor_payload):
            block(
                CollisionEligibilityBlockerCode.FLOOR_EVIDENCE_REFERENCE_INVALID,
                "Floor evidence ref does not identify the exact serialized floor-fit record.",
                floor_ref,
            )
        if (
            floor.job_id != package.job_id
            or floor.source_artifact_ref != aligned_points_ref
            or floor.point_cloud_checksum != point_checksum
            or floor.floor_model.source_checksum != point_checksum
            or floor.floor_model.point_count != point_count
        ):
            block(
                CollisionEligibilityBlockerCode.FLOOR_EVIDENCE_SOURCE_MISMATCH,
                "Floor evidence must bind the exact LiDAR geometry bytes, point ordering, and point count.",
                floor_ref,
            )
        if (
            floor.floor_model.status != "supported"
            or floor.floor_model.frame != "world"
            or floor.floor_model.distance_unit != "m"
        ):
            block(
                CollisionEligibilityBlockerCode.FLOOR_MODEL_UNSUPPORTED,
                "Collision generation requires a supported measured floor plane in canonical world meters.",
                floor_ref,
            )
    else:
        block(
            CollisionEligibilityBlockerCode.FLOOR_EVIDENCE_SOURCE_MISMATCH,
            "The exact aligned point-cloud receipt, checksum, and count are required to verify floor evidence.",
            inputs.floor_evidence_ref,
        )

    if inputs.self_mask_evidence is None or inputs.self_mask_evidence_ref is None:
        block(
            CollisionEligibilityBlockerCode.SELF_MASK_EVIDENCE_MISSING,
            "A resolved sensor-frame self-mask receipt is required before constructing a sensor-package collider.",
        )
    elif package is not None and package_ref is not None and geometry_ref is not None:
        mask = inputs.self_mask_evidence
        mask_ref = inputs.self_mask_evidence_ref
        mask_payload = mask.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if not _valid_ref(
            mask_ref, "LidarSelfMaskEvidence", StageId.COLLIDER, package.job_id, mask.schema_version
        ) or mask_ref.artifact_checksum != _sha256(mask_payload):
            block(
                CollisionEligibilityBlockerCode.SELF_MASK_EVIDENCE_REFERENCE_INVALID,
                "Self-mask ref does not identify the exact serialized, typed evidence artifact.",
                mask_ref,
            )
        if (
            mask.job_id != package.job_id
            or mask.package_ref != package_ref
            or mask.source_geometry_ref != geometry_ref
            or mask.alignment_ref != confirmed_alignment_ref
            or mask.aligned_point_cloud_ref != aligned_points_ref
            or mask.trajectory_ref != package.trajectory_ref
            or mask.point_count != point_count
            or mask.source_point_checksum != point_checksum
            or mask.covered_pose_count != package.pose_count
            or mask.total_pose_count != package.pose_count
        ):
            block(
                CollisionEligibilityBlockerCode.SELF_MASK_EVIDENCE_SOURCE_MISMATCH,
                "Self-mask evidence must cover every package pose and the exact LiDAR geometry point ordering.",
                mask_ref,
            )

    if inputs.profile is None:
        block(
            CollisionEligibilityBlockerCode.COLLISION_PROFILE_MISSING,
            "An immutable, resource-bounded collision profile is required.",
        )

    return LidarCollisionEligibilityAssessment(
        state="eligible" if not blockers else "blocked",
        input_mode=inputs.input_mode,
        source_geometry_ref=geometry_ref,
        profile_checksum=inputs.profile.checksum() if inputs.profile is not None else None,
        evidence_refs=evidence_refs,
        blockers=blockers,
    )


def bundle_ref(bundle: ReconstructionBundle | None) -> ProductArtifactRef | None:
    """Return the bundle's published identity in the generic artifact-ref form."""
    if bundle is None:
        return None
    return ProductArtifactRef(
        artifact_type=bundle.artifact_type,
        schema_version=bundle.schema_version,
        artifact_uri=bundle.artifact_uri,
        artifact_checksum=bundle.artifact_checksum,
        data_class="derived",
        producer_stage=bundle.producer_stage,
        job_id=bundle.job_id,
        source_provenance=bundle.provenance,
    )


def alignment_reference(record: AlignmentRecord) -> ProductArtifactRef:
    """Return the exact alignment record identity carried in a bundle."""
    return ProductArtifactRef(
        artifact_type=record.artifact_type,
        schema_version=record.schema_version,
        artifact_uri=record.artifact_uri,
        artifact_checksum=record.artifact_checksum,
        data_class="derived",
        producer_stage=record.producer_stage,
        job_id=record.job_id,
        source_provenance=record.provenance,
    )


def _valid_ref(
    reference: ProductArtifactRef,
    artifact_type: str,
    stage: StageId,
    job_id: str,
    schema_version: str = "1.0",
) -> bool:
    return (
        reference.artifact_type == artifact_type
        and reference.schema_version == schema_version
        and reference.producer_stage == stage
        and reference.job_id == job_id
        and reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/")
    )


def _sha256(payload: bytes) -> Checksum:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_record_checksum(package: LidarPackageRecord) -> Checksum:
    from src.models.contracts.identity import canonical_content_checksum

    return canonical_content_checksum(package, "record_checksum")
