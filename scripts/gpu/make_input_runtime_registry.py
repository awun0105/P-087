"""Sinh registry năng lực xử lý input (`PRODUCT_INPUT_RUNTIME_REGISTRY`) cho MỘT máy dev.

Registry này KHÔNG phải kết quả kiểm định. Nó là lời khai "runtime này có mặt trên máy và đúng phiên bản đã
ghim", dùng để luồng tạo scene chạy được khi phát triển cục bộ. Triển khai thật phải có registry do quy trình
kiểm định runtime sinh ra; vì thế script từ chối chạy khi `APP_ENV=production`, ghi nhãn `dev-local` vào
`registry_version`, và chỉ khai `qualified` cho hướng mà runtime tương ứng *đọc được ngay trên máy này*.

    set -a; source scripts/gpu/studio.env; set +a
    python -m scripts.gpu.make_input_runtime_registry --out data/studio_local/input_runtime_registry.dev.json

API và worker phải trỏ cùng một file (worker kiểm lại cả chuỗi checksum trước khi chạy).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.input_assembly import (
    RuntimeCapabilityKey,
    RuntimeQualificationStatus,
    seal_runtime_registry,
)

DEV_LABEL = "dev-local"
_ODOMETRY_KEYS = (RuntimeCapabilityKey.R5, RuntimeCapabilityKey.R6)
_VIDEO_KEYS = (RuntimeCapabilityKey.R1, RuntimeCapabilityKey.R2, RuntimeCapabilityKey.R3, RuntimeCapabilityKey.R4)
_VIEW_KEYS = (RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW, RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW)
_DEFAULT_ODOMETRY_PYTHON = "/opt/real2sim/lidar_runtime/bin/python"
_PINNED_ODOMETRY_VERSION = "1.3.0"


def parse_env_file(path: Path) -> dict[str, str]:
    """Đọc `KEY=VALUE` (có thể bọc nháy đơn/kép) giống cách `run_stack.sh` source file env."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def odometry_version(python: Path) -> str | None:
    """Phiên bản KISS-ICP cài trong interpreter cô lập; None khi không chạy được."""
    if not python.is_file() or not os.access(python, os.X_OK):
        return None
    try:
        result = subprocess.run(
            [str(python), "-c", "import importlib.metadata as m; print(m.version('kiss-icp'))"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _evidence(capability: str, components: Mapping[str, str]) -> str:
    """Checksum của chính lời khai (không phải số đo): đổi runtime thì checksum đổi theo."""
    payload = {"declaration": "dev-local-unmeasured", "capability": capability, "components": dict(components)}
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_registry(env: Mapping[str, str]) -> dict[str, object]:
    colmap = env.get("REC03_COLMAP_RUNTIME_IDENTITY", "").strip()
    brush = env.get("REC04_BRUSH_RUNTIME_IDENTITY", "").strip()
    brush_version = env.get("REC04_BRUSH_EXPECTED_VERSION", "").strip()
    splat_module = env.get("REC04_SPLAT_MODULE_PATH", "").strip()
    brush_command = env.get("REC04_BRUSH_COMMAND", "").strip()
    brush_binary = ""
    if brush_command:
        try:
            parsed = json.loads(brush_command)
            brush_binary = str(parsed[0]) if isinstance(parsed, list) and parsed else str(parsed)
        except (json.JSONDecodeError, ValueError):
            brush_binary = brush_command
    python = Path(env.get("REC17_LIDAR_ODOMETRY_PYTHON", _DEFAULT_ODOMETRY_PYTHON)).expanduser()
    kiss_version = odometry_version(python)

    video_missing = [
        name
        for name, ok in (
            ("colmap_identity_unset", bool(colmap)),
            ("brush_identity_unset", bool(brush and brush_version)),
            ("brush_binary_missing", bool(brush_binary) and Path(brush_binary).is_file()),
        )
        if not ok
    ]
    view_missing = [] if splat_module and Path(splat_module).is_file() else ["splat_transform_missing"]
    if kiss_version is None:
        odometry_missing = ["odometry_runtime_missing"]
    elif kiss_version != _PINNED_ODOMETRY_VERSION:
        odometry_missing = ["odometry_version_differs_from_pin"]
    else:
        odometry_missing = []

    video_components = {"colmap": colmap, "brush": brush, "brush_version": brush_version}
    records: list[dict[str, object]] = []

    def add(key: RuntimeCapabilityKey, missing: list[str], components: Mapping[str, str], version: str) -> None:
        if missing:
            records.append(
                {
                    "capability_key": key.value,
                    "status": RuntimeQualificationStatus.UNAVAILABLE.value,
                    "reason_codes": missing,
                }
            )
            return
        records.append(
            {
                "capability_key": key.value,
                "status": RuntimeQualificationStatus.QUALIFIED.value,
                "runtime_id": f"{DEV_LABEL}-{key.value.lower().replace('_', '-')}",
                "runtime_version": version,
                "qualification_evidence_checksum": _evidence(key.value, components),
                "reason_codes": [],
            }
        )

    for key in _VIDEO_KEYS:
        add(key, video_missing, video_components, f"colmap-{colmap[-12:]}+brush-{brush_version}")
    odometry_components = {**video_components, "kiss_icp": kiss_version or ""}
    for key in _ODOMETRY_KEYS:
        add(
            key,
            [*video_missing, *odometry_missing],
            odometry_components,
            f"colmap-{colmap[-12:]}+brush-{brush_version}+kiss-icp-{kiss_version}",
        )
    for key in _VIEW_KEYS:
        add(key, view_missing, {"splat_transform": splat_module}, "splat-transform-local")
    return {
        "schema_version": "1.0",
        "registry_version": f"{DEV_LABEL}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "capabilities": records,
        "registry_checksum": "sha256:" + "0" * 64,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sinh registry năng lực input cho máy dev (không phải kiểm định)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, help="đọc cấu hình runtime từ file env thay vì môi trường hiện tại")
    parser.add_argument("--force", action="store_true", help="ghi đè file đã có")
    args = parser.parse_args(argv)

    env: dict[str, str] = dict(os.environ)
    if args.env_file is not None:
        env.update(parse_env_file(args.env_file))
    if env.get("APP_ENV", "").strip().lower() == "production":
        print("Từ chối: registry dev-local không được dùng trong APP_ENV=production.", file=sys.stderr)
        return 2
    if args.out.exists() and not args.force:
        print(f"{args.out} đã tồn tại; dùng --force để ghi đè.", file=sys.stderr)
        return 2

    registry = seal_runtime_registry(build_registry(env))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {args.out}  (registry_checksum={registry.registry_checksum})")
    print("LƯU Ý: đây là lời khai dev-local, không phải kết quả kiểm định runtime.")
    for item in registry.capabilities:
        reasons = f"  [{', '.join(item.reason_codes)}]" if item.reason_codes else ""
        print(f"  {item.capability_key.value:20s} {item.status.value}{reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
