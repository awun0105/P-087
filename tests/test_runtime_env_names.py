"""Tên biến runtime theo chức năng (`R2S_*`) và tên cũ (`RECxx_*`) vẫn được nhận, kèm đúng một cảnh báo mỗi tên (T-036)."""

import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest

from src import runtime_env
from src.runtime_env import legacy_name, requirement_env_name, reset_warnings
from src.runtime_env import runtime_env as read_env
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings
from src.services.reconstruction.adapters.colmap_runtime import ColmapRuntimeSettings
from src.services.reconstruction.adapters.splat import SplatRuntimeSettings
from src.services.reconstruction.adapters.voxel_runtime import VoxelRuntimeSettings
from src.services.reconstruction.lidar.odometry import LidarOdometryRuntimeSettings
from src.services.reconstruction.metric_proposal import MogeSettings

PREFIX_PAIRS = list(runtime_env.LEGACY_PREFIXES.items())
_WARNING_LOGGER = "src.runtime_env"

#: (lớp, tiền tố mới, tiền tố cũ, trường bắt buộc, trường dò, giá trị chuỗi, giá trị mong đợi)
CASES: list[tuple[Any, str, str, dict[str, str], str, str, Any]] = [
    (
        ColmapRuntimeSettings,
        "R2S_COLMAP_",
        "REC03_COLMAP_",
        {"runtime_identity": "colmap-1"},
        "timeout_seconds",
        "120",
        120.0,
    ),
    (
        BrushRuntimeSettings,
        "R2S_BRUSH_",
        "REC04_BRUSH_",
        {"expected_version": "0.3.0", "runtime_identity": "brush-1"},
        "checkpoint_every",
        "500",
        500,
    ),
    (SplatRuntimeSettings, "R2S_SPLAT_", "REC04_SPLAT_", {"module_path": "/tmp/splat.mjs"}, "device", "cpu", "cpu"),
    (
        VoxelRuntimeSettings,
        "R2S_VOXEL_",
        "REC05_VOXEL_",
        {"cli": "/tmp/cli.js", "module_path": "/tmp/voxel.js"},
        "timeout_seconds",
        "45",
        45.0,
    ),
    (MogeSettings, "R2S_MOGE_", "REC06_MOGE_", {}, "max_frames", "12", 12),
    (LidarOdometryRuntimeSettings, "R2S_LIDAR_ODOMETRY_", "REC17_LIDAR_ODOMETRY_", {}, "timeout_seconds", "99", 99.0),
]
CASE_IDS = [case[0].__name__ for case in CASES]


@pytest.fixture(autouse=True)
def clean_runtime_env(monkeypatch: pytest.MonkeyPatch):
    """Xoá mọi biến runtime trước mỗi test và reset bộ đếm cảnh báo, để test không ảnh hưởng nhau."""
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix, _ in PREFIX_PAIRS) or any(
            name.startswith(old) for _, old in PREFIX_PAIRS
        ):
            monkeypatch.delenv(name, raising=False)
    reset_warnings()
    yield
    reset_warnings()


def _set(monkeypatch: pytest.MonkeyPatch, prefix: str, values: dict[str, str]) -> None:
    for field, value in values.items():
        monkeypatch.setenv(prefix + field.upper(), value)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == _WARNING_LOGGER]


