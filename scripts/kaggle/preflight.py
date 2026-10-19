"""Kiểm máy GPU (Kaggle / GPU thuê) có đủ công cụ để chạy trọn pipeline không, trước khi tốn giờ GPU.

    set -a; source <file env>; set +a
    python -m scripts.kaggle.preflight

Mỗi dòng là một thứ pipeline thật sự gọi tới, đọc từ đúng biến môi trường mà worker dùng. Thiếu mục
"bắt buộc" → exit 1. Mục "tuỳ chọn" thiếu thì pipeline vẫn chạy nhưng lùi về đường kém hơn (ghi rõ).
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from src.runtime_env import runtime_env


def _run(command: list[str], timeout: float = 120.0, env: dict[str, str] | None = None) -> tuple[bool, str]:
    """Chạy lệnh kiểm; trả (thành công, dòng cuối của output)."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        return False, type(error).__name__
    # Ưu tiên stdout: stderr của các runtime Python thường chỉ là cảnh báo.
    lines = [line for line in (done.stdout.strip() or done.stderr.strip()).splitlines() if line.strip()]
    return done.returncode == 0, lines[-1][:120] if lines else ""


def _command(variable: str) -> list[str] | None:
    value = runtime_env(os.environ, variable)
    return list(json.loads(value)) if value else None


def gpu() -> tuple[bool, str]:
    """Card NVIDIA và VRAM trống."""
    return _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"])


def ffmpeg() -> tuple[bool, str]:
    """Tách frame từ video."""
    ok, text = _run(["ffmpeg", "-version"])
    return ok, text if not ok else "có"


def colmap() -> tuple[bool, str]:
    """Dựng pose camera (REC-03) qua đúng lệnh `R2S_COLMAP_COMMAND`."""
    command = _command("R2S_COLMAP_COMMAND")
    if command is None:
        return False, "chưa đặt R2S_COLMAP_COMMAND"
    ok, text = _run([*command, "help"])
    return ok, "chạy được" if ok else text


