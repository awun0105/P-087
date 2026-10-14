"""Harness dựng tổ hợp video + file LiDAR rời để kiểm resolver theo ma trận.

Mọi file được nộp riêng lẻ (không ZIP). Khai báo người dùng được điền đủ để phép thử chỉ lộ chỗ
nghẹt về cấu trúc: file nào được dùng, file nào bị loại, thiếu vai trò nào.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.input_assembly import (
    InputBinding,
    InputResolutionReport,
    InputRole,
    RuntimeCapabilityKey,
    RuntimeCapabilityRecord,
    RuntimeQualificationStatus,
)
from src.services.reconstruction.inputs.input_resolver import resolve_input_assembly
from tests.test_reconstruction.test_input_assembly_resolution import (
    _assembly,
    _qualified,
    _registry,
    _upload,
    _video,
    _wired,
    _write,
)

PCD = (
    b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
)
PLY = (
    b"ply\nformat ascii 1.0\nelement vertex 1\n"
    b"property float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n"
)
CALIBRATION = b'{"lidar_from_camera":{"translation_xyz":[0,0,0],"rotation_xyzw":[0,0,0,1]}}'


def _declared(value: object) -> dict[str, object]:
    return {"value": value, "provenance": "declared"}


@dataclass(frozen=True)
class Capture:
    """Một lần nộp: video luôn có; mọi thứ còn lại là tuỳ chọn."""

    clouds: int = 0
    cloud_state: str | None = None
    calibration: bool = False
    rgb_times: bool = False
    trajectory: bool = False
    lidar_times: bool = False
    videos: int = 1
    intent: str | None = None
    declare_sidecars: bool = True
    runtime: str = "qualified"  # qualified | wired | none
    same_scene: bool = True
    #: Số dòng file thời điểm frame; None = khớp số pose (hoặc 30 khi không có quỹ đạo).
    frame_time_rows: int | None = None
    scan_format: str = "pcd"  # pcd | ply
    #: False = để file thời điểm scan/frame không bind vai trò, nhờ resolver suy theo số dòng.
    bind_times: bool = True
    declare_lidar_unit: bool = True


@dataclass(frozen=True)
class Outcome:
    state: str
    recommended: bool
    chosen: str | None
    candidates: tuple[tuple[str, str, frozenset[str]], ...]  # (nhóm, trạng thái, mã fact)

    def groups(self) -> set[str]:
        return {group for group, _, _ in self.candidates}

    def facts(self, group: str) -> set[str]:
        merged: set[str] = set()
        for candidate_group, _, codes in self.candidates:
            if candidate_group == group:
                merged |= codes
        return merged

    def states(self, group: str) -> set[str]:
        return {state for candidate_group, state, _ in self.candidates if candidate_group == group}


def resolve(capture: Capture) -> InputResolutionReport:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        uploads = [
            _upload(
                _write(tmp, f"video_{index}.mp4", _video()), upload_id=f"video-up-{index}", file_id=f"video-{index}"
            )
            for index in range(capture.videos)
        ]
        scan_payload = PCD if capture.scan_format == "pcd" else PLY
        for index in range(capture.clouds):
            uploads.append(
                _upload(
                    _write(tmp, f"scan_{index}.{capture.scan_format}", scan_payload),
                    upload_id=f"cloud-up-{index}",
                    file_id=f"cloud-{index}",
                )
            )
        if capture.calibration:
            uploads.append(
                _upload(_write(tmp, "calibration.json", CALIBRATION), upload_id="cal-up", file_id="calibration")
            )
        if capture.rgb_times:
            # Có quỹ đạo thì mỗi pose một dòng thời điểm frame (đúng điều kiện của gói R4).
            frame_rows = capture.frame_time_rows or (max(capture.clouds, 2) if capture.trajectory else 30)
            rows = "".join(f"{0.1 * index}\n" for index in range(frame_rows)).encode()
            uploads.append(_upload(_write(tmp, "rgb_times.txt", rows), upload_id="rgbt-up", file_id="rgb-times"))
        if capture.trajectory:
            rows = "".join(f"{0.1 * index} {index} 0 0 0 0 0 1\n" for index in range(max(capture.clouds, 2))).encode()
            uploads.append(_upload(_write(tmp, "trajectory.txt", rows), upload_id="traj-up", file_id="trajectory"))
        if capture.lidar_times:
            rows = "".join(f"{0.2 * index}\n" for index in range(capture.clouds)).encode()
            uploads.append(_upload(_write(tmp, "lidar_times.txt", rows), upload_id="lt-up", file_id="lidar-times"))

        declarations: dict[str, object] = {}
        if capture.declare_sidecars:
            declarations.update(
                same_scene=_declared(capture.same_scene),
                coordinate_unit=_declared("m"),
                lidar_frame_id=_declared("lidar"),
                rgb_timestamp_unit=_declared("seconds"),
                lidar_timestamp_unit=_declared("seconds"),
                clock_relation=_declared("same_clock"),
                trajectory_convention=_declared("world_from_sensor"),
            )
        if capture.cloud_state:
            declarations["cloud_state"] = _declared(capture.cloud_state)

        bindings: list[InputBinding] = []
        if capture.rgb_times and capture.bind_times:
            bindings.append(
                InputBinding(binding_id="b-rgb-times", role=InputRole.RGB_FRAME_TIMES, file_ids=["rgb-times"])
            )
        if capture.lidar_times and capture.bind_times:
            bindings.append(
                InputBinding(binding_id="b-lidar-times", role=InputRole.LIDAR_SCAN_TIMES, file_ids=["lidar-times"])
            )
        assembly, probes = _assembly(uploads, declarations=declarations, bindings=bindings, intent=capture.intent)
        records: list[RuntimeCapabilityRecord] = []
        if capture.runtime == "qualified":
            records = [_qualified(key) for key in RuntimeCapabilityKey]
        elif capture.runtime == "wired":
            records = [_wired(key) for key in RuntimeCapabilityKey]
        elif capture.runtime != "none":
            raise ValueError(f"unknown runtime mode: {capture.runtime}")
        return resolve_input_assembly(assembly, _registry(*records), probes)


def outcome(capture: Capture) -> Outcome:
    report = resolve(capture)
    rows = [
        (item.recipe_group.value, item.state.value, frozenset(fact.code for fact in item.required_facts))
        for item in report.candidates
        if item.candidate_kind == "video_recipe"
    ]
    rows.sort(key=lambda row: (row[0], row[1], sorted(row[2])))
    chosen = next(
        (
            item.recipe_group.value
            for item in report.candidates
            if item.candidate_kind == "video_recipe" and item.candidate_id == report.recommended_candidate_id
        ),
        None,
    )
    return Outcome(report.state.value, report.recommended_candidate_id is not None, chosen, tuple(rows))


__all__ = ["Capture", "Outcome", "outcome", "resolve", "RuntimeQualificationStatus"]
