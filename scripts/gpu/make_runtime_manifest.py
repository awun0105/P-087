"""Sinh `RuntimeManifest` từ version thật của máy worker (local hoặc GPU thuê).

Chỉ ghi VERIFIED cho component đọc được version ngay trên máy; còn lại
UNVERIFIED kèm lý do. File này là identity runtime của job (checksum đi vào
JobManifest), nên phải sinh lại trên từng máy, không copy giữa các máy.

    python -m scripts.gpu.make_runtime_manifest --out data/runtime/runtime_manifest.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import RuntimeManifest
from src.runtime_env import runtime_env


def _run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout or result.stderr).strip()


def _component(version: str | None, missing: str) -> dict[str, str]:
    if version:
        return {"status": "VERIFIED", "version": version}
    return {"status": "UNVERIFIED", "notes": missing}


def collect() -> dict[str, dict[str, str]]:
    """Đọc version từ tool thật theo cùng env mà worker dùng (REC03_/REC04_)."""
    ffmpeg = _run(["ffmpeg", "-version"])
    raw_brush = (runtime_env(os.environ, "R2S_BRUSH_COMMAND") or "").strip()
    brush_command = None
    if raw_brush:
        try:
            parsed = json.loads(raw_brush)
            brush_command = parsed if isinstance(parsed, list) else [str(parsed)]
        except (json.JSONDecodeError, ValueError):
            brush_command = [raw_brush]
    brush = _run([*brush_command, "--version"]) if brush_command else None
    splat_module = runtime_env(os.environ, "R2S_SPLAT_MODULE_PATH")
    splat = None
    if splat_module:
        package = Path(splat_module).resolve().parents[1] / "package.json"
        splat = json.loads(package.read_text()).get("version") if package.is_file() else None
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    gpu_fields = [field.strip() for field in gpu.splitlines()[0].split(",")] if gpu else []
    scene_python = os.environ.get("PRODUCT_SCENE_RUNTIME_PYTHON")
    usd = (
        _run([scene_python, "-c", "from pxr import Usd; print('.'.join(map(str, Usd.GetVersion())))"])
        if scene_python
        else None
    )
    launcher = os.environ.get("PRODUCT_ISAAC_VALIDATION_LAUNCHER")
    isaac = (
        _run([launcher, "-c", "import importlib.metadata as m; print('.'.join(m.version('isaacsim').split('.')[:3]))"])
        if launcher
        else None
    )
    return {
        "python": _component(sys.version.split()[0], "python không đọc được"),
        "ffmpeg": _component(ffmpeg.splitlines()[0] if ffmpeg else None, "ffmpeg không có trong PATH"),
        "colmap": _component(runtime_env(os.environ, "R2S_COLMAP_RUNTIME_IDENTITY"), "đặt R2S_COLMAP_RUNTIME_IDENTITY"),
        "brush": _component(brush.splitlines()[0] if brush else None, "đặt R2S_BRUSH_COMMAND trỏ brush binary"),
        "splat_transform": _component(splat, "đặt R2S_SPLAT_MODULE_PATH"),
        "gpu_model": _component(gpu_fields[0] if gpu_fields else None, "không có nvidia-smi"),
        "vram": _component(gpu_fields[1] if len(gpu_fields) > 1 else None, "không có nvidia-smi"),
        "nvidia_driver": _component(gpu_fields[2] if len(gpu_fields) > 2 else None, "không có nvidia-smi"),
        "isaac_sim": _component(isaac, "Isaac launcher chưa cấu hình hoặc không đọc được phiên bản"),
        "openusd": _component(usd, "USD runtime chưa cấu hình hoặc không nạp được pxr.Usd"),
    }


def main() -> None:
    """Ghi manifest có canonical checksum; không ghi đè file đã có (identity bất biến)."""
    parser = argparse.ArgumentParser(description="Write RuntimeManifest for this worker machine")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} đã tồn tại; runtime mới cần file mới")
    if shutil.which("ffmpeg") is None:
        print("Cảnh báo: thiếu ffmpeg — upload video sẽ không xử lý được", file=sys.stderr)
    draft = RuntimeManifest.model_validate(
        {"schema_version": "1.0", "components": collect(), "runtime_manifest_checksum": "sha256:" + "0" * 64}
    )
    # Checksum tính trên model đã chuẩn hóa (kể cả field mặc định) — đúng cách loader verify.
    manifest = draft.model_copy(
        update={"runtime_manifest_checksum": canonical_content_checksum(draft, "runtime_manifest_checksum")}
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runtime_manifest": str(args.out), "checksum": manifest.runtime_manifest_checksum}))


if __name__ == "__main__":
    main()
