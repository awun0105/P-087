"""Registry production: trạng thái đến từ bản ghi có bằng chứng, máy chỉ có thể hạ chứ không nâng."""

from __future__ import annotations

import copy
import json
import stat
from pathlib import Path

import pytest

from scripts.gpu import qualify_input_runtimes as qualify
from src.models.contracts.input_assembly import (
    RuntimeCapabilityKey,
    RuntimeQualificationRegistry,
    seal_runtime_registry,
    verify_runtime_registry_checksum,
)


@pytest.fixture
def record() -> dict:
    return qualify.load_record(qualify.DEFAULT_RECORD)


def _env(tmp_path: Path, record: dict, **overrides: str) -> dict[str, str]:
    brush = tmp_path / "brush_app"
    brush.write_text("#!/bin/sh\n")
    brush.chmod(brush.stat().st_mode | stat.S_IXUSR)
    splat = tmp_path / "dist" / "index.mjs"
    splat.parent.mkdir(exist_ok=True)
    splat.write_text("//")
    (tmp_path / "package.json").write_text(json.dumps({"version": "3.6.6"}))
    odometry = tmp_path / "python"
    odometry.write_text("#!/bin/sh\necho 1.3.0\n")
    odometry.chmod(odometry.stat().st_mode | stat.S_IXUSR)
    env = dict(record["capabilities"]["R1"]["requires"])
    env.update(
        {
            "REC04_BRUSH_COMMAND": json.dumps([str(brush)]),
            "REC04_SPLAT_MODULE_PATH": str(splat),
            "REC17_LIDAR_ODOMETRY_PYTHON": str(odometry),
        }
    )
    env.update(overrides)
    return env


def _by_key(registry: dict) -> dict[str, dict]:
    return {item["capability_key"]: item for item in registry["capabilities"]}


def test_the_committed_record_only_qualifies_what_has_evidence_and_nothing_else(record: dict) -> None:
    qualified = {name for name, entry in record["capabilities"].items() if entry["status"] == "qualified"}
    assert qualified == set(record["capabilities"])  # hạ hướng nào về wired_unqualified là quyết định có chủ ý
    kinds = {name: entry["evidence"]["kind"] for name, entry in record["capabilities"].items()}
    assert kinds["R1"] == "baseline_job"
    assert {k for n, k in kinds.items() if n != "R1"} == {"owner_decision"}  # không giả làm số đo
    evidence = record["capabilities"]["R1"]["evidence"]
    assert evidence["kind"] and evidence["reference"]
    assert set(record["capabilities"]) == {key.value for key in RuntimeCapabilityKey}


def test_a_machine_that_matches_the_record_gets_exactly_the_recorded_statuses(tmp_path: Path, record: dict) -> None:
    built = qualify.build_registry(record, _env(tmp_path, record))
    items = _by_key(built)
    assert items["R1"]["status"] == "qualified"
    assert items["R1"]["qualification_evidence_checksum"].startswith("sha256:")
    assert {item["status"] for item in items.values()} == {"qualified"}
    sealed = seal_runtime_registry(built)
    verify_runtime_registry_checksum(RuntimeQualificationRegistry.model_validate_json(sealed.model_dump_json()))


def test_wired_unqualified_in_the_record_stays_wired_unqualified(tmp_path: Path, record: dict) -> None:
    held = copy.deepcopy(record)
    held["capabilities"]["R5"] = {"status": "wired_unqualified", "reason_codes": ["pending"]}
    assert _by_key(qualify.build_registry(held, _env(tmp_path, record)))["R5"]["status"] == "wired_unqualified"


def test_the_machine_can_only_demote_never_promote(tmp_path: Path, record: dict) -> None:
    drifted = _env(tmp_path, record, REC03_COLMAP_RUNTIME_IDENTITY="colmap-image-sha256:" + "f" * 64)
    r1 = _by_key(qualify.build_registry(record, drifted))["R1"]
    assert r1["status"] == "incompatible"
    assert "runtime_identity_differs" in r1["reason_codes"]

    no_brush = _env(tmp_path, record, REC04_BRUSH_COMMAND=json.dumps([str(tmp_path / "missing")]))
    items = _by_key(qualify.build_registry(record, no_brush))
    assert items["R1"]["status"] == items["R2"]["status"] == "unavailable"  # kể cả hướng đang chờ xác minh


