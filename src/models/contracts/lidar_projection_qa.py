"""Projection scoring evidence for RGB/LiDAR calibration qualification."""

import math
from enum import StrEnum
from statistics import median
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.lidar_calibration_qa import LidarCalibrationQAConfig


class LidarProjectionDiagnosticCode(StrEnum):
    """Reasons a projection score cannot qualify a calibration observation."""

    CALIBRATION_EVIDENCE_MISSING = "CALIBRATION_EVIDENCE_MISSING"
    CAMERA_INTRINSICS_MISSING = "CAMERA_INTRINSICS_MISSING"
    CAMERA_DISTORTION_UNQUALIFIED = "CAMERA_DISTORTION_UNQUALIFIED"
    CAMERA_PIXEL_BASIS_UNKNOWN = "CAMERA_PIXEL_BASIS_UNKNOWN"
    RGB_FRAME_SET_MISSING = "RGB_FRAME_SET_MISSING"
    CLOCK_EVIDENCE_MISSING = "CLOCK_EVIDENCE_MISSING"
    METRIC_UNIT_UNAVAILABLE = "METRIC_UNIT_UNAVAILABLE"
    STRUCTURAL_QA_FAILED = "STRUCTURAL_QA_FAILED"
    NO_SAMPLED_FRAMES = "NO_SAMPLED_FRAMES"
    INSUFFICIENT_SAMPLE_COUNT = "INSUFFICIENT_SAMPLE_COUNT"
    FRAME_SOURCE_MAPPING_INVALID = "FRAME_SOURCE_MAPPING_INVALID"
    FRAME_TIMESTAMP_RESIDUAL_EXCEEDED = "FRAME_TIMESTAMP_RESIDUAL_EXCEEDED"
    IMAGE_ASPECT_UNSUPPORTED = "IMAGE_ASPECT_UNSUPPORTED"
    NO_EDGE_FEATURES = "NO_EDGE_FEATURES"
    TOO_FEW_PROJECTED_POINTS = "TOO_FEW_PROJECTED_POINTS"
    INSUFFICIENT_EDGE_SUPPORT = "INSUFFICIENT_EDGE_SUPPORT"
    EDGE_ORIENTATION_DEGENERATE = "EDGE_ORIENTATION_DEGENERATE"
    EDGE_SPAN_DEGENERATE = "EDGE_SPAN_DEGENERATE"
    CROSS_FRAME_SCORE_VARIANCE = "CROSS_FRAME_SCORE_VARIANCE"


