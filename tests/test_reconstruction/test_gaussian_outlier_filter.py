from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from src.models.contracts.identity import canonical_json_bytes
from src.services.reconstruction.adapters.gaussian_outlier_filter import filter_gaussian_ply
from src.services.reconstruction.finalize import GeometryProfile, build_voxel_config
from src.services.reconstruction.rgb.geometry.geometry_artifact import _cleanup_evidence
from src.services.reconstruction.rgb.geometry.voxel import (
    StatisticalOutlierRemovalConfig,
    VoxelConfig,
    cluster_command,
)

_ROW_DTYPE = np.dtype(
    [
        ("x", "<f4"),
        ("y", "<f4"),
        ("z", "<f4"),
        ("opacity", "<f4"),
        ("scale_0", "<f4"),
        ("scale_1", "<f4"),
        ("scale_2", "<f4"),
        ("rot_0", "<f4"),
        ("f_dc_0", "<f4"),
        ("semantic_id", "<u4"),
    ]
)


def _config(**changes: object) -> StatisticalOutlierRemovalConfig:
    values: dict[str, object] = {"neighbors": 8, "standard_deviation_ratio": 1.0, "max_gaussians": 500}
    values.update(changes)
    return StatisticalOutlierRemovalConfig.model_validate(values)


def _ply(rows: np.ndarray) -> bytes:
    fields = [
        ("float", "x"),
        ("float", "y"),
        ("float", "z"),
        ("float", "opacity"),
        ("float", "scale_0"),
        ("float", "scale_1"),
        ("float", "scale_2"),
        ("float", "rot_0"),
        ("float", "f_dc_0"),
        ("uint", "semantic_id"),
    ]
    header = ["ply", "format binary_little_endian 1.0", "comment source test", f"element vertex {len(rows)}"]
    header.extend(f"property {ply_type} {name}" for ply_type, name in fields)
    header.extend(("element face 0", "property list uchar int vertex_indices", "end_header"))
    return ("\n".join(header) + "\n").encode("ascii") + np.ascontiguousarray(rows).tobytes()


def _rows(points: np.ndarray) -> np.ndarray:
    rows = np.zeros(len(points), dtype=_ROW_DTYPE)
    rows["x"], rows["y"], rows["z"] = points[:, 0], points[:, 1], points[:, 2]
    rows["opacity"] = np.linspace(-1.0, 1.0, len(rows), dtype=np.float32)
    rows["scale_0"] = np.arange(len(rows), dtype=np.float32) / 100.0
    rows["semantic_id"] = np.arange(len(rows), dtype=np.uint32) + 100
    return rows


def _read_rows(path: Path) -> np.ndarray:
    payload = path.read_bytes()
    header_end = payload.index(b"end_header\n") + len(b"end_header\n")
    declared = next(
        int(line.split()[2]) for line in payload[:header_end].decode().splitlines() if line.startswith("element vertex")
    )
    return np.frombuffer(payload, dtype=_ROW_DTYPE, count=declared, offset=header_end)


@pytest.mark.parametrize(("scale", "noise", "slope"), [(0.25, 0.0, 0.0), (1.0, 0.002, 0.0), (4.0, 0.005, 0.5)])
def test_sor_removes_an_isolated_floater_and_preserves_every_vertex_field(
    tmp_path: Path, scale: float, noise: float, slope: float
) -> None:
    grid = np.array([(x * 0.05, y * 0.05, slope * x * 0.05) for x in range(12) for y in range(12)], dtype=np.float64)
    if noise:
        grid += np.random.default_rng(77).normal(0.0, noise, size=grid.shape)
    grid *= scale
    points = np.vstack((grid, np.array([[10.0, 10.0, 10.0]]) * scale))
    rows = _rows(points)
    source = tmp_path / "input.ply"
    output = tmp_path / "filtered.ply"
    source.write_bytes(_ply(rows))

    evidence = filter_gaussian_ply(source, output, _config())
    retained = _read_rows(output)

    assert evidence.input_gaussian_count == len(rows)
    assert evidence.retained_gaussian_count > len(grid) * 0.8
    assert evidence.removed_gaussian_count >= 1
    assert evidence.input_checksum.startswith("sha256:")
    assert evidence.output_checksum.startswith("sha256:")
    assert evidence.quality_status == "diagnostic_only"
    assert retained.dtype.names == rows.dtype.names
    assert rows[-1]["semantic_id"] not in retained["semantic_id"]
    retained_indices = retained["semantic_id"].astype(np.int64) - 100
    np.testing.assert_array_equal(retained, rows[retained_indices])
    assert source.read_bytes() == _ply(rows)


def test_sor_can_remove_a_sparse_true_obstacle_and_is_not_quality_acceptance(tmp_path: Path) -> None:
    grid = np.array([(x * 0.05, y * 0.05, 0.0) for x in range(12) for y in range(12)], dtype=np.float64)
    sparse_obstacle = np.array([[2.0, 0.0, z] for z in (0.0, 0.04, 0.08)], dtype=np.float64)
    rows = _rows(np.vstack((grid, sparse_obstacle)))
    source = tmp_path / "input.ply"
    source.write_bytes(_ply(rows))

    evidence = filter_gaussian_ply(source, tmp_path / "filtered.ply", _config())

    assert evidence.removed_gaussian_count >= len(sparse_obstacle)
    assert evidence.quality_status == "diagnostic_only"


