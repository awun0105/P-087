"""Geometry overrides retain legacy receipts and reach the publication adapter."""

import hashlib
import json
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_json_bytes
from src.services.reconstruction.adapters.voxel import ProductVoxelRequest, _require_cluster_capacity
from src.services.reconstruction.rgb.geometry.geometry_publication import GeometryExecutionRequest
from src.services.reconstruction.rgb.geometry.voxel import VoxelConfig, collision_command, occupancy_command
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline
from tests.test_reconstruction.test_rec05_voxel import config


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_legacy_receipt_bytes(version: str) -> None:
    cfg = config(schema_version=version)
    legacy = cfg.model_dump(mode="json")
    assert "collision_mesh" not in legacy
    assert "floor_fill_size_m" not in legacy
    assert cfg.checksum() == "sha256:" + hashlib.sha256(canonical_json_bytes(legacy)).hexdigest()
    # Captured from the pre-CFG-04 implementation, not recomputed by this model.
    expected = {
        "1.0": "sha256:6d8063abf1a3bd9c7dc0a41cc1be256bc0d63e5a5936186b1493f0c1941743ef",
        "1.1": "sha256:8f19e50485955aabcf16e79bdcf0def7ad10d346a4f73e4fd856fe27b054395e",
        "1.2": "sha256:8235c1c8da3dbe01f40dd156387408f4c8875601dfc7e240fd93b776d6f1ca4c",
    }
    assert cfg.checksum() == expected[version]
    assert VoxelConfig.model_validate(legacy).model_dump(mode="json") == legacy
    assert config(schema_version=version, collision_mesh="faces").checksum() != cfg.checksum()
    assert config(schema_version=version, floor_fill_size_m=0.5).checksum() != cfg.checksum()


@pytest.mark.parametrize("mesh", ["smooth", "faces"])
def test_collision_mesh_selection(mesh: str) -> None:
    command = collision_command(config(collision_mesh=mesh))
    assert command[command.index("--collision-mesh") + 1] == mesh


@pytest.mark.parametrize("external,floor", [(None, None), (0.5, None), (None, 0.7), (0.5, 0.7)])
def test_fill_controls_apply_to_occupancy_and_collision(external: float | None, floor: float | None) -> None:
    cfg = config(schema_version="1.2", external_fill_size_m=external, floor_fill_size_m=floor)
    for command in (collision_command(cfg), occupancy_command(cfg)):
        for flag, value in (("--voxel-external-fill", external), ("--voxel-floor-fill", floor)):
            if value is None:
                assert flag not in command
            else:
                assert command[command.index(flag) + 1] == str(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"collision_mesh": "invalid"},
        {"floor_fill_size_m": 0},
        {"floor_fill_size_m": -1},
        {"floor_fill_size_m": float("inf")},
        {"floor_fill_size_m": float("nan")},
    ],
)
def test_invalid_overrides_fail_before_execution(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        config(**changes)


def test_request_overrides_reach_adapter_and_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, canonicalizer, confirmation_ref, metric_request, _ = setup_pipeline(tmp_path)
    cfg = config(collision_mesh="faces", floor_fill_size_m=0.4)
    original = service.deps.adapter.run_product
    process = service.deps.adapter.process
    original_run = process.run
    seen: list[VoxelConfig] = []

    def run(arguments: tuple[str, ...], target: tuple[Path, str]) -> str:
        output = original_run(arguments, target)
        workspace, name = target
        if name == "help":
            output += " --voxel-floor-fill"
            (workspace / "help.log").write_text(output)
        if name == "inspect-cluster":
            path = workspace / "cluster-inspection.json"
            data = json.loads(path.read_text())
            data["stats"] = {
                "lods": [
                    {
                        "columns": ["x", "y", "z", "scale_0", "scale_1", "scale_2"],
                        "data": {"min": [0] * 6, "max": [1, 1, 1, -3, -3, -3]},
                    }
                ]
            }
            path.write_text(json.dumps(data))
        return output

    def capture(request: ProductVoxelRequest, workspace: Path) -> dict:
        seen.append(request.config)
        return original(request, workspace)

    monkeypatch.setattr(service.deps.adapter, "run_product", capture)
    monkeypatch.setattr(process, "run", run)
    request = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=confirmation_ref,
        source_visual=metric_request.source_visual,
        config=cfg,
        job_id="test-job-rec05",
        seed_proposal=canonicalizer.propose_navigation_seed(confirmation_ref),
    )
    result = service.execute(request, tmp_path / "override")
    assert seen == [cfg]
    assert result.report["config"]["collision_mesh"] == "faces"
    assert result.report["config"]["floor_fill_size_m"] == 0.4
    assert result.report["config_checksum"] == cfg.checksum()


def test_floor_fill_capacity_rejects_oversized_grid(tmp_path: Path) -> None:
    stats = {
        "stats": {
            "lods": [
                {
                    "columns": ["x", "y", "z", "scale_0", "scale_1", "scale_2"],
                    "data": {"min": [0] * 6, "max": [1, 1, 1, -3, -3, -3]},
                }
            ]
        }
    }
    (tmp_path / "cluster-inspection.json").write_text(json.dumps(stats))
    _require_cluster_capacity(tmp_path, config(floor_fill_size_m=0.4))
    with pytest.raises(ValueError, match="voxel capacity"):
        _require_cluster_capacity(tmp_path, config(floor_fill_size_m=1000))
