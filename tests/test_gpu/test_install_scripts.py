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
    "COLMAP_BINARY_SHA",
    "COLMAP_LICENSE_SHA",
    "ONNXRUNTIME_LICENSE_SHA",
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


def test_colmap_binary_bundle_already_extracted_is_recognised_without_download(tmp_path: Path) -> None:
    root = tmp_path / "data"
    wrapper = root / "colmap/bin/colmap-run"
    body = (
        'if [ "$1" = help ]; then echo "COLMAP 4.3.0.dev0 (Commit Unknown)"; else echo "  --prior_position_std_x"; fi'
    )
    _stub_bin(wrapper.parent, wrapper.name, body)
    env, curl_log = _env_with_failing_curl(tmp_path)

    result = _run(
        ["bash", str(GPU / "install.sh"), str(root), "--only", "colmap", "--colmap=binary", "--no-doctor"], env=env
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[nhận ra] colmap" in result.stdout
    assert not curl_log.exists()
    assert f'R2S_COLMAP_COMMAND=["{wrapper}"]' in (root / "runtime.env").read_text(encoding="utf-8")


def test_colmap_binary_install_refuses_a_bundle_with_the_wrong_checksum(tmp_path: Path) -> None:
    root = tmp_path / "data"
    wrong = tmp_path / "wrong-bundle.tar.zst"
    wrong.write_bytes(b"not the pinned bundle")
    result = _run(
        [
            "bash",
            str(GPU / "install.sh"),
            str(root),
            "--only",
            "colmap",
            "--colmap=binary",
            "--colmap-from-file",
            str(wrong),
            "--no-doctor",
        ]
    )

    assert result.returncode != 0
    assert "sai sha256" in result.stdout + result.stderr
    assert not (root / "colmap/bin").exists()


def test_objectgs_probe_environment_matches_the_runner(tmp_path: Path) -> None:
    """Probe (doctor và verify của install) dùng đúng biến biên dịch như lúc chạy ObjectGS, để cache dùng được."""
    from scripts.kaggle import preflight

    python = tmp_path / "objgs/python/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    env = preflight.objectgs_probe_env(
        {
            "PATH": "/usr/bin",
            "PRODUCT_OBJECTGS_RUNTIME_PYTHON": str(python),
            "PRODUCT_OBJECTGS_GSPLAT_REPOSITORY": "/g",
            "PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR": "/cache",
            "PRODUCT_OBJECTGS_CUDA_HOME": "/cuda",
            "PRODUCT_OBJECTGS_CXX": "/cuda/bin/g++",
            "PRODUCT_OBJECTGS_GLM_REPOSITORY": "/glm",
        }
    )
    assert env["CPLUS_INCLUDE_PATH"] == os.pathsep.join([str(tmp_path / "objgs/python/include"), "/glm"])
    assert env["PATH"] == os.pathsep.join(["/cuda/bin", "/usr/bin"])
    assert env["CUDA_HOME"] == "/cuda"
    assert env["CXX"] == env["CC"] == "/cuda/bin/g++"
    assert env["PYTHONPATH"] == "/g" and env["TORCH_EXTENSIONS_DIR"] == "/cache" and env["MAX_JOBS"] == "2"
    assert "TORCH_CUDA_ARCH_LIST" not in env


def test_objectgs_runner_sets_the_variables_the_probe_mirrors() -> None:
    runner = (REPO / "src/services/scene/objectgs.py").read_text(encoding="utf-8")
    for key in ["CPLUS_INCLUDE_PATH", "TORCH_EXTENSIONS_DIR", "MAX_JOBS", "CUDA_HOME", "CXX", "CC"]:
        assert f'"{key}"' in runner or f"{key}=" in runner, key
    assert "TORCH_CUDA_ARCH_LIST" not in runner


def test_no_forced_cuda_arch_list_so_the_cache_matches_the_runner() -> None:
    for path in [INSTALL_D / "objectgs.sh", GPU / "setup_objectgs_runtime.sh", REPO / "scripts/kaggle/preflight.py"]:
        assert not re.search(r"TORCH_CUDA_ARCH_LIST\s*=", path.read_text(encoding="utf-8")), path.name


