"""Versioned evidence contract for LiDAR sensor-package calibration QA."""

from enum import StrEnum
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum


class LidarCalibrationQAResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class LidarCalibrationObservability(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT = "INSUFFICIENT"
    READY_FOR_SCORING = "READY_FOR_SCORING"


class LidarCalibrationFindingCode(StrEnum):
    PACKAGE_REFERENCE_INVALID = "PACKAGE_REFERENCE_INVALID"
    CALIBRATION_SOURCE_MISSING = "CALIBRATION_SOURCE_MISSING"
    TRANSFORM_DIRECTION_INVALID = "TRANSFORM_DIRECTION_INVALID"
    TRANSFORM_NONFINITE = "TRANSFORM_NONFINITE"
    TRANSFORM_NOT_SE3 = "TRANSFORM_NOT_SE3"
    TRANSLATION_UNIT_MISSING = "TRANSLATION_UNIT_MISSING"
    TRANSLATION_UNIT_UNSUPPORTED = "TRANSLATION_UNIT_UNSUPPORTED"
    CAMERA_INTRINSICS_MISSING = "CAMERA_INTRINSICS_MISSING"
    INTRINSICS_SOURCE_MISSING = "INTRINSICS_SOURCE_MISSING"
    DISTORTION_UNAVAILABLE = "DISTORTION_UNAVAILABLE"
    RGB_FRAME_SET_MISSING = "RGB_FRAME_SET_MISSING"
    TIMING_UNIT_MISSING = "TIMING_UNIT_MISSING"
    TIMING_UNIT_UNSUPPORTED = "TIMING_UNIT_UNSUPPORTED"
    CLOCK_RELATION_MISSING = "CLOCK_RELATION_MISSING"
    CLOCK_OFFSET_MISSING = "CLOCK_OFFSET_MISSING"
    CLOCK_OFFSET_CONFLICT = "CLOCK_OFFSET_CONFLICT"
    TIMESTAMP_ORDER_INVALID = "TIMESTAMP_ORDER_INVALID"
    FRAME_MAPPING_INVALID = "FRAME_MAPPING_INVALID"
    TIMESTAMP_RESIDUAL_EXCEEDED = "TIMESTAMP_RESIDUAL_EXCEEDED"
    INSUFFICIENT_SAMPLED_FRAMES = "INSUFFICIENT_SAMPLED_FRAMES"
    INSUFFICIENT_MATCHED_FRAMES = "INSUFFICIENT_MATCHED_FRAMES"
    INSUFFICIENT_PROJECTED_POINTS = "INSUFFICIENT_PROJECTED_POINTS"
    INSUFFICIENT_OVERLAP = "INSUFFICIENT_OVERLAP"
    PROJECTION_SCORING_PENDING = "PROJECTION_SCORING_PENDING"
    PRODUCTION_QUALIFICATION_PENDING = "PRODUCTION_QUALIFICATION_PENDING"


class LidarCalibrationQAFinding(ContractModel):
    code: LidarCalibrationFindingCode
    severity: Literal["fail", "inconclusive"]
    detail: str = Field(min_length=1)
    remediation: str = Field(min_length=1)


class LidarCalibrationQAConfig(ContractModel):
    """Explicit qualification profile; these thresholds are not production defaults."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: Identifier
    minimum_sampled_frames: int = Field(ge=1)
    minimum_matched_frames: int = Field(ge=1)
    minimum_overlapping_frames: int = Field(ge=1)
    minimum_projected_points_per_frame: int = Field(ge=1)
    minimum_overlap_fraction: FiniteFloat = Field(gt=0, le=1)
    maximum_timestamp_residual_sec: FiniteFloat = Field(ge=0)
    config_checksum: Checksum

    @model_validator(mode="after")
    def _check_config(self) -> "LidarCalibrationQAConfig":
        if self.minimum_matched_frames > self.minimum_sampled_frames:
            raise ValueError("minimum_matched_frames cannot exceed minimum_sampled_frames")
        if self.minimum_overlapping_frames > self.minimum_sampled_frames:
            raise ValueError("minimum_overlapping_frames cannot exceed minimum_sampled_frames")
        verify_content_checksum(self, "config_checksum")
        return self


class LidarCalibrationFrameObservation(ContractModel):
    """One sampled RGB frame and its explicitly matched LiDAR trajectory pose."""

    rgb_frame_id: int = Field(ge=0)
    rgb_timestamp_sec: FiniteFloat
    lidar_pose_id: int | None = Field(default=None, ge=0)
    lidar_timestamp_sec: FiniteFloat | None = None
    projected_point_count: int = Field(default=0, ge=0)
    overlap_point_count: int = Field(default=0, ge=0)
    overlay_ref: ProductArtifactRef | None = None

    @model_validator(mode="after")
    def _check_observation(self) -> "LidarCalibrationFrameObservation":
        if (self.lidar_pose_id is None) != (self.lidar_timestamp_sec is None):
            raise ValueError("LiDAR pose ID and timestamp must both be present or both be absent")
        if self.overlap_point_count > self.projected_point_count:
            raise ValueError("overlap_point_count cannot exceed projected_point_count")
        return self


class LidarCalibrationQAReport(ContractModel):
    """QA result bound to exact package, calibration, timing, intrinsics and profile identities."""

    schema_version: Literal["1.0"] = "1.0"
    package_ref: ProductArtifactRef
    calibration_ref: ProductArtifactRef | None = None
    trajectory_ref: ProductArtifactRef
    timing_ref: ProductArtifactRef
    intrinsics_ref: ProductArtifactRef | None = None
    rgb_frame_set_ref: ProductArtifactRef | None = None
    profile: LidarCalibrationQAConfig
    input_checksum: Checksum
    calibration_checksum: Checksum | None = None
    timing_checksum: Checksum
    intrinsics_checksum: Checksum | None = None
    config_checksum: Checksum
    coordinate_unit: str | None = None
    timestamp_unit: str | None = None
    clock_relation: str | None = None
    clock_offset_seconds: FiniteFloat | None = None
    sampled_rgb_frame_ids: list[int] = Field(default_factory=list)
    matched_lidar_pose_ids: list[int] = Field(default_factory=list)
    sampled_frame_count: int = Field(ge=0)
    matched_frame_count: int = Field(ge=0)
    trajectory_pose_count: int = Field(gt=1)
    observable_frame_count: int = Field(ge=0)
    projected_point_count: int = Field(ge=0)
    overlap_point_count: int = Field(ge=0)
    overlap_fraction: FiniteFloat | None = Field(default=None, ge=0, le=1)
    maximum_timestamp_residual_sec: FiniteFloat | None = Field(default=None, ge=0)
    observability: LidarCalibrationObservability
    result: LidarCalibrationQAResult
    findings: list[LidarCalibrationQAFinding] = Field(default_factory=list)
    overlay_refs: list[ProductArtifactRef] = Field(default_factory=list)
    diagnostic_projection_ref: ProductArtifactRef | None = Field(default=None, exclude_if=lambda value: value is None)
    projection_evidence_ref: ProductArtifactRef | None = None
    report_checksum: Checksum

    @model_validator(mode="after")
    def _check_report(self) -> "LidarCalibrationQAReport":
        if self.package_ref.artifact_checksum != self.input_checksum:
            raise ValueError("input_checksum must match package_ref")
        if self.timing_ref.artifact_checksum != self.timing_checksum:
            raise ValueError("timing_checksum must match timing_ref")
        if (self.calibration_ref.artifact_checksum if self.calibration_ref else None) != self.calibration_checksum:
            raise ValueError("calibration_checksum must match calibration_ref")
        if (self.intrinsics_ref.artifact_checksum if self.intrinsics_ref else None) != self.intrinsics_checksum:
            raise ValueError("intrinsics_checksum must match intrinsics_ref")
        if self.profile.config_checksum != self.config_checksum:
            raise ValueError("config_checksum must match the embedded qualification profile")
        if self.diagnostic_projection_ref is not None and (
            self.diagnostic_projection_ref.artifact_type != "LidarCalibrationProjectionEvidence"
            or self.diagnostic_projection_ref.job_id != self.package_ref.job_id
            or self.diagnostic_projection_ref.producer_stage != "ST-LIDAR-CALIBRATION-QA"
            or not self.diagnostic_projection_ref.artifact_uri.startswith(f"artifact://jobs/{self.package_ref.job_id}/")
        ):
            raise ValueError("diagnostic projection reference must be a same-job QA artifact")
        if any(
            reference.artifact_type != "LidarCalibrationQAOverlay"
            or reference.job_id != self.package_ref.job_id
            or reference.producer_stage != "ST-LIDAR-CALIBRATION-QA"
            or not reference.artifact_uri.startswith(f"artifact://jobs/{self.package_ref.job_id}/")
            for reference in self.overlay_refs
        ):
            raise ValueError("overlay references must be same-job QA artifacts")
        if self.sampled_frame_count != len(self.sampled_rgb_frame_ids):
            raise ValueError("sampled_frame_count must match sampled_rgb_frame_ids")
        if self.matched_frame_count != len(self.matched_lidar_pose_ids):
            raise ValueError("matched_frame_count must match matched_lidar_pose_ids")
        if self.sampled_rgb_frame_ids != sorted(set(self.sampled_rgb_frame_ids)):
            raise ValueError("sampled_rgb_frame_ids must be ordered and unique")
        if self.matched_lidar_pose_ids != sorted(set(self.matched_lidar_pose_ids)) or any(
            pose_id >= self.trajectory_pose_count for pose_id in self.matched_lidar_pose_ids
        ):
            raise ValueError("matched_lidar_pose_ids must be ordered, unique and within the trajectory inventory")
        if self.overlap_point_count > self.projected_point_count:
            raise ValueError("overlap_point_count cannot exceed projected_point_count")
        expected_overlap_fraction = (
            self.overlap_point_count / self.projected_point_count if self.projected_point_count else None
        )
        if self.overlap_fraction != expected_overlap_fraction:
            raise ValueError("overlap_fraction must match the recorded projected/overlap point counts")
        if self.result == LidarCalibrationQAResult.PASS:
            if self.observability != LidarCalibrationObservability.READY_FOR_SCORING:
                raise ValueError("PASS requires observable frames under a qualification profile")
            if self.projection_evidence_ref is None:
                raise ValueError("PASS requires projection evidence")
            if any(finding.severity == "fail" for finding in self.findings):
                raise ValueError("PASS cannot include a failing finding")
            if any(finding.severity == "inconclusive" for finding in self.findings):
                raise ValueError("PASS cannot include an inconclusive finding")
            if not all((self.calibration_ref, self.intrinsics_ref, self.rgb_frame_set_ref)):
                raise ValueError("PASS requires calibration, intrinsics and RGB frame-set references")
            if (
                self.coordinate_unit != "m"
                or self.timestamp_unit != "seconds"
                or self.clock_relation in {None, "unknown"}
                or self.clock_offset_seconds is None
            ):
                raise ValueError("PASS requires explicit supported unit and clock declarations")
            if (
                self.sampled_frame_count < self.profile.minimum_sampled_frames
                or self.matched_frame_count < self.profile.minimum_matched_frames
                or self.observable_frame_count < self.profile.minimum_overlapping_frames
            ):
                raise ValueError("PASS does not meet the embedded sampling and overlap profile")
        elif self.projection_evidence_ref is not None and self.result == LidarCalibrationQAResult.INCONCLUSIVE:
            raise ValueError("INCONCLUSIVE report cannot bind accepted projection evidence")
        verify_content_checksum(self, "report_checksum")
        return self


def seal_lidar_calibration_qa_config(**payload: object) -> LidarCalibrationQAConfig:
    """Validate and checksum an explicit QA threshold profile."""
    draft = LidarCalibrationQAConfig.model_construct(**payload, config_checksum="sha256:" + "0" * 64)
    normalized = draft.model_dump(mode="json")
    normalized["config_checksum"] = canonical_content_checksum(normalized, "config_checksum")
    return LidarCalibrationQAConfig.model_validate(normalized)


def seal_lidar_calibration_qa_report(**payload: object) -> LidarCalibrationQAReport:
    """Validate and checksum a source-bound calibration QA report."""
    draft = LidarCalibrationQAReport.model_construct(**payload, report_checksum="sha256:" + "0" * 64)
    normalized = draft.model_dump(mode="json")
    normalized["report_checksum"] = canonical_content_checksum(normalized, "report_checksum")
    return LidarCalibrationQAReport.model_validate(normalized)