@pytest.mark.parametrize(("cls", "new", "old", "required", "field", "text", "expected"), CASES, ids=CASE_IDS)
def test_new_name_is_read_without_warning(
    cls: Any,
    new: str,
    old: str,
    required: dict[str, str],
    field: str,
    text: str,
    expected: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set(monkeypatch, new, {**required, field: text})

    with caplog.at_level(logging.WARNING, logger=_WARNING_LOGGER):
        settings = cls()

    assert getattr(settings, field) == expected
    assert _warnings(caplog) == []


@pytest.mark.parametrize(("cls", "new", "old", "required", "field", "text", "expected"), CASES, ids=CASE_IDS)
def test_legacy_name_is_read_with_one_warning_per_name(
    cls: Any,
    new: str,
    old: str,
    required: dict[str, str],
    field: str,
    text: str,
    expected: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set(monkeypatch, old, {**required, field: text})

    with caplog.at_level(logging.WARNING, logger=_WARNING_LOGGER):
        first = cls()
        second = cls()

    assert getattr(first, field) == expected and getattr(second, field) == expected
    warned = _warnings(caplog)
    assert (
        len(warned) == len(required) + 1
    )  # mỗi tên cũ được dùng một lần cảnh báo, không lặp lại theo mỗi lần khởi tạo
    assert all("tên cũ" in message for message in warned)
    assert any(f"{old}{field.upper()}" in message and f"{new}{field.upper()}" in message for message in warned)


@pytest.mark.parametrize(("cls", "new", "old", "required", "field", "text", "expected"), CASES, ids=CASE_IDS)
def test_new_name_wins_when_both_names_are_set(
    cls: Any,
    new: str,
    old: str,
    required: dict[str, str],
    field: str,
    text: str,
    expected: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set(monkeypatch, old, {**required, field: "999999"})  # giá trị cũ khác: không được đọc
    _set(monkeypatch, new, {**required, field: text})

    with caplog.at_level(logging.WARNING, logger=_WARNING_LOGGER):
        settings = cls()

    assert getattr(settings, field) == expected
    assert _warnings(caplog) == []


def test_json_tuple_field_accepts_both_names(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, "R2S_COLMAP_", {"runtime_identity": "colmap-1"})
    monkeypatch.setenv("R2S_COLMAP_COMMAND", '["sh", "colmap-wrapper"]')

    assert ColmapRuntimeSettings().command == ("sh", "colmap-wrapper")


def test_json_tuple_field_accepts_legacy_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set(monkeypatch, "REC03_COLMAP_", {"runtime_identity": "colmap-1"})
    monkeypatch.setenv("REC03_COLMAP_COMMAND", '["sh", "colmap-wrapper"]')

    with caplog.at_level(logging.WARNING, logger=_WARNING_LOGGER):
        assert ColmapRuntimeSettings().command == ("sh", "colmap-wrapper")
    assert len(_warnings(caplog)) == 2  # runtime_identity và command, mỗi tên một lần


def test_json_dict_field_accepts_both_names(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, "R2S_BRUSH_", {"expected_version": "0.3.0", "runtime_identity": "brush-1"})
    monkeypatch.setenv("R2S_BRUSH_ENVIRONMENT", '{"WGPU_BACKEND": "vulkan"}')
    assert BrushRuntimeSettings().environment == {"WGPU_BACKEND": "vulkan"}

    monkeypatch.delenv("R2S_BRUSH_ENVIRONMENT")
    monkeypatch.setenv("REC04_BRUSH_ENVIRONMENT", '{"WGPU_BACKEND": "gl"}')
    assert BrushRuntimeSettings().environment == {"WGPU_BACKEND": "gl"}


def test_extra_forbid_does_not_reject_both_names_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, "R2S_COLMAP_", {"runtime_identity": "colmap-1"})
    _set(monkeypatch, "REC03_COLMAP_", {"runtime_identity": "colmap-old", "timeout_seconds": "30"})

    settings = ColmapRuntimeSettings()

    assert settings.runtime_identity == "colmap-1"
    assert settings.timeout_seconds == 30.0  # chỉ có tên cũ thì vẫn lấy tên cũ


def test_legacy_name_maps_every_prefix_and_leaves_other_names_alone() -> None:
    assert legacy_name("R2S_COLMAP_COMMAND") == "REC03_COLMAP_COMMAND"
    assert legacy_name("R2S_LIDAR_ODOMETRY_WORK_ROOT") == "REC17_LIDAR_ODOMETRY_WORK_ROOT"
    assert legacy_name("R2S_SCENE_RUNTIME") is None


def test_requirement_name_maps_the_qualification_keys_to_the_new_names() -> None:
    assert requirement_env_name("REC03_COLMAP_RUNTIME_IDENTITY") == "R2S_COLMAP_RUNTIME_IDENTITY"
    assert requirement_env_name("REC04_BRUSH_EXPECTED_VERSION") == "R2S_BRUSH_EXPECTED_VERSION"
    assert requirement_env_name("SCENE_RUNTIME_PATH") == "SCENE_RUNTIME_PATH"


def test_runtime_env_reads_the_new_name_then_the_legacy_one_then_default(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_WARNING_LOGGER):
        assert read_env({"R2S_BRUSH_LPIPS_PYTHON": " /py "}, "R2S_BRUSH_LPIPS_PYTHON") == "/py"
        assert read_env({"REC04_BRUSH_LPIPS_PYTHON": "/old"}, "R2S_BRUSH_LPIPS_PYTHON") == "/old"
        assert read_env({}, "R2S_BRUSH_LPIPS_PYTHON", "/default") == "/default"
    assert len(_warnings(caplog)) == 1  # chỉ lần đọc tên cũ mới cảnh báo


_REPO = Path(__file__).resolve().parents[1]
_GUARDED = [_REPO / "src", _REPO / "scripts", _REPO / "eval", _REPO / "Makefile.studio"]
#: File không thuộc phạm vi: entrypoint Docker (T-038 đổi), file env riêng của máy (không trong git; T-036 bước 4 đổi).
_OUT_OF_SCOPE = {_REPO / "scripts/gpu/docker_entrypoint.sh", _REPO / "scripts/gpu/studio.env"}
#: Bảng đổi tên là nơi duy nhất được phép chứa tên cũ.
_ALLOWED = {_REPO / "src/runtime_env.py"}
_OLD_NAME = re.compile(r"\bREC(?:03_COLMAP|04_BRUSH|04_SPLAT|05_VOXEL|06_MOGE|17_LIDAR_ODOMETRY)_[A-Z0-9_]+")


def _guarded_files() -> list[Path]:
    files: list[Path] = []
    for root in _GUARDED:
        candidates = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        files += [path for path in candidates if "__pycache__" not in path.parts and path.suffix != ".pyc"]
    return sorted(path for path in files if path not in _OUT_OF_SCOPE and path not in _ALLOWED)


def test_no_legacy_runtime_name_is_left_outside_the_rename_table() -> None:
    hits: list[str] = []
    for path in _guarded_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _OLD_NAME.search(line):
                hits.append(f"{path.relative_to(_REPO)}:{number}: {line.strip()[:120]}")
    assert hits == [], "tên RECxx_* còn sót ngoài bảng đổi tên:\n" + "\n".join(hits)
