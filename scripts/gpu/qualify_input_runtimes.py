"""Sinh registry năng lực input của PRODUCTION từ bản ghi kiểm định đã commit + identity runtime đo trên máy này.

Khác với `make_input_runtime_registry` (lời khai dev-local, từ chối production), script này không tự nâng trạng
thái nào. Trạng thái của từng hướng do `configs/product/input_runtime_qualification_v1.json` quyết định, và một
hướng `qualified` bắt buộc có `evidence`. Script chỉ làm hai việc an toàn:

  * hạ xuống `incompatible` khi identity runtime đo được trên máy KHÁC với identity mà bản ghi đã kiểm định;
  * hạ xuống `unavailable` khi runtime cần có không hiện diện (COLMAP/Brush/KISS-ICP/splat-transform).

Kết quả là xác định (không có mốc thời gian): cùng bản ghi + cùng runtime thì cùng checksum, nên API và worker
dùng chung một file mà không bị lệch chuỗi checksum giữa các lần khởi động.

    python -m scripts.gpu.qualify_input_runtimes --out /data/studio_local/input_runtime_registry.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.gpu.make_input_runtime_registry import odometry_version, parse_env_file
from src.models.contracts.input_assembly import (
    RuntimeCapabilityKey,
    RuntimeQualificationStatus,
    seal_runtime_registry,
)
from src.runtime_env import requirement_env_name, runtime_env
from src.services.reconstruction.lidar.odometry import DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION

DEFAULT_RECORD = Path(__file__).resolve().parents[2] / "configs/product/input_runtime_qualification_v1.json"
_DEFAULT_ODOMETRY_PYTHON = "/opt/real2sim/lidar_runtime/bin/python"
_PINNED_ODOMETRY_VERSION = "1.3.0"
_VIDEO_KEYS = {RuntimeCapabilityKey.R1, RuntimeCapabilityKey.R2, RuntimeCapabilityKey.R3, RuntimeCapabilityKey.R4}
_ODOMETRY_KEYS = {RuntimeCapabilityKey.R5, RuntimeCapabilityKey.R6}
_VIEW_KEYS = {RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW, RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW}
#: Tên phiên bản mà bản ghi được phép ghim (đo trực tiếp trên máy, không phải biến môi trường).
_VERSION_PINS = ("splat_transform", "kiss_icp", "odometry_profile")
_RECORDABLE = {RuntimeQualificationStatus.QUALIFIED.value, RuntimeQualificationStatus.WIRED_UNQUALIFIED.value}


class QualificationRecordError(ValueError):
    """Bản ghi kiểm định sai cấu trúc hoặc khai `qualified` mà không có bằng chứng."""


def _checksum(payload: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_record(path: Path) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != "1.0" or not record.get("record_id"):
        raise QualificationRecordError("bản ghi kiểm định thiếu schema_version/record_id")
    entries = record.get("capabilities")
    if not isinstance(entries, dict):
        raise QualificationRecordError("bản ghi kiểm định thiếu `capabilities`")
    known = {key.value for key in RuntimeCapabilityKey}
    for name, entry in entries.items():
        if name not in known:
            raise QualificationRecordError(f"capability không biết: {name}")
        if not isinstance(entry, dict) or entry.get("status") not in _RECORDABLE:
            raise QualificationRecordError(f"{name}: status chỉ được là {sorted(_RECORDABLE)}")
        if entry["status"] == RuntimeQualificationStatus.QUALIFIED.value:
            evidence = entry.get("evidence")
            if not isinstance(evidence, dict) or not evidence.get("kind") or not evidence.get("reference"):
                raise QualificationRecordError(f"{name}: `qualified` bắt buộc có evidence.kind và evidence.reference")
            for field in ("requires", "requires_versions"):
                if not isinstance(entry.get(field, {}), dict):
                    raise QualificationRecordError(f"{name}: `{field}` phải là một object")
            pins = {**(entry.get("requires") or {}), **(entry.get("requires_versions") or {})}
            if (
                not pins
                or not isinstance(entry.get("requires", {}), dict)
                or not isinstance(entry.get("requires_versions", {}), dict)
            ):
                raise QualificationRecordError(
                    f"{name}: `qualified` bắt buộc khai `requires` (biến môi trường) hoặc `requires_versions` (phiên bản)"
                )
            unknown = set(entry.get("requires_versions") or {}) - set(_VERSION_PINS)
            if unknown:
                raise QualificationRecordError(f"{name}: requires_versions không biết: {sorted(unknown)}")
        elif not entry.get("reason_codes"):
            raise QualificationRecordError(f"{name}: `wired_unqualified` bắt buộc có reason_codes")
    return record


def _live(env: Mapping[str, str]) -> dict[str, str]:
    return {
        name: runtime_env(env, name, "").strip()
        for name in (
            "R2S_COLMAP_RUNTIME_IDENTITY",
            "R2S_BRUSH_RUNTIME_IDENTITY",
            "R2S_BRUSH_EXPECTED_VERSION",
        )
    }


def _splat_version(env: Mapping[str, str]) -> str | None:
    module = runtime_env(env, "R2S_SPLAT_MODULE_PATH", "").strip()
    if not module or not Path(module).is_file():
        return None
    package = Path(module).resolve().parents[1] / "package.json"
    try:
        return str(json.loads(package.read_text(encoding="utf-8")).get("version") or "") or None
    except (OSError, ValueError):
        return None


def _brush_binary_present(env: Mapping[str, str]) -> bool:
    raw = runtime_env(env, "R2S_BRUSH_COMMAND", "").strip()
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
        binary = str(parsed[0]) if isinstance(parsed, list) and parsed else str(parsed)
    except (ValueError, IndexError):
        binary = raw
    return Path(binary).is_file()


def build_registry(record: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, object]:
    live = _live(env)
    colmap, brush, brush_version = (
        live["R2S_COLMAP_RUNTIME_IDENTITY"],
        live["R2S_BRUSH_RUNTIME_IDENTITY"],
        live["R2S_BRUSH_EXPECTED_VERSION"],
    )
    video_version = f"colmap-{colmap[-12:]}+brush-{brush_version}"
    video_missing = [
        code
        for code, ok in (
            ("colmap_identity_unset", bool(colmap)),
            ("brush_identity_unset", bool(brush and brush_version)),
            ("brush_binary_missing", _brush_binary_present(env)),
        )
        if not ok
    ]
    kiss = odometry_version(Path(runtime_env(env, "R2S_LIDAR_ODOMETRY_PYTHON", _DEFAULT_ODOMETRY_PYTHON)).expanduser())
    odometry_missing = (
        ["odometry_runtime_missing"]
        if kiss is None
        else ([] if kiss == _PINNED_ODOMETRY_VERSION else ["odometry_version_differs_from_pin"])
    )
    splat = _splat_version(env)
    view_missing = [] if splat else ["splat_transform_missing"]

    live_versions = {
        "splat_transform": splat or "",
        "kiss_icp": kiss or "",
        "odometry_profile": DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION,
    }
    records: list[dict[str, object]] = []
    for key in RuntimeCapabilityKey:
        entry = record["capabilities"].get(key.value)
        if key in _VIDEO_KEYS:
            runtime_id, version, missing = "colmap-brush", video_version, video_missing
        elif key in _ODOMETRY_KEYS:
            runtime_id, version = "kiss-icp", f"kiss-icp-{kiss}+{video_version}"
            missing = [*video_missing, *odometry_missing]
        else:
            runtime_id, version, missing = "splat-transform", f"splat-transform-{splat}", view_missing

        if entry is None:
            records.append(
                {
                    "capability_key": key.value,
                    "status": RuntimeQualificationStatus.UNAVAILABLE.value,
                    "reason_codes": ["not_in_qualification_record"],
                }
            )
            continue
        if missing:
            records.append(
                {
                    "capability_key": key.value,
                    "status": RuntimeQualificationStatus.UNAVAILABLE.value,
                    "reason_codes": missing,
                }
            )
            continue
        if entry["status"] == RuntimeQualificationStatus.QUALIFIED.value:
            drift = sorted(
                [
                    name
                    for name, expected in (entry.get("requires") or {}).items()
                    if runtime_env(env, requirement_env_name(name), "").strip() != expected
                ]
                + [
                    f"version_{name}"
                    for name, expected in (entry.get("requires_versions") or {}).items()
                    if live_versions[name] != expected
                ]
            )
            if drift:
                records.append(
                    {
                        "capability_key": key.value,
                        "status": RuntimeQualificationStatus.INCOMPATIBLE.value,
                        "reason_codes": ["runtime_identity_differs", *(f"drift_{name.lower()}" for name in drift)],
                    }
                )
                continue
            records.append(
                {
                    "capability_key": key.value,
                    "status": RuntimeQualificationStatus.QUALIFIED.value,
                    "runtime_id": runtime_id,
                    "runtime_version": version,
                    "qualification_evidence_checksum": _checksum(
                        {
                            "record": record["record_id"],
                            "capability": key.value,
                            "entry": entry,
                            "live": live,
                            "live_versions": live_versions,
                        }
                    ),
                    "reason_codes": [],
                }
            )
            continue
        records.append(
            {
                "capability_key": key.value,
                "status": RuntimeQualificationStatus.WIRED_UNQUALIFIED.value,
                "runtime_id": runtime_id,
                "runtime_version": version,
                "reason_codes": list(entry["reason_codes"]),
            }
        )
    return {
        "schema_version": "1.0",
        "registry_version": f"{record['record_id']}-{_checksum(record)[7:19]}",
        "capabilities": records,
        "registry_checksum": "sha256:" + "0" * 64,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sinh registry năng lực input từ bản ghi kiểm định + identity runtime")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--env-file", type=Path, help="đọc cấu hình runtime từ file env thay vì môi trường hiện tại")
    args = parser.parse_args(argv)

    env: dict[str, str] = dict(os.environ)
    if args.env_file is not None:
        env.update(parse_env_file(args.env_file))
    try:
        record = load_record(args.record)
    except (OSError, ValueError) as error:
        print(f"Bản ghi kiểm định không dùng được: {error}", file=sys.stderr)
        return 2

    registry = seal_runtime_registry(build_registry(record, env))
    payload = registry.model_dump_json(indent=2) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not (args.out.is_file() and args.out.read_text(encoding="utf-8") == payload):
        temporary = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, args.out)
    print(f"Registry {args.out}  checksum={registry.registry_checksum}")
    for item in registry.capabilities:
        reasons = f"  [{', '.join(item.reason_codes)}]" if item.reason_codes else ""
        print(f"  {item.capability_key.value:20s} {item.status.value}{reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
