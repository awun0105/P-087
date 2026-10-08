"""Bounded LiDAR voxel collision mesh candidates preserve source points and evidence."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.floor_model import FloorFitProfile, FloorModel, FloorPrior
from src.models.contracts.identity import canonical_json_bytes
from src.services.reconstruction.adapters.collision_glb import read_collision_glb, topology
from src.services.reconstruction.adapters.lidar_collision import (
    LidarCollisionProfile,
    build_lidar_collision_candidate,
)
from src.services.scene.floor_model import fit_floor_model, point_cloud_checksum


def source_points() -> np.ndarray:
    floor = np.asarray([(x, y, 0.0) for x in np.linspace(-1.0, 1.0, 9) for y in np.linspace(-1.0, 1.0, 9)])
    low_obstacle = np.asarray([(0.0, 0.0, 0.07), (0.1, 0.0, 0.12), (0.2, 0.0, 0.25)])
    below_floor = np.asarray([(0.4, 0.2, -0.08)])
    return np.vstack((floor, low_obstacle, below_floor)).astype(np.float64)


def supported_floor(points: np.ndarray) -> FloorModel:
    return fit_floor_model(
        points,
        point_cloud_checksum(points),
        FloorPrior(up_direction_world=(0.0, 0.0, 1.0), point_on_floor_world=(0.0, 0.0, 0.0)),
        FloorFitProfile(min_coverage_area_m2=0.5),
    )


def profile(**overrides: object) -> LidarCollisionProfile:
    return LidarCollisionProfile(profile_id="unit-test", voxel_m=0.1, **overrides)


def mask_evidence_ref() -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type="LidarSelfMask",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-1/lidar/self-mask.bin",
        artifact_checksum="sha256:" + "b" * 64,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="lidar.self-mask",
        job_id="job-1",
    )


def test_candidate_preserves_floor_low_obstacles_and_below_floor_points(tmp_path) -> None:  # noqa: ANN001
    points = source_points()
    floor = supported_floor(points)
    assert floor.status == "supported"
    original = points.copy()
    selected_profile = profile()

    result = build_lidar_collision_candidate(points, floor, selected_profile)
    output = tmp_path / "lidar-collision.glb"
    output.write_bytes(result.glb_bytes)
    decoded = read_collision_glb(output)

    assert np.array_equal(points, original)
    assert result.report.input_point_count == len(points)
    assert result.report.retained_point_count == len(points)
    assert result.report.self_masked_point_count == 0
    assert result.report.floor_support_point_count == 81
    assert result.report.above_floor_point_count == 3
    assert result.report.below_floor_point_count == 1
    assert result.report.occupied_voxel_count == len(np.unique(np.floor(points / 0.1), axis=0))
    assert result.report.floor_model_checksum == "sha256:" + hashlib.sha256(canonical_json_bytes(floor)).hexdigest()
    assert result.report.profile_id == selected_profile.profile_id
    assert result.report.algorithm == selected_profile.algorithm
    assert result.report.voxel_m == selected_profile.voxel_m
    assert result.report.physics_claim == "unverified"
    assert result.report.calibration_eligibility == "not_evaluated_by_mesh_builder"
    assert topology(decoded)["degenerate_triangles"] == 0
    assert topology(decoded)["boundary_edges"] == 0
    assert topology(decoded)["nonmanifold_edges"] == 0
    assert result.report.output_collision_checksum == "sha256:" + hashlib.sha256(result.glb_bytes).hexdigest()
    # The voxel surface covers source cells and remains in the source frame.
    assert min(point[2] for point in decoded.positions) < 0.0
    assert max(point[2] for point in decoded.positions) > 0.25


def test_self_mask_requires_exactly_aligned_boolean_mask_and_reference() -> None:
    points = source_points()
    floor = supported_floor(points)
    mask = np.zeros(len(points), dtype=bool)
    mask[-2] = True
    evidence_ref = mask_evidence_ref()

    with pytest.raises(ValueError, match="evidence reference"):
        build_lidar_collision_candidate(points, floor, profile(), self_mask=mask)
    with pytest.raises(ValueError, match="boolean vector"):
        build_lidar_collision_candidate(
            points, floor, profile(), self_mask=mask.astype(np.uint8), self_mask_ref=evidence_ref
        )
    with pytest.raises(ValueError, match="no resolved mask"):
        build_lidar_collision_candidate(points, floor, profile(), self_mask_ref=evidence_ref)

    result = build_lidar_collision_candidate(points, floor, profile(), self_mask=mask, self_mask_ref=evidence_ref)
    assert result.report.self_masked_point_count == 1
    assert result.report.retained_point_count == len(points) - 1
    assert result.report.above_floor_point_count == 2
    assert result.report.self_mask_evidence_ref == evidence_ref
    assert result.report.self_mask_binding_checksum is not None


def test_rejects_uncertain_or_stale_floor_model() -> None:
    points = source_points()
    floor = supported_floor(points)
    stale = floor.model_copy(update={"source_checksum": "sha256:" + "a" * 64})
    uncertain = fit_floor_model(points, point_cloud_checksum(points), None)

    with pytest.raises(ValueError, match="exact ordered"):
        build_lidar_collision_candidate(points, stale, profile())
    with pytest.raises(ValueError, match="supported measured floor"):
        build_lidar_collision_candidate(points, uncertain, profile())


def test_resource_budgets_fail_before_grid_allocation() -> None:
    points = source_points()
    floor = supported_floor(points)
    with pytest.raises(ValueError, match="voxel grid exceeds"):
        build_lidar_collision_candidate(points, floor, profile(max_voxel_cells=100))
    with pytest.raises(ValueError, match="point count"):
        build_lidar_collision_candidate(points, floor, profile(max_input_points=8))
    with pytest.raises(ValueError, match="triangle limit"):
        build_lidar_collision_candidate(points, floor, profile(max_triangles=12))


@pytest.mark.parametrize("points", [np.empty((0, 3)), np.asarray([[1.0, 2.0]]), np.asarray([[0.0, 0.0, np.nan]])])
def test_rejects_empty_malformed_and_nonfinite_clouds(points: np.ndarray) -> None:
    floor = supported_floor(source_points())
    with pytest.raises(ValueError):
        build_lidar_collision_candidate(points, floor, profile())


def test_repeated_candidate_encoding_is_deterministic() -> None:
    points = source_points()
    floor = supported_floor(points)
    first = build_lidar_collision_candidate(points, floor, profile())
    second = build_lidar_collision_candidate(points, floor, profile())

    assert first.glb_bytes == second.glb_bytes
    assert first.report.output_collision_checksum == second.report.output_collision_checksum