@pytest.mark.parametrize(
    ("neighbors", "standard_deviation_ratio", "max_gaussians"),
    [(1, 1.0, 20), (8, 0.0, 20), (8, 1.0, 8), (8, 1.0, 5_000_001)],
)
def test_sor_profile_rejects_invalid_or_unbounded_parameters(
    neighbors: int, standard_deviation_ratio: float, max_gaussians: int
) -> None:
    with pytest.raises(ValueError):
        _config(
            neighbors=neighbors,
            standard_deviation_ratio=standard_deviation_ratio,
            max_gaussians=max_gaussians,
        )


def test_sor_respects_profile_row_limit_and_rejects_malformed_ply(tmp_path: Path) -> None:
    rows = _rows(np.array([(float(index), 0.0, 0.0) for index in range(12)], dtype=np.float64))
    source = tmp_path / "input.ply"
    source.write_bytes(_ply(rows))
    with pytest.raises(ValueError, match="resource bound"):
        filter_gaussian_ply(source, tmp_path / "too-large.ply", _config(max_gaussians=10))

    source.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\nend_header\n")
    with pytest.raises(ValueError, match="binary_little_endian"):
        filter_gaussian_ply(source, tmp_path / "unsupported.ply", _config())

    existing = tmp_path / "existing.ply"
    existing.write_bytes(b"keep existing evidence")
    source.write_bytes(_ply(rows))
    with pytest.raises(FileExistsError):
        filter_gaussian_ply(source, existing, _config())
    assert existing.read_bytes() == b"keep existing evidence"


def test_sor_is_opt_in_and_does_not_change_existing_cluster_input() -> None:
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
    config = VoxelConfig.model_validate(values)
    enabled = VoxelConfig.model_validate(
        values
        | {
            "schema_version": "1.1",
            "statistical_outlier_removal": _config().model_dump(mode="json"),
        }
    )
    with pytest.raises(ValueError, match="schema 1.1"):
        VoxelConfig.model_validate(
            values
            | {
                "schema_version": "1.0",
                "statistical_outlier_removal": _config().model_dump(mode="json"),
            }
        )

    assert config.schema_version == "1.0"
    assert config.statistical_outlier_removal is None
    assert cluster_command(config)[0] == "input.ply"
    assert config.checksum() != enabled.checksum()
    assert (
        cluster_command(config, input_filename="statistical-filtered-input.ply")[0] == "statistical-filtered-input.ply"
    )


def test_sor_profile_is_versioned_and_passed_into_the_voxel_attempt() -> None:
    root = Path(__file__).resolve().parents[2]
    profile = GeometryProfile.model_validate(json.loads((root / "configs/product/geometry_v1.json").read_text()))
    with pytest.raises(ValueError, match="schema 1.1"):
        GeometryProfile.model_validate(
            profile.model_dump(mode="json") | {"statistical_outlier_removal": _config().model_dump(mode="json")}
        )

    opt_in_profile = GeometryProfile.model_validate(
        profile.model_dump(mode="json")
        | {"schema_version": "1.1", "statistical_outlier_removal": _config().model_dump(mode="json")}
    )
    voxel = build_voxel_config(
        opt_in_profile,
        crop=((-2.0, -2.0, 0.0), (2.0, 2.0, 3.0)),
        seed=(0.0, 0.0, 0.5),
    )
    assert voxel.schema_version == "1.1"
    assert voxel.statistical_outlier_removal == _config()


def test_cleanup_builder_binds_statistical_filter_to_metric_input_and_profile() -> None:
    config = {
        "cleanup": "floaters",
        "statistical_outlier_removal": _config().model_dump(mode="json"),
    }
    statistics = {
        "algorithm": "statistical_outlier_v1",
        "input_checksum": "sha256:" + "1" * 64,
        "output_checksum": "sha256:" + "2" * 64,
        "input_gaussian_count": 10,
        "retained_gaussian_count": 9,
        "removed_gaussian_count": 1,
        "neighbors": 8,
        "standard_deviation_ratio": 1.0,
        "max_gaussians": 500,
        "mean_neighbor_distance_m": 0.1,
        "standard_deviation_m": 0.01,
        "threshold_m": 0.11,
        "quality_status": "diagnostic_only",
    }
    report = {
        "config": config,
        "config_checksum": "sha256:" + hashlib.sha256(canonical_json_bytes(config)).hexdigest(),
        "source_checksum": "sha256:" + "3" * 64,
        "gaussian_counts": {"input": 10, "cluster": 8},
        "statistical_filter_evidence": statistics,
        "files": {
            "input.ply": statistics["input_checksum"],
            "statistical-filtered-input.ply": statistics["output_checksum"],
            "cluster.ply": "sha256:" + "4" * 64,
            "collision.glb": "sha256:" + "5" * 64,
        },
    }

    cleanup = _cleanup_evidence("job-1", report)

    assert cleanup.statistical_filter_evidence is not None
    assert cleanup.statistical_filter_evidence.output_checksum == statistics["output_checksum"]
    with pytest.raises(ValueError, match="source checksum"):
        _cleanup_evidence(
            "job-1",
            report | {"files": report["files"] | {"input.ply": "sha256:" + "6" * 64}},
        )
    inconsistent_statistics = statistics | {
        "input_gaussian_count": 9,
        "retained_gaussian_count": 8,
        "removed_gaussian_count": 1,
    }
    with pytest.raises(ValueError, match="count differs"):
        _cleanup_evidence("job-1", report | {"statistical_filter_evidence": inconsistent_statistics})
