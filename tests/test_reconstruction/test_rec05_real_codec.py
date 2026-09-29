"""Opt-in upstream PLY inspection thật và negative capsule test trên GPU thật."""

import os
from pathlib import Path

import pytest

from src.services.reconstruction.adapters import voxel
from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, VoxelRuntimeSettings
from tests.test_reconstruction.smoke.rec05_smoke import smoke_config, synthetic_room
from tests.test_reconstruction.test_rec04_brush import gaussian_ply


@pytest.mark.parametrize("mode", ["valid", "plain", "nan", "quaternion", "truncated"])
def test_upstream_gaussian_inspection(tmp_path: Path, mode: str) -> None:
    """Bật REC05_TEST_SPLAT_MODULE để test package provision thực, không npm install."""
    module = os.environ.get("REC05_TEST_SPLAT_MODULE")
    if not module:
        pytest.skip("REC05_TEST_SPLAT_MODULE chưa được cấu hình")
    gaussian_ply(tmp_path / "input.ply", mode)
    settings = VoxelRuntimeSettings(cli=Path("unused"), module_path=Path(module))
    process = VoxelProcess(settings)
    script = Path(voxel.__file__).with_name("voxel_inspect.mjs")
    arguments = (str(script.resolve()), str(Path(module).resolve()))
    if mode == "valid":
        process.run(arguments, (tmp_path, "inspect"))
        assert (tmp_path / "inspection.json").is_file()
    else:
        with pytest.raises(GeometryError):
            process.run(arguments, (tmp_path, "inspect"))
        assert not (tmp_path / "inspection.json").exists()


def test_real_gpu_rejects_before_skipped_carve(tmp_path: Path) -> None:
    """Occupancy GPU thật reject seed ngoài grid trước khi gọi carve có thể skip."""
    if os.environ.get("REC05_TEST_GPU") != "1":
        pytest.skip("REC05_TEST_GPU=1 và runtime settings cần được cấu hình")
    source = tmp_path / "synthetic.ply"
    synthetic_room(source)
    values = smoke_config(0.1).model_dump() | {"navigation_seed_world": (100, 100, 100)}
    request = voxel.SyntheticVoxelRequest(
        source=source,
        source_checksum=voxel.file_checksum(source),
        config=values,
    )
    runner = voxel.SplatTransformVoxelAdapter(VoxelProcess(VoxelRuntimeSettings()))
    output = tmp_path / "negative"
    with pytest.raises(GeometryError) as failure:
        runner.run_synthetic(request, output)
    assert "outside occupancy bounds" in str(failure.value.__cause__)
    assert not (output / "collision.log").exists()
    assert (output / "occupancy.voxel.bin").is_file()
    assert not (output / "qualification.json").exists()
    assert not (output / "collision.glb").exists()
    assert voxel.file_checksum(source) == request.source_checksum
