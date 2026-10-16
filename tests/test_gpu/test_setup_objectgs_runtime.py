"""Test tĩnh của scripts/gpu/setup_objectgs_runtime.sh (T-037): không cài gì, chỉ kiểm nội dung và cách đọc số ghim."""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/gpu/setup_objectgs_runtime.sh"
LISTS = REPO / "configs/runtime/objectgs"
SCRIPT_TEXT = SCRIPT.read_text(encoding="utf-8")


def _pin(key: str) -> str:
    text = (REPO / "configs/runtime/pins.env").read_text(encoding="utf-8")
    return re.search(rf"^{key}=(.*)$", text, flags=re.M).group(1)


EXPECTED_PYTHON = {"python": "3.8.19", "wheel": "0.45.1"}
EXPECTED_CUDA = {
    "cuda-nvcc": "11.8.89",
    "cuda-cudart": "11.8.89",
    "cuda-cudart-dev": "11.8.89",
    "cuda-cccl": "11.8.89",
    "gxx_linux-64": "11.4.0",
    "sysroot_linux-64": "2.39",
}


def _specs(name: str) -> dict[str, str]:
    lines = [line.strip() for line in (LISTS / name).read_text(encoding="utf-8").splitlines()]
    pairs = [line.split("=", 1) for line in lines if line and not line.startswith("#")]
    return {key: value.lstrip("=") for key, value in pairs}


def _plan(script: Path, dest: Path) -> dict[str, str]:
    out = subprocess.run(
        ["bash", str(script), str(dest), "--print-plan"], capture_output=True, text=True, check=True
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if re.match(r"^[A-Z_]+=", line))


def test_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_commit_pins_are_read_from_objectgs_module_not_copied(tmp_path: Path) -> None:
    """Đổi số ghim trong một bản sao của objectgs.py thì script in đúng số mới: một nguồn duy nhất."""
    root = tmp_path / "repo"
    (root / "scripts/gpu").mkdir(parents=True)
    (root / "configs/runtime/objectgs").mkdir(parents=True)
    (root / "src/services/scene").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts/gpu/setup_objectgs_runtime.sh")
    shutil.copy(REPO / "configs/runtime/pins.env", root / "configs/runtime/pins.env")
    for name in ["requirements.lock.txt", "torch.txt", "conda-python.txt", "conda-cuda.txt"]:
        shutil.copy(LISTS / name, root / "configs/runtime/objectgs" / name)
    source = (REPO / "src/services/scene/objectgs.py").read_text(encoding="utf-8")
    fake = {"OBJECTGS_COMMIT": "1" * 40, "GSPLAT_COMMIT": "2" * 40, "GLM_COMMIT": "3" * 40}
    for key, value in fake.items():
        source, count = re.subn(rf'^{key} = "[0-9a-f]{{40}}"$', f'{key} = "{value}"', source, flags=re.M)
        assert count == 1, key
    (root / "src/services/scene/objectgs.py").write_text(source, encoding="utf-8")

    plan = _plan(root / "scripts/gpu/setup_objectgs_runtime.sh", tmp_path / "dest")
    assert plan["OBJECTGS_COMMIT"] == "1" * 40
    assert plan["GSPLAT_COMMIT"] == "2" * 40
    assert plan["GLM_COMMIT"] == "3" * 40


def test_real_plan_matches_the_pins_in_the_module(tmp_path: Path) -> None:
    plan = _plan(SCRIPT, tmp_path / "dest")
    source = (REPO / "src/services/scene/objectgs.py").read_text(encoding="utf-8")
    for key in ["OBJECTGS_COMMIT", "GSPLAT_COMMIT", "GLM_COMMIT"]:
        assert re.search(rf'^{key} = "{plan[key]}"$', source, flags=re.M), key
    assert not (tmp_path / "dest").exists(), "--print-plan không được tạo thư mục đích"


def test_no_commit_is_hardcoded_in_the_script() -> None:
    assert not re.search(r"\b[0-9a-f]{40}\b", SCRIPT_TEXT)


def test_every_download_goes_through_a_checksum_check() -> None:
    curl_lines = [line for line in SCRIPT_TEXT.splitlines() if "curl " in line]
    assert len(curl_lines) == 1, "chỉ một chỗ được gọi curl, bên trong fetch() có kiểm sha256"
    assert SCRIPT_TEXT.index("fetch() {") < SCRIPT_TEXT.index(curl_lines[0].strip())
    assert re.fullmatch(r"[0-9a-f]{64}", _pin("MICROMAMBA_SHA"))
    assert 'fetch "$MICROMAMBA_URL" "$TMP/micromamba.tar.bz2" "$MICROMAMBA_SHA"' in SCRIPT_TEXT


