"""Opt-in real GPU: full similarity derivative → voxel/carve/canonical collision."""

import math
import os
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.gaussian_scale import (
    GaussianTransformRequest,
    SplatTransformSimilarityAdapter,
)
from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter, SyntheticVoxelRequest, file_checksum
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings
from src.services.reconstruction.rgb.metric_math import SimilarityTransform
from src.services.reconstruction.rgb.voxel import VoxelConfig
from tests.test_reconstruction.rec05_smoke import smoke_config, synthetic_room


def _config(transform: SimilarityTransform) -> VoxelConfig:
    config = smoke_config(0.05)
    return config.model_copy(
        update={
            "cluster_resolution_m": 0.05,
            "cluster_seed_world": transform.apply_point(config.cluster_seed_world),
            "navigation_seed_world": transform.apply_point(config.navigation_seed_world),
            "capsule_height_m": 0.2,
            "capsule_radius_m": 0.05,
        }
    )


def test_transformed_room_real_gpu(tmp_path: Path) -> None:
    """Kích thước/footprint chỉ cho fixture, không là real robot hay Aisle_CW metric."""
    if os.environ.get("REC05_TEST_GPU") != "1":
        pytest.skip("REC05_TEST_GPU=1 và runtime settings cần được cấu hình")
    process = VoxelProcess(VoxelRuntimeSettings())
    source = tmp_path / "source.ply"
    synthetic_room(source)
    transform = SimilarityTransform(
        scale_m_per_sfm_unit=0.5,
        rotation_xyzw=(0, 0, math.sqrt(0.5), math.sqrt(0.5)),
        translation_m=(4, 2, 1),
    )
    request = GaussianTransformRequest(source=source, source_checksum=file_checksum(source), transform=transform)
    SplatTransformSimilarityAdapter(process).transform(request, tmp_path / "metric")
    derivative = tmp_path / "metric/input.ply"
    voxel_request = SyntheticVoxelRequest(
        source=derivative,
        source_checksum=file_checksum(derivative),
        config=_config(transform),
    )
    report = SplatTransformVoxelAdapter(process).run_synthetic(voxel_request, tmp_path / "voxel")
    assert report["gaussian_counts"] == {"input": 2703, "cluster": 2702}
    for key in ("boundary_edges", "nonmanifold_edges", "degenerate_triangles"):
        assert report["topology"][key] == 0
    assert report["canonical_bounds"]["min"] == pytest.approx((2.5, 2, 1), abs=0.25)
    assert report["canonical_bounds"]["max"] == pytest.approx((4, 3, 1.75), abs=0.25)
    assert file_checksum(source) == request.source_checksum