class LidarCalibrationProjectionConfig(ContractModel):
    """Diagnostic projection profile; it is not a production acceptance threshold."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: Identifier
    edge_distance_threshold_px: FiniteFloat = Field(gt=0)
    minimum_edge_pixels: int = Field(gt=0)
    maximum_points_per_frame: int = Field(ge=1, le=500_000)
    maximum_edge_pixels_per_frame: int = Field(ge=1, le=500_000)
    maximum_overlay_samples_per_frame: int = Field(ge=1, le=2_048)
    minimum_edge_orientation_bins: int = Field(ge=2, le=8)
    minimum_edge_span_fraction: FiniteFloat = Field(gt=0, le=1)
    maximum_frame_median_spread_px: FiniteFloat = Field(gt=0)
    config_checksum: Checksum

    @model_validator(mode="after")
    def _check_config(self) -> Self:
        if self.minimum_edge_pixels > self.maximum_edge_pixels_per_frame:
            raise ValueError("minimum_edge_pixels cannot exceed maximum_edge_pixels_per_frame")
        verify_content_checksum(self, "config_checksum")
        return self


class LidarCalibrationProjectionModel(ContractModel):
    """Exact camera basis and effective sensor-from-camera model used for projection."""

    pixel_basis: Literal["source_video", "prepared_rgb"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fx: FiniteFloat = Field(gt=0)
    fy: FiniteFloat = Field(gt=0)
    cx: FiniteFloat
    cy: FiniteFloat
    distortion: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    distortion_status: Literal["declared"]
    sensor_from_camera: Transform
    pixel_transform_checksum: Checksum | None = None


class LidarProjectionOverlaySample(ContractModel):
    """One deterministic projected LiDAR sample ready for an RGB overlay renderer."""

    u_px: FiniteFloat = Field(ge=0)
    v_px: FiniteFloat = Field(ge=0)
    depth_m: FiniteFloat = Field(gt=0)
    nearest_edge_distance_px: FiniteFloat = Field(ge=0)


class LidarCalibrationProjectionFrameEvidence(ContractModel):
    """Per-frame source binding, projection counts, edge score and preview points."""

    frame_id: int = Field(ge=0)
    lidar_pose_id: int = Field(ge=0)
    rgb_frame_checksum: Checksum
    lidar_scan_checksum: Checksum
    edge_samples_checksum: Checksum
    point_samples_checksum: Checksum
    timestamp_residual_sec: FiniteFloat = Field(ge=0)
    input_point_count: int = Field(ge=0)
    sampled_point_count: int = Field(ge=0)
    front_facing_point_count: int = Field(ge=0)
    in_frame_point_count: int = Field(ge=0)
    visible_projected_point_count: int = Field(ge=0)
    overlap_point_count: int = Field(ge=0)
    overlap_fraction: FiniteFloat | None = Field(default=None, ge=0, le=1)
    median_edge_distance_px: FiniteFloat | None = Field(default=None, ge=0)
    p90_edge_distance_px: FiniteFloat | None = Field(default=None, ge=0)
    matched_edge_orientation_bins: list[int] = Field(default_factory=list)
    matched_edge_span_fraction: tuple[FiniteFloat, FiniteFloat] | None = None
    observable: bool
    diagnostic_reasons: list[LidarProjectionDiagnosticCode] = Field(default_factory=list)
    overlay_samples: list[LidarProjectionOverlaySample] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_evidence(self) -> Self:
        if self.sampled_point_count > self.input_point_count:
            raise ValueError("sampled_point_count cannot exceed input_point_count")
        if self.front_facing_point_count > self.sampled_point_count:
            raise ValueError("front_facing_point_count cannot exceed sampled_point_count")
        if self.in_frame_point_count > self.front_facing_point_count:
            raise ValueError("in_frame_point_count cannot exceed front_facing_point_count")
        if self.visible_projected_point_count > self.in_frame_point_count:
            raise ValueError("visible_projected_point_count cannot exceed in_frame_point_count")
        if self.overlap_point_count > self.visible_projected_point_count:
            raise ValueError("overlap_point_count cannot exceed visible_projected_point_count")
        expected_overlap = (
            self.overlap_point_count / self.visible_projected_point_count
            if self.visible_projected_point_count
            else None
        )
        if self.overlap_fraction != expected_overlap:
            raise ValueError("overlap_fraction must match visible and overlapping point counts")
        if (self.median_edge_distance_px is None) != (self.p90_edge_distance_px is None):
            raise ValueError("median and p90 edge distance summaries must be present together")
        if self.median_edge_distance_px is not None and self.visible_projected_point_count == 0:
            raise ValueError("edge distance summaries require visible projected points")
        if self.median_edge_distance_px is None and self.overlap_point_count > 0:
            raise ValueError("edge overlap counts require edge distance summaries")
        if self.median_edge_distance_px is not None and self.p90_edge_distance_px < self.median_edge_distance_px:
            raise ValueError("p90_edge_distance_px cannot be less than the median")
        if self.matched_edge_orientation_bins != sorted(set(self.matched_edge_orientation_bins)) or any(
            value < 0 or value > 7 for value in self.matched_edge_orientation_bins
        ):
            raise ValueError("matched edge orientation bins must be unique, ordered values in [0, 7]")
        if self.matched_edge_span_fraction is not None and any(
            value < 0 or value > 1 for value in self.matched_edge_span_fraction
        ):
            raise ValueError("matched edge span fractions must lie in [0, 1]")
        if self.observable != (not self.diagnostic_reasons):
            raise ValueError("observable must agree with per-frame diagnostic reasons")
        if len(self.overlay_samples) > self.visible_projected_point_count:
            raise ValueError("overlay samples cannot exceed visible projected points")
        return self


class LidarCalibrationProjectionEvidence(ContractModel):
    """Checksummed diagnostic metrics and overlay data; never a calibration PASS."""

    schema_version: Literal["1.0"] = "1.0"
    package_ref: ProductArtifactRef
    calibration_ref: ProductArtifactRef | None = None
    trajectory_ref: ProductArtifactRef
    timing_ref: ProductArtifactRef
    intrinsics_ref: ProductArtifactRef | None = None
    rgb_frame_set_ref: ProductArtifactRef | None = None
    qa_profile: LidarCalibrationQAConfig
    projection_profile: LidarCalibrationProjectionConfig
    projection_model: LidarCalibrationProjectionModel | None = None
    frames: list[LidarCalibrationProjectionFrameEvidence] = Field(default_factory=list)
    scoring_status: Literal["SCORED", "INCONCLUSIVE"]
    qualification_status: Literal["diagnostic_only"] = "diagnostic_only"
    diagnostic_reasons: list[LidarProjectionDiagnosticCode] = Field(default_factory=list)
    observable_frame_count: int = Field(ge=0)
    projected_point_count: int = Field(ge=0)
    overlap_point_count: int = Field(ge=0)
    overlap_fraction: FiniteFloat | None = Field(default=None, ge=0, le=1)
    median_frame_error_px: FiniteFloat | None = Field(default=None, ge=0)
    p90_frame_error_px: FiniteFloat | None = Field(default=None, ge=0)
    frame_median_spread_px: FiniteFloat | None = Field(default=None, ge=0)
    report_checksum: Checksum

    @model_validator(mode="after")
    def _check_evidence(self) -> Self:
        refs = [
            self.package_ref,
            self.calibration_ref,
            self.trajectory_ref,
            self.timing_ref,
            self.intrinsics_ref,
            self.rgb_frame_set_ref,
        ]
        if any(ref is not None and ref.job_id != self.package_ref.job_id for ref in refs):
            raise ValueError("all calibration projection source refs must belong to the same job")
        frame_ids = [frame.frame_id for frame in self.frames]
        pose_ids = [frame.lidar_pose_id for frame in self.frames]
        if frame_ids != sorted(set(frame_ids)) or len(pose_ids) != len(set(pose_ids)):
            raise ValueError("projection frame IDs and matched LiDAR pose IDs must be ordered and unique")
        observable = [frame for frame in self.frames if frame.observable]
        if self.observable_frame_count != len(observable):
            raise ValueError("observable_frame_count must match per-frame evidence")
        if self.projected_point_count != sum(frame.visible_projected_point_count for frame in self.frames):
            raise ValueError("projected_point_count must match per-frame visible counts")
        if self.overlap_point_count != sum(frame.overlap_point_count for frame in self.frames):
            raise ValueError("overlap_point_count must match per-frame edge support")
        expected_overlap = self.overlap_point_count / self.projected_point_count if self.projected_point_count else None
        if self.overlap_fraction != expected_overlap:
            raise ValueError("overlap_fraction must match aggregate projected and overlapping counts")

        frame_errors = sorted(
            frame.median_edge_distance_px for frame in self.frames if frame.median_edge_distance_px is not None
        )
        expected_median = median(frame_errors) if frame_errors else None
        expected_p90 = frame_errors[nearest_rank_index(len(frame_errors), 0.9)] if frame_errors else None
        expected_spread = (
            expected_p90 - expected_median if expected_p90 is not None and expected_median is not None else None
        )
        if self.median_frame_error_px != expected_median:
            raise ValueError("median_frame_error_px must match scored frame metrics")
        if self.p90_frame_error_px != expected_p90:
            raise ValueError("p90_frame_error_px must match scored frame metrics")
        if self.frame_median_spread_px != expected_spread:
            raise ValueError("frame_median_spread_px must match the frame score distribution")

        enough_data = (
            len(self.frames) >= self.qa_profile.minimum_sampled_frames
            and len(
                [
                    frame
                    for frame in self.frames
                    if frame.timestamp_residual_sec <= self.qa_profile.maximum_timestamp_residual_sec
                ]
            )
            >= self.qa_profile.minimum_matched_frames
            and self.observable_frame_count >= self.qa_profile.minimum_overlapping_frames
        )
        stable_frames = (
            expected_spread is None or expected_spread <= self.projection_profile.maximum_frame_median_spread_px
        )
        if self.scoring_status == "SCORED" and self.projection_model is None:
            raise ValueError("SCORED evidence requires an explicit projection model")
        if self.projection_model is None and not {
            LidarProjectionDiagnosticCode.CAMERA_INTRINSICS_MISSING,
            LidarProjectionDiagnosticCode.CAMERA_DISTORTION_UNQUALIFIED,
            LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN,
        }.intersection(self.diagnostic_reasons):
            raise ValueError("missing projection model must carry a camera or pixel-basis diagnostic")
        expected_status = "SCORED" if enough_data and stable_frames and not self.diagnostic_reasons else "INCONCLUSIVE"
        if self.scoring_status != expected_status:
            raise ValueError("scoring_status must match available, observable and stable frame evidence")
        if stable_frames and LidarProjectionDiagnosticCode.CROSS_FRAME_SCORE_VARIANCE in self.diagnostic_reasons:
            raise ValueError("cross-frame variance diagnostic requires an exceeded profile threshold")
        if (
            not stable_frames
            and LidarProjectionDiagnosticCode.CROSS_FRAME_SCORE_VARIANCE not in self.diagnostic_reasons
        ):
            raise ValueError("cross-frame score variance must be reported when it exceeds the profile")
        verify_content_checksum(self, "report_checksum")
        return self


def nearest_rank_index(count: int, quantile: float) -> int:
    """Nearest-rank quantile index used consistently by the evidence validator and scorer."""
    return max(0, math.ceil(count * quantile) - 1)


def seal_lidar_calibration_projection_config(**payload: object) -> LidarCalibrationProjectionConfig:
    """Validate and checksum an explicit projection scoring profile."""
    draft = LidarCalibrationProjectionConfig.model_construct(**payload, config_checksum="sha256:" + "0" * 64)
    normalized = draft.model_dump(mode="json")
    normalized["config_checksum"] = canonical_content_checksum(normalized, "config_checksum")
    return LidarCalibrationProjectionConfig.model_validate(normalized)


def seal_lidar_calibration_projection_evidence(**payload: object) -> LidarCalibrationProjectionEvidence:
    """Validate and checksum source-bound diagnostic projection evidence."""
    draft = LidarCalibrationProjectionEvidence.model_construct(**payload, report_checksum="sha256:" + "0" * 64)
    normalized = draft.model_dump(mode="json")
    normalized["report_checksum"] = canonical_content_checksum(normalized, "report_checksum")
    return LidarCalibrationProjectionEvidence.model_validate(normalized)
