"""Test tĩnh và cục bộ của scripts/gpu/install.sh, install.d/*.sh, doctor.sh (T-038 bước 1).

Không tải gì từ mạng: curl được thay bằng stub lỗi trong PATH, nên mọi lần gọi curl đều bị ghi lại và làm test thất bại.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GPU = REPO / "scripts/gpu"
INSTALL_D = GPU / "install.d"
PINS = REPO / "configs/runtime/pins.env"
COMPONENT_FILES = [GPU / "install.sh", GPU / "doctor.sh", *sorted(INSTALL_D.glob("*.sh"))]

REQUIRED_PINS = [
    "BRUSH_VERSION",
    "BRUSH_SHA",
    "NODE_VERSION",
    "NODE_SHA",
    "SPLAT_TRANSFORM_VERSION",
    "COLMAP_IMAGE",
    "KISS_ICP_VERSION",
    "MICROMAMBA_URL",
    "MICROMAMBA_SHA",
    "MICROMAMBA_BIN_SHA",
]


def _pins() -> dict[str, str]:
    pairs = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            pairs[key] = value
    return pairs


def _stub_bin(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env)


def _env_with_failing_curl(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """PATH có curl giả: gọi tới là ghi nhật ký và thoát lỗi. Trả về môi trường và file nhật ký."""
    stubs = tmp_path / "stubs"
    log = tmp_path / "curl-calls.log"
    _stub_bin(stubs, "curl", f'echo "$@" >> "{log}"; exit 99')
    env = dict(os.environ)
    env["PATH"] = f"{stubs}:{env['PATH']}"
    return env, log


def test_install_scripts_parse() -> None:
    for path in COMPONENT_FILES:
        assert _run(["bash", "-n", str(path)]).returncode == 0, path.name


def test_pins_file_has_every_version_and_real_checksums() -> None:
    pins = _pins()
    for key in REQUIRED_PINS:
        assert pins.get(key), key
    for key in ["BRUSH_SHA", "NODE_SHA", "MICROMAMBA_SHA", "MICROMAMBA_BIN_SHA"]:
        assert re.fullmatch(r"[0-9a-f]{64}", pins[key]), key
    assert re.fullmatch(r"colmap/colmap@sha256:[0-9a-f]{64}", pins["COLMAP_IMAGE"])


def test_curl_is_called_only_inside_fetch() -> None:
    lib = (INSTALL_D / "_lib.sh").read_text(encoding="utf-8")
    assert lib.count("curl -L") == 1
    assert lib.index("fetch() {") < lib.index("curl -L")
    for path in COMPONENT_FILES:
        if path.name == "_lib.sh":
            continue
        assert "curl" not in path.read_text(encoding="utf-8"), path.name


def test_no_pinned_value_is_copied_outside_pins_file() -> None:
    """Số phiên bản và checksum chỉ có trong pins.env: các script chỉ gọi pin, không chép tay."""
    for key, value in _pins().items():
        if len(value) < 6:
            continue
        for path in COMPONENT_FILES:
            assert value not in path.read_text(encoding="utf-8"), f"{key} bị chép trong {path.name}"


def test_runtime_env_writer_emits_only_allowed_keys_one_line_each(tmp_path: Path) -> None:
    out = tmp_path / "runtime.env"
    script = (
        f'REPO="{REPO}"; GOC="{tmp_path / "root"}"; COLMAP_MODE=docker; source "{INSTALL_D}/_lib.sh"; layout; '
        f'write_runtime_env "{out}" colmap brush splat lidar_odometry scene objectgs; '
        'printf "%s" "$RUNTIME_ENV_ALLOWED"'
    )
    allowed_run = _run(["bash", "-c", script])
    assert allowed_run.returncode == 0, allowed_run.stderr
    allowed = set(allowed_run.stdout.split())
    keys = [line.split("=", 1)[0] for line in out.read_text(encoding="utf-8").splitlines()]
    assert keys, "runtime.env trống"
    assert set(keys) <= allowed
    assert len(keys) == len(set(keys))
    assert not {"DATABASE_URL", "ARTIFACT_ROOT", "PRODUCT_WORKER_ROOT"} & set(keys)


def test_runtime_env_loader_keeps_variables_already_set(tmp_path: Path) -> None:
    file = tmp_path / "runtime.env"
    file.write_text('R2S_BRUSH_COMMAND=["/a/brush_app"]\nPRODUCT_OBJECTGS_CXX=/b/g++\n', encoding="utf-8")
    env = dict(os.environ)
    env["PRODUCT_OBJECTGS_CXX"] = "/operator/override"
    script = (
        f'REPO="{REPO}"; source "{INSTALL_D}/_lib.sh"; load_runtime_env "{file}"; '
        'printf "%s|%s" "$R2S_BRUSH_COMMAND" "$PRODUCT_OBJECTGS_CXX"'
    )
    result = _run(["bash", "-c", script], env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == '["/a/brush_app"]|/operator/override'


def test_install_recognises_an_installed_brush_without_downloading(tmp_path: Path) -> None:
    root = tmp_path / "data"
    brush = root / "reconstruction_runtime/brush/brush-app-x86_64-unknown-linux-gnu/brush_app"
    _stub_bin(brush.parent, "brush_app", 'echo "brush-cli 0.3.0"')
    env, curl_log = _env_with_failing_curl(tmp_path)

    result = _run(["bash", str(GPU / "install.sh"), str(root), "--only", "brush", "--no-doctor"], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[nhận ra] brush" in result.stdout
    assert not curl_log.exists(), "không được tải khi đã có sẵn"
    assert (root / ".r2s-installed/brush").is_file()
    assert f'R2S_BRUSH_COMMAND=["{brush}"]' in (root / "runtime.env").read_text(encoding="utf-8")


def test_second_run_skips_a_component_already_stamped(tmp_path: Path) -> None:
    root = tmp_path / "data"
    brush = root / "reconstruction_runtime/brush/brush-app-x86_64-unknown-linux-gnu/brush_app"
    _stub_bin(brush.parent, "brush_app", 'echo "brush-cli 0.3.0"')
    env, curl_log = _env_with_failing_curl(tmp_path)
    args = ["bash", str(GPU / "install.sh"), str(root), "--only", "brush", "--no-doctor"]
    assert _run(args, env=env).returncode == 0
    second = _run(args, env=env)

    assert second.returncode == 0
    assert "[bỏ qua] brush" in second.stdout
    assert not curl_log.exists()


def test_colmap_docker_launcher_with_the_pinned_digest_is_recognised(tmp_path: Path) -> None:
    root = tmp_path / "data"
    launcher = root / "reconstruction_runtime/colmap-launcher.sh"
    launcher.parent.mkdir(parents=True)
    pinned = _pins()["COLMAP_IMAGE"]
    launcher.write_text(f'#!/bin/sh\nexec docker run --rm {pinned} colmap "$@"\n', encoding="utf-8")
    env, _ = _env_with_failing_curl(tmp_path)

    result = _run(["bash", str(GPU / "install.sh"), str(root), "--only", "colmap", "--no-doctor"], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[nhận ra] colmap" in result.stdout


def test_splat_is_recognised_with_system_node_and_no_download(tmp_path: Path) -> None:
    root = tmp_path / "data"
    package = root / "reconstruction_runtime/node_modules/@playcanvas/splat-transform"
    (package / "dist").mkdir(parents=True)
    (package / "dist/index.mjs").write_text("//", encoding="utf-8")
    (package / "package.json").write_text('{"version": "3.6.6"}', encoding="utf-8")
    env, curl_log = _env_with_failing_curl(tmp_path)
    _stub_bin(tmp_path / "stubs", "node", 'echo "v24.11.1"')

    result = _run(
        ["bash", str(GPU / "install.sh"), str(root), "--only", "splat", "--system-node", "--no-doctor"], env=env
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[nhận ra] splat" in result.stdout
    assert not curl_log.exists()


def test_lidar_odometry_is_recognised_by_its_pinned_version(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _stub_bin(root / "lidar_odometry_runtime/bin", "python", 'echo "1.3.0"')
    env, curl_log = _env_with_failing_curl(tmp_path)

    result = _run(["bash", str(GPU / "install.sh"), str(root), "--only", "lidar_odometry", "--no-doctor"], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[nhận ra] lidar_odometry" in result.stdout
    assert not curl_log.exists()


def test_unknown_colmap_mode_is_refused(tmp_path: Path) -> None:
    result = _run(["bash", str(GPU / "install.sh"), str(tmp_path), "--colmap=apt", "--no-doctor"])
    assert result.returncode != 0
    assert "--colmap" in result.stderr


def test_check_system_reports_packages_without_needing_root(tmp_path: Path) -> None:
    result = _run(["bash", str(GPU / "install.sh"), str(tmp_path / "data"), "--check-system"])
    assert "[hệ thống]" in result.stdout + result.stderr
