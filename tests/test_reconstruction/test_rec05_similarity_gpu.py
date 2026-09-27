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
from src.services.reconstruction.adapters.voxel_clearance import validate_seed_clearance
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
            # Tâm phòng synthetic: seed cũ z=.5 chạm dilation floor ở native y=1.1.
            "navigation_seed_world": transform.apply_point((1, 1.5, 0.75)),
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
    _assert_room_report(report)
    _assert_relocation_on_real_occupancy(tmp_path, transform)
    assert file_checksum(source) == request.source_checksum


def _assert_relocation_on_real_occupancy(tmp_path: Path, transform: SimilarityTransform) -> None:
    """Seed chạm dilation sàn phải được dời trong vùng liên thông, không phải bị từ chối.

    Đây là seed cũ từng làm test fail; giữ nó làm negative proof cho ADR amendment
    thay vì xoá đi, vì upstream 3.6.6 sẽ âm thầm dời mà không ghi lại điểm mới.
    """
    occupied = tmp_path / "voxel"
    probe = tmp_path / "relocation-probe"
    probe.mkdir()
    for name in ("occupancy.voxel.json", "occupancy.voxel.bin"):
        (probe / name).write_bytes((occupied / name).read_bytes())
    settings = _config(transform).model_copy(update={"navigation_seed_world": (3.25, 2.5, 1.25)})
    receipt = validate_seed_clearance(probe, settings)
    assert receipt["relocates"] is True
    assert receipt["requested_seed_world"] == [3.25, 2.5, 1.25]
    assert receipt["accepted_seed_world"] != receipt["requested_seed_world"]
    assert 0 < receipt["relocation_distance_m"] <= settings.max_seed_relocation_m
    assert receipt["relocation_bound_m"] == settings.max_seed_relocation_m
    assert receipt["reachable_cells"] > 0


def _assert_room_report(report: dict) -> None:
    assert report["gaussian_counts"] == {"input": 2703, "cluster": 2702}
    for key in ("boundary_edges", "nonmanifold_edges", "degenerate_triangles"):
        assert report["topology"][key] == 0
    assert report["canonical_bounds"]["min"] == pytest.approx((2.5, 2, 1), abs=0.25)
    assert report["canonical_bounds"]["max"] == pytest.approx((4, 3, 1.75), abs=0.25)
