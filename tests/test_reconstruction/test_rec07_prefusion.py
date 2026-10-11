"""Unit và contract tests cho REC-07 TorWIC LiDAR prefusion offline tool."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.torwic.prefusion_inputs import checksum, validate_inputs
from scripts.torwic.prefusion_models import (
    PrefusionRequest,
    PrefusionSettings,
    ScanSource,
    SourceFile,
    safe_relative,
)
from src.models.contracts.reconstruction import DependencyOrigin


def _hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


_DUMMY_HASH = "sha256:" + "a" * 64


def test_safe_relative_path_traversal() -> None:
    """Chặn path traversal, absolute path, empty hoặc backslash."""
    for bad in ("../secret.txt", "/etc/passwd", "a/../b", "a//b", "a\\b", ""):
        with pytest.raises(ValueError):
            safe_relative(bad)
    assert safe_relative("valid/relative/path.pcd") == "valid/relative/path.pcd"


def test_scan_source_frame_id_mismatch() -> None:
    """Frame ID bắt buộc phải khớp với tên file 6 chữ số."""
    with pytest.raises(ValidationError):
        ScanSource(frame_id=1, relative_path="scans/000002.pcd", checksum=_DUMMY_HASH)

    valid = ScanSource(frame_id=1, relative_path="scans/000001.pcd", checksum=_DUMMY_HASH)
    assert valid.frame_id == 1


def test_prefusion_request_validation_rules() -> None:
    """Kiểm tra các ràng buộc schema của PrefusionRequest."""
    base_args = dict(
        traversal_id="aisle_cw",
        scans=[ScanSource(frame_id=0, relative_path="lidar/000000.pcd", checksum=_DUMMY_HASH)],
        trajectory=SourceFile(relative_path="traj.txt", checksum=_DUMMY_HASH),
        timestamps=SourceFile(relative_path="timestamps.txt", checksum=_DUMMY_HASH),
        calibration=SourceFile(relative_path="calibrations.txt", checksum=_DUMMY_HASH),
        coordinate_evidence=SourceFile(relative_path="coordinates.json", checksum=_DUMMY_HASH),
        pose_origin=DependencyOrigin.ESTIMATED,
        allow_ground_truth_poses=False,
        source_frame="os_sensor",
        target_frame="world",
        unit="meter",
        transform_semantics="target_from_source",
        timestamp_tolerance_s=0.05,
        quaternion_norm_tolerance=0.001,
        min_range_m=0.5,
        max_range_m=50.0,
        max_scan_points=10000,
        max_merged_points=20000,
    )

    # 1. Trajectory là traj_gt.txt nhưng khai báo không phải ground_truth
    with pytest.raises(ValidationError):
        bad = base_args.copy()
        bad["trajectory"] = SourceFile(relative_path="traj_gt.txt", checksum=_DUMMY_HASH)
        PrefusionRequest.model_validate(bad)

    # 2. pose_origin là ground_truth nhưng allow_ground_truth_poses là False
    with pytest.raises(ValidationError):
        bad = base_args.copy()
        bad["pose_origin"] = DependencyOrigin.GROUND_TRUTH
        bad["allow_ground_truth_poses"] = False
        PrefusionRequest.model_validate(bad)

    # 3. Source frame và Target frame trùng nhau
    with pytest.raises(ValidationError):
        bad = base_args.copy()
        bad["target_frame"] = "os_sensor"
        PrefusionRequest.model_validate(bad)

    # 4. max_range_m <= min_range_m
    with pytest.raises(ValidationError):
        bad = base_args.copy()
        bad["max_range_m"] = 0.4
        PrefusionRequest.model_validate(bad)

    # 5. Dùng file cấm groundtruth_map.ply
    with pytest.raises(ValidationError):
        bad = base_args.copy()
        bad["calibration"] = SourceFile(relative_path="groundtruth_map.ply", checksum=_DUMMY_HASH)
        PrefusionRequest.model_validate(bad)


def test_prefusion_settings_output_boundary(tmp_path: Path) -> None:
    """Output relative bắt buộc phải nằm dưới derived/."""
    with pytest.raises(ValidationError):
        PrefusionSettings(dataset_root=tmp_path, output_relative="outside/attempt_01")
    valid = PrefusionSettings(dataset_root=tmp_path, output_relative="derived/attempt_01")
    assert valid.output_relative == "derived/attempt_01"


def _create_mock_dataset(root: Path) -> tuple[PrefusionRequest, dict[str, str]]:
    """Tạo bộ dữ liệu nhỏ chuẩn để kiểm thử resolve và validate."""
    pcd_content = b"""# .PCD v0.7 - Point Cloud Data file format
