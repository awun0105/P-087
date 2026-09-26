"""REC-05 config/adapter proof; synthetic geometry không xác nhận scale Aisle_CW."""

import pytest

from src.services.reconstruction.rgb.voxel import (
    VoxelConfig,
    cluster_command,
    collision_command,
    native_from_world,
    world_from_native,
)


def config(**changes: object) -> VoxelConfig:
    """Kích thước chỉ dành cho synthetic fixture, không default robot product."""
    values = dict(
        resolution_m=0.1,
        opacity=0.1,
        cluster_resolution_m=0.1,
        cluster_opacity=0.1,
        cluster_min_contribution=0.004,
        cluster_seed_world=(1.0, 0.0, 0.5),
        navigation_seed_world=(0.0, 0.0, 0.5),
        capsule_height_m=0.4,
        capsule_radius_m=0.1,
        gpu_index=0,
    )
    return VoxelConfig.model_validate(values | changes)


def test_explicit_pipeline_and_coordinate_conversion() -> None:
    """Hai seeds khác nhau; capsule theo Y-up sau chuyển canonical đúng một lần."""
    cfg = config()
    cluster, collision = cluster_command(cfg), collision_command(cfg)
    assert cluster[cluster.index("--filter-cluster") + 1] == "0.1,0.1,0.004"
    assert cluster[cluster.index("--seed-pos") + 1] == "1.0,0.5,-0.0"
    assert collision[-1] == "geometry.voxel.json"
    assert collision[collision.index("--voxel-carve") + 1] == "0.4,0.1"
    assert "--scale" not in cluster + collision
    assert "--voxel-floor-fill" not in collision
    assert world_from_native(native_from_world((1.0, 2.0, 3.0))) == (1.0, 2.0, 3.0)
    assert config(capsule_radius_m=0.2).checksum() != cfg.checksum()


@pytest.mark.parametrize(
    "field,value",
    [
        ("resolution_m", 0),
        ("opacity", float("nan")),
        ("capsule_radius_m", -1),
        ("capsule_height_m", 0),
        ("gpu_index", "cpu"),
        ("navigation_seed_world", (0, float("inf"), 0)),
    ],
)
def test_invalid_config_rejected(field: str, value: object) -> None:
    """Không để malformed metric config tới subprocess."""
    with pytest.raises(ValueError):
        config(**{field: value})


@pytest.mark.parametrize("field", ["capsule_height_m", "capsule_radius_m", "navigation_seed_world"])
def test_missing_robot_configuration_rejected(field: str) -> None:
    """CLI defaults không phải authority cho robot thực."""
    values = config().model_dump()
    del values[field]
    with pytest.raises(ValueError):
        VoxelConfig.model_validate(values)
