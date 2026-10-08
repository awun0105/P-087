"""Proof cho shared `GeometryArtifact`: EX-SIM không cần tin lời producer.

Contract này là hợp đồng giữa EX-REC (produce) và EX-SIM (consume), nên test tập trung
vào các invariant mà validator phải chặn được, không chỉ kiểm field tồn tại.
"""

import hashlib
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.coordinates import CoordinateSystem, MetricScale, MetricScaleStatus, Transform
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.reconstruction import (
    CapsuleFootprint,
    DependencyOrigin,
    GeometryArtifact,
    GeometryCleanupEvidence,
    PreprocessingDependency,
    PreprocessingProvenance,
    SeedDecision,
    VoxelGridSummary,
)
from src.services.reconstruction.rgb.geometry.geometry_artifact import (
    GeometryArtifactInput,
    build_geometry_artifact,
)

SHA = "sha256:" + "a" * 64
OTHER_SHA = "sha256:" + "b" * 64


def _voxel() -> VoxelGridSummary:
    return VoxelGridSummary(
        resolution_m=0.05,
        grid_bounds_min_xyz_m=(-1.0, -1.0, -1.0),
        grid_bounds_max_xyz_m=(1.0, 1.0, 1.0),
        scene_bounds_min_xyz_m=(-0.9, -0.9, -0.9),
        scene_bounds_max_xyz_m=(0.9, 0.9, 0.9),
    )


def _seed(relocates: bool = False) -> SeedDecision:
    accepted = (0.4, 0.0, 0.2) if relocates else (0.3, 0.0, 0.1)
    return SeedDecision(
        requested_world_m=(0.3, 0.0, 0.1),
        accepted_world_m=accepted,
        relocates=relocates,
        relocation_distance_m=math.dist((0.3, 0.0, 0.1), accepted),
        relocation_bound_m=1.0,
        occupancy_checksum=OTHER_SHA,
        clearance_evidence_checksum=SHA,
    )


def _transform() -> Transform:
    return Transform(
        parent_frame="world",
        local_frame="sfm_world",
        translation_xyz=(10.0, 20.0, 30.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.7071067811865476, 0.7071067811865476),
    )


def _provenance(origin: DependencyOrigin = DependencyOrigin.ESTIMATED) -> PreprocessingProvenance:
    return PreprocessingProvenance(
        dependencies=[PreprocessingDependency(role="source_visual_master", origin=origin, source_checksum=OTHER_SHA)],
        ground_truth_assisted=origin == DependencyOrigin.GROUND_TRUTH,
    )


def _artifact(**overrides) -> GeometryArtifact:
    values = dict(
        artifact_type="GeometryArtifact",
        schema_version="1.0",
        artifact_uri="artifact://jobs/j1/rec05/collision.glb",
        artifact_checksum=SHA,
        producer_stage="ST-RGB-GEOMETRY",
        job_id="j1",
        source_modality="rgb_3dgs",
        geometry_format="glb",
        coordinate_system=CoordinateSystem(),
        metric_scale=MetricScale(status=MetricScaleStatus.CONFIRMED, meters_per_unit=1.0),
        applied_confirmation_checksum=OTHER_SHA,
        applied_transform=_transform(),
        source_master_checksum=OTHER_SHA,
        voxel=_voxel(),
        seed=_seed(),
        capsule=CapsuleFootprint(height_m=1.2, radius_m=0.35, length_m=0.5),
        provenance=_provenance(),
    )
    values.update(overrides)
    return GeometryArtifact.model_validate(values)


def test_geometry_artifact_is_constructible_and_metric_bound() -> None:
    """Consumer thấy đủ: metric CONFIRMED, transform rigid đã áp, seed đã xác nhận."""
    artifact = _artifact()
    assert artifact.metric_scale.meters_per_unit == 1.0
    assert artifact.applied_transform.parent_frame == "world"
    assert artifact.voxel.resolution_m == 0.05
    assert artifact.seed.relocates is False


@pytest.mark.parametrize("meters", [None, 0.0, -1.0])
def test_unconfirmed_or_invalid_metric_scale_is_rejected(meters: float | None) -> None:
    """Scale chưa CONFIRMED thì không được xuất bản collision geometry."""
    with pytest.raises(ValidationError):
        _artifact(metric_scale=MetricScale(status=MetricScaleStatus.UNCONFIRMED, meters_per_unit=meters))


