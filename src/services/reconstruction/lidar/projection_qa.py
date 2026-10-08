"""Metric RGB/LiDAR projection scoring over explicitly matched frame/scan pairs."""

import hashlib
import json
import math
from dataclasses import dataclass
from statistics import median
from typing import Literal

import numpy as np
from scipy.spatial import cKDTree

from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.input_assembly import ClockRelation
from src.models.contracts.lidar_calibration_qa import (
    LidarCalibrationQAConfig,
    LidarCalibrationQAResult,
)
from src.models.contracts.lidar_projection_qa import (
    LidarCalibrationProjectionConfig,
    LidarCalibrationProjectionEvidence,
    LidarCalibrationProjectionFrameEvidence,
    LidarCalibrationProjectionModel,
    LidarProjectionDiagnosticCode,
    LidarProjectionOverlaySample,
    nearest_rank_index,
    seal_lidar_calibration_projection_evidence,
)
from src.models.contracts.video_preparation import ServerVideoPreparationVerification
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.lidar.calibration_qa import LidarCalibrationQAInput, evaluate_lidar_calibration_qa
from src.services.reconstruction.lidar.camera_priors import CameraPriorError, prepared_camera_calibration
from src.services.reconstruction.lidar.package import SENSOR_FRAME, CameraCalibration


@dataclass(frozen=True)
class LidarCalibrationProjectionFrame:
    """Raw sensor-frame points and RGB edge samples for one explicit scan/frame pair.

    LiDAR points are in meters in `lidar_sensor`; they are not fused into a world map.
    Edge pixels and their outward image-gradient normals share the prepared RGB pixel basis.
    """

    frame_id: int
    lidar_pose_id: int
    rgb_timestamp_sec: float
    lidar_timestamp_sec: float
    rgb_frame_checksum: str
    lidar_scan_checksum: str
    pixel_basis: Literal["source_video", "prepared_rgb"]
    image_width: int
    image_height: int
    edge_pixels_xy: np.ndarray
    edge_normals_xy: np.ndarray
    lidar_points_sensor_m: np.ndarray


@dataclass(frozen=True)
class _PreparedFrame:
    source: LidarCalibrationProjectionFrame
    edge_pixels_xy: np.ndarray
    edge_normals_xy: np.ndarray
    lidar_points_sensor_m: np.ndarray
    sampled_edge_pixels_xy: np.ndarray
    sampled_edge_normals_xy: np.ndarray
    sampled_lidar_points_sensor_m: np.ndarray


def build_lidar_calibration_projection_model(
    inputs: LidarCalibrationQAInput,
    *,
    camera_pixel_basis: Literal["source_video", "prepared_rgb"],
    rgb_frame_pixel_basis: Literal["source_video", "prepared_rgb"],
    video_preparation_verification: ServerVideoPreparationVerification | None = None,
) -> LidarCalibrationProjectionModel | None:
    """Bind intrinsics/extrinsics to the exact image pixel basis used by projection frames.

    Source-video calibration is mapped to prepared RGB only through the existing verified
    pixel-transform contract. Other basis changes remain inconclusive.
    """
    camera = inputs.camera
    if camera is None or camera.distortion_status != "declared":
        return None
    transform = inputs.package.sensor_from_camera
    pixel_transform_checksum = None
    if camera_pixel_basis == rgb_frame_pixel_basis:
        effective_camera = camera
        pixel_basis = rgb_frame_pixel_basis
    elif (
        camera_pixel_basis == "source_video"
        and rgb_frame_pixel_basis == "prepared_rgb"
        and video_preparation_verification is not None
    ):
        try:
            transform, mapped = prepared_camera_calibration(transform, camera, video_preparation_verification)
        except CameraPriorError:
            return None
        if mapped is None:
            return None
        width, height, parameters = mapped
        effective_camera = CameraCalibration(
            width=width,
            height=height,
            fx=parameters[0],
            fy=parameters[1],
            cx=parameters[2],
            cy=parameters[3],
            distortion=tuple(parameters[4:8]),
            distortion_status="declared",
        )
        pixel_basis = "prepared_rgb"
        pixel_transform_checksum = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(video_preparation_verification.client_manifest.pixel_transform)
            ).hexdigest()
        )
    else:
        return None
    return LidarCalibrationProjectionModel(
        pixel_basis=pixel_basis,
        width=effective_camera.width,
        height=effective_camera.height,
        fx=effective_camera.fx,
        fy=effective_camera.fy,
        cx=effective_camera.cx,
        cy=effective_camera.cy,
        distortion=effective_camera.distortion,
        distortion_status="declared",
        sensor_from_camera=transform,
        pixel_transform_checksum=pixel_transform_checksum,
    )


