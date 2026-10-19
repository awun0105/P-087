"""Evaluation-only LiDAR odometry drift metrics against an independent trajectory."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from bisect import bisect_left
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.input_assembly import ClockRelation, TimestampUnit
from src.models.contracts.reconstruction import EstimatedTrajectoryArtifact
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.inputs.timestamps import timestamps_in_seconds
from src.services.reconstruction.lidar.fusion import ScanPose, parse_trajectory

_MAX_ESTIMATE_BYTES = 128 * 1024 * 1024
_MAX_REFERENCE_BYTES = 16 * 1024 * 1024
_DISTANCE_TO_METERS = {"m": 1.0, "cm": 0.01, "mm": 0.001}


def evaluate_lidar_odometry(
    estimate: EstimatedTrajectoryArtifact,
    reference: Sequence[ScanPose],
    *,
    reference_checksum: str,
    reference_pose_frame: str,
    reference_distance_unit: str,
    reference_timestamp_unit: TimestampUnit,
    clock_relation: ClockRelation,
    clock_offset_seconds: float | None,
    maximum_interpolation_gap_seconds: float,
) -> dict[str, Any]:
    """Compare metric sensor poses without feeding the reference into the product path.

    ``clock_offset_seconds`` means estimate-clock time minus reference-clock time.
    Reference poses must already use seconds and meters and the same sensor frame.
    ATE uses only a rigid alignment at the first matched pose; it never fits scale or
    uses the full path to hide accumulated drift.
    """
    verify_content_checksum(estimate, "artifact_checksum")
    if reference_pose_frame != estimate.sensor_frame_id:
        raise ValueError("reference pose frame must match the estimated sensor frame")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", reference_checksum) is None:
        raise ValueError("reference trajectory checksum must be a SHA-256 digest")
    if reference_distance_unit not in _DISTANCE_TO_METERS:
        raise ValueError("reference distance unit must be m, cm, or mm")
    try:
        timestamp_unit = TimestampUnit(reference_timestamp_unit)
    except ValueError as error:
        raise ValueError("reference timestamp unit is unsupported") from error
    if not math.isfinite(maximum_interpolation_gap_seconds) or maximum_interpolation_gap_seconds <= 0:
        raise ValueError("maximum interpolation gap must be finite and positive")
    if clock_relation == ClockRelation.UNKNOWN:
        raise ValueError("reference clock relation must be same_clock or known_offset")
    if clock_relation == ClockRelation.SAME_CLOCK:
        if clock_offset_seconds not in (None, 0.0):
            raise ValueError("same-clock declaration cannot carry a non-zero offset")
        offset = 0.0
    else:
        if clock_offset_seconds is None or not math.isfinite(clock_offset_seconds):
            raise ValueError("known reference clock offset must be finite and explicit")
        offset = clock_offset_seconds

    reference_samples = _validated_reference(reference)
    reference_times = [sample[0] for sample in reference_samples]
    matches: list[tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    unmatched: list[int] = []
    for pose in estimate.poses:
        reference_time = pose.timestamp_seconds - offset
        sampled = _sample_reference(
            reference_samples, reference_times, reference_time, maximum_interpolation_gap_seconds
        )
        if sampled is None:
            unmatched.append(pose.scan_index)
            continue
        position, orientation = sampled
        matches.append(
            (
                pose.scan_index,
                np.asarray(pose.map_from_sensor.translation_xyz, dtype=np.float64),
                rotation_matrix(pose.map_from_sensor.rotation_quaternion_xyzw),
                position,
                orientation,
            )
        )

    reason_codes: list[str] = []
    absolute_error: dict[str, float] | None = None
    relative_translation_error: dict[str, float] | None = None
    relative_rotation_error: dict[str, float] | None = None
    relative_pair_count = 0
    if len(matches) < 2:
        status = "inconclusive"
        reason_codes.append("INSUFFICIENT_MATCHED_REFERENCE_POSES")
    else:
        status = "measured"
        first = matches[0]
        rotation_estimate_to_reference = first[4] @ first[2].T
        translation_estimate_to_reference = first[3] - rotation_estimate_to_reference @ first[1]
        position_errors = [
            float(
                np.linalg.norm(
                    rotation_estimate_to_reference @ sample[1] + translation_estimate_to_reference - sample[3]
                )
            )
            for sample in matches
        ]
        absolute_error = _summary(position_errors)

        translation_errors: list[float] = []
        rotation_errors: list[float] = []
        for left, right in zip(matches, matches[1:], strict=False):
            if right[0] != left[0] + 1:
                continue
            estimate_delta_rotation = left[2].T @ right[2]
            reference_delta_rotation = left[4].T @ right[4]
            rotation_error = estimate_delta_rotation @ reference_delta_rotation.T
            angle = math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(rotation_error)) - 1.0) / 2.0))))
            estimate_delta_translation = left[2].T @ (right[1] - left[1])
            reference_delta_translation = left[4].T @ (right[3] - left[3])
            translation_errors.append(float(np.linalg.norm(estimate_delta_translation - reference_delta_translation)))
            rotation_errors.append(angle)
        relative_pair_count = len(translation_errors)
        if relative_pair_count:
            relative_translation_error = _summary(translation_errors)
            relative_rotation_error = _summary(rotation_errors)
        else:
            reason_codes.append("NO_ADJACENT_MATCHED_POSE_PAIRS")

    return {
        "schema_version": "1.0",
        "artifact_type": "LidarOdometryReferenceEvaluation",
        "status": status,
        "trajectory_artifact_checksum": estimate.artifact_checksum,
        "reference_trajectory_checksum": reference_checksum,
        "reference_pose_frame": reference_pose_frame,
        "reference_distance_unit": reference_distance_unit,
        "reference_timestamp_unit": timestamp_unit.value,
        "reference_clock_relation": clock_relation.value,
        "reference_clock_offset_seconds": offset,
        "maximum_interpolation_gap_seconds": maximum_interpolation_gap_seconds,
        "alignment": "first_common_pose_rigid_no_scale",
        "requested_pose_count": len(estimate.poses),
        "matched_pose_count": len(matches),
        "coverage_ratio": len(matches) / len(estimate.poses),
        "unmatched_scan_indices": unmatched,
        "absolute_trajectory_error_m": absolute_error,
        "relative_pose_error_translation_m": relative_translation_error,
        "relative_pose_error_rotation_deg": relative_rotation_error,
        "relative_pose_pair_count": relative_pair_count,
        "trajectory_runtime_qualification_status": estimate.runtime_qualification_status,
        "product_solver_used_reference": False,
        "reason_codes": reason_codes,
    }


def _validated_reference(reference: Sequence[ScanPose]) -> list[tuple[float, np.ndarray, np.ndarray]]:
    if len(reference) < 2:
        raise ValueError("reference trajectory must contain at least two poses")
    result: list[tuple[float, np.ndarray, np.ndarray]] = []
    previous = -math.inf
    for pose in reference:
        timestamp = float(pose.timestamp)
        position = np.asarray(pose.translation, dtype=np.float64)
        quaternion = tuple(float(value) for value in pose.rotation_xyzw)
        if not math.isfinite(timestamp) or timestamp <= previous:
            raise ValueError("reference timestamps must be finite and strictly increasing")
        if position.shape != (3,) or not np.isfinite(position).all():
            raise ValueError("reference translations must be finite 3D positions in meters")
        quaternion_norm = math.hypot(*quaternion)
        if len(quaternion) != 4 or not math.isclose(quaternion_norm, 1.0, rel_tol=0.0, abs_tol=1e-3):
            raise ValueError("reference rotations must be normalized xyzw quaternions")
        normalized_quaternion = tuple(value / quaternion_norm for value in quaternion)
        result.append((timestamp, position, rotation_matrix(normalized_quaternion)))
        previous = timestamp
    return result


def _sample_reference(
    samples: list[tuple[float, np.ndarray, np.ndarray]],
    times: list[float],
    timestamp: float,
    maximum_gap_seconds: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    index = bisect_left(times, timestamp)
    if index < len(times) and math.isclose(times[index], timestamp, rel_tol=0.0, abs_tol=1e-9):
        return samples[index][1], samples[index][2]
    if index > 0 and math.isclose(times[index - 1], timestamp, rel_tol=0.0, abs_tol=1e-9):
        return samples[index - 1][1], samples[index - 1][2]
    if index == 0 or index == len(times):
        return None
    left, right = index - 1, index
    gap = times[right] - times[left]
    if gap > maximum_gap_seconds:
        return None
    fraction = (timestamp - times[left]) / gap
    position = (1.0 - fraction) * samples[left][1] + fraction * samples[right][1]
    rotations = Rotation.from_matrix([samples[left][2], samples[right][2]])
    orientation = Slerp([times[left], times[right]], rotations)([timestamp])[0].as_matrix()
    return position, orientation


def _summary(values: Sequence[float]) -> dict[str, float]:
    observed = np.asarray(values, dtype=np.float64)
    return {
        "rmse": round(float(math.sqrt(np.mean(observed**2))), 6),
        "median": round(float(np.percentile(observed, 50)), 6),
        "p90": round(float(np.percentile(observed, 90)), 6),
        "max": round(float(observed.max()), 6),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimate", type=Path, required=True, help="checksummed EstimatedTrajectoryArtifact JSON")
    parser.add_argument("--reference", type=Path, required=True, help="independent TUM reference trajectory")
    parser.add_argument("--reference-pose-frame", required=True, help="verified frame name of the reference poses")
    parser.add_argument("--reference-distance-unit", choices=tuple(_DISTANCE_TO_METERS), required=True)
    parser.add_argument("--reference-timestamp-unit", choices=[unit.value for unit in TimestampUnit], required=True)
    parser.add_argument(
        "--reference-clock-relation",
        choices=[ClockRelation.SAME_CLOCK.value, ClockRelation.KNOWN_OFFSET.value],
        required=True,
    )
    parser.add_argument("--reference-clock-offset-seconds", type=float)
    parser.add_argument("--maximum-interpolation-gap-seconds", type=float, required=True)
    parser.add_argument("--output", type=Path, help="optional JSON report path; defaults to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.estimate.stat().st_size > _MAX_ESTIMATE_BYTES:
            raise ValueError("estimated trajectory artifact exceeds the 128 MiB evaluator limit")
        if args.reference.stat().st_size > _MAX_REFERENCE_BYTES:
            raise ValueError("reference trajectory exceeds the 16 MiB evaluator limit")
        estimate = EstimatedTrajectoryArtifact.model_validate_json(args.estimate.read_bytes())
        reference_bytes = args.reference.read_bytes()
        reference_rows = parse_trajectory(reference_bytes.decode("utf-8-sig"))
        seconds = timestamps_in_seconds(
            tuple(pose.timestamp for pose in reference_rows), TimestampUnit(args.reference_timestamp_unit)
        )
        scale = _DISTANCE_TO_METERS[args.reference_distance_unit]
        reference = [
            ScanPose(
                timestamp=seconds[index],
                translation=tuple(value * scale for value in pose.translation),
                rotation_xyzw=pose.rotation_xyzw,
            )
            for index, pose in enumerate(reference_rows)
        ]
        checksum = "sha256:" + hashlib.sha256(reference_bytes).hexdigest()
        report = evaluate_lidar_odometry(
            estimate,
            reference,
            reference_checksum=checksum,
            reference_pose_frame=args.reference_pose_frame,
            reference_distance_unit=args.reference_distance_unit,
            reference_timestamp_unit=TimestampUnit(args.reference_timestamp_unit),
            clock_relation=ClockRelation(args.reference_clock_relation),
            clock_offset_seconds=args.reference_clock_offset_seconds,
            maximum_interpolation_gap_seconds=args.maximum_interpolation_gap_seconds,
        )
        payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            sys.stdout.write(payload)
        else:
            if args.output.resolve() in {args.estimate.resolve(), args.reference.resolve()}:
                raise ValueError("evaluation output must not overwrite an input file")
            args.output.write_text(payload, encoding="utf-8")
        return 0
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"LIDAR_ODOMETRY_EVALUATION_FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
