"""Fixture orchestration proof tách biệt real GPU qualification."""

import json
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter, SyntheticVoxelRequest, file_checksum
from src.services.reconstruction.adapters.voxel_output import validate_voxel_output
from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, VoxelRuntimeSettings
from tests.test_reconstruction.rec05_occupancy_fixture import occupancy_fixture, write_occupancy
from tests.test_reconstruction.test_rec05_collision import collision_fixture, write_fixture
from tests.test_reconstruction.test_rec05_voxel import config


def voxel_fixture(workspace: Path) -> dict:
    """Octree hợp lệ cho consumer reload; không chứng minh GPU carve hay quan hệ mesh/voxel."""
    metadata = write_occupancy(workspace, {(63, 63, 63)}, name="geometry")
    # Giữ extent 64 ô × 0.1m để pointers/depth nhất quán; bounds chứa mesh fixture.
    metadata["gridBounds"] = {"min": [-1, -1, -1], "max": [5.4, 5.4, 5.4]}
    metadata["sceneBounds"] = {"min": [-1, -1, -1], "max": [5.4, 5.4, 5.4]}
    (workspace / "geometry.voxel.json").write_text(json.dumps(metadata))
    return metadata


class FixtureProcess(VoxelProcess):
    """Không mô phỏng physics hoặc GPU; inject đúng process seam của adapter."""

    def run(self, arguments: tuple[str, ...], target: tuple[Path, str]) -> str:
        """Tạo bytes kiểm thử để exercise đầy đủ source/copy/output/report flow."""
        workspace, name = target
        text = "splat-transform v3.6.6 (afbc281)\n"
        text += "--filter-cluster --voxel-size --voxel-opacity --voxel-carve --seed-pos --collision-mesh"
        (workspace / f"{name}.log").write_text(text)
        if name == "inspect":
            (workspace / "inspection.json").write_text('{"info":{"numGaussians":256}}')
        elif name == "inspect-cluster":
            (workspace / "cluster-inspection.json").write_text('{"info":{"numGaussians":255}}')
        elif name == "cluster":
            (workspace / "cluster.ply").write_bytes((workspace / "input.ply").read_bytes())
        elif name == "collision":
            voxel_fixture(workspace)
            write_fixture(workspace / "geometry.collision.glb", collision_fixture())
        elif name == "occupancy":
            occupancy_fixture(workspace)
        elif name == "metric-transform":
            _fixture_metric_transform(workspace)
        return text


def _fixture_metric_transform(workspace: Path) -> None:
    """Mock process plumbing ONLY, không chứng minh Gaussian transform đúng."""
    (workspace / "input.ply").write_bytes((workspace / "source.ply").read_bytes())
    receipt = dict(
        version="3.6.6",
        revision="afbc281",
        transform=json.loads((workspace / "metric-transform.json").read_text()),
        num_gaussians=256,
        sh_bands=0,
        storage_mapping="PLY_inverse_times_PLY_times_metric",
    )
    (workspace / "metric-transform-receipt.json").write_text(json.dumps(receipt))


def adapter() -> SplatTransformVoxelAdapter:
    """Fixture runtime phải được inject chủ động, không là default của product."""
    return SplatTransformVoxelAdapter(
        FixtureProcess(VoxelRuntimeSettings(cli=Path("unused"), module_path=Path("unused")))
    )


def request(source: Path) -> SyntheticVoxelRequest:
    """Expected source identity bị khóa trước process."""
    return SyntheticVoxelRequest(source=source, source_checksum=file_checksum(source), config=config())


def test_private_attempt_and_immutable_source(tmp_path: Path) -> None:
    """Không publish shared artifact hay overwrite attempt hiện hữu."""
    source = tmp_path / "source.ply"
    source.write_bytes(b"fixture")
    task = request(source)
    output = tmp_path / "attempt"
    report = adapter().run_synthetic(task, output)
    assert report["evidence_kind"] == "synthetic_known_dimensions"
    assert report["product_artifact_published"] is False
    assert report["scale_applied"] == 1.0
    assert report["files"]["input.ply"] == file_checksum(source) == task.source_checksum
    assert json.loads((output / "qualification.json").read_text()) == report
    with pytest.raises(FileExistsError):
        adapter().run_synthetic(task, output)


@pytest.mark.parametrize("failure", ["missing", "tampered", "non_synthetic"])
def test_input_gate_precedes_process(tmp_path: Path, failure: str) -> None:
    """Không dùng synthetic entrypoint để tự nhận real scene metric-confirmed."""
    source = tmp_path / "source.ply"
    source.write_bytes(b"fixture")
    task = request(source)
    if failure == "missing":
        task = task.model_copy(update={"source": tmp_path / "missing.ply"})
    elif failure == "tampered":
        source.write_bytes(b"changed")
    else:
        task = task.model_copy(update={"evidence_kind": "metric_confirmed"})
    with pytest.raises((ValueError, OSError)):
        adapter().run_synthetic(task, tmp_path / "attempt")
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize("failure", ["truncated", "resolution", "bounds", "producer"])
def test_voxel_metadata_rejects_corruption(tmp_path: Path, failure: str) -> None:
    """Metadata cùng binary phải match requested run, không chỉ JSON parse được."""
    metadata = voxel_fixture(tmp_path)
    validate_voxel_output(tmp_path, config())
    if failure == "truncated":
        (tmp_path / "geometry.voxel.bin").write_bytes(b"\0")
    elif failure == "resolution":
        metadata["voxelResolution"] = 0.05
    elif failure == "bounds":
        metadata["gridBounds"]["min"][0] = 100
    else:
        metadata["asset"] = {}
    (tmp_path / "geometry.voxel.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        validate_voxel_output(tmp_path, config())


def test_no_report_on_invalid_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool output không đủ thì không có qualification receipt."""
    source = tmp_path / "source.ply"
    source.write_bytes(b"fixture")
    runner = adapter()
    monkeypatch.setattr(runner, "_pipeline", lambda cfg, workspace: None)
    with pytest.raises(GeometryError, match="no artifact published"):
        runner.run_synthetic(request(source), tmp_path / "attempt")
    assert not (tmp_path / "attempt/qualification.json").exists()
