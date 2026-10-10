"""Registry dev-local: chỉ khai `qualified` cho runtime đọc được trên máy, và không bao giờ cho production."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from scripts.gpu import make_input_runtime_registry as script
from src.models.contracts.input_assembly import (
    RuntimeCapabilityKey,
    RuntimeQualificationRegistry,
    RuntimeQualificationStatus,
    seal_runtime_registry,
    verify_runtime_registry_checksum,
)

_COLMAP = "colmap-image-sha256:" + "a" * 64
_BRUSH = "brush-v0.3.0-linux-archive-sha256:" + "b" * 64


def _env(tmp_path: Path, *, with_odometry: bool) -> dict[str, str]:
    brush = tmp_path / "brush_app"
    brush.write_text("#!/bin/sh\n")
    brush.chmod(brush.stat().st_mode | stat.S_IXUSR)
    splat = tmp_path / "index.mjs"
    splat.write_text("//")
    env = {
        "REC03_COLMAP_RUNTIME_IDENTITY": _COLMAP,
        "REC04_BRUSH_RUNTIME_IDENTITY": _BRUSH,
        "REC04_BRUSH_EXPECTED_VERSION": "0.3.0",
        "REC04_BRUSH_COMMAND": json.dumps([str(brush)]),
        "REC04_SPLAT_MODULE_PATH": str(splat),
    }
    if with_odometry:
        python = tmp_path / "python"
        python.write_text("#!/bin/sh\necho 1.3.0\n")
        python.chmod(python.stat().st_mode | stat.S_IXUSR)
        env["REC17_LIDAR_ODOMETRY_PYTHON"] = str(python)
    else:
        env["REC17_LIDAR_ODOMETRY_PYTHON"] = str(tmp_path / "missing" / "python")
    return env


def _statuses(registry: dict[str, object]) -> dict[str, str]:
    return {item["capability_key"]: item["status"] for item in registry["capabilities"]}  # type: ignore[index]


def test_every_runnable_direction_is_qualified_and_the_registry_seals_and_verifies(tmp_path: Path) -> None:
    built = script.build_registry(_env(tmp_path, with_odometry=True))
    assert set(_statuses(built).values()) == {"qualified"}
    sealed = seal_runtime_registry(built)
    verify_runtime_registry_checksum(RuntimeQualificationRegistry.model_validate_json(sealed.model_dump_json()))
    assert sealed.registry_version.startswith(script.DEV_LABEL)  # luôn thấy nhãn dev-local
    assert {item.capability_key for item in sealed.capabilities} == set(RuntimeCapabilityKey)


def test_without_the_isolated_odometry_runtime_only_r5_and_r6_are_unavailable(tmp_path: Path) -> None:
    statuses = _statuses(script.build_registry(_env(tmp_path, with_odometry=False)))
    assert statuses["R5"] == statuses["R6"] == RuntimeQualificationStatus.UNAVAILABLE.value
    assert statuses["R1"] == statuses["R4"] == statuses["gaussian_sog_view"] == "qualified"


def test_a_missing_video_runtime_is_never_claimed_qualified(tmp_path: Path) -> None:
    env = _env(tmp_path, with_odometry=True)
    env["REC03_COLMAP_RUNTIME_IDENTITY"] = ""
    statuses = _statuses(script.build_registry(env))
    assert statuses["R1"] == statuses["R5"] == "unavailable"
    assert statuses["gaussian_ply_view"] == "qualified"  # xem 3DGS không cần COLMAP


def test_the_evidence_follows_the_runtime_identity(tmp_path: Path) -> None:
    env = _env(tmp_path, with_odometry=True)
    first = script.build_registry(env)["capabilities"][0]["qualification_evidence_checksum"]  # type: ignore[index]
    env["REC03_COLMAP_RUNTIME_IDENTITY"] = "colmap-image-sha256:" + "c" * 64
    second = script.build_registry(env)["capabilities"][0]["qualification_evidence_checksum"]  # type: ignore[index]
    assert first != second


def test_production_is_refused_and_an_existing_file_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "registry.json"
    monkeypatch.setenv("APP_ENV", "production")
    assert script.main(["--out", str(out)]) == 2
    assert not out.exists()
    monkeypatch.delenv("APP_ENV")
    out.write_text("keep")
    assert script.main(["--out", str(out)]) == 2
    assert out.read_text() == "keep"
    assert os.environ.get("APP_ENV") is None
