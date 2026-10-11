"""Quality-preserving geometry profile resolution for REC-05."""

import pytest

from src.services.reconstruction.finalize import GeometryProfile, build_voxel_config


def profile(**overrides: object) -> GeometryProfile:
    values = {
        "profile": "fixture",
        "resolution_m": 0.05,
        "opacity": 0.1,
        "cluster_resolution_m": 0.025,
        "cluster_opacity": 0.1,
        "cluster_min_contribution": 0.004,
        "capsule_radius_m": 0.461,
        "capsule_height_m": 0.308,
        "max_seed_relocation_m": 1.0,
        "seed_floor_clearance_m": 0.05,
        "crop_margin_m": 6.0,
        "crop_below_floor_m": 0.5,
        "crop_height_m": 4.0,
        "cluster_seed_height_m": 0.02,
        "cleanup": "floaters",
        "gpu_index": 0,
    }
    return GeometryProfile.model_validate(values | overrides)


def test_voxel_config_keeps_requested_resolution_and_cleanup_profile() -> None:
    """The effective config must not silently coarsen either requested resolution."""
    config = build_voxel_config(profile(), ((-1.0, -1.0, -0.5), (1.0, 1.0, 3.0)), (0.0, 0.0, 0.5))
    assert config.resolution_m == 0.05
    assert config.cluster_resolution_m == 0.025
    assert config.cleanup == "floaters"


def test_oversized_crop_fails_instead_of_raising_voxel_resolution() -> None:
    """A capacity limit must ask for an explicit crop/profile change, not degrade geometry."""
    with pytest.raises(ValueError, match="requested voxel resolution 0.05 m exceeds voxel capacity"):
        build_voxel_config(profile(), ((0.0, 0.0, 0.0), (10_000.0, 10_000.0, 10.0)), (1.0, 1.0, 0.5))
