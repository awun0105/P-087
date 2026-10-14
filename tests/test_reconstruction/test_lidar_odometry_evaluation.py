from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from eval.pose.lidar_odometry_error import evaluate_lidar_odometry, main
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.input_assembly import ClockRelation, TimestampUnit
from src.models.contracts.reconstruction import (
    EstimatedTrajectoryArtifact,
    EstimatedTrajectoryDiagnostics,
    EstimatedTrajectoryPose,
)
from src.services.reconstruction.lidar.fusion import ScanPose


def _estimate(
    timestamps: tuple[float, ...],
    positions: tuple[tuple[float, float, float], ...],
    rotations: tuple[tuple[float, float, float, float], ...] | None = None,
) -> EstimatedTrajectoryArtifact:
    assert len(timestamps) == len(positions) >= 2
    orientations = rotations or ((0.0, 0.0, 0.0, 1.0),) * len(timestamps)
    assert len(orientations) == len(timestamps)
    poses = [
        EstimatedTrajectoryPose(
            scan_index=index,
            source_scan_file_id=f"scan-{index}",
            source_scan_checksum="sha256:" + hashlib.sha256(f"scan-{index}".encode()).hexdigest(),
            timestamp_seconds=timestamp,
            map_from_sensor=Transform(
                parent_frame="odometry-map",
                local_frame="lidar",
                translation_xyz=position,
                rotation_quaternion_xyzw=orientation,
            ),
        )
        for index, (timestamp, position, orientation) in enumerate(
            zip(timestamps, positions, orientations, strict=True)
        )
    ]
    gaps = [right - left for left, right in zip(timestamps, timestamps[1:], strict=False)]
    diagnostics = EstimatedTrajectoryDiagnostics(
        scan_count=len(poses),
        valid_pose_count=len(poses),
        coverage_ratio=1.0,
        timestamp_gap_threshold_seconds=max(gaps) + 1.0,
        timestamp_gap_count=0,
        maximum_timestamp_gap_seconds=max(gaps),
    )
    payload = {
        "artifact_type": "EstimatedTrajectoryArtifact",
        "schema_version": "1.0",
        "artifact_uri": "artifact://jobs/job-eval/attempts/attempt-1/lidar-odometry/trajectory.json",
        "artifact_checksum": "sha256:" + "0" * 64,
        "job_id": "job-eval",
        "assembly_id": "assembly-eval",
        "assembly_revision": 1,
        "assembly_checksum": "sha256:" + "1" * 64,
        "recipe_checksum": "sha256:" + "2" * 64,
        "provider_id": "kiss-icp-python",
        "provider_version": "1.3.0",
        "adapter_protocol_version": "1",
        "runtime_qualification_checksum": "sha256:" + "3" * 64,
        "config_checksum": "sha256:" + "4" * 64,
        "timestamp_file_checksum": "sha256:" + "5" * 64,
        "coordinate_unit": "meter",
        "sensor_frame_id": "lidar",
        "odometry_map_frame_id": "odometry-map",
        "world_from_map": None,
        "trajectory_origin": "estimated",
        "runtime_qualification_status": "wired_unqualified",
        "poses": [pose.model_dump(mode="json") for pose in poses],
        "diagnostics": diagnostics.model_dump(mode="json"),
    }
    provisional = EstimatedTrajectoryArtifact.model_validate(payload)
    payload["artifact_checksum"] = canonical_content_checksum(provisional, "artifact_checksum")
    return EstimatedTrajectoryArtifact.model_validate(payload)


def _reference(
    timestamps: tuple[float, ...],
    positions: tuple[tuple[float, float, float], ...],
    rotation: tuple[float, float, float, float] = (0, 0, 0, 1),
) -> list[ScanPose]:
    return [ScanPose(timestamp, position, rotation) for timestamp, position in zip(timestamps, positions, strict=True)]


def _evaluate(
    estimate: EstimatedTrajectoryArtifact,
    reference: list[ScanPose],
    *,
    clock_relation: ClockRelation = ClockRelation.SAME_CLOCK,
    clock_offset_seconds: float | None = None,
    maximum_interpolation_gap_seconds: float = 1.0,
) -> dict:
    return evaluate_lidar_odometry(
        estimate,
        reference,
        reference_checksum="sha256:" + "a" * 64,
        reference_pose_frame="lidar",
        reference_distance_unit="m",
        reference_timestamp_unit=TimestampUnit.SECONDS,
        clock_relation=clock_relation,
        clock_offset_seconds=clock_offset_seconds,
        maximum_interpolation_gap_seconds=maximum_interpolation_gap_seconds,
    )


def test_rigid_initial_alignment_reports_no_error_for_same_path_in_another_map() -> None:
    estimate = _estimate((0.0, 1.0, 2.0), ((0, 0, 0), (1, 0, 0), (2, 1, 0)))
    rotation = Rotation.from_euler("z", 72, degrees=True)
    matrix = rotation.as_matrix()
    offset = np.array((7.0, -3.0, 1.5))
    positions = tuple(tuple(matrix @ np.asarray(point) + offset) for point in ((0, 0, 0), (1, 0, 0), (2, 1, 0)))

    report = _evaluate(estimate, _reference((0.0, 1.0, 2.0), positions, tuple(rotation.as_quat())))

    assert report["status"] == "measured"
    assert report["alignment"] == "first_common_pose_rigid_no_scale"
    assert report["absolute_trajectory_error_m"]["rmse"] == pytest.approx(0.0, abs=1e-6)
    assert report["relative_pose_error_translation_m"]["rmse"] == pytest.approx(0.0, abs=1e-6)
    assert report["relative_pose_error_rotation_deg"]["rmse"] == pytest.approx(0.0, abs=1e-6)