def colmap_gpu() -> tuple[bool, str]:
    """COLMAP trích đặc trưng trên GPU khi PRODUCT_COLMAP_USE_GPU bật."""
    use_gpu_env = os.environ.get("PRODUCT_COLMAP_USE_GPU", "").lower() in {"1", "true", "yes"}
    if not use_gpu_env:
        return True, "bỏ qua (PRODUCT_COLMAP_USE_GPU tắt)"
    command = _command("R2S_COLMAP_COMMAND")
    if command is None:
        return False, "chưa đặt R2S_COLMAP_COMMAND"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        for idx in (1, 2):
            img_file = img_dir / f"img_{idx}.ppm"
            img_file.write_bytes(b"P6\n64 64\n255\n" + (b"\x80\x80\x80" * (64 * 64)))
        db_path = tmp_path / "database.db"
        # COLMAP 4.x đổi tiền tố cờ thành FeatureExtraction; chọn theo help của chính binary này.
        try:
            help_text = subprocess.run(
                [*command, "feature_extractor", "-h"], capture_output=True, text=True, timeout=120.0, check=False
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, type(error).__name__
        options = help_text.stdout + help_text.stderr
        prefix = "FeatureExtraction" if "--FeatureExtraction.use_gpu" in options else "SiftExtraction"
        cmd = [
            *command,
            "feature_extractor",
            "--database_path",
            str(db_path),
            "--image_path",
            str(img_dir),
            f"--{prefix}.use_gpu",
            "1",
        ]
        ok, text = _run(cmd, timeout=120.0)
        return ok, "chạy được trên GPU" if ok else f"lỗi GPU: {text}"


def colmap_guided() -> tuple[bool, str]:
    """Luồng video + gói LiDAR (ADR 0009) cần `pose_prior_mapper` của COLMAP 4.x; bản 3.x chỉ chạy được luồng video."""
    command = _command("R2S_COLMAP_COMMAND")
    if command is None:
        return False, "chưa đặt R2S_COLMAP_COMMAND"
    # Cần cả phần trợ giúp (không chỉ dòng cuối như `_run`) để tìm đúng tuỳ chọn của chế độ bám quỹ đạo.
    try:
        done = subprocess.run(
            [*command, "pose_prior_mapper", "-h"], capture_output=True, text=True, timeout=120.0, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, type(error).__name__
    ok = "--prior_position_std_x" in done.stdout + done.stderr
    return ok, "có pose_prior_mapper" if ok else "COLMAP này không có pose_prior_mapper (cần COLMAP ≥ 4.0)"


def vulkan() -> tuple[bool, str]:
    """Brush train 3DGS qua Vulkan; phải thấy đúng card NVIDIA, không phải llvmpipe (CPU)."""
    ok, _ = _run(["vulkaninfo", "--summary"])
    if not ok:
        return False, "vulkaninfo lỗi hoặc chưa cài (apt install vulkan-tools)"
    done = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, check=False)
    devices = [line.split("=", 1)[1].strip() for line in done.stdout.splitlines() if "deviceName" in line]
    hardware = [name for name in devices if "llvmpipe" not in name.lower()]
    return bool(hardware), ", ".join(devices) or "không có thiết bị Vulkan"


def brush() -> tuple[bool, str]:
    """Binary Brush đúng phiên bản ghim (`R2S_BRUSH_EXPECTED_VERSION`)."""
    command = _command("R2S_BRUSH_COMMAND")
    if command is None:
        return False, "chưa đặt R2S_BRUSH_COMMAND"
    extra = json.loads(runtime_env(os.environ, "R2S_BRUSH_ENVIRONMENT", "{}") or "{}")
    ok, text = _run([*command, "--version"], env={**os.environ, **extra})
    expected = runtime_env(os.environ, "R2S_BRUSH_EXPECTED_VERSION", "")
    return ok and text.endswith(expected), text


def splat_transform() -> tuple[bool, str]:
    """Nén SOG cho web + dựng voxel collision (Node + splat-transform)."""
    cli = runtime_env(os.environ, "R2S_VOXEL_CLI")
    if not cli or not Path(cli).is_file() or shutil.which("node") is None:
        return False, "thiếu node hoặc R2S_VOXEL_CLI"
    return _run(["node", cli, "--version"])


def splat_gpu() -> tuple[bool, str]:
    """GPU cho splat-transform (WebGPU/Dawn); không có thì đặt R2S_SPLAT_DEVICE=cpu (chậm hơn)."""
    cli = runtime_env(os.environ, "R2S_VOXEL_CLI")
    if not cli or shutil.which("node") is None:
        return False, "thiếu node hoặc R2S_VOXEL_CLI"
    return _run(["node", cli, "--list-gpus"])


def scene_runtime() -> tuple[bool, str]:
    """Runtime tách theo vật: torch thấy GPU, kernel gsplat nạp được, usd-core có schema Gaussian."""
    python = os.environ.get("PRODUCT_SCENE_RUNTIME_PYTHON")
    weights = [os.environ.get("PRODUCT_SAM2_CHECKPOINT"), os.environ.get("PRODUCT_LAMA_CHECKPOINT")]
    if not python or not Path(python).is_file() or any(not item or not Path(item).is_file() for item in weights):
        return False, "thiếu PRODUCT_SCENE_RUNTIME_PYTHON hoặc checkpoint SAM2/LaMa"
    probe = (
        "import torch, coacd, cv2, skimage;"
        "from gsplat.cuda._backend import _C;"
        "from pxr import UsdVol;"
        "from sam2.build_sam import build_sam2;"
        "assert torch.cuda.is_available() and _C is not None;"
        "assert hasattr(UsdVol, 'ParticleField3DGaussianSplat');"
        "print(torch.__version__, torch.cuda.get_device_name(0))"
    )
    return _run([python, "-c", probe], timeout=1800.0)


def objectgs_probe_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Môi trường đúng như src/services/scene/objectgs.py đặt khi chạy ObjectGS.

    Probe và lúc chạy thật phải dùng chung môi trường: gsplat so cấu hình biên dịch (đường dẫn trình biên dịch,
    include, cờ CUDA) với build.ninja trong cache, lệch một biến là nó biên dịch lại từ đầu.
    """
    env = dict(environ)
    python = Path(environ["PRODUCT_OBJECTGS_RUNTIME_PYTHON"])
    includes = [str(python.absolute().parent.parent / "include")]
    env["MAX_JOBS"] = "2"
    if gsplat := environ.get("PRODUCT_OBJECTGS_GSPLAT_REPOSITORY"):
        env["PYTHONPATH"] = gsplat
    if cache := environ.get("PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR"):
        env["TORCH_EXTENSIONS_DIR"] = cache
    if cuda := environ.get("PRODUCT_OBJECTGS_CUDA_HOME"):
        env["CUDA_HOME"] = cuda
        env["PATH"] = os.pathsep.join([str(Path(cuda) / "bin"), environ.get("PATH", "")])
    if cxx := environ.get("PRODUCT_OBJECTGS_CXX"):
        env["CXX"] = cxx
        env["CC"] = cxx
    if glm := environ.get("PRODUCT_OBJECTGS_GLM_REPOSITORY"):
        includes.append(glm)
    env["CPLUS_INCLUDE_PATH"] = os.pathsep.join(includes)
    return env


def objectgs_extension_loads() -> tuple[bool, str]:
    """Kernel gsplat nạp được trong môi trường ObjectGS, không cần GPU (install.sh kiểm cả lúc build image).

    Nạp lần đầu là lúc biên dịch: cache khớp thì vài giây, không khớp thì biên dịch lại (vài phút).
    """
    python = os.environ.get("PRODUCT_OBJECTGS_RUNTIME_PYTHON")
    if not python or not Path(python).is_file():
        return False, "thiếu PRODUCT_OBJECTGS_RUNTIME_PYTHON"
    probe = "import torch;from gsplat.cuda._backend import _C;assert _C is not None;print(torch.__version__)"
    return _run([python, "-c", probe], timeout=1800.0, env=objectgs_probe_env(os.environ))


def objectgs_runtime() -> tuple[bool, str]:
    """Runtime ObjectGS (tuỳ chọn trên doctor): torch thấy GPU và kernel gsplat nạp từ cache biên dịch dùng chung."""
    python = os.environ.get("PRODUCT_OBJECTGS_RUNTIME_PYTHON")
    if not python or not Path(python).is_file():
        return False, "thiếu PRODUCT_OBJECTGS_RUNTIME_PYTHON"
    probe = (
        "import torch;from gsplat.cuda._backend import _C;"
        "assert torch.cuda.is_available() and _C is not None;"
        "print(torch.__version__, torch.cuda.get_device_name(0))"
    )
    return _run([python, "-c", probe], timeout=1800.0, env=objectgs_probe_env(os.environ))


#: (tên, hàm kiểm, bắt buộc, hậu quả khi thiếu)
CHECKS: list[tuple[str, Callable[[], tuple[bool, str]], bool, str]] = [
    ("GPU NVIDIA", gpu, True, "không chạy được"),
    ("ffmpeg", ffmpeg, True, "không tách được frame"),
    ("COLMAP", colmap, True, "không dựng được pose camera"),
    ("COLMAP dùng GPU", colmap_gpu, False, "đặt PRODUCT_COLMAP_USE_GPU=false"),
    ("COLMAP dựng bám quỹ đạo", colmap_guided, False, "job video + gói LiDAR sẽ dừng ở bước dựng pose"),
    ("Vulkan (GPU thật)", vulkan, True, "Brush không train được 3DGS"),
    ("Brush", brush, True, "không train được 3DGS"),
    ("splat-transform", splat_transform, True, "không nén SOG / dựng collision"),
    ("splat-transform GPU", splat_gpu, False, "đặt R2S_SPLAT_DEVICE=cpu"),
    ("Runtime tách theo vật", scene_runtime, False, "scene lùi về đường hộp"),
    ("Runtime ObjectGS", objectgs_runtime, False, "tách vật dùng đường khác (không có ObjectGS)"),
]


def main() -> int:
    """In bảng kết quả; trả 1 nếu thiếu mục bắt buộc."""
    blocked = False
    for name, check, required, consequence in CHECKS:
        if os.environ.get("R2S_REQUIRE_FULL_RUNTIME") == "1" and check in {scene_runtime, objectgs_runtime}:
            required = True
        ok, detail = check()
        mark = "OK  " if ok else ("LỖI " if required else "THIẾU")
        print(f"{mark} {name:<24} {detail}" + ("" if ok else f"  → {consequence}"))
        blocked = blocked or (required and not ok)
    try:
        from scripts.gpu.gpu_plan import plan_for_machine

        gpus, result = plan_for_machine(64)
        print(f"\nChia GPU: {len(gpus)} GPU → {len(result.slots)} worker song song ({result.reason})")
        for gpu in gpus:
            vulkan = "ghép được" if gpu.wgpu_discrete_index is not None else "CHƯA ghép được (Brush dùng GPU mặc định)"
            print(f"  GPU {gpu.index}: {gpu.name}, trống {gpu.free_gb:.1f}/{gpu.total_gb:.1f} GB, Vulkan {vulkan}")
    except (ImportError, ValueError, OSError) as error:
        print(f"\nChia GPU: không lập được kế hoạch ({error})")
    print("\nKết luận:", "CHƯA chạy được pipeline trên máy này." if blocked else "đủ điều kiện chạy.")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