def test_micromamba_comes_from_the_official_release_and_its_binary_is_checked() -> None:
    """Giá trị micromamba nằm ở configs/runtime/pins.env (một nguồn); script chỉ đọc và kiểm binary."""
    assert _pin("MICROMAMBA_URL") == (
        "https://github.com/mamba-org/micromamba-releases/releases/download/2.0.5-0/micromamba-linux-64.tar.bz2"
    )
    assert "micro.mamba.pm" not in SCRIPT_TEXT
    assert re.fullmatch(r"[0-9a-f]{64}", _pin("MICROMAMBA_BIN_SHA"))
    assert 'sha_of "$TMP/bin/micromamba")" = "$MICROMAMBA_BIN_SHA"' in SCRIPT_TEXT
    assert "pins_value MICROMAMBA_BIN_SHA" in SCRIPT_TEXT


def test_conda_specs_match_the_laptop_runtime() -> None:
    assert _specs("conda-python.txt") == EXPECTED_PYTHON
    assert _specs("conda-cuda.txt") == EXPECTED_CUDA


def test_pip_lock_is_fully_pinned_hashed_and_leaves_torch_to_its_index() -> None:
    """Mỗi gói ghim `==` đúng một dòng --hash sha256 (định dạng requirements có --require-hashes)."""
    text = (LISTS / "requirements.lock.txt").read_text(encoding="utf-8")
    entries = re.findall(r"^([A-Za-z0-9_.\-]+==[^=\s]+) \\\n    --hash=sha256:([0-9a-f]{64})$", text, flags=re.M)
    assert len(entries) == 126
    assert len(set(name for name, _ in entries)) == 126
    assert text.count("--hash=") == 126
    assert not [name for name, _ in entries if re.match(r"(torch|torchvision|torchaudio|torch-scatter)==", name)]


def test_pip_lock_is_installed_with_require_hashes() -> None:
    assert 'pip install --require-hashes -r "$LISTS/requirements.lock.txt"' in SCRIPT_TEXT


def test_lock_hashes_match_the_offline_wheel_files() -> None:
    wheels = REPO / "data/objectgs_runtime/wheels"
    if not wheels.is_dir():
        pytest.skip("không có thư mục wheel offline trên máy này")
    text = (LISTS / "requirements.lock.txt").read_text(encoding="utf-8")
    entries = re.findall(r"^([A-Za-z0-9_.\-]+)==([^=\s]+) \\\n    --hash=sha256:([0-9a-f]{64})$", text, flags=re.M)
    files = {path.name: path for path in wheels.iterdir() if path.is_file()}
    for name, version, digest in entries:
        dist = re.sub(r"[-_.]+", "-", name).lower()
        candidates = []
        for fname, path in files.items():
            if fname.endswith(".whl"):
                parts = fname[:-4].split("-")
            elif fname.endswith(".tar.gz"):
                parts = fname[:-7].rsplit("-", 1)
            else:
                continue
            if re.sub(r"[-_.]+", "-", parts[0]).lower() == dist and parts[1] == version:
                candidates.append(path)
        assert len(candidates) == 1, f"{name}=={version}: {len(candidates)} file"
        assert hashlib.sha256(candidates[0].read_bytes()).hexdigest() == digest, name


def test_torch_pins_use_the_cu118_builds() -> None:
    torch = (LISTS / "torch.txt").read_text(encoding="utf-8")
    assert "torch==2.1.2+cu118" in torch
    assert "torchvision==0.16.2+cu118" in torch
    assert "torchaudio==2.1.2+cu118" in torch
    assert "torch-scatter==2.1.2+pt21cu118" in torch


def test_extension_is_prebuilt_into_the_shared_cache_with_objectgs_environment() -> None:
    assert 'TORCH_EXTENSIONS_DIR="$DEST/torch_extensions"' in SCRIPT_TEXT
    assert "import gsplat.cuda._backend" in SCRIPT_TEXT
    assert "PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR=$DEST/torch_extensions" in SCRIPT_TEXT


def test_install_refuses_a_non_empty_folder_without_the_install_stamp(tmp_path: Path) -> None:
    """Thư mục có nội dung mà không có .r2s-installed: dừng ngay với thông báo rõ, không tải, không đụng nội dung cũ."""
    dest = tmp_path / "existing"
    dest.mkdir()
    (dest / "keep.txt").write_text("của người khác", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(SCRIPT), str(dest), "--skip-gpu-check"], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert ".r2s-installed" in result.stderr and "Script không tự xoá gì" in result.stderr
    assert sorted(path.name for path in dest.iterdir()) == ["keep.txt"]
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "của người khác"


def test_objectgs_preflight_is_optional_and_reports_missing_runtime(monkeypatch) -> None:
    """Mục ObjectGS trong preflight là tuỳ chọn: thiếu runtime thì báo thiếu, không đặt cờ bắt buộc."""
    from scripts.kaggle import preflight

    monkeypatch.delenv("PRODUCT_OBJECTGS_RUNTIME_PYTHON", raising=False)
    ok, detail = preflight.objectgs_runtime()
    assert ok is False and "PRODUCT_OBJECTGS_RUNTIME_PYTHON" in detail
    entry = next(item for item in preflight.CHECKS if item[0] == "Runtime ObjectGS")
    assert entry[2] is False