def test_reference_evaluator_reports_accumulated_translation_drift_without_fitting_it_away() -> None:
    estimate = _estimate((0.0, 1.0, 2.0), ((0, 0, 0), (1, 0, 0), (2.2, 0, 0)))
    reference = _reference((0.0, 1.0, 2.0), ((0, 0, 0), (1, 0, 0), (2, 0, 0)))

    report = _evaluate(estimate, reference)

    assert report["absolute_trajectory_error_m"]["max"] == pytest.approx(0.2)
    assert report["relative_pose_error_translation_m"]["max"] == pytest.approx(0.2)
    assert report["trajectory_runtime_qualification_status"] == "wired_unqualified"
    assert report["product_solver_used_reference"] is False


def test_reference_evaluator_reports_relative_rotation_drift() -> None:
    estimate = _estimate((0.0, 1.0, 2.0), ((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    reference = [
        ScanPose(timestamp, (timestamp, 0, 0), tuple(Rotation.from_euler("z", yaw, degrees=True).as_quat()))
        for timestamp, yaw in ((0.0, 0.0), (1.0, 5.0), (2.0, 10.0))
    ]

    report = _evaluate(estimate, reference)

    assert report["relative_pose_error_rotation_deg"]["median"] == pytest.approx(5.0)
    assert report["relative_pose_error_rotation_deg"]["max"] == pytest.approx(5.0)


def test_known_clock_offset_and_bounded_reference_interpolation_are_explicit() -> None:
    estimate = _estimate((10.0, 11.0, 12.0), ((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    reference = _reference((0.0, 0.5, 1.5, 2.0), ((0, 0, 0), (0.5, 0, 0), (1.5, 0, 0), (2, 0, 0)))

    report = _evaluate(
        estimate,
        reference,
        clock_relation=ClockRelation.KNOWN_OFFSET,
        clock_offset_seconds=10.0,
        maximum_interpolation_gap_seconds=1.0,
    )

    assert report["reference_clock_offset_seconds"] == 10.0
    assert report["matched_pose_count"] == 3
    assert report["coverage_ratio"] == 1.0
    assert report["absolute_trajectory_error_m"]["rmse"] == pytest.approx(0.0, abs=1e-6)


def test_reference_evaluator_does_not_extrapolate_or_cross_large_reference_gaps() -> None:
    estimate = _estimate((0.0, 1.0, 2.0), ((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    reference = _reference((0.0, 2.0), ((0, 0, 0), (2, 0, 0)))

    report = _evaluate(estimate, reference, maximum_interpolation_gap_seconds=1.0)

    assert report["matched_pose_count"] == 2
    assert report["unmatched_scan_indices"] == [1]
    assert report["coverage_ratio"] == pytest.approx(2 / 3)
    assert report["relative_pose_pair_count"] == 0
    assert "NO_ADJACENT_MATCHED_POSE_PAIRS" in report["reason_codes"]


def test_evaluator_rejects_unknown_clock_and_mismatched_sensor_frame() -> None:
    estimate = _estimate((0.0, 1.0), ((0, 0, 0), (1, 0, 0)))
    reference = _reference((0.0, 1.0), ((0, 0, 0), (1, 0, 0)))
    kwargs = {
        "reference_checksum": "sha256:" + "a" * 64,
        "reference_distance_unit": "m",
        "reference_timestamp_unit": TimestampUnit.SECONDS,
        "clock_offset_seconds": None,
        "maximum_interpolation_gap_seconds": 1.0,
    }

    with pytest.raises(ValueError, match="clock relation"):
        evaluate_lidar_odometry(
            estimate,
            reference,
            reference_pose_frame="lidar",
            clock_relation=ClockRelation.UNKNOWN,
            **kwargs,
        )
    with pytest.raises(ValueError, match="sensor frame"):
        evaluate_lidar_odometry(
            estimate,
            reference,
            reference_pose_frame="camera",
            clock_relation=ClockRelation.SAME_CLOCK,
            **kwargs,
        )


def test_evaluator_rejects_estimated_artifact_with_stale_logical_checksum() -> None:
    estimate = _estimate((0.0, 1.0), ((0, 0, 0), (1, 0, 0)))
    tampered = estimate.model_copy(update={"assembly_revision": 2})

    with pytest.raises(ValueError, match="does not match canonical content"):
        _evaluate(tampered, _reference((0.0, 1.0), ((0, 0, 0), (1, 0, 0))))


def test_cli_converts_declared_reference_units_and_writes_report(tmp_path: Path) -> None:
    estimate = _estimate((0.0, 1.0, 2.0), ((0, 0, 0), (1, 0, 0), (2.2, 0, 0)))
    estimate_path = tmp_path / "estimate.json"
    estimate_path.write_text(estimate.model_dump_json(), encoding="utf-8")
    reference_bytes = b"0 0 0 0 0 0 0 1\n1000 100 0 0 0 0 0 1\n2000 200 0 0 0 0 0 1\n"
    reference_path = tmp_path / "reference.txt"
    reference_path.write_bytes(reference_bytes)
    output_path = tmp_path / "report.json"

    result = main(
        [
            "--estimate",
            str(estimate_path),
            "--reference",
            str(reference_path),
            "--reference-pose-frame",
            "lidar",
            "--reference-distance-unit",
            "cm",
            "--reference-timestamp-unit",
            "milliseconds",
            "--reference-clock-relation",
            "same_clock",
            "--maximum-interpolation-gap-seconds",
            "1",
            "--output",
            str(output_path),
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["reference_trajectory_checksum"] == "sha256:" + hashlib.sha256(reference_bytes).hexdigest()
    assert report["reference_distance_unit"] == "cm"
    assert report["reference_timestamp_unit"] == "milliseconds"
    assert report["absolute_trajectory_error_m"]["max"] == pytest.approx(0.2)