def _array_checksum(value: np.ndarray) -> str:
    """Checksum normalized array bytes plus shape and dtype, independent of native endianness."""
    normalized = np.ascontiguousarray(value)
    header = json.dumps({"shape": normalized.shape, "dtype": normalized.dtype.str}, separators=(",", ":")).encode()
    digest = hashlib.sha256(header + b"\0" + normalized.tobytes(order="C")).hexdigest()
    return f"sha256:{digest}"


def _even_indices(count: int, maximum: int) -> np.ndarray:
    if count <= maximum:
        return np.arange(count, dtype=np.int64)
    return np.linspace(0, count - 1, maximum, dtype=np.int64)


def _prepare_frame(frame: LidarCalibrationProjectionFrame, config: LidarCalibrationProjectionConfig) -> _PreparedFrame:
    if frame.frame_id < 0 or frame.lidar_pose_id < 0:
        raise ValueError("projection frame and LiDAR pose IDs must be nonnegative")
    if frame.image_width < 2 or frame.image_height < 2:
        raise ValueError("projection frame image dimensions must be at least 2x2")
    if not math.isfinite(frame.rgb_timestamp_sec) or not math.isfinite(frame.lidar_timestamp_sec):
        raise ValueError("projection frame timestamps must be finite seconds")

    edges = np.asarray(frame.edge_pixels_xy)
    normals = np.asarray(frame.edge_normals_xy, dtype=np.float64)
    points = np.asarray(frame.lidar_points_sensor_m, dtype=np.float64)
    if edges.ndim != 2 or edges.shape[1:] != (2,):
        raise ValueError("edge_pixels_xy must have shape (N, 2)")
    if normals.shape != edges.shape:
        raise ValueError("edge_normals_xy must provide one 2D normal for every edge pixel")
    if points.ndim != 2 or points.shape[1:] != (3,):
        raise ValueError("lidar_points_sensor_m must have shape (N, 3)")
    if not np.isfinite(edges).all() or not np.isfinite(normals).all() or not np.isfinite(points).all():
        raise ValueError("projection input arrays must contain only finite values")
    rounded_edges = np.rint(edges)
    if not np.allclose(edges, rounded_edges, atol=1e-6):
        raise ValueError("edge pixel coordinates must be integer-valued")
    edges = rounded_edges.astype("<i4", copy=False)
    if len(edges) and (
        (edges[:, 0] < 0).any()
        or (edges[:, 0] >= frame.image_width).any()
        or (edges[:, 1] < 0).any()
        or (edges[:, 1] >= frame.image_height).any()
    ):
        raise ValueError("edge pixel coordinates must fall inside the prepared RGB frame")
    lengths = np.linalg.norm(normals, axis=1)
    if len(lengths) and (lengths <= 1e-8).any():
        raise ValueError("edge normals must have nonzero length")
    normals = normals / lengths[:, None] if len(normals) else normals

    # A row-major deterministic edge order makes capped samples stable across runs.
    edge_order = np.lexsort((edges[:, 0], edges[:, 1])) if len(edges) else np.empty(0, dtype=np.int64)
    edges = np.ascontiguousarray(edges[edge_order], dtype="<i4")
    normals = np.ascontiguousarray(normals[edge_order], dtype="<f8")
    points = np.ascontiguousarray(points, dtype="<f8")
    edge_indices = _even_indices(len(edges), config.maximum_edge_pixels_per_frame)
    point_indices = _even_indices(len(points), config.maximum_points_per_frame)
    return _PreparedFrame(
        source=frame,
        edge_pixels_xy=edges,
        edge_normals_xy=normals,
        lidar_points_sensor_m=points,
        sampled_edge_pixels_xy=np.ascontiguousarray(edges[edge_indices], dtype="<i4"),
        sampled_edge_normals_xy=np.ascontiguousarray(normals[edge_indices], dtype="<f8"),
        sampled_lidar_points_sensor_m=np.ascontiguousarray(points[point_indices], dtype="<f8"),
    )