def test_ground_truth_dependency_is_rejected() -> None:
    """Product geometry không được phụ thuộc evaluation-only data."""
    with pytest.raises(ValidationError, match="evaluation ground truth"):
        _artifact(provenance=_provenance(DependencyOrigin.GROUND_TRUTH))


def test_seed_relocation_flag_must_match_the_two_points() -> None:
    """`relocates` là khẳng định, không phải gợi ý; consumer so được."""
    with pytest.raises(ValidationError, match="relocates must match"):
        _artifact(seed=_seed().model_copy(update={"relocates": True}))


def test_relocation_beyond_bound_is_rejected() -> None:
    """Distance vượt ngưỡng đã ghi thì contract invalid, không phải chỉ báo cáo."""
    too_far = _seed(relocates=True).model_copy(update={"relocation_distance_m": 5.0})
    with pytest.raises(ValidationError, match="exceeds the configured bound"):
        _artifact(seed=too_far)


def test_in_place_seed_cannot_claim_a_relocation_distance() -> None:
    """Seed giữ nguyên chỗ mà có distance là mâu thuẫn nội tại."""
    inconsistent = _seed().model_copy(update={"relocation_distance_m": 0.1})
    with pytest.raises(ValidationError, match="accepted in place"):
        _artifact(seed=inconsistent)


@pytest.mark.parametrize(
    "low,high",
    [((1.0, 0.0, 0.0), (1.0, 1.0, 1.0)), ((0.0, 2.0, 0.0), (1.0, 1.0, 1.0))],
)
def test_voxel_bounds_must_have_positive_extent(low: tuple, high: tuple) -> None:
    with pytest.raises(ValidationError, match="positive extent"):
        _artifact(voxel=_voxel().model_copy(update={"grid_bounds_min_xyz_m": low, "grid_bounds_max_xyz_m": high}))


@pytest.mark.parametrize("length", [0.9, 0.0, 0.6])
def test_capsule_length_must_be_height_minus_two_radii(length: float) -> None:
    """Physics engine dựng capsule từ ba số; lệch là sai hình học im lặng."""
    with pytest.raises(ValidationError, match="height minus two radii"):
        _artifact(capsule=CapsuleFootprint(height_m=1.2, radius_m=0.35, length_m=length))


def test_builder_converts_native_bounds_and_similarity() -> None:
    """Builder phải quy đổi native Y-up và tách scale khỏi phần rigid."""
    cleanup_config = {"cleanup": "floaters", "capsule_height_m": 0.4, "capsule_radius_m": 0.1}
    cleanup_config_checksum = "sha256:" + hashlib.sha256(canonical_json_bytes(cleanup_config)).hexdigest()
    payload = GeometryArtifactInput(
        job_id="j2",
        artifact_uri="artifact://jobs/j2/rec05/collision.glb",
        artifact_checksum=SHA,
        clearance_checksum=OTHER_SHA,
        source_master_checksum=OTHER_SHA,
        report={
            "coordinate_system": {"unit": "meter", "up_axis": "Z", "handedness": "right", "world_frame": "world"},
            "scale_applied": 0.5,
            "applied_confirmation_checksum": OTHER_SHA,
            "applied_transform": {
                "source_frame": "sfm_world",
                "target_frame": "world",
                "scale_m_per_sfm_unit": 0.5,
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "translation_m": [1.0, 2.0, 3.0],
            },
            "config": cleanup_config,
            "config_checksum": cleanup_config_checksum,
            "source_checksum": OTHER_SHA,
            "gaussian_counts": {"input": 10, "cluster": 8},
            "files": {"input.ply": OTHER_SHA, "cluster.ply": SHA, "collision.glb": SHA},
            "native_voxel_metadata": {
                "gridBounds": {"min": [0.0, 0.0, -4.0], "max": [2.0, 2.0, 0.0]},
                "sceneBounds": {"min": [0.0, 0.0, -4.0], "max": [2.0, 2.0, 0.0]},
                "voxelResolution": 0.1,
            },
        },
        clearance_receipt={
            "requested_seed_world": [0.1, 0.2, 0.3],
            "accepted_seed_world": [0.1, 0.2, 0.3],
            "relocates": False,
            "relocation_distance_m": 0.0,
            "relocation_bound_m": 1.0,
            "occupancy_binary_checksum": SHA,
        },
    )
    artifact = build_geometry_artifact(payload)
    # world_from_native(x, y, z) = (x, -z, y): native z=-4..0 thành world y=0..4.
    assert artifact.voxel.grid_bounds_min_xyz_m == (0.0, 0.0, 0.0)
    assert artifact.voxel.grid_bounds_max_xyz_m == (2.0, 4.0, 2.0)
    assert artifact.metric_scale.meters_per_unit == 1.0
    assert artifact.applied_scale_m_per_source_unit == 0.5
    assert artifact.applied_transform.translation_xyz == (1.0, 2.0, 3.0)
    assert artifact.capsule.shape == "clearance_cylinder"
    assert artifact.capsule.length_m == pytest.approx(0.4)
    assert artifact.cleanup_evidence is not None
    assert artifact.cleanup_evidence.removed_gaussian_count == 2
    assert artifact.cleanup_evidence.qualification_status == "diagnostic_only"


