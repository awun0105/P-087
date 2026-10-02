"""ADR 0001 §2 — AI Auto-Scale Assist: toán thuần của projector, scale aligner và đề xuất sàn."""

from pathlib import Path

import numpy as np
import pytest

from src.services.reconstruction.rgb.canonical.auto_scale import (
    MIN_FRAMES,
    align_scale,
    propose_floor,
    read_sparse,
    rotation_matrix,
    sparse_samples,
)
from src.services.reconstruction.rgb.pose.camera_pose import CameraPose

TRUE_SCALE = 0.4  # mét cho mỗi đơn vị SfM


def _pose(frame_id: int, x: float) -> CameraPose:
    """Camera nhìn dọc +z của SfM, không xoay (trục y camera = y SfM = hướng xuống)."""
    return CameraPose(
        frame_id=frame_id,
        image_id=frame_id + 1,
        camera_id=1,
        image_name=f"{frame_id:06d}.png",
        translation=(x, 0.0, 0.0),
        rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
    )


def _write_sparse(tmp_path: Path, points: np.ndarray, poses: list[CameraPose]) -> tuple[Path, Path]:
    points_path, images_path = tmp_path / "points3D.txt", tmp_path / "images.txt"
    lines = ["# 3D point list"]
    for index, (x, y, z) in enumerate(points, start=1):
        lines.append(f"{index} {x} {y} {z} 10 20 30 0.5 1 0 2 0")
    points_path.write_text("\n".join(lines) + "\n")
    rows = ["# Image list", "#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME"]
    for pose in poses:
        rows.append(f"{pose.image_id} 1 0 0 0 0 0 0 1 {pose.image_name}")
        keypoints = " ".join(f"{10 + i} {20 + i} {i + 1}" for i in range(len(points)))
        rows.append(keypoints + " 5 5 -1 6 6 999999")  # điểm không có 3D và id lạ phải bị bỏ
    images_path.write_text("\n".join(rows) + "\n")
    return points_path, images_path


def test_rotation_matrix_matches_parent_from_local_convention() -> None:
    half = np.sqrt(0.5)
    turn = rotation_matrix((0.0, half, 0.0, half))  # xoay 90° quanh y
    assert np.allclose(turn @ np.array([0, 0, 1]), [1, 0, 0])
    assert np.allclose(rotation_matrix((0, 0, 0, 1)), np.eye(3))


