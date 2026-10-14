"""Quality-preserving geometry profile resolution for REC-05."""

import json
from pathlib import Path

import pytest

from src.services.reconstruction.finalize import GeometryProfile, build_voxel_config, load_geometry_profile


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


def test_job_geometry_controls_reach_voxel_and_preserve_deployment_profile(tmp_path: Path) -> None:
    """Explicit zero disables deployment fill; the chosen mesh mode reaches the native adapter."""
    original = profile(schema_version="1.2", external_fill_size_m=1.6)
    path = tmp_path / "geometry.json"
    path.write_text(original.model_dump_json())
    resolved = load_geometry_profile(
        path,
        overrides={"external_fill_size_m": 0, "floor_fill_size_m": 1.2, "collision_mesh": "faces", "resolution_m": 0.1},
    )
    config = build_voxel_config(resolved, ((-1.0, -1.0, -0.5), (1.0, 1.0, 3.0)), (0.0, 0.0, 0.5))
    assert config.external_fill_size_m is None
    assert config.floor_fill_size_m == 1.2 and config.collision_mesh == "faces"
    assert config.resolution_m == 0.1
    assert resolved.capsule_radius_m == original.capsule_radius_m
    assert load_geometry_profile(path).checksum() == original.checksum()
    assert resolved.checksum() != original.checksum()
    assert GeometryProfile.model_validate_json(resolved.model_dump_json()) == resolved


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_default_new_geometry_controls_preserve_historical_profile_bytes(version: str) -> None:
    """Added defaults must not invalidate bundle geometry snapshots."""
    resolved = profile(schema_version=version)
    historical = resolved.model_dump()
    assert "floor_fill_size_m" not in historical and "collision_mesh" not in historical
    assert resolved.model_dump_json() == json.dumps(historical, separators=(",", ":"))


def test_enabling_external_fill_versions_legacy_profile(tmp_path: Path) -> None:
    path = tmp_path / "geometry.json"
    path.write_text(profile().model_dump_json())
    resolved = load_geometry_profile(path, overrides={"external_fill_size_m": 1.6})
    assert resolved.schema_version == "1.2" and resolved.external_fill_size_m == 1.6


@pytest.mark.parametrize(
    "overrides",
    [
        {"unexpected": 1},
        {"external_fill_size_m": -1},
        {"floor_fill_size_m": True},
        {"resolution_m": 0},
        {"collision_mesh": "unknown"},
    ],
)
def test_invalid_job_geometry_fails_before_native_execution(tmp_path: Path, overrides: dict) -> None:
    path = tmp_path / "geometry.json"
    path.write_text(profile().model_dump_json())
    with pytest.raises(ValueError):
        load_geometry_profile(path, overrides=overrides)


def test_floor_fill_capacity_is_checked_before_native_execution() -> None:
    with pytest.raises(ValueError, match="capacity"):
        build_voxel_config(profile(floor_fill_size_m=1000), ((-1.0, -1.0, -0.5), (1.0, 1.0, 3.0)), (0.0, 0.0, 0.5))
