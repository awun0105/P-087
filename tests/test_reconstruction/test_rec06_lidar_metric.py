"""Tỉ lệ mét và sàn từ gói LiDAR (ADR 0009): đề xuất `lidar_trajectory_alignment` đi qua REC-06 mà không ai chọn điểm."""

import io
import math
import zipfile
from pathlib import Path

import numpy as np
import pytest

from src.services.orchestration.artifacts import ArtifactNotFoundError
from src.services.reconstruction.inputs.detect import detect_input
from src.services.reconstruction.lidar.fusion import ply_bytes
from src.services.reconstruction.lidar.metric import propose_metric_from_lidar
from src.services.reconstruction.lidar.package import LidarPackageIngest
from src.services.reconstruction.metric_port import UserMetricInput
from src.services.reconstruction.metric_proposal import load_proposal
from tests.test_reconstruction.test_rec06_user_metric_port import JOB, _world

CAMERA_HEIGHT = 1.0
CALIBRATION = "".join(
    f"T_cam1_os.{key}: {value}\n"
    for key, value in zip("px py pz qx qy qz qw".split(), "0 0 0 0 0 0 1".split(), strict=True)
)


def _setup(tmp_path: Path, shift: tuple[float, float, float] = (0.0, 0.0, 0.0)):  # noqa: ANN202
    """Scene fixture REC-03/04 + gói LiDAR có quỹ đạo trùng tâm camera (lệch thêm `shift`) và sàn dưới camera 1 m."""
    port, visual, _, resolver, writer = _world(tmp_path)
    store_root = tmp_path / "store"
    frames = resolver.poses.frames

    def resolve(reference):  # noqa: ANN001, ANN202 - frame set của fixture nằm ở store riêng
        try:
            return resolver.resolve(reference)
        except ArtifactNotFoundError:
            return frames._resolve(reference)

    def locate(uri: str) -> Path | None:
        path = store_root / uri.removeprefix("artifact://")
        return path if path.is_file() else None

    poses = resolver.poses.load(visual.artifact.source_camera_poses).poses
    by_frame = {pose.frame_id: np.asarray(pose.translation) + np.asarray(shift) for pose in poses}
    last = max(by_frame)
    # Quỹ đạo có một dòng cho mỗi frame gốc của video; frame không dựng được vẫn có pose (nội suy tuyến tính).
    lines = []
    for index in range(last + 1):
        point = by_frame.get(index, by_frame[min(by_frame, key=lambda key: abs(key - index))])
        lines.append(f"{index * 0.1} {point[0]} {point[1]} {point[2]} 0 0 0 1\n")
    floor_z = min(point[2] for point in by_frame.values()) - CAMERA_HEIGHT
    centre = np.mean(list(by_frame.values()), axis=0)
    grid = np.stack(np.meshgrid(np.arange(-6, 6, 0.05), np.arange(-6, 6, 0.05)), axis=-1).reshape(-1, 2)
    cloud = np.column_stack([grid + centre[:2], np.full(len(grid), floor_z)])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("map.ply", ply_bytes(cloud))
        archive.writestr("traj.txt", "".join(lines))
        archive.writestr("calibrations.txt", CALIBRATION)
        archive.writestr("frame_times.txt", "".join(f"{index * 0.1}\n" for index in range(last + 1)))
    package = tmp_path / "lidar.zip"
    package.write_bytes(buffer.getvalue())
    evidence = detect_input(package, 10**9).lidar
    assert evidence is not None
    record = LidarPackageIngest(writer).ingest(package, evidence, JOB, "estimated", tmp_path / "lidar-work")
    arguments = (JOB, visual.reference, record.reference, resolve, writer, locate)
    return arguments, port, visual, locate, floor_z, len(poses)


def test_proposal_takes_scale_and_floor_from_the_lidar_package(tmp_path: Path) -> None:
    arguments, _, visual, locate, floor_z, registered = _setup(tmp_path)
    reference = propose_metric_from_lidar(*arguments)
    proposal = load_proposal(JOB, visual.reference, locate)
    assert proposal is not None and proposal.method == "lidar_trajectory_alignment"
    assert proposal.scale_m_per_sfm_unit == pytest.approx(1.0)  # scene đã ở hệ mét của quỹ đạo
    alignment = proposal.alignment
    assert alignment is not None and alignment.registered_frames == registered
    assert alignment.offset_max_m == pytest.approx(0.0, abs=1e-9) and alignment.trajectory_origin == "estimated"
    assert proposal.floor is not None and proposal.segments is not None
    assert {round(point[2], 6) for point in proposal.floor.points} == {round(floor_z, 6)}
    assert proposal.segments.distance_m == pytest.approx(2.0) and proposal.segments.check_distance_m == pytest.approx(
        1.5
    )
    assert propose_metric_from_lidar(*arguments) == reference  # gọi lại trả đúng artifact đã có


def test_lidar_proposal_confirms_without_any_user_point(tmp_path: Path) -> None:
    """Đưa nguyên đề xuất vào REC-06: tỉ lệ 1, camera cao đúng 1 m trên sàn LiDAR, đoạn kiểm khớp."""
    arguments, port, visual, locate, _, _ = _setup(tmp_path)
    propose_metric_from_lidar(*arguments)
    port.locate = locate
    proposal = port.auto_proposal(JOB, visual.reference)
    assert proposal is not None and proposal.floor is not None and proposal.segments is not None
    segments = proposal.segments
    data = UserMetricInput(
        floor_points=proposal.floor.points,
        point_a=segments.point_a,
        point_b=segments.point_b,
        distance_m=segments.distance_m,
        check_a=segments.check_a,
        check_b=segments.check_b,
        check_distance_m=segments.check_distance_m,
        distance_source="lidar_trajectory",
    )
    summary = port.preview(JOB, visual.reference, data)
    assert summary.scale_m_per_sfm_unit == pytest.approx(1.0) and summary.check_passed
    assert summary.camera_height_min_m == pytest.approx(CAMERA_HEIGHT, abs=0.03)
    assert summary.distance_source == "lidar_trajectory"
    # Không cho gắn nhãn ước lượng của mô hình đoán độ sâu lên đề xuất từ LiDAR, và số tự nghĩ ra bị từ chối.
    with pytest.raises(ValueError, match="không khớp loại đề xuất"):
        port.preview(JOB, visual.reference, data.model_copy(update={"distance_source": "ai_estimated"}))
    with pytest.raises(ValueError, match="không khớp đề xuất"):
        port.preview(JOB, visual.reference, data.model_copy(update={"distance_m": segments.distance_m * 1.2}))


def test_offset_between_poses_and_trajectory_is_reported(tmp_path: Path) -> None:
    """Quỹ đạo lệch pose cuối 0,3 m: đề xuất vẫn có, nhưng độ lệch hiện ra để người dùng quyết định."""
    arguments, _, visual, locate, _, _ = _setup(tmp_path, shift=(0.0, 0.3, 0.0))
    propose_metric_from_lidar(*arguments)
    proposal = load_proposal(JOB, visual.reference, locate)
    assert proposal is not None and proposal.alignment is not None
    assert proposal.alignment.offset_median_m == pytest.approx(0.3)
    assert proposal.alignment.path_length_m > 0 and proposal.relative_uncertainty > 0
    assert math.isfinite(proposal.scale_m_per_sfm_unit)