VERSION 0.7
FIELDS x y z
SIZE 4 4 4
TYPE F F F
COUNT 1 1 1
WIDTH 3
HEIGHT 1
VIEWPOINT 0 0 0 1 0 0 0
POINTS 3
DATA ascii
0.0 0.0 1.0
0.5 0.5 1.5
1.0 1.0 2.0
"""
    (root / "lidar").mkdir(parents=True, exist_ok=True)
    pcd0 = root / "lidar/000000.pcd"
    pcd1 = root / "lidar/000001.pcd"
    pcd0.write_bytes(pcd_content)
    pcd1.write_bytes(pcd_content)

    traj_content = "100.0 0.0 0.0 0.0 0.0 0.0 0.0 1.0\n100.1 0.1 0.0 0.0 0.0 0.0 0.0 1.0\n"
    traj_path = root / "traj.txt"
    traj_path.write_text(traj_content)

    times_content = "100.0\n100.1\n"
    times_path = root / "timestamps.txt"
    times_path.write_text(times_content)

    calib_content = "T_cam1_os: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]\n"
    calib_path = root / "calibrations.txt"
    calib_path.write_text(calib_content)

    coord_content = json.dumps({"source_frame_hypothesis": "os_sensor"})
    coord_path = root / "coordinates.json"
    coord_path.write_text(coord_content)

    hashes = {
        "pcd0": checksum(pcd0),
        "pcd1": checksum(pcd1),
        "traj": checksum(traj_path),
        "times": checksum(times_path),
        "calib": checksum(calib_path),
        "coord": checksum(coord_path),
    }

    request = PrefusionRequest(
        traversal_id="aisle_cw",
        scans=[
            ScanSource(frame_id=0, relative_path="lidar/000000.pcd", checksum=hashes["pcd0"]),
            ScanSource(frame_id=1, relative_path="lidar/000001.pcd", checksum=hashes["pcd1"]),
        ],
        trajectory=SourceFile(relative_path="traj.txt", checksum=hashes["traj"]),
        timestamps=SourceFile(relative_path="timestamps.txt", checksum=hashes["times"]),
        calibration=SourceFile(relative_path="calibrations.txt", checksum=hashes["calib"]),
        coordinate_evidence=SourceFile(relative_path="coordinates.json", checksum=hashes["coord"]),
        pose_origin=DependencyOrigin.ESTIMATED,
        allow_ground_truth_poses=False,
        source_frame="os_sensor",
        target_frame="world",
        unit="meter",
        transform_semantics="target_from_source",
        timestamp_tolerance_s=0.05,
        quaternion_norm_tolerance=0.001,
        min_range_m=0.5,
        max_range_m=50.0,
        max_scan_points=1000,
        max_merged_points=2000,
    )
    return request, hashes


def test_validate_inputs_success_and_tamper_rejection(tmp_path: Path) -> None:
    """Validate inputs trả về dict ScanPose và chặn file bị sửa đổi."""
    request, hashes = _create_mock_dataset(tmp_path)
    poses = validate_inputs(tmp_path, request)
    assert len(poses) == 2
    assert poses[0].timestamp == 100.0
    assert poses[1].timestamp == 100.1

    # Thử sửa nội dung file trajectory để kiểm tra phát hiện checksum sai
    (tmp_path / "traj.txt").write_text("tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_inputs(tmp_path, request)


def test_validate_inputs_unnormalized_quaternion(tmp_path: Path) -> None:
    """Chặn pose có quaternion chưa chuẩn hóa vượt ngưỡng tolerance."""
    request, hashes = _create_mock_dataset(tmp_path)
    # Quaternion có norm = sqrt(1.5^2) = 1.5 (lệch nhiều hơn tolerance 0.001)
    (tmp_path / "traj.txt").write_text("100.0 0.0 0.0 0.0 0.0 0.0 0.0 1.5\n100.1 0.1 0.0 0.0 0.0 0.0 0.0 1.0\n")
    # Cập nhật checksum mới
    req_dict = request.model_dump()
    req_dict["trajectory"]["checksum"] = checksum(tmp_path / "traj.txt")
    new_request = PrefusionRequest.model_validate(req_dict)

    with pytest.raises(ValueError, match="not normalized"):
        validate_inputs(tmp_path, new_request)


def test_validate_inputs_desynchronized_timestamps(tmp_path: Path) -> None:
    """Chặn khi timestamp của pose và scan lệch quá timestamp_tolerance_s."""
    request, hashes = _create_mock_dataset(tmp_path)
    # timestamps = 100.0, 100.2 (lệch 0.1s so với pose 100.1, vượt tolerance 0.05s)
    (tmp_path / "timestamps.txt").write_text("100.0\n100.2\n")
    req_dict = request.model_dump()
    req_dict["timestamps"]["checksum"] = checksum(tmp_path / "timestamps.txt")
    new_request = PrefusionRequest.model_validate(req_dict)

    with pytest.raises(ValueError, match="not synchronized"):
        validate_inputs(tmp_path, new_request)


def test_cli_prefusion_e2e_execution(tmp_path: Path) -> None:
    """Thực thi CLI build_registered_lidar.py với python runtime của REC-07."""
    py_runtime = Path("data/rec07_runtime/bin/python").absolute()
    if not py_runtime.is_file():
        pytest.skip("data/rec07_runtime chưa được provision")

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    request, hashes = _create_mock_dataset(dataset_root)

    request_file = tmp_path / "request.json"
    request_file.write_text(request.model_dump_json(indent=2))

    cmd = [
        str(py_runtime),
        "scripts/torwic/build_registered_lidar.py",
        "--dataset-root",
        str(dataset_root),
        "--request",
        str(request_file),
        "--output-relative",
        "derived/test_prefusion_01",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=dict(os.environ, REC07_DEBUG="1"))
    assert result.returncode == 0, f"CLI error: {result.stderr}\n{result.stdout}"

    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "SUCCEEDED"
    assert "manifest_checksum" in payload
    assert payload["point_count"] > 0

    # Kiểm tra các file đầu ra
    target_dir = dataset_root / "derived/test_prefusion_01"
    ply_file = target_dir / "registered_lidar.ply"
    manifest_file = target_dir / "preparation_manifest.json"

    assert ply_file.is_file()
    assert manifest_file.is_file()

    manifest = json.loads(manifest_file.read_text())
    assert manifest["artifact_type"] == "TorwicLiDARPreparation"
    assert manifest["trajectory_gt_used_for_lidar_prefusion"] is False
    assert manifest["output"]["checksum"] == checksum(ply_file)

    # Thử chạy lại vào cùng thư mục đích: bắt buộc fail để đảm bảo anti-overwrite
    rerun = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert rerun.returncode == 2
    err_payload = json.loads(rerun.stdout.strip())
    assert err_payload["status"] == "FAILED"


def test_prefusion_deterministic_output(tmp_path: Path) -> None:
    """Hai lần chạy độc lập với cùng input bắt buộc sinh ra byte PLY và checksum y hệt nhau."""
    py_runtime = Path("data/rec07_runtime/bin/python").absolute()
    if not py_runtime.is_file():
        pytest.skip("data/rec07_runtime chưa được provision")

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    request, hashes = _create_mock_dataset(dataset_root)

    request_file = tmp_path / "request.json"
    request_file.write_text(request.model_dump_json(indent=2))

    for attempt in ("attempt_01", "attempt_02"):
        cmd = [
            str(py_runtime),
            "scripts/torwic/build_registered_lidar.py",
            "--dataset-root",
            str(dataset_root),
            "--request",
            str(request_file),
            "--output-relative",
            f"derived/{attempt}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert res.returncode == 0

    ply1 = dataset_root / "derived/attempt_01/registered_lidar.ply"
    ply2 = dataset_root / "derived/attempt_02/registered_lidar.ply"
    assert checksum(ply1) == checksum(ply2)
    assert ply1.read_bytes() == ply2.read_bytes()