def test_a_capability_missing_from_the_record_is_unavailable(tmp_path: Path, record: dict) -> None:
    trimmed = copy.deepcopy(record)
    del trimmed["capabilities"]["R6"]
    item = _by_key(qualify.build_registry(trimmed, _env(tmp_path, record)))["R6"]
    assert item["status"] == "unavailable"
    assert item["reason_codes"] == ["not_in_qualification_record"]


def test_the_registry_is_deterministic_so_api_and_worker_share_one_checksum(tmp_path: Path, record: dict) -> None:
    env = _env(tmp_path, record)
    first = seal_runtime_registry(qualify.build_registry(record, env))
    second = seal_runtime_registry(qualify.build_registry(copy.deepcopy(record), dict(env)))
    assert first.registry_checksum == second.registry_checksum


def test_a_qualified_entry_without_evidence_or_pins_is_rejected(tmp_path: Path, record: dict) -> None:
    for mutate in (
        lambda r: r["capabilities"]["R2"].pop("evidence"),
        lambda r: r["capabilities"]["R1"].pop("evidence"),
        lambda r: r["capabilities"]["R1"].pop("requires"),
        lambda r: r["capabilities"].update({"R9": {"status": "qualified"}}),
        lambda r: r["capabilities"]["R3"].update({"status": "incompatible"}),
    ):
        broken = copy.deepcopy(record)
        mutate(broken)
        path = tmp_path / "record.json"
        path.write_text(json.dumps(broken))
        with pytest.raises(qualify.QualificationRecordError):
            qualify.load_record(path)


def test_main_writes_atomically_is_idempotent_and_runs_in_production(
    tmp_path: Path, record: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in _env(tmp_path, record).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "production")  # khác bản dev-local: production là chỗ script này dành cho
    out = tmp_path / "state" / "input_runtime_registry.json"
    assert qualify.main(["--out", str(out)]) == 0
    first = out.read_text()
    inode = out.stat().st_ino
    assert qualify.main(["--out", str(out)]) == 0
    assert out.read_text() == first and out.stat().st_ino == inode  # không ghi lại khi nội dung y hệt
    assert list(out.parent.glob(".*.tmp")) == []
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert qualify.main(["--out", str(out), "--record", str(bad)]) == 2
    assert out.read_text() == first  # bản ghi hỏng không làm mất registry đang chạy


def test_view_capabilities_do_not_depend_on_the_video_runtime_but_pin_the_splat_version(
    tmp_path: Path, record: dict
) -> None:
    broken_colmap = _env(tmp_path, record, REC03_COLMAP_RUNTIME_IDENTITY="colmap-image-sha256:" + "f" * 64)
    items = _by_key(qualify.build_registry(record, broken_colmap))
    assert items["R1"]["status"] == "incompatible"
    assert items["gaussian_ply_view"]["status"] == items["gaussian_sog_view"]["status"] == "qualified"

    env = _env(tmp_path, record)
    (tmp_path / "package.json").write_text(json.dumps({"version": "9.9.9"}))  # sau _env, vì helper ghi 3.6.6
    drifted = _by_key(qualify.build_registry(record, env))
    assert drifted["gaussian_ply_view"]["status"] == "incompatible"
    assert "drift_version_splat_transform" in drifted["gaussian_ply_view"]["reason_codes"]


def test_r5_and_r6_are_bound_to_the_kiss_icp_version_and_the_delivered_odometry_profile(
    tmp_path: Path, record: dict
) -> None:
    from src.services.reconstruction.lidar.odometry import DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION

    assert (
        record["capabilities"]["R5"]["requires_versions"]["odometry_profile"] == DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION
    )
    stale = copy.deepcopy(record)
    for key in ("R5", "R6"):
        stale["capabilities"][key]["requires_versions"]["odometry_profile"] = "rec17-default-v0"
    items = _by_key(qualify.build_registry(stale, _env(tmp_path, record)))
    assert items["R5"]["status"] == items["R6"]["status"] == "incompatible"
    assert items["R1"]["status"] == "qualified"  # chỉ hướng bị ảnh hưởng mới bị hạ