def _distort_and_project(
    points_camera: np.ndarray,
    *,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    distortion: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    z = points_camera[:, 2]
    x = points_camera[:, 0] / z
    y = points_camera[:, 1] / z
    k1, k2, p1, p2 = distortion
    radius2 = x * x + y * y
    radial = 1.0 + k1 * radius2 + k2 * radius2 * radius2
    xd = x * radial + 2.0 * p1 * x * y + p2 * (radius2 + 2.0 * x * x)
    yd = y * radial + p1 * (radius2 + 2.0 * y * y) + 2.0 * p2 * x * y
    uv = np.column_stack((fx * xd + cx, fy * yd + cy))
    return uv, z


def _edge_orientation_bins(normals: np.ndarray) -> list[int]:
    if len(normals) == 0:
        return []
    # Edge normals are unoriented; theta and theta + pi describe the same edge family.
    angles = np.mod(np.arctan2(normals[:, 1], normals[:, 0]), math.pi)
    bins = np.minimum(7, np.floor(angles * (8.0 / math.pi)).astype(int))
    return sorted(set(int(value) for value in bins))


def _frame_evidence(
    frame: _PreparedFrame,
    qa_inputs: LidarCalibrationQAInput,
    qa_profile: LidarCalibrationQAConfig,
    projection_profile: LidarCalibrationProjectionConfig,
    projection_model: LidarCalibrationProjectionModel,
) -> LidarCalibrationProjectionFrameEvidence:
    source = frame.source
    reasons: list[LidarProjectionDiagnosticCode] = []
    offset = qa_inputs.clock_offset_seconds.value
    timestamp_residual = abs(source.rgb_timestamp_sec - (source.lidar_timestamp_sec + offset))
    input_count = len(frame.lidar_points_sensor_m)
    sampled_points = frame.sampled_lidar_points_sensor_m
    sampled_edges = frame.sampled_edge_pixels_xy
    edge_checksum = _array_checksum(np.column_stack((sampled_edges, frame.sampled_edge_normals_xy)).astype("<f8"))
    point_checksum = _array_checksum(sampled_points)

    def empty(
        *,
        front: int = 0,
        in_frame: int = 0,
        visible: int = 0,
        overlap: int = 0,
        overlap_fraction: float | None = None,
        median_distance: float | None = None,
        p90_distance: float | None = None,
        orientation_bins: list[int] | None = None,
        edge_span: tuple[float, float] | None = None,
        samples: list[LidarProjectionOverlaySample] | None = None,
    ) -> LidarCalibrationProjectionFrameEvidence:
        return LidarCalibrationProjectionFrameEvidence(
            frame_id=source.frame_id,
            lidar_pose_id=source.lidar_pose_id,
            rgb_frame_checksum=source.rgb_frame_checksum,
            lidar_scan_checksum=source.lidar_scan_checksum,
            edge_samples_checksum=edge_checksum,
            point_samples_checksum=point_checksum,
            timestamp_residual_sec=timestamp_residual,
            input_point_count=input_count,
            sampled_point_count=len(sampled_points),
            front_facing_point_count=front,
            in_frame_point_count=in_frame,
            visible_projected_point_count=visible,
            overlap_point_count=overlap,
            overlap_fraction=overlap_fraction,
            median_edge_distance_px=median_distance,
            p90_edge_distance_px=p90_distance,
            matched_edge_orientation_bins=orientation_bins or [],
            matched_edge_span_fraction=edge_span,
            observable=not reasons,
            diagnostic_reasons=reasons,
            overlay_samples=samples or [],
        )

    if timestamp_residual > qa_profile.maximum_timestamp_residual_sec:
        reasons.append(LidarProjectionDiagnosticCode.FRAME_TIMESTAMP_RESIDUAL_EXCEEDED)
        return empty()

    camera = projection_model
    source_transform = projection_model.sensor_from_camera
    rotation = rotation_matrix(source_transform.rotation_quaternion_xyzw)
    points_camera = (sampled_points - np.asarray(source_transform.translation_xyz, dtype=np.float64)) @ rotation
    front_mask = points_camera[:, 2] > 1e-6
    front_points = points_camera[front_mask]
    if len(front_points):
        uv, depths = _distort_and_project(
            front_points,
            fx=camera.fx,
            fy=camera.fy,
            cx=camera.cx,
            cy=camera.cy,
            distortion=camera.distortion,
        )
    else:
        uv = np.empty((0, 2), dtype=np.float64)
        depths = np.empty(0, dtype=np.float64)

    scale_x = source.image_width / projection_model.width
    scale_y = source.image_height / projection_model.height
    if abs(scale_x - scale_y) > max(scale_x, scale_y) * 1e-6:
        reasons.append(LidarProjectionDiagnosticCode.IMAGE_ASPECT_UNSUPPORTED)
        return empty(front=len(front_points))
    uv[:, 0] *= scale_x
    uv[:, 1] *= scale_y
    in_bounds = (uv[:, 0] >= 0) & (uv[:, 0] < source.image_width) & (uv[:, 1] >= 0) & (uv[:, 1] < source.image_height)
    uv = uv[in_bounds]
    depths = depths[in_bounds]
    rounded = np.floor(uv + 0.5).astype(np.int64) if len(uv) else np.empty((0, 2), dtype=np.int64)
    pixel_ids = rounded[:, 1] * source.image_width + rounded[:, 0] if len(rounded) else np.empty(0, dtype=np.int64)
    order = np.lexsort((depths, pixel_ids)) if len(pixel_ids) else np.empty(0, dtype=np.int64)
    first_for_pixel = np.r_[True, np.diff(pixel_ids[order]) != 0] if len(order) else np.empty(0, dtype=bool)
    visible_order = order[first_for_pixel]
    visible_uv = uv[visible_order]
    visible_depths = depths[visible_order]

    if len(sampled_edges) < projection_profile.minimum_edge_pixels:
        reasons.append(LidarProjectionDiagnosticCode.NO_EDGE_FEATURES)
        visible_count = len(visible_uv)
        return empty(
            front=len(front_points),
            in_frame=len(uv),
            visible=visible_count,
            overlap_fraction=0.0 if visible_count else None,
        )

    tree = cKDTree(sampled_edges.astype(np.float64, copy=False))
    distances, nearest_edges = (
        tree.query(visible_uv, k=1, workers=1)
        if len(visible_uv)
        else (
            np.empty(0, dtype=np.float64),
            np.empty(0, dtype=np.int64),
        )
    )
    overlap_mask = distances <= projection_profile.edge_distance_threshold_px
    overlap_count = int(overlap_mask.sum())
    visible_count = len(visible_uv)
    overlap_fraction = overlap_count / visible_count if visible_count else None
    matched_normals = frame.sampled_edge_normals_xy[nearest_edges[overlap_mask]] if overlap_count else np.empty((0, 2))
    orientation_bins = _edge_orientation_bins(matched_normals)
    if visible_count < qa_profile.minimum_projected_points_per_frame:
        reasons.append(LidarProjectionDiagnosticCode.TOO_FEW_PROJECTED_POINTS)
    if overlap_fraction is None or overlap_fraction < qa_profile.minimum_overlap_fraction:
        reasons.append(LidarProjectionDiagnosticCode.INSUFFICIENT_EDGE_SUPPORT)
    if len(orientation_bins) < projection_profile.minimum_edge_orientation_bins:
        reasons.append(LidarProjectionDiagnosticCode.EDGE_ORIENTATION_DEGENERATE)

    matched_uv = visible_uv[overlap_mask]
    edge_span = None
    if len(matched_uv):
        edge_span = (
            float(np.ptp(matched_uv[:, 0]) / max(source.image_width - 1, 1)),
            float(np.ptp(matched_uv[:, 1]) / max(source.image_height - 1, 1)),
        )
        if min(edge_span) < projection_profile.minimum_edge_span_fraction:
            reasons.append(LidarProjectionDiagnosticCode.EDGE_SPAN_DEGENERATE)
    else:
        reasons.append(LidarProjectionDiagnosticCode.EDGE_SPAN_DEGENERATE)

    median_distance = float(np.median(distances)) if visible_count else None
    p90_distance = float(np.quantile(distances, 0.9, method="higher")) if visible_count else None
    sample_indices = _even_indices(visible_count, projection_profile.maximum_overlay_samples_per_frame)
    overlay_samples = [
        LidarProjectionOverlaySample(
            u_px=float(visible_uv[index, 0]),
            v_px=float(visible_uv[index, 1]),
            depth_m=float(visible_depths[index]),
            nearest_edge_distance_px=float(distances[index]),
        )
        for index in sample_indices
    ]
    return empty(
        front=len(front_points),
        in_frame=len(uv),
        visible=visible_count,
        overlap=overlap_count,
        overlap_fraction=overlap_fraction,
        median_distance=median_distance,
        p90_distance=p90_distance,
        orientation_bins=orientation_bins,
        edge_span=edge_span,
        samples=overlay_samples,
    )


def score_lidar_calibration_projection(
    inputs: LidarCalibrationQAInput,
    qa_profile: LidarCalibrationQAConfig,
    projection_profile: LidarCalibrationProjectionConfig,
    frames: list[LidarCalibrationProjectionFrame],
    *,
    camera_pixel_basis: Literal["source_video", "prepared_rgb"],
    rgb_frame_pixel_basis: Literal["source_video", "prepared_rgb"],
    video_preparation_verification: ServerVideoPreparationVerification | None = None,
) -> LidarCalibrationProjectionEvidence:
    """Score projected scan points against image edges; return diagnostics, never a PASS.

    The per-frame scan remains in the LiDAR sensor frame and is paired by its explicit
    pose ID and timestamp. This function does not interpolate, deskew, optimize or
    mutate the supplied calibration. A SCORED result means metrics are observable,
    not that the calibration is production-qualified.
    """
    preflight = evaluate_lidar_calibration_qa(inputs, qa_profile)
    projection_model = build_lidar_calibration_projection_model(
        inputs,
        camera_pixel_basis=camera_pixel_basis,
        rgb_frame_pixel_basis=rgb_frame_pixel_basis,
        video_preparation_verification=video_preparation_verification,
    )
    reasons: list[LidarProjectionDiagnosticCode] = []
    if preflight.result == LidarCalibrationQAResult.FAIL:
        reasons.append(LidarProjectionDiagnosticCode.STRUCTURAL_QA_FAILED)
    # This scorer produces projected-point and overlap metrics. Requiring the
    # structural preflight to already contain those metrics would prevent the
    # first projection pass from running. Source completeness and sample counts
    # are checked independently below; the final worker report evaluates the
    # completed metrics after this scorer returns.
    package = inputs.package
    if package.calibration_ref is None:
        reasons.append(LidarProjectionDiagnosticCode.CALIBRATION_EVIDENCE_MISSING)
    if inputs.camera is None or inputs.intrinsics_ref is None:
        reasons.append(LidarProjectionDiagnosticCode.CAMERA_INTRINSICS_MISSING)
    elif inputs.camera.distortion_status != "declared":
        reasons.append(LidarProjectionDiagnosticCode.CAMERA_DISTORTION_UNQUALIFIED)
    if projection_model is None:
        if camera_pixel_basis != rgb_frame_pixel_basis or (
            inputs.camera is not None and inputs.camera.distortion_status == "declared"
        ):
            reasons.append(LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN)
    elif any(frame.pixel_basis != projection_model.pixel_basis for frame in frames):
        reasons.append(LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN)
    if projection_model is not None and (
        projection_model.sensor_from_camera.parent_frame != SENSOR_FRAME
        or projection_model.sensor_from_camera.semantics != "parent_from_local"
    ):
        reasons.append(LidarProjectionDiagnosticCode.STRUCTURAL_QA_FAILED)
    if inputs.rgb_frame_set_ref is None:
        reasons.append(LidarProjectionDiagnosticCode.RGB_FRAME_SET_MISSING)
    if (
        inputs.clock_offset_seconds is None
        or inputs.clock_relation is None
        or inputs.clock_relation.value == ClockRelation.UNKNOWN
        or inputs.timestamp_unit != "seconds"
    ):
        reasons.append(LidarProjectionDiagnosticCode.CLOCK_EVIDENCE_MISSING)
    if inputs.coordinate_unit is None or inputs.coordinate_unit.value.value != "m":
        reasons.append(LidarProjectionDiagnosticCode.METRIC_UNIT_UNAVAILABLE)
    if not frames:
        reasons.append(LidarProjectionDiagnosticCode.NO_SAMPLED_FRAMES)
    elif len(frames) < qa_profile.minimum_sampled_frames:
        reasons.append(LidarProjectionDiagnosticCode.INSUFFICIENT_SAMPLE_COUNT)

    frame_ids = [frame.frame_id for frame in frames]
    pose_ids = [frame.lidar_pose_id for frame in frames]
    if frame_ids != sorted(set(frame_ids)) or len(pose_ids) != len(set(pose_ids)):
        reasons.append(LidarProjectionDiagnosticCode.FRAME_SOURCE_MAPPING_INVALID)
    observations = {row.rgb_frame_id: row for row in inputs.observations}
    for frame in frames:
        observation = observations.get(frame.frame_id)
        if (
            observation is None
            or observation.lidar_pose_id != frame.lidar_pose_id
            or observation.lidar_timestamp_sec is None
            or not math.isclose(observation.rgb_timestamp_sec, frame.rgb_timestamp_sec, abs_tol=1e-9)
            or not math.isclose(observation.lidar_timestamp_sec, frame.lidar_timestamp_sec, abs_tol=1e-9)
            or frame.lidar_pose_id >= package.pose_count
        ):
            reasons.append(LidarProjectionDiagnosticCode.FRAME_SOURCE_MAPPING_INVALID)
            break

    readiness_reasons = {
        LidarProjectionDiagnosticCode.STRUCTURAL_QA_FAILED,
        LidarProjectionDiagnosticCode.INSUFFICIENT_SAMPLE_COUNT,
        LidarProjectionDiagnosticCode.CALIBRATION_EVIDENCE_MISSING,
        LidarProjectionDiagnosticCode.CAMERA_INTRINSICS_MISSING,
        LidarProjectionDiagnosticCode.CAMERA_DISTORTION_UNQUALIFIED,
        LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN,
        LidarProjectionDiagnosticCode.RGB_FRAME_SET_MISSING,
        LidarProjectionDiagnosticCode.CLOCK_EVIDENCE_MISSING,
        LidarProjectionDiagnosticCode.METRIC_UNIT_UNAVAILABLE,
        LidarProjectionDiagnosticCode.NO_SAMPLED_FRAMES,
        LidarProjectionDiagnosticCode.FRAME_SOURCE_MAPPING_INVALID,
    }
    frame_evidence: list[LidarCalibrationProjectionFrameEvidence] = []
    if not any(code in readiness_reasons for code in reasons) and projection_model is not None:
        prepared = [_prepare_frame(frame, projection_profile) for frame in frames]
        frame_evidence = [
            _frame_evidence(frame, inputs, qa_profile, projection_profile, projection_model) for frame in prepared
        ]

    frame_errors = sorted(
        frame.median_edge_distance_px for frame in frame_evidence if frame.median_edge_distance_px is not None
    )
    median_error = median(frame_errors) if frame_errors else None
    p90_error = frame_errors[nearest_rank_index(len(frame_errors), 0.9)] if frame_errors else None
    spread = p90_error - median_error if p90_error is not None and median_error is not None else None
    if spread is not None and spread > projection_profile.maximum_frame_median_spread_px:
        reasons.append(LidarProjectionDiagnosticCode.CROSS_FRAME_SCORE_VARIANCE)

    visible_count = sum(frame.visible_projected_point_count for frame in frame_evidence)
    overlap_count = sum(frame.overlap_point_count for frame in frame_evidence)
    overlap_fraction = overlap_count / visible_count if visible_count else None
    observable_count = sum(frame.observable for frame in frame_evidence)
    matched_count = sum(
        frame.timestamp_residual_sec <= qa_profile.maximum_timestamp_residual_sec for frame in frame_evidence
    )
    enough_data = (
        len(frame_evidence) >= qa_profile.minimum_sampled_frames
        and matched_count >= qa_profile.minimum_matched_frames
        and observable_count >= qa_profile.minimum_overlapping_frames
    )
    stable_frames = spread is None or spread <= projection_profile.maximum_frame_median_spread_px
    scoring_status = "SCORED" if enough_data and stable_frames and not reasons else "INCONCLUSIVE"

    return seal_lidar_calibration_projection_evidence(
        package_ref=inputs.package_ref,
        calibration_ref=package.calibration_ref,
        trajectory_ref=package.trajectory_ref,
        timing_ref=package.frame_times_ref,
        intrinsics_ref=inputs.intrinsics_ref,
        rgb_frame_set_ref=inputs.rgb_frame_set_ref,
        qa_profile=qa_profile,
        projection_profile=projection_profile,
        projection_model=projection_model,
        frames=frame_evidence,
        scoring_status=scoring_status,
        qualification_status="diagnostic_only",
        diagnostic_reasons=sorted(set(reasons), key=lambda value: value.value),
        observable_frame_count=observable_count,
        projected_point_count=visible_count,
        overlap_point_count=overlap_count,
        overlap_fraction=overlap_fraction,
        median_frame_error_px=median_error,
        p90_frame_error_px=p90_error,
        frame_median_spread_px=spread,
    )