def test_cleanup_evidence_rejects_changed_config_or_nonconserving_counts() -> None:
    """Cleanup evidence must bind the exact profile and account for every removed splat."""
    effective_config = {"cleanup": "floaters"}
    checksum = "sha256:" + hashlib.sha256(canonical_json_bytes(effective_config)).hexdigest()
    evidence = GeometryCleanupEvidence(
        job_id="j1",
        mode="floaters",
        source_checksum=OTHER_SHA,
        metric_input_checksum=SHA,
        retained_gaussian_checksum=OTHER_SHA,
        collision_mesh_checksum=SHA,
        effective_config=effective_config,
        config_checksum=checksum,
        input_gaussian_count=10,
        retained_gaussian_count=8,
        removed_gaussian_count=2,
    )
    with pytest.raises(ValidationError, match="checksum"):
        GeometryCleanupEvidence.model_validate(
            evidence.model_dump() | {"effective_config": {"cleanup": "floaters", "threshold": 0.2}}
        )
    with pytest.raises(ValidationError, match="conserve"):
        GeometryCleanupEvidence.model_validate(evidence.model_dump() | {"removed_gaussian_count": 1})


def test_geometry_artifact_v1_2_requires_cleanup_evidence() -> None:
    """New RGB collision outputs cannot omit their cleanup report."""
    with pytest.raises(ValidationError, match="requires cleanup evidence"):
        _artifact(schema_version="1.2")


def test_builder_keeps_relocation_visible_in_the_contract(tmp_path: Path) -> None:
    """Relocation không được biến mất khi đi qua contract."""
    cleanup_config = {"cleanup": "floaters", "capsule_height_m": 1.2, "capsule_radius_m": 0.35}
    cleanup_config_checksum = "sha256:" + hashlib.sha256(canonical_json_bytes(cleanup_config)).hexdigest()
    payload = GeometryArtifactInput(
        job_id="j3",
        artifact_uri="artifact://jobs/j3/rec05/collision.glb",
        artifact_checksum=SHA,
        clearance_checksum=OTHER_SHA,
        source_master_checksum=OTHER_SHA,
        report={
            "coordinate_system": {"unit": "meter", "up_axis": "Z", "handedness": "right", "world_frame": "world"},
            "scale_applied": 1.0,
            "applied_confirmation_checksum": OTHER_SHA,
            "applied_transform": {
                "source_frame": "sfm_world",
                "target_frame": "world",
                "scale_m_per_sfm_unit": 1.0,
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "translation_m": [0.0, 0.0, 0.0],
            },
            "config": cleanup_config,
            "config_checksum": cleanup_config_checksum,
            "source_checksum": OTHER_SHA,
            "gaussian_counts": {"input": 10, "cluster": 8},
            "files": {"input.ply": OTHER_SHA, "cluster.ply": SHA, "collision.glb": SHA},
            "native_voxel_metadata": {
                "gridBounds": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
                "sceneBounds": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
                "voxelResolution": 0.05,
            },
        },
        clearance_receipt={
            "requested_seed_world": [0.1, 0.0, 0.1],
            "accepted_seed_world": [0.4, 0.0, 0.1],
            "relocates": True,
            "relocation_distance_m": 0.3,
            "relocation_bound_m": 1.0,
            "occupancy_binary_checksum": SHA,
        },
    )
    artifact = build_geometry_artifact(payload)
    assert artifact.seed.relocates is True
    assert artifact.seed.requested_world_m == (0.1, 0.0, 0.1)
    assert artifact.seed.accepted_world_m == (0.4, 0.0, 0.1)
    assert artifact.seed.relocation_distance_m == pytest.approx(0.3)
    assert artifact.capsule.length_m == pytest.approx(1.2)