def test_projector_reads_observed_pixels_and_camera_depth(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    points = np.column_stack([rng.uniform(-2, 2, 40), rng.uniform(-1, 1, 40), rng.uniform(3, 9, 40)])
    points[0, 2] = -1.0  # sau lưng camera: không có độ sâu hợp lệ
    poses = [_pose(i, 0.5 * i) for i in range(6)]
    sparse = read_sparse(*_write_sparse(tmp_path, points, poses))
    assert len(sparse.points) == 40 and len(sparse.observations[1]) == 40
    samples = sparse_samples(poses, sparse, max_frames=3, max_points=20)
    assert [item.frame_id for item in samples] == [0, 2, 4]  # chọn đều theo thứ tự quay, tất định
    first = samples[0]
    assert len(first.depth_sfm) == 19 and (first.depth_sfm > 0).all()  # 20 điểm trừ điểm sau lưng
    assert np.allclose(first.depth_sfm, first.points[:, 2])  # camera ở gốc, không xoay
    shifted = samples[1]
    assert np.allclose(shifted.depth_sfm, shifted.points[:, 2])  # dời ngang không đổi độ sâu
    assert first.pixels[0].tolist() == [12.0, 22.0]  # pixel lấy từ images.txt, không tự chiếu
    assert (
        sparse_samples(poses, read_sparse(*_write_sparse(tmp_path, points[:5], poses)), max_frames=3, max_points=20)
        == []
    )


def _pairs(frames: int, scale: float, noise: float, seed: int = 1) -> list[tuple[np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(seed)
    result = []
    for _ in range(frames):
        depth = rng.uniform(1, 10, 200)
        result.append((depth, depth * scale * rng.normal(1.0, noise, 200)))
    return result


def test_scale_only_alignment_recovers_scale_and_reports_spread() -> None:
    estimate = align_scale(_pairs(12, TRUE_SCALE, 0.03))
    assert estimate is not None and estimate.frames_used == 12 and estimate.pairs_used == 2400
    assert estimate.scale_m_per_sfm_unit == pytest.approx(TRUE_SCALE, rel=0.01)
    assert estimate.dispersion < 0.02


def test_frames_guessed_badly_do_not_drag_the_scale() -> None:
    pairs = _pairs(9, TRUE_SCALE, 0.02) + _pairs(3, TRUE_SCALE * 3, 0.02, seed=7)
    estimate = align_scale(pairs)
    assert estimate is not None and estimate.scale_m_per_sfm_unit == pytest.approx(TRUE_SCALE, rel=0.02)


def test_alignment_has_no_offset_term() -> None:
    """Độ sâu mét lệch một hằng số cộng (z·s + b) không được hấp thụ: tỉ lệ ra khác và phân tán tăng."""
    rng = np.random.default_rng(3)
    pairs = []
    for _ in range(8):
        depth = rng.uniform(1, 10, 200)
        pairs.append((depth, depth * TRUE_SCALE + 1.0))
    estimate = align_scale(pairs)
    assert estimate is not None and estimate.scale_m_per_sfm_unit > TRUE_SCALE * 1.2


def test_too_little_evidence_gives_no_scale() -> None:
    assert align_scale([]) is None
    assert align_scale(_pairs(MIN_FRAMES - 1, TRUE_SCALE, 0.01)) is None
    few = [(depth[:5], metric[:5]) for depth, metric in _pairs(10, TRUE_SCALE, 0.01)]
    assert align_scale(few) is None
    bad = [(depth, np.full_like(metric, np.nan)) for depth, metric in _pairs(10, TRUE_SCALE, 0.01)]
    assert align_scale(bad) is None
    negative = [(depth, -metric) for depth, metric in _pairs(10, TRUE_SCALE, 0.01)]
    assert align_scale(negative) is None


def _room(seed: int = 5) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Phòng trong hệ SfM, y hướng xuống: sàn y = 2,5; mặt kệ y = 1,0 (ít điểm hơn); tường; trần y = −3."""
    rng = np.random.default_rng(seed)
    floor = np.column_stack([rng.uniform(-5, 5, 400), 2.5 + rng.normal(0, 0.01, 400), rng.uniform(0, 20, 400)])
    shelf = np.column_stack([rng.uniform(2, 3, 80), np.full(80, 1.0), rng.uniform(5, 8, 80)])
    ceiling = np.column_stack([rng.uniform(-5, 5, 500), np.full(500, -3.0), rng.uniform(0, 20, 500)])
    wall = np.column_stack([np.full(300, 5.0), rng.uniform(-3, 2.5, 300), rng.uniform(0, 20, 300)])
    points = np.vstack([floor, shelf, ceiling, wall])
    up, side = np.array([0.0, -1.0, 0.0]), np.array([-1.0, 0.0, 0.0])
    normals = np.vstack([np.tile(up, (400, 1)), np.tile(up, (80, 1)), np.tile(-up, (500, 1)), np.tile(side, (300, 1))])
    normals += rng.normal(0, 0.05, normals.shape)
    cameras = np.column_stack([np.zeros(10), np.zeros(10), np.linspace(0, 18, 10)])
    return points, normals, cameras, np.array([0.05, 1.0, 0.02])  # hướng xuống ước lượng, hơi lệch


def test_floor_is_the_densest_horizontal_layer_below_the_cameras() -> None:
    points, normals, cameras, down = _room()
    floor = propose_floor(points, normals, cameras, down, TRUE_SCALE)
    assert floor is not None and floor.support_points > 300
    for point in (*floor.floor_points, *floor.segment_ab, *floor.segment_cd):
        assert point[1] == pytest.approx(2.5, abs=0.03)  # trên sàn, không phải mặt kệ hay trần
    assert floor.residual_m < 0.02
    ab = np.linalg.norm(floor.segment_ab[1] - floor.segment_ab[0]) * TRUE_SCALE
    cd = np.linalg.norm(floor.segment_cd[1] - floor.segment_cd[0]) * TRUE_SCALE
    assert ab > 6 and cd > 3  # hai đoạn dài, theo hai trục khác nhau của sàn
    direction_ab = floor.segment_ab[1] - floor.segment_ab[0]
    direction_cd = floor.segment_cd[1] - floor.segment_cd[0]
    cosine = abs(direction_ab @ direction_cd) / (np.linalg.norm(direction_ab) * np.linalg.norm(direction_cd))
    assert cosine < 0.5
    # Ba điểm sàn không thẳng hàng.
    p1, p2, p3 = floor.floor_points
    assert np.linalg.norm(np.cross(p2 - p1, p3 - p1)) > 1.0


def test_no_floor_is_proposed_without_enough_horizontal_points() -> None:
    points, normals, cameras, down = _room()
    walls_only = slice(980, 1280)
    assert propose_floor(points[walls_only], normals[walls_only], cameras, down, TRUE_SCALE) is None
    assert propose_floor(points[:10], normals[:10], cameras, down, TRUE_SCALE) is None
    assert propose_floor(np.empty((0, 3)), np.empty((0, 3)), cameras, down, TRUE_SCALE) is None
    ceiling_only = slice(480, 980)  # mặt ngang nhưng ở trên camera
    assert propose_floor(points[ceiling_only], normals[ceiling_only], cameras, down, TRUE_SCALE) is None
    assert propose_floor(points, normals, cameras, down, 0.0) is None


def test_projector_handles_rotated_cameras(tmp_path: Path) -> None:
    """Camera xoay 90° quanh y: trục nhìn của nó là +x của SfM, nên độ sâu là toạ độ x của điểm."""
    rng = np.random.default_rng(2)
    points = np.column_stack([rng.uniform(3, 9, 30), rng.uniform(-1, 1, 30), rng.uniform(-2, 2, 30)])
    half = float(np.sqrt(0.5))
    pose = CameraPose(
        frame_id=0, image_id=1, camera_id=1, image_name="000000.png", translation=(1.0, 0.0, 0.0),
        rotation_xyzw=(0.0, half, 0.0, half),
    )  # fmt: skip
    sparse = read_sparse(*_write_sparse(tmp_path, points, [pose]))
    sample = sparse_samples([pose], sparse, max_frames=5, max_points=100)[0]
    assert np.allclose(sample.depth_sfm, sample.points[:, 0] - 1.0)
    assert np.allclose(sample.rotation @ np.array([0, 0, 1]), [1, 0, 0])


def test_floor_that_is_only_a_thin_strip_is_not_proposed() -> None:
    """Điểm sàn nằm gần như trên một đường thẳng: ba điểm sàn sẽ thẳng hàng, REC-06 không dựng được khung."""
    rng = np.random.default_rng(9)
    strip = np.column_stack([rng.uniform(-5, 5, 200), np.full(200, 2.5), np.full(200, 4.0)])
    normals = np.tile([0.0, -1.0, 0.0], (200, 1))
    cameras = np.zeros((4, 3))
    assert propose_floor(strip, normals, cameras, np.array([0.0, 1.0, 0.0]), TRUE_SCALE) is None
