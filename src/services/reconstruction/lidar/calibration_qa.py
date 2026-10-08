"""Structural and observability checks for calibrated RGB/LiDAR sensor packages."""

import math
from typing import Literal

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel, ProductArtifactRef
from src.models.contracts.input_assembly import ClockRelation, DistanceUnit, EvidenceValue
from src.models.contracts.lidar_calibration_qa import (
    LidarCalibrationFindingCode,
    LidarCalibrationFrameObservation,
    LidarCalibrationObservability,
    LidarCalibrationQAConfig,
    LidarCalibrationQAFinding,
    LidarCalibrationQAReport,
    LidarCalibrationQAResult,
    seal_lidar_calibration_qa_report,
)
from src.services.reconstruction.lidar.package import CAMERA_FRAME, SENSOR_FRAME, CameraCalibration, LidarPackageRecord


class LidarCalibrationQAInput(ContractModel):
    """Exact package record and external declarations needed before projection scoring."""

    package_ref: ProductArtifactRef
    package: LidarPackageRecord
    rgb_frame_set_ref: ProductArtifactRef | None = None
    camera: CameraCalibration | None = None
    intrinsics_ref: ProductArtifactRef | None = None
    coordinate_unit: EvidenceValue[DistanceUnit] | None = None
    timestamp_unit: str | None = None
    clock_relation: EvidenceValue[ClockRelation] | None = None
    #: Sign convention: `rgb_timestamp = lidar_timestamp + clock_offset_seconds`.
    clock_offset_seconds: EvidenceValue[FiniteFloat] | None = None
    observations: list[LidarCalibrationFrameObservation] = Field(default_factory=list)


