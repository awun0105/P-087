"""Saved benchmark parsing and deterministic collision-quality fixture checks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from eval.fixtures.collision_quality import (
    CAMERA_OFFSET_SENSITIVITY,
    CLEARANCE_FIXTURES,
    FLOOR_SUPPORT_SAMPLES_M,
    PATH_CENTER_M,
    ROBOT_HEIGHT_M,
    ROBOT_RADIUS_M,
    SAMPLE_RETENTION_TOLERANCE_M,
    ClearanceFixture,
)
from eval.path.collision_quality import measure_sample_retention, parse_clearance_jsonl
from eval.path.path_clearance import blocked_positions

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_saved_rgb_baseline_preserves_counts_and_missing_provenance() -> None:
    path = REPOSITORY_ROOT / "eval/results/collision_path_clearance/aisle-cw-local-t2000.jsonl"
    evidence = parse_clearance_jsonl(path)

    assert len(evidence.records) == 3
    baseline = next(record for record in evidence.records if record.resolution_m == 0.05)
    assert (baseline.blocked_positions, baseline.camera_positions, baseline.blocked_fraction) == (33, 50, 0.66)
    assert baseline.evidence_class == "origin_unrecorded_free_space_proxy"
    assert baseline.independent_obstacle_recall_measured is False
    assert "source_geometry_checksum" in baseline.missing_provenance
    assert "hardware_id" in baseline.missing_provenance
    assert evidence.file_checksum.startswith("sha256:")


def test_saved_lidar_baseline_keeps_ground_truth_assisted_label() -> None:
    path = REPOSITORY_ROOT / "eval/results/collision_path_clearance/aisle-cw-100-lidar-job.jsonl"
    evidence = parse_clearance_jsonl(path)
    passing = next(record for record in evidence.records if record.min_range_m == 2.0 and record.floor_band_m == 0.15)

    assert (passing.blocked_positions, passing.camera_positions, passing.blocked_fraction) == (0, 100, 0.0)
    assert passing.evidence_class == "gt_assisted_free_space_proxy"
    assert passing.independent_obstacle_recall_measured is False
    assert {"profile_checksum", "source_geometry_checksum", "hardware_id"}.issubset(passing.missing_provenance)


def test_saved_record_parser_rejects_count_fraction_disagreement(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(
            {
                "benchmark": "collision_path_clearance",
                "label": "bad",
                "measured_at": "2026-10-01T00:00:00+00:00",
                "status": "ok",
                "resolution_m": 0.05,
                "blocked_positions": 1,
                "camera_positions": 2,
                "blocked_fraction": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="blocked_fraction does not match"):
        parse_clearance_jsonl(path)


@pytest.mark.parametrize("fixture", CLEARANCE_FIXTURES, ids=lambda fixture: fixture.fixture_id)
def test_clearance_path_fixture_classification(fixture: ClearanceFixture) -> None:
    vertices = np.asarray(fixture.vertices_m, dtype=float).reshape(-1, 3)
    centers = np.asarray([PATH_CENTER_M], dtype=float)
    result = blocked_positions(vertices, centers, ROBOT_RADIUS_M, ROBOT_HEIGHT_M)

    assert bool(result) is fixture.expected_blocked


def test_floor_support_samples_are_retained_and_do_not_block_robot() -> None:
    expected, retained, fraction = measure_sample_retention(
        FLOOR_SUPPORT_SAMPLES_M, FLOOR_SUPPORT_SAMPLES_M, SAMPLE_RETENTION_TOLERANCE_M
    )
    blocked = blocked_positions(FLOOR_SUPPORT_SAMPLES_M, np.asarray([PATH_CENTER_M]), ROBOT_RADIUS_M, ROBOT_HEIGHT_M)

    assert (expected, retained, fraction) == (4, 4, 1.0)
    assert blocked == []


def test_deleted_geometry_fails_thin_obstacle_retention() -> None:
    reference = np.asarray(
        ((0.2, 0.0, 0.1), (0.35, 0.0, 0.05), (0.25, 0.0, 0.04)),
        dtype=float,
    )
    expected, retained, fraction = measure_sample_retention(reference, np.empty((0, 3)), 0.01)

    assert expected == 3
    assert retained == 0
    assert fraction == 0.0


def test_thin_obstacle_fixture_matrix_measures_full_sample_retention() -> None:
    selected = [
        fixture
        for fixture in CLEARANCE_FIXTURES
        if fixture.fixture_id
        in {
            "shelf_leg_thin_obstacle",
            "pallet_foot_low_obstacle",
            "cable_low_obstacle",
        }
    ]
    reference = np.asarray([fixture.vertices_m[0] for fixture in selected], dtype=float)
    expected, retained, fraction = measure_sample_retention(reference, reference.copy(), SAMPLE_RETENTION_TOLERANCE_M)
    partial_expected, partial_retained, partial_fraction = measure_sample_retention(
        reference, reference[:-1], SAMPLE_RETENTION_TOLERANCE_M
    )

    assert (expected, retained, fraction) == (3, 3, 1.0)
    assert partial_expected == 3
    assert partial_retained == 2
    assert partial_fraction == pytest.approx(2 / 3)


def test_camera_offset_changes_a_boundary_clearance_result() -> None:
    obstacle = np.asarray([CAMERA_OFFSET_SENSITIVITY["obstacle_vertex_m"]], dtype=float)
    camera_center = np.asarray([CAMERA_OFFSET_SENSITIVITY["camera_center_m"]], dtype=float)
    robot_center = np.asarray([CAMERA_OFFSET_SENSITIVITY["robot_center_after_offset_m"]], dtype=float)

    camera_result = blocked_positions(obstacle, camera_center, ROBOT_RADIUS_M, ROBOT_HEIGHT_M)
    robot_result = blocked_positions(obstacle, robot_center, ROBOT_RADIUS_M, ROBOT_HEIGHT_M)

    assert bool(camera_result) is CAMERA_OFFSET_SENSITIVITY["camera_path_expected_blocked"]
    assert bool(robot_result) is CAMERA_OFFSET_SENSITIVITY["robot_path_expected_blocked"]


def test_fixture_matrix_contains_required_thin_obstacles_and_walls() -> None:
    fixture_ids = {fixture.fixture_id for fixture in CLEARANCE_FIXTURES}
    assert {
        "shelf_leg_thin_obstacle",
        "pallet_foot_low_obstacle",
        "cable_low_obstacle",
        "wall_crossing_path",
        "ramp_edge_crossing_path",
        "low_box_crossing_path",
        "narrow_passage_inside_envelope",
    }.issubset(fixture_ids)
