"""T-043 bước 3 (voxel): Node/splat-transform không ghi log trong cửa sổ treo thì bị dừng."""

import sys
import time
from pathlib import Path

import pytest

from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, VoxelRuntimeSettings


def test_stall_window_default_and_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = VoxelRuntimeSettings(cli=Path("cli.js"), module_path=Path("mod"))
    assert settings.stall_seconds == 120
    monkeypatch.setenv("R2S_VOXEL_STALL_SECONDS", "7")
    assert VoxelRuntimeSettings(cli=Path("cli.js"), module_path=Path("mod")).stall_seconds == 7


def test_silent_geometry_tool_is_stopped_with_a_vietnamese_remedy(tmp_path: Path) -> None:
    fake = tmp_path / "silent_node.py"
    fake.write_text("import time\nprint('Voxelizing', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    settings = VoxelRuntimeSettings(
        cli=Path("cli.js"),
        module_path=Path("mod"),
        node_command=(sys.executable, str(fake)),
        timeout_seconds=30,
        stall_seconds=1,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = time.monotonic()

    with pytest.raises(GeometryError) as error:
        VoxelProcess(settings).run(("--voxel",), (workspace, "collision"))

    assert time.monotonic() - started < 20
    assert "không tiến triển" in str(error.value)
    assert "R2S_VOXEL_STALL_SECONDS" in str(error.value)
    assert "GEOMETRY_STALLED" in (workspace / "collision.log").read_text()


def test_geometry_tool_that_keeps_logging_is_not_stopped(tmp_path: Path) -> None:
    fake = tmp_path / "chatty_node.py"
    fake.write_text(
        "import time\nend = time.monotonic() + 2.5\nwhile time.monotonic() < end:\n"
        "    print('  ▸ Voxelizing', flush=True)\n    time.sleep(0.2)\n",
        encoding="utf-8",
    )
    settings = VoxelRuntimeSettings(
        cli=Path("cli.js"),
        module_path=Path("mod"),
        node_command=(sys.executable, str(fake)),
        timeout_seconds=30,
        stall_seconds=1,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    text = VoxelProcess(settings).run(("--voxel",), (workspace, "collision"))

    assert text.count("Voxelizing") >= 5