def _rotation_matrix(quaternion: tuple[float, float, float, float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def _finding(
    code: LidarCalibrationFindingCode,
    severity: Literal["fail", "inconclusive"],
    detail: str,
    remediation: str,
) -> LidarCalibrationQAFinding:
    return LidarCalibrationQAFinding(code=code, severity=severity, detail=detail, remediation=remediation)


def evaluate_lidar_calibration_qa(
    inputs: LidarCalibrationQAInput,
    config: LidarCalibrationQAConfig,
) -> LidarCalibrationQAReport:
    """Reject malformed source facts and report observability without claiming projection accuracy.

    A report cannot PASS in this sprint. Projection metrics and qualification belong to AUD-13.S2.
    """
    failures: list[LidarCalibrationQAFinding] = []
    uncertainties: list[LidarCalibrationQAFinding] = []
    package = inputs.package
    calibration_ref = package.calibration_ref
    timing_ref = package.frame_times_ref

    def fail(code: LidarCalibrationFindingCode, detail: str, remediation: str) -> None:
        failures.append(_finding(code, "fail", detail, remediation))

    def inconclusive(code: LidarCalibrationFindingCode, detail: str, remediation: str) -> None:
        uncertainties.append(_finding(code, "inconclusive", detail, remediation))

    if inputs.package_ref.artifact_type != "LidarPackageRecord" or inputs.package_ref.job_id != package.job_id:
        fail(
            LidarCalibrationFindingCode.PACKAGE_REFERENCE_INVALID,
            "Package reference type or job identity does not match the supplied LidarPackageRecord.",
            "Resolve the package record from the same job and bind its exact artifact reference.",
        )
    if inputs.intrinsics_ref is not None and inputs.intrinsics_ref.job_id != package.job_id:
        fail(
            LidarCalibrationFindingCode.INTRINSICS_SOURCE_MISSING,
            "Intrinsics reference belongs to a different job than the LiDAR package.",
            "Bind intrinsics from the exact reconstruction attempt that consumes this package.",
        )
    if inputs.rgb_frame_set_ref is not None and inputs.rgb_frame_set_ref.job_id != package.job_id:
        fail(
            LidarCalibrationFindingCode.RGB_FRAME_SET_MISSING,
            "RGB frame-set reference belongs to a different job than the LiDAR package.",
            "Bind the frame-set artifact from the same job and selected input recipe.",
        )

    transform = package.sensor_from_camera
    if (
        transform.semantics != "parent_from_local"
        or transform.parent_frame != SENSOR_FRAME
        or transform.local_frame != CAMERA_FRAME
    ):
        fail(
            LidarCalibrationFindingCode.TRANSFORM_DIRECTION_INVALID,
            f"Expected T_{SENSOR_FRAME}_from_{CAMERA_FRAME}; received {transform.canonical_name}.",
            "Supply the sensor-from-camera transform. Do not invert or rename frames by assumption.",
        )
    transform_values = (*transform.translation_xyz, *transform.rotation_quaternion_xyzw)
    if not all(math.isfinite(value) for value in transform_values):
        fail(
            LidarCalibrationFindingCode.TRANSFORM_NONFINITE,
            "Calibration transform contains a non-finite translation or quaternion component.",
            "Correct the source calibration and ingest it as a new immutable input.",
        )
    else:
        quaternion_norm = math.sqrt(sum(value * value for value in transform.rotation_quaternion_xyzw))
        rotation = _rotation_matrix(transform.rotation_quaternion_xyzw)
        determinant = float(np.linalg.det(rotation))
        orthogonality_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
        if (
            not math.isclose(quaternion_norm, 1.0, rel_tol=1e-6, abs_tol=1e-6)
            or not math.isclose(determinant, 1.0, rel_tol=1e-6, abs_tol=1e-6)
            or orthogonality_error > 1e-6
        ):
            fail(
                LidarCalibrationFindingCode.TRANSFORM_NOT_SE3,
                "Calibration rotation is not a normalized proper SE(3) rotation with determinant +1.",
                "Provide a finite normalized xyzw quaternion representing a rigid transform.",
            )

    coordinate_unit = inputs.coordinate_unit.value if inputs.coordinate_unit else None
    if inputs.coordinate_unit is None:
        inconclusive(
            LidarCalibrationFindingCode.TRANSLATION_UNIT_MISSING,
            "No evidence declares the calibration translation unit.",
            "Declare the source unit explicitly; the QA stage does not infer meters from numeric magnitude.",
        )
    elif coordinate_unit != DistanceUnit.METER:
        fail(
            LidarCalibrationFindingCode.TRANSLATION_UNIT_UNSUPPORTED,
            f"Calibration translation unit is {coordinate_unit.value}; this profile accepts meter-valued transforms only.",
            "Convert the calibration once using an explicit unit conversion, then ingest a new package identity.",
        )

    if calibration_ref is None:
        inconclusive(
            LidarCalibrationFindingCode.CALIBRATION_SOURCE_MISSING,
            "This package record does not retain the exact calibration artifact reference.",
            "Re-ingest the package with a version that publishes the calibration source artifact.",
        )
    if inputs.camera is None:
        inconclusive(
            LidarCalibrationFindingCode.CAMERA_INTRINSICS_MISSING,
            "Camera intrinsics are not available for projection QA.",
            "Provide calibrated intrinsics or run this QA after COLMAP has published its camera model.",
        )
    elif inputs.intrinsics_ref is None:
        inconclusive(
            LidarCalibrationFindingCode.INTRINSICS_SOURCE_MISSING,
            "Intrinsics values have no source artifact reference.",
            "Bind the camera model to its calibration or COLMAP artifact checksum.",
        )
    elif inputs.camera.distortion_status != "declared":
        inconclusive(
            LidarCalibrationFindingCode.DISTORTION_UNAVAILABLE,
            f"Lens distortion is {inputs.camera.distortion_status}; zero-filled compatibility values are not QA evidence.",
            "Provide all four supported OpenCV distortion coefficients or a qualified zero-distortion declaration.",
        )

    if inputs.rgb_frame_set_ref is None:
        inconclusive(
            LidarCalibrationFindingCode.RGB_FRAME_SET_MISSING,
            "No exact sampled RGB frame-set reference is available.",
            "Provide the normalized frame-set artifact used by the reconstruction.",
        )
    if inputs.timestamp_unit is None:
        inconclusive(
            LidarCalibrationFindingCode.TIMING_UNIT_MISSING,
            "Timestamp units are not declared.",
            "Declare timestamps in seconds before comparing camera frames with LiDAR poses.",
        )
    elif inputs.timestamp_unit != "seconds":
        fail(
            LidarCalibrationFindingCode.TIMING_UNIT_UNSUPPORTED,
            f"Timestamp unit is {inputs.timestamp_unit!r}; the QA profile accepts seconds only.",
            "Convert timestamps to seconds with an explicit source conversion and preserve the original artifact.",
        )

    relation = inputs.clock_relation.value if inputs.clock_relation else None
    offset = inputs.clock_offset_seconds.value if inputs.clock_offset_seconds else None
    if inputs.clock_relation is None or relation == ClockRelation.UNKNOWN:
        inconclusive(
            LidarCalibrationFindingCode.CLOCK_RELATION_MISSING,
            "Camera and LiDAR clock relation is absent or unknown.",
            "Declare a shared clock or provide a measured clock offset with its evidence source.",
        )
    if offset is None:
        inconclusive(
            LidarCalibrationFindingCode.CLOCK_OFFSET_MISSING,
            "No explicit camera-to-LiDAR time offset is available.",
            "Provide a measured offset; do not treat an absent offset as zero.",
        )
    elif relation == ClockRelation.SAME_CLOCK and not math.isclose(offset, 0.0, abs_tol=1e-9):
        fail(
            LidarCalibrationFindingCode.CLOCK_OFFSET_CONFLICT,
            "A non-zero offset conflicts with the declared same-clock relation.",
            "Correct either the clock relation or the offset evidence.",
        )

    observations = inputs.observations
    rgb_ids = [row.rgb_frame_id for row in observations]
    rgb_times = [row.rgb_timestamp_sec for row in observations]
    if rgb_ids != sorted(set(rgb_ids)) or any(later <= earlier for earlier, later in zip(rgb_times, rgb_times[1:])):
        fail(
            LidarCalibrationFindingCode.TIMESTAMP_ORDER_INVALID,
            "Sampled RGB frame IDs and timestamps must be strictly increasing and unique.",
            "Rebuild the sampled frame map from ordered source timestamps.",
        )

    matched = [row for row in observations if row.lidar_pose_id is not None]
    lidar_pose_ids = [row.lidar_pose_id for row in matched]
    lidar_times = [row.lidar_timestamp_sec for row in matched]
    if (
        len(lidar_pose_ids) != len(set(lidar_pose_ids))
        or any(pose_id >= package.pose_count for pose_id in lidar_pose_ids)
        or lidar_pose_ids != sorted(lidar_pose_ids)
        or any(later <= earlier for earlier, later in zip(lidar_times, lidar_times[1:]))
    ):
        fail(
            LidarCalibrationFindingCode.FRAME_MAPPING_INVALID,
            "Matched LiDAR pose IDs must be unique, ordered, and within the package trajectory inventory.",
            "Correct the RGB-to-trajectory frame map and preserve source frame IDs after video normalization.",
        )

    timestamp_residuals: list[float] = []
    if offset is not None and inputs.timestamp_unit == "seconds":
        timestamp_residuals = [
            abs(float(row.rgb_timestamp_sec) - float(row.lidar_timestamp_sec) - offset)
            for row in matched
            if row.lidar_timestamp_sec is not None
        ]
        if any(value > config.maximum_timestamp_residual_sec for value in timestamp_residuals):
            fail(
                LidarCalibrationFindingCode.TIMESTAMP_RESIDUAL_EXCEEDED,
                "At least one matched RGB/LiDAR timestamp exceeds the profile residual bound.",
                "Correct frame pairing or remeasure the clock offset; do not tune the QA threshold on held-out data.",
            )

    if len(observations) < config.minimum_sampled_frames:
        inconclusive(
            LidarCalibrationFindingCode.INSUFFICIENT_SAMPLED_FRAMES,
            f"Only {len(observations)} sampled RGB frames are available; profile requires {config.minimum_sampled_frames}.",
            "Sample more temporally distributed frames under a qualified profile.",
        )
    if len(matched) < config.minimum_matched_frames:
        inconclusive(
            LidarCalibrationFindingCode.INSUFFICIENT_MATCHED_FRAMES,
            f"Only {len(matched)} frames map to LiDAR poses; profile requires {config.minimum_matched_frames}.",
            "Provide a complete, checksum-bound RGB-to-LiDAR frame map.",
        )

    projected_total = sum(row.projected_point_count for row in matched)
    overlap_total = sum(row.overlap_point_count for row in matched)
    observable_count = sum(
        row.projected_point_count >= config.minimum_projected_points_per_frame
        and row.overlap_point_count / row.projected_point_count >= config.minimum_overlap_fraction
        for row in matched
        if row.projected_point_count > 0
    )
    if not any(row.projected_point_count >= config.minimum_projected_points_per_frame for row in matched):
        inconclusive(
            LidarCalibrationFindingCode.INSUFFICIENT_PROJECTED_POINTS,
            "No sampled frame meets the profile's minimum projectable point count.",
            "Choose frames and cloud coverage that provide enough visible projected LiDAR points.",
        )
    if observable_count < config.minimum_overlapping_frames:
        inconclusive(
            LidarCalibrationFindingCode.INSUFFICIENT_OVERLAP,
            f"Only {observable_count} frames meet the overlap profile; {config.minimum_overlapping_frames} are required.",
            "Use a sequence with more static, jointly visible structure; do not infer a calibration score from empty overlap.",
        )

    structural_failure = bool(failures)
    metadata_available = all(
        (
            calibration_ref is not None,
            inputs.camera is not None,
            inputs.intrinsics_ref is not None,
            inputs.camera is not None and inputs.camera.distortion_status == "declared",
            inputs.rgb_frame_set_ref is not None,
            inputs.coordinate_unit is not None,
            inputs.timestamp_unit == "seconds",
            inputs.clock_relation is not None and relation != ClockRelation.UNKNOWN,
            offset is not None,
        )
    )
    enough_observation = (
        len(observations) >= config.minimum_sampled_frames
        and len(matched) >= config.minimum_matched_frames
        and observable_count >= config.minimum_overlapping_frames
    )
    observability = (
        LidarCalibrationObservability.UNAVAILABLE
        if not metadata_available
        else LidarCalibrationObservability.READY_FOR_SCORING
        if enough_observation
        else LidarCalibrationObservability.INSUFFICIENT
    )
    if not structural_failure:
        inconclusive(
            LidarCalibrationFindingCode.PROJECTION_SCORING_PENDING,
            "Structural checks and availability checks do not measure image-to-cloud calibration consistency.",
            "Run AUD-13.S2 projection scoring before treating this package as sensor-QA qualified.",
        )

    findings = list({finding.code: finding for finding in [*failures, *uncertainties]}.values())
    result = LidarCalibrationQAResult.FAIL if structural_failure else LidarCalibrationQAResult.INCONCLUSIVE
    overlap_fraction = overlap_total / projected_total if projected_total else None
    return seal_lidar_calibration_qa_report(
        package_ref=inputs.package_ref,
        calibration_ref=calibration_ref,
        trajectory_ref=package.trajectory_ref,
        timing_ref=timing_ref,
        intrinsics_ref=inputs.intrinsics_ref,
        rgb_frame_set_ref=inputs.rgb_frame_set_ref,
        profile=config,
        input_checksum=inputs.package_ref.artifact_checksum,
        calibration_checksum=calibration_ref.artifact_checksum if calibration_ref else None,
        timing_checksum=timing_ref.artifact_checksum,
        intrinsics_checksum=inputs.intrinsics_ref.artifact_checksum if inputs.intrinsics_ref else None,
        config_checksum=config.config_checksum,
        coordinate_unit=coordinate_unit.value if coordinate_unit else None,
        timestamp_unit=inputs.timestamp_unit,
        clock_relation=relation.value if relation else None,
        clock_offset_seconds=offset,
        sampled_rgb_frame_ids=rgb_ids,
        matched_lidar_pose_ids=[int(pose_id) for pose_id in lidar_pose_ids],
        sampled_frame_count=len(observations),
        matched_frame_count=len(matched),
        trajectory_pose_count=package.pose_count,
        observable_frame_count=observable_count,
        projected_point_count=projected_total,
        overlap_point_count=overlap_total,
        overlap_fraction=overlap_fraction,
        maximum_timestamp_residual_sec=max(timestamp_residuals) if timestamp_residuals else None,
        observability=observability,
        result=result,
        findings=findings,
        overlay_refs=[row.overlay_ref for row in observations if row.overlay_ref is not None],
        projection_evidence_ref=None,
    )


def is_sensor_package_collision_eligible(report: LidarCalibrationQAReport) -> bool:
    """Consumer gate: only scored PASS reports can qualify a sensor-package source."""
    return (
        report.result == LidarCalibrationQAResult.PASS
        and report.observability == LidarCalibrationObservability.READY_FOR_SCORING
        and report.projection_evidence_ref is not None
    )
