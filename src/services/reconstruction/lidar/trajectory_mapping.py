"""Diagnostic camera-pose mapping from estimated LiDAR odometry to RGB source PTS."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Literal

from scipy.spatial.transform import Rotation, Slerp

from src.models.contracts.coordinates import Transform
from src.models.contracts.input_assembly import ClockRelation
from src.models.contracts.reconstruction import EstimatedTrajectoryArtifact
from src.services.reconstruction.alignment.transforms import compose_transforms


@dataclass(frozen=True)
class RGBFrameTimestamp:
    """Verified output frame mapped to its original source frame and PTS in seconds."""

    output_frame_id: int
    source_frame_id: int
    source_timestamp_seconds: float


@dataclass(frozen=True)
class EstimatedCameraPose:
    """One diagnostic-only RGB camera pose interpolated from two LiDAR scan poses."""

    output_frame_id: int
    source_frame_id: int
    source_timestamp_seconds: float
    lidar_timestamp_seconds: float
    left_scan_index: int
    right_scan_index: int
    interpolation_fraction: float
    map_from_camera: Transform
    world_from_camera: Transform | None


@dataclass(frozen=True)
class UnmappedRGBFrame:
    output_frame_id: int
    source_frame_id: int
    reason_code: str


@dataclass(frozen=True)
class EstimatedCameraPoseMapping:
    """A pose mapping diagnostic. This result is never a calibration or drift PASS."""

    status: Literal["diagnostic_only"]
    #: True only when runtime qualification, world bridge, calibration/time, and all frame mappings are complete.
    complete_for_consumer: bool
    requested_frame_count: int
    poses: tuple[EstimatedCameraPose, ...]
    unmapped_frames: tuple[UnmappedRGBFrame, ...]
    reason_codes: tuple[str, ...]
    max_source_gap_seconds: float | None


def map_estimated_trajectory_to_rgb_frames(
    trajectory: EstimatedTrajectoryArtifact,
    rgb_frames: tuple[RGBFrameTimestamp, ...],
    sensor_from_camera: Transform | None,
    *,
    clock_relation: ClockRelation | None,
    clock_offset_seconds: float | None,
    maximum_interpolation_gap_seconds: float,
) -> EstimatedCameraPoseMapping:
    """Map source-video PTS to estimated camera poses without extrapolation.

    The offset follows AUD-13's residual convention: ``rgb_time - lidar_time - offset``.
    Without `world_from_map`, valid poses are still returned in the local odometry map
    frame for alignment diagnostics. Such a result is incomplete for canonical consumers.
    """
    if not rgb_frames:
        raise ValueError("RGB pose mapping requires at least one selected frame")
    if not math.isfinite(maximum_interpolation_gap_seconds) or maximum_interpolation_gap_seconds <= 0:
        raise ValueError("maximum interpolation gap must be finite and positive")
    _validate_rgb_frames(rgb_frames)

    mapping_blockers: list[str] = []
    if sensor_from_camera is None:
        mapping_blockers.append("CAMERA_LIDAR_CALIBRATION_REQUIRED")
    if clock_relation in (None, ClockRelation.UNKNOWN):
        mapping_blockers.append("CLOCK_RELATION_REQUIRED")
    elif clock_relation == ClockRelation.KNOWN_OFFSET and clock_offset_seconds is None:
        mapping_blockers.append("CLOCK_OFFSET_REQUIRED")
    if mapping_blockers:
        if trajectory.runtime_qualification_status != "qualified":
            mapping_blockers.append("ODOMETRY_RUNTIME_NOT_QUALIFIED")
        return _blocked_mapping(rgb_frames, tuple(mapping_blockers))

    assert sensor_from_camera is not None
    assert clock_relation is not None
    if trajectory.world_from_map is not None and (
        trajectory.world_from_map.parent_frame != "world"
        or trajectory.world_from_map.local_frame != trajectory.odometry_map_frame_id
    ):
        raise ValueError("confirmed world_from_map does not match the estimated odometry frame")
    if sensor_from_camera.parent_frame != trajectory.sensor_frame_id:
        raise ValueError("camera calibration parent frame does not match the estimated sensor frame")
    if clock_offset_seconds is not None and not math.isfinite(clock_offset_seconds):
        raise ValueError("clock offset must be finite")
    if clock_relation == ClockRelation.SAME_CLOCK and clock_offset_seconds not in (None, 0.0):
        raise ValueError("same-clock declaration cannot carry a non-zero offset")
    offset = (
        0.0 if clock_relation == ClockRelation.SAME_CLOCK and clock_offset_seconds is None else clock_offset_seconds
    )
    assert offset is not None

    times = [pose.timestamp_seconds for pose in trajectory.poses]
    mapped: list[EstimatedCameraPose] = []
    unmapped: list[UnmappedRGBFrame] = []
    reason_codes: list[str] = []
    if trajectory.runtime_qualification_status != "qualified":
        reason_codes.append("ODOMETRY_RUNTIME_NOT_QUALIFIED")
    if trajectory.world_from_map is None:
        reason_codes.append("WORLD_FROM_MAP_CONFIRMATION_REQUIRED")
    maximum_used_gap: float | None = None

    for frame in rgb_frames:
        lidar_time = frame.source_timestamp_seconds - offset
        bracket = _bracket(times, lidar_time)
        if bracket is None:
            reason = "RGB_TIMESTAMP_OUTSIDE_LIDAR_TRAJECTORY"
            unmapped.append(UnmappedRGBFrame(frame.output_frame_id, frame.source_frame_id, reason))
            reason_codes.append(reason)
            continue

        left_index, right_index, fraction = bracket
        gap = times[right_index] - times[left_index]
        if gap > maximum_interpolation_gap_seconds:
            reason = "LIDAR_TIMESTAMP_GAP_EXCEEDS_LIMIT"
            unmapped.append(UnmappedRGBFrame(frame.output_frame_id, frame.source_frame_id, reason))
            reason_codes.append(reason)
            continue
        maximum_used_gap = max(maximum_used_gap or 0.0, gap)

        left_pose = trajectory.poses[left_index]
        right_pose = trajectory.poses[right_index]
        map_from_sensor = _interpolate_transform(left_pose.map_from_sensor, right_pose.map_from_sensor, fraction)
        map_from_camera = compose_transforms(map_from_sensor, sensor_from_camera)
        world_from_camera = (
            compose_transforms(trajectory.world_from_map, map_from_camera)
            if trajectory.world_from_map is not None
            else None
        )
        mapped.append(
            EstimatedCameraPose(
                output_frame_id=frame.output_frame_id,
                source_frame_id=frame.source_frame_id,
                source_timestamp_seconds=frame.source_timestamp_seconds,
                lidar_timestamp_seconds=lidar_time,
                left_scan_index=left_index,
                right_scan_index=right_index,
                interpolation_fraction=fraction,
                map_from_camera=map_from_camera,
                world_from_camera=world_from_camera,
            )
        )

    return EstimatedCameraPoseMapping(
        status="diagnostic_only",
        complete_for_consumer=(
            trajectory.runtime_qualification_status == "qualified"
            and trajectory.world_from_map is not None
            and not unmapped
        ),
        requested_frame_count=len(rgb_frames),
        poses=tuple(mapped),
        unmapped_frames=tuple(unmapped),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        max_source_gap_seconds=maximum_used_gap,
    )


def _validate_rgb_frames(frames: tuple[RGBFrameTimestamp, ...]) -> None:
    output_ids = [frame.output_frame_id for frame in frames]
    source_ids = [frame.source_frame_id for frame in frames]
    timestamps = [frame.source_timestamp_seconds for frame in frames]
    if (
        any(frame_id < 0 for frame_id in output_ids + source_ids)
        or output_ids != sorted(set(output_ids))
        or source_ids != sorted(set(source_ids))
        or any(not math.isfinite(timestamp) for timestamp in timestamps)
        or any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False))
    ):
        raise ValueError("RGB frame IDs and source PTS must be unique, ordered, and finite")


def _blocked_mapping(
    frames: tuple[RGBFrameTimestamp, ...], reason_codes: tuple[str, ...]
) -> EstimatedCameraPoseMapping:
    unique_reason_codes = tuple(dict.fromkeys(reason_codes))
    return EstimatedCameraPoseMapping(
        status="diagnostic_only",
        complete_for_consumer=False,
        requested_frame_count=len(frames),
        poses=(),
        unmapped_frames=tuple(
            UnmappedRGBFrame(frame.output_frame_id, frame.source_frame_id, unique_reason_codes[0]) for frame in frames
        ),
        reason_codes=unique_reason_codes,
        max_source_gap_seconds=None,
    )


def _bracket(times: list[float], timestamp: float) -> tuple[int, int, float] | None:
    index = bisect.bisect_left(times, timestamp)
    if index < len(times) and math.isclose(times[index], timestamp, rel_tol=0.0, abs_tol=1e-9):
        return index, index, 0.0
    if index == 0 or index == len(times):
        return None
    left, right = index - 1, index
    gap = times[right] - times[left]
    return left, right, (timestamp - times[left]) / gap


def _interpolate_transform(left: Transform, right: Transform, fraction: float) -> Transform:
    if fraction == 0.0:
        return left
    if fraction == 1.0:
        return right
    position = tuple(
        (1.0 - fraction) * start + fraction * end
        for start, end in zip(left.translation_xyz, right.translation_xyz, strict=True)
    )
    orientations = Rotation.from_quat([left.rotation_quaternion_xyzw, right.rotation_quaternion_xyzw])
    rotation = Slerp([0.0, 1.0], orientations)([fraction])[0].as_quat()
    return Transform(
        parent_frame=left.parent_frame,
        local_frame=left.local_frame,
        translation_xyz=position,
        rotation_quaternion_xyzw=tuple(float(value) for value in rotation),
    )
