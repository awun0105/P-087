"""Opt-in upstream PLY inspection thật, không dùng fake parser hoặc GPU."""

import os
from pathlib import Path

import pytest

from src.services.reconstruction.adapters import voxel
from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, VoxelRuntimeSettings
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
