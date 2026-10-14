"""Nhận gói LiDAR (ADR 0009): hai dạng gói ra cùng một loại artifact, provenance đúng nguồn gốc quỹ đạo."""

import zipfile
from pathlib import Path

import numpy as np
import pytest

from src.models.contracts.reconstruction import LiDARGeometryArtifact
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.inputs.detect import detect_input
from src.services.reconstruction.lidar.fusion import ply_bytes
from src.services.reconstruction.lidar.package import (
    LidarPackageError,
    LidarPackageIngest,
    LidarPackageRecord,
    parse_calibration,
    parse_camera,
)

LIMIT = 10**9
POSES = 6
SENSOR_HEIGHT = 1.2
CALIBRATION = "T_cam1_os.px: 0.1\nT_cam1_os.py: 0.0\nT_cam1_os.pz: -0.1\nT_cam1_os.qx: 0\nT_cam1_os.qy: 0\nT_cam1_os.qz: 0\nT_cam1_os.qw: 1\n"


def _pcd(points: np.ndarray) -> bytes:
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
        f"COUNT 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA binary\n"
    )
    return header.encode() + points.astype("<f4").tobytes()


def _scan() -> np.ndarray:
    """Một lần quét trong hệ cảm biến: mảng sàn nằm dưới cảm biến SENSOR_HEIGHT mét và một bức tường phía trước."""
    grid = np.stack(np.meshgrid(np.arange(-2.5, 2.5, 0.05), np.arange(-2.5, 2.5, 0.05)), axis=-1).reshape(-1, 2)
    floor = np.column_stack([grid, np.full(len(grid), -SENSOR_HEIGHT)])
    wall = np.column_stack([np.full(200, 4.0), np.linspace(-2, 2, 200), np.linspace(-1, 1, 200)])
    return np.concatenate([floor, wall])


def _companions() -> dict[str, bytes]:
    trajectory = "".join(f"{i * 0.1} {i * 0.5} 0 {SENSOR_HEIGHT - 0.25} 0 0 0 1\n" for i in range(POSES))
    return {
        "traj.txt": trajectory.encode(),
        "calibrations.txt": CALIBRATION.encode(),
        "frame_times.txt": "".join(f"{i * 0.1}\n" for i in range(POSES)).encode(),
    }


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


def _ingest(tmp_path: Path, package: Path, origin: str = "estimated") -> tuple[LidarPackageRecord, ArtifactResolver]:
    resolver = ArtifactResolver(tmp_path / "store")
    evidence = detect_input(package, LIMIT).lidar
    assert evidence is not None
    result = LidarPackageIngest(FilesystemArtifactStore(resolver)).ingest(
        package,
        evidence,
        "job-lidar",
        origin,  # type: ignore[arg-type]
        tmp_path / "work",
    )
    assert result.reference.schema_version == result.record.schema_version
    assert LidarPackageRecord.model_validate_json(resolver.require(result.reference).read_bytes()) == result.record
    return result.record, resolver


def test_scan_package_is_fused_and_floor_goes_to_zero(tmp_path: Path) -> None:
    scans = {f"lidar/{index:06d}.pcd": _pcd(_scan()) for index in range(POSES)}
    record, resolver = _ingest(tmp_path, _zip(tmp_path / "scans.zip", {**_companions(), **scans}))
    assert record.kind == "lidar_scan_sequence" and record.fusion is not None and record.fusion.scan_count == POSES
    # Sàn nằm dưới cảm biến SENSOR_HEIGHT; cảm biến ở z = SENSOR_HEIGHT − 0,25 → sàn ở z = −0,25 trong hệ quỹ đạo.
    assert record.floor_z_m == pytest.approx(-0.25, abs=0.02)
    metadata = LiDARGeometryArtifact.model_validate_json(resolver.require(record.lidar_metadata_ref).read_bytes())
    assert metadata.source_frame == "lidar_map"
    assert metadata.declared_transform_to_canonical is not None
    assert metadata.declared_transform_to_canonical.translation_xyz[2] == pytest.approx(0.25, abs=0.02)
    provenance = metadata.preprocessing_provenance
    assert provenance.ground_truth_assisted is False
    assert sum(1 for item in provenance.dependencies if item.role == "scan") == POSES
    assert record.sensor_from_camera.translation_xyz == (0.1, 0.0, -0.1)
    assert resolver.require(record.trajectory_ref).read_bytes() == _companions()["traj.txt"]
    assert record.calibration_ref is not None
    assert resolver.require(record.calibration_ref).read_bytes() == CALIBRATION.encode()
    assert record.schema_version == "1.1"

    # Old immutable record payloads did not include the calibration ref or distortion provenance.
    old_payload = record.model_dump(mode="json", exclude={"calibration_ref"})
    old_payload["schema_version"] = "1.0"
    if old_payload["camera"] is not None:
        old_payload["camera"].pop("distortion_status", None)
    old_record = LidarPackageRecord.model_validate(old_payload)
    assert old_record.calibration_ref is None


