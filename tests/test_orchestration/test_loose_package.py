"""Đóng gói file LiDAR nộp rời và kiểm tra thành viên gói do server đóng."""

from __future__ import annotations

import pytest

from src.models.contracts.input_assembly import (
    ArchiveMemberRef,
    InputAssetFormat,
    InputRole,
    StagedInputFile,
)
from src.models.contracts.manifests import InputFile
from src.services.orchestration.inputs.loose_package import (
    LoosePackageError,
    is_user_supplied_package,
    verify_package_members,
)
from src.services.orchestration.projects.models import LidarPackageMember


def _checksum(char: str) -> str:
    return "sha256:" + char * 64


def _source(name: str, char: str, media_type: str = "text/plain") -> InputFile:
    return InputFile(
        original_name=name,
        media_type=media_type,
        size_bytes=10,
        checksum=_checksum(char),
        artifact_uri=f"artifact://jobs/{name}/input/source",
        data_class="product_input",
    )


def _staged(file_id: str, fmt: InputAssetFormat, char: str, *, member_of: str | None = None) -> StagedInputFile:
    if member_of is None:
        return StagedInputFile(
            file_id=file_id, upload_id=f"up-{file_id}", source_file=_source(file_id, char), observed_format=fmt
        )
    container = _source(member_of, "c", "application/zip")
    return StagedInputFile(
        file_id=file_id,
        upload_id=f"up-{member_of}",
        source_file=container,
        observed_format=fmt,
        archive_member=ArchiveMemberRef(
            container_checksum=container.checksum,
            member_path=f"{file_id}.dat",
            member_checksum=_checksum(char),
            uncompressed_size_bytes=10,
        ),
    )


def _fixture(scan_count: int = 3):
    staged = {f"scan-{i}": _staged(f"scan-{i}", InputAssetFormat.POINT_CLOUD_PCD, str(i)) for i in range(scan_count)}
    staged["traj"] = _staged("traj", InputAssetFormat.TUM_TRAJECTORY, "a")
    staged["calib"] = _staged("calib", InputAssetFormat.CALIBRATION_TORWIC_TEXT, "b")
    staged["times"] = _staged("times", InputAssetFormat.TIMESTAMP_ROWS, "d")
    bindings = {
        InputRole.LIDAR_SCAN: [f"scan-{i}" for i in range(scan_count)],
        InputRole.SENSOR_TRAJECTORY: ["traj"],
        InputRole.CAMERA_LIDAR_CALIBRATION: ["calib"],
        InputRole.RGB_FRAME_TIMES: ["times"],
    }
    members = [
        LidarPackageMember(
            member_path=f"{i:06d}.pcd", file_id=f"scan-{i}", source_checksum=_checksum(str(i)), role="lidar_scan"
        )
        for i in range(scan_count)
    ] + [
        LidarPackageMember(
            member_path="trajectory.txt", file_id="traj", source_checksum=_checksum("a"), role="sensor_trajectory"
        ),
        LidarPackageMember(
            member_path="calibrations.txt",
            file_id="calib",
            source_checksum=_checksum("b"),
            role="camera_lidar_calibration",
        ),
        LidarPackageMember(
            member_path="frame_times.txt", file_id="times", source_checksum=_checksum("d"), role="rgb_frame_times"
        ),
    ]
    return staged, bindings, members


def _verify(members, staged, bindings, **overrides) -> None:
    arguments = {
        "trajectory_member": "trajectory.txt",
        "calibration_member": "calibrations.txt",
        "frame_times_member": "frame_times.txt",
        "scan_count": 3,
    }
    arguments.update(overrides)
    verify_package_members(members, staged=staged, role_bindings=bindings, **arguments)


def test_exact_members_verify() -> None:
    staged, bindings, members = _fixture()
    _verify(members, staged, bindings)


def test_scan_order_in_the_package_must_follow_the_confirmed_binding_order() -> None:
    staged, bindings, members = _fixture()
    bindings[InputRole.LIDAR_SCAN] = ["scan-1", "scan-0", "scan-2"]  # người dùng đổi thứ tự sau khi gói đã đóng
    with pytest.raises(LoosePackageError, match="Thứ tự scan"):
        _verify(members, staged, bindings)


def test_a_changed_source_checksum_is_rejected() -> None:
    staged, bindings, members = _fixture()
    staged["traj"] = _staged("traj", InputAssetFormat.TUM_TRAJECTORY, "f")  # nguồn đã đổi sau khi đóng gói
    with pytest.raises(LoosePackageError, match="Checksum thành viên"):
        _verify(members, staged, bindings)


def test_a_member_with_the_wrong_role_is_rejected() -> None:
    staged, bindings, members = _fixture()
    members[-1] = members[-1].model_copy(update={"role": "sensor_trajectory"})
    with pytest.raises(LoosePackageError):
        _verify(members, staged, bindings)


def test_member_names_must_match_what_the_detector_found_in_the_package() -> None:
    staged, bindings, members = _fixture()
    with pytest.raises(LoosePackageError, match="thiếu hoặc nhầm"):
        _verify(members, staged, bindings, calibration_member="other.json")


def test_scan_count_must_match_the_detected_package() -> None:
    staged, bindings, members = _fixture()
    with pytest.raises(LoosePackageError, match="không khớp số file"):
        _verify(members, staged, bindings, scan_count=2)


def test_archive_members_verify_against_their_member_checksum_not_the_container() -> None:
    staged, bindings, members = _fixture()
    staged["traj"] = _staged("traj", InputAssetFormat.TUM_TRAJECTORY, "a", member_of="bundle")
    _verify(members, staged, bindings)


def test_a_zip_the_user_supplied_is_recognized_so_the_old_path_is_kept() -> None:
    staged = {
        "a": _staged("a", InputAssetFormat.POINT_CLOUD_PCD, "1", member_of="pkg"),
        "b": _staged("b", InputAssetFormat.TUM_TRAJECTORY, "2", member_of="pkg"),
    }
    assert is_user_supplied_package(staged, ["a", "b"])
    staged["c"] = _staged("c", InputAssetFormat.POINT_CLOUD_PCD, "3", member_of="other")
    assert not is_user_supplied_package(staged, ["a", "c"])  # nhiều ZIP: phải đóng lại
    loose = {"x": _staged("x", InputAssetFormat.POINT_CLOUD_PCD, "4")}
    assert not is_user_supplied_package(loose, ["x"])