def test_objectgs_install_verifies_through_the_shared_probe() -> None:
    text = (INSTALL_D / "objectgs.sh").read_text(encoding="utf-8")
    assert "write_runtime_env" in text and "objectgs_runtime" in text
    assert "gsplat_cuda.so" not in text, "file .so có mặt không đủ: cache phải khớp cấu hình lúc chạy"


def test_partial_runtime_env_write_keeps_the_components_written_before(tmp_path: Path) -> None:
    """install.sh --only scene sau --only brush không được xoá dòng brush: runtime.env là hợp của mọi lần chạy."""
    out = tmp_path / "runtime.env"
    script = (
        f'REPO="{REPO}"; GOC="{tmp_path / "root"}"; COLMAP_MODE=docker; source "{INSTALL_D}/_lib.sh"; layout; '
        f'write_runtime_env "{out}" brush; write_runtime_env "{out}" scene'
    )
    result = _run(["bash", "-c", script])
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "R2S_BRUSH_COMMAND=" in text and "PRODUCT_SCENE_RUNTIME_PYTHON=" in text
    assert len([line for line in text.splitlines() if line.startswith("R2S_BRUSH_COMMAND=")]) == 1


def test_runtime_env_carries_no_timeouts(tmp_path: Path) -> None:
    """Timeout là chính sách vận hành (studio.env.example), không thuộc runtime.env."""
    out = tmp_path / "runtime.env"
    script = (
        f'REPO="{REPO}"; GOC="{tmp_path / "root"}"; COLMAP_MODE=docker; source "{INSTALL_D}/_lib.sh"; layout; '
        f'write_runtime_env "{out}" colmap brush splat lidar_odometry scene objectgs'
    )
    assert _run(["bash", "-c", script]).returncode == 0
    assert "TIMEOUT" not in out.read_text(encoding="utf-8")


def test_extracted_colmap_tree_from_the_image_only_gets_a_wrapper(tmp_path: Path) -> None:
    """Image COPY cây COLMAP vào <gốc>/colmap: install chỉ tạo wrapper colmap-run, không tải hay giải nén lại."""
    root = tmp_path / "data"
    _stub_bin(
        root / "colmap/bin",
        "colmap",
        'if [ "$1" = help ]; then echo "COLMAP 4.3.0.dev0 (Commit Unknown)"; else echo "  --prior_position_std_x"; fi',
    )
    env, curl_log = _env_with_failing_curl(tmp_path)

    result = _run(
        ["bash", str(GPU / "install.sh"), str(root), "--only", "colmap", "--colmap=binary", "--no-doctor"], env=env
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[cài] colmap" in result.stdout, "chưa có wrapper nên install phải chạy, không tải"
    assert (root / "colmap/bin/colmap-run").is_file()
    assert not curl_log.exists()


def test_node_bin_dir_is_written_only_for_a_node_we_installed(tmp_path: Path) -> None:
    """App gọi `node` từ PATH: runtime.env chỉ ghi thư mục node khi node do install.sh cài, không ghi khi --system-node."""
    out = tmp_path / "runtime.env"
    base = f'REPO="{REPO}"; GOC="{tmp_path / "root"}"; COLMAP_MODE=docker; source "{INSTALL_D}/_lib.sh"; layout; '
    assert _run(["bash", "-c", base + f'write_runtime_env "{out}" splat']).returncode == 0
    assert "R2S_NODE_BIN_DIR=" not in out.read_text(encoding="utf-8")

    _stub_bin(tmp_path / "root/reconstruction_runtime/node/bin", "node", 'echo "v22.20.0"')
    assert _run(["bash", "-c", base + f'write_runtime_env "{out}" splat']).returncode == 0
    assert f"R2S_NODE_BIN_DIR={tmp_path / 'root/reconstruction_runtime/node/bin'}" in out.read_text(encoding="utf-8")