def test_registered_package_keeps_the_submitted_cloud_bytes(tmp_path: Path) -> None:
    cloud = _scan() + np.array([1.0, 0.0, SENSOR_HEIGHT - 0.25])
    payload = ply_bytes(cloud)
    record, resolver = _ingest(
        tmp_path, _zip(tmp_path / "reg.zip", {**_companions(), "map.ply": payload}), "ground_truth"
    )
    assert record.kind == "registered_lidar" and record.fusion is None
    assert resolver.require(record.lidar_geometry_ref).read_bytes() == payload  # không sửa bytes người dùng nộp
    metadata = LiDARGeometryArtifact.model_validate_json(resolver.require(record.lidar_metadata_ref).read_bytes())
    assert metadata.preprocessing_provenance.ground_truth_assisted is True
    assert record.trajectory_origin == "ground_truth"


def test_supplied_trajectory_is_sensor_input_not_ground_truth(tmp_path: Path) -> None:
    from src.models.contracts.reconstruction import DependencyOrigin

    scans = {f"lidar/{index:06d}.pcd": _pcd(_scan()) for index in range(POSES)}
    record, resolver = _ingest(tmp_path, _zip(tmp_path / "supplied.zip", {**_companions(), **scans}), "supplied")
    metadata = LiDARGeometryArtifact.model_validate_json(resolver.require(record.lidar_metadata_ref).read_bytes())

    assert record.trajectory_origin == "supplied"
    assert metadata.preprocessing_provenance.ground_truth_assisted is False
    pose = next(item for item in metadata.preprocessing_provenance.dependencies if item.role == "pose")
    assert pose.origin == DependencyOrigin.SENSOR_INPUT


def test_package_without_floor_under_trajectory_is_rejected(tmp_path: Path) -> None:
    """Quỹ đạo không thuộc đám mây (hoặc trục lên không phải Z): dừng với lý do rõ, không đoán sàn."""
    far = _scan() + np.array([500.0, 500.0, 0.0])
    package = _zip(tmp_path / "far.zip", {**_companions(), "map.ply": ply_bytes(far)})
    with pytest.raises(LidarPackageError, match="Không tìm thấy mặt sàn dưới quỹ đạo"):
        _ingest(tmp_path, package)


def test_calibration_formats_and_bad_values() -> None:
    assert parse_calibration(CALIBRATION, "torwic_txt").local_frame == "camera"
    json_text = '{"lidar_from_camera": {"translation_xyz": [0.1, 0, -0.1], "rotation_xyzw": [0, 0, 0, 1]}}'
    assert parse_calibration(json_text, "json") == parse_calibration(CALIBRATION, "torwic_txt")
    with pytest.raises(LidarPackageError, match="Calibration"):
        parse_calibration(CALIBRATION.replace("qw: 1", "qw: 3"), "torwic_txt")
    with pytest.raises(LidarPackageError, match="Calibration"):
        parse_calibration('{"lidar_from_camera": {"translation_xyz": [0, 0]}}', "json")


def test_camera_parser_preserves_distortion_availability_without_changing_legacy_values() -> None:
    intrinsics = (
        "Camera1.width: 640\nCamera1.height: 480\nCamera1.fx: 500\nCamera1.fy: 500\nCamera1.cx: 320\nCamera1.cy: 240\n"
    )
    missing = parse_camera(intrinsics, "torwic_txt")
    declared = parse_camera(intrinsics + "Camera1.D: [0, 0, 0, 0]\n", "torwic_txt")
    partial = parse_camera(intrinsics + "Camera1.D: [0.1, -0.02]\n", "torwic_txt")
    json_missing = parse_camera(
        '{"camera": {"width": 640, "height": 480, "fx": 500, "fy": 500, "cx": 320, "cy": 240}}',
        "json",
    )

    assert missing is not None and missing.distortion == (0.0, 0.0, 0.0, 0.0)
    assert missing.distortion_status == "missing"
    assert declared is not None and declared.distortion_status == "declared"
    assert partial is not None and partial.distortion_status == "partial"
    assert json_missing is not None and json_missing.distortion_status == "missing"
