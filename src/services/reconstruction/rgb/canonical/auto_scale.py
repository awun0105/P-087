"""Đề xuất tỉ lệ mét và mặt sàn từ video RGB (ADR 0001 §2, AI Auto-Scale Assist).

Ba phần theo ADR, đều là toán thuần (numpy), không gọi mô hình:

- `sparse_samples` — *ColmapSparseDepthProjector*: với mỗi ảnh, lấy các điểm thưa COLMAP đã
  quan sát được ở ảnh đó (vị trí pixel đọc thẳng từ `images.txt`, không tự chiếu lại nên không
  phụ thuộc mô hình méo ống kính) cùng độ sâu của chúng trong hệ camera, đơn vị SfM.
- `align_scale` — *RobustScaleAligner*: chỉ giải **một hệ số tỉ lệ** `z_mét ≈ s · z_sfm`, không
  có hệ số dịch (ADR đã từ chối `s·z + b` vì phá phép đồng dạng của cả scene).
- `propose_floor` — mặt sàn từ các điểm có pháp tuyến hướng lên (bổ sung theo quyết định owner
  02/10/2026): thay ba điểm sàn người dùng phải tự chọn bằng một đề xuất.

Độ sâu mét và pháp tuyến do mô hình đoán (MoGe-2) nên mọi kết quả ở đây là **ước lượng**, luôn
kèm độ phân tán; người dùng vẫn phải xác nhận ở REC-06.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.services.reconstruction.rgb.pose.camera_pose import CameraPose

#: Số cặp tối thiểu để một ảnh được tính: ít hơn thì trung vị của ảnh đó không đáng tin.
MIN_PAIRS_PER_FRAME = 20
#: Số ảnh tối thiểu có đủ cặp để công bố một tỉ lệ.
MIN_FRAMES = 3
#: Điểm được coi là nằm trên mặt ngang khi pháp tuyến lệch hướng lên không quá góc này.
FLOOR_NORMAL_MAX_DEGREES = 25.0
#: Bề dày lớp điểm sàn (mét) khi gom điểm theo độ cao; cỡ nhiễu của điểm thưa trên sàn kho.
FLOOR_LAYER_M = 0.05
#: Số điểm tối thiểu trên lớp sàn để công bố mặt sàn.
MIN_FLOOR_POINTS = 30
_RANSAC_ITERATIONS = 300


@dataclass(frozen=True)
class SparseModel:
    """Điểm thưa và quan sát của COLMAP: `points[id] = xyz`, `observations[image_id] = (u, v, id)`."""

    points: dict[int, tuple[float, float, float]]
    observations: dict[int, list[tuple[float, float, int]]]


def read_sparse(points_path: Path, images_path: Path) -> SparseModel:
    """Đọc `points3D.txt` và `images.txt` (định dạng text của COLMAP)."""
    points: dict[int, tuple[float, float, float]] = {}
    with points_path.open(encoding="utf-8") as stream:
        for line in stream:
            fields = line.split()
            if not fields or fields[0].startswith("#") or len(fields) < 8:
                continue
            points[int(fields[0])] = (float(fields[1]), float(fields[2]), float(fields[3]))
    observations: dict[int, list[tuple[float, float, int]]] = {}
    with images_path.open(encoding="utf-8") as stream:
        rows = [line for line in stream if not line.startswith("#")]
    # Mỗi ảnh hai dòng: header (IMAGE_ID … NAME) rồi POINTS2D[] là các bộ (X, Y, POINT3D_ID).
    for header, keypoints in zip(rows[0::2], rows[1::2], strict=False):
        image_id = int(header.split()[0])
        values = keypoints.split()
        seen = []
        for index in range(0, len(values) - 2, 3):
            point_id = int(values[index + 2])
            if point_id in points:
                seen.append((float(values[index]), float(values[index + 1]), point_id))
        observations[image_id] = seen
    return SparseModel(points=points, observations=observations)


def rotation_matrix(rotation_xyzw: Sequence[float]) -> np.ndarray:
    """Ma trận xoay của quaternion xyzw (parent_from_local: p_world = R · p_camera + t)."""
    x, y, z, w = rotation_xyzw
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


@dataclass(frozen=True)
class FrameSamples:
    """Các điểm thưa một ảnh nhìn thấy: pixel, toạ độ SfM và độ sâu trong hệ camera (đơn vị SfM)."""

    frame_id: int
    pixels: np.ndarray  # (N, 2) toạ độ ảnh gốc
    points: np.ndarray  # (N, 3) hệ SfM
    depth_sfm: np.ndarray  # (N,)
    rotation: np.ndarray  # (3, 3) camera → SfM


def sparse_samples(
    poses: Sequence[CameraPose], sparse: SparseModel, *, max_frames: int, max_points: int
) -> list[FrameSamples]:
    """ColmapSparseDepthProjector: chọn đều `max_frames` ảnh, mỗi ảnh tối đa `max_points` điểm đã quan sát.

    Chọn đều theo thứ tự quay để các ảnh phủ cả đường đi; lấy điểm cách đều trong danh sách quan sát
    (tất định, không ngẫu nhiên) để hai lần chạy cho cùng kết quả.
    """
    usable = [pose for pose in poses if len(sparse.observations.get(pose.image_id, ())) >= MIN_PAIRS_PER_FRAME]
    if not usable:
        return []
    step = max(1, len(usable) // max_frames) if max_frames > 0 else 1
    samples = []
    for pose in usable[::step][:max_frames]:
        seen = sparse.observations[pose.image_id]
        stride = max(1, len(seen) // max_points)
        seen = seen[::stride][:max_points]
        points = np.array([sparse.points[point_id] for _, _, point_id in seen])
        rotation = rotation_matrix(pose.rotation_xyzw)
        camera = (points - np.array(pose.translation)) @ rotation  # R^T (p − t) cho từng hàng
        keep = camera[:, 2] > 0
        samples.append(
            FrameSamples(
                frame_id=pose.frame_id,
                pixels=np.array([[u, v] for u, v, _ in seen])[keep],
                points=points[keep],
                depth_sfm=camera[keep, 2],
                rotation=rotation,
            )
        )
    return samples


@dataclass(frozen=True)
class ScaleEstimate:
    """Tỉ lệ mét/đơn vị SfM và độ tin: độ phân tán tương đối giữa các ảnh (1,4826·MAD/trung vị)."""

    scale_m_per_sfm_unit: float
    dispersion: float
    frames_used: int
    pairs_used: int


def align_scale(pairs: Sequence[tuple[np.ndarray, np.ndarray]]) -> ScaleEstimate | None:
    """RobustScaleAligner: trung vị của trung vị từng ảnh của `z_mét / z_sfm`; chỉ tỉ lệ, không dịch.

    Lỗi tỉ lệ của mô hình độ sâu gần như chung cho cả ảnh, nên mỗi ảnh góp một phiếu (trung vị của
    nó) rồi lấy trung vị các phiếu: vài ảnh đoán hỏng không kéo lệch kết quả. Trả None khi không đủ
    ảnh có đủ cặp hợp lệ — khi đó không công bố tỉ lệ thay vì đoán.
    """
    votes: list[float] = []
    count = 0
    for depth_sfm, depth_metric in pairs:
        valid = np.isfinite(depth_sfm) & np.isfinite(depth_metric) & (depth_sfm > 0) & (depth_metric > 0)
        if int(valid.sum()) < MIN_PAIRS_PER_FRAME:
            continue
        votes.append(float(np.median(depth_metric[valid] / depth_sfm[valid])))
        count += int(valid.sum())
    if len(votes) < MIN_FRAMES:
        return None
    scale = float(np.median(votes))
    if not np.isfinite(scale) or scale <= 0:
        return None
    spread = float(1.4826 * np.median(np.abs(np.array(votes) - scale)) / scale)
    return ScaleEstimate(scale_m_per_sfm_unit=scale, dispersion=spread, frames_used=len(votes), pairs_used=count)


@dataclass(frozen=True)
class FloorEstimate:
    """Mặt sàn đề xuất trong hệ SfM: ba điểm trên sàn, hai đoạn A–B và C–D nằm trên sàn."""

    floor_points: tuple[np.ndarray, np.ndarray, np.ndarray]
    segment_ab: tuple[np.ndarray, np.ndarray]
    segment_cd: tuple[np.ndarray, np.ndarray]
    residual_m: float
    support_points: int


def propose_floor(
    points: np.ndarray,
    normals: np.ndarray,
    camera_centers: np.ndarray,
    camera_down: np.ndarray,
    scale_m_per_sfm_unit: float,
) -> FloorEstimate | None:
    """Mặt sàn = lớp điểm nằm ngang đông nhất bên dưới camera.

    `points`/`normals` ở hệ SfM (pháp tuyến do mô hình đoán, đã xoay theo camera). `camera_down` là
    trung bình trục y (xuống) của các camera: người quay và robot giữ máy gần thẳng đứng nên đây là
    ước lượng ban đầu của hướng xuống; mặt phẳng khớp lại bằng bình phương tối thiểu cho hướng chính
    xác. Trả None khi không đủ điểm — nơi gọi để người dùng tự chọn sàn.
    """
    if len(points) == 0 or scale_m_per_sfm_unit <= 0:
        return None
    down = camera_down / np.linalg.norm(camera_down)
    lengths = np.linalg.norm(normals, axis=1)
    usable = np.isfinite(points).all(axis=1) & np.isfinite(normals).all(axis=1) & (lengths > 0)
    cosine = np.abs((normals[usable] / lengths[usable, None]) @ down)
    horizontal = points[usable][cosine >= np.cos(np.radians(FLOOR_NORMAL_MAX_DEGREES))]
    depth = (horizontal - camera_centers.mean(axis=0)) @ down  # dương = bên dưới camera
    below = horizontal[depth > 0]
    if len(below) < MIN_FLOOR_POINTS:
        return None
    layer = FLOOR_LAYER_M / scale_m_per_sfm_unit
    # RANSAC tất định (seed cố định): hướng xuống chỉ là ước lượng, gom theo độ cao dọc hướng đó sẽ
    # làm nhoè sàn khi camera hơi nghiêng; mặt phẳng tự tìm hướng của nó trong giới hạn góc cho phép.
    rng = np.random.default_rng(0)
    limit = np.cos(np.radians(FLOOR_NORMAL_MAX_DEGREES))
    best: np.ndarray | None = None
    for _ in range(_RANSAC_ITERATIONS):
        p1, p2, p3 = below[rng.choice(len(below), size=3, replace=False)]
        candidate = np.cross(p2 - p1, p3 - p1)
        length = np.linalg.norm(candidate)
        if length < 1e-12:
            continue
        candidate = candidate / length
        if abs(candidate @ down) < limit:
            continue
        mask = np.abs((below - p1) @ candidate) <= layer
        if best is None or int(mask.sum()) > int(best.sum()):
            best = mask
    if best is None or int(best.sum()) < MIN_FLOOR_POINTS:
        return None
    members = below[best]
    # Khớp lại bằng bình phương tối thiểu: pháp tuyến là hướng phương sai nhỏ nhất của lớp điểm.
    centroid = members.mean(axis=0)
    _, _, axes = np.linalg.svd(members - centroid, full_matrices=False)
    normal = axes[2]
    inliers = below[np.abs((below - centroid) @ normal) <= layer]
    if len(inliers) < MIN_FLOOR_POINTS:
        return None
    residual = float(np.sqrt(np.mean(((inliers - centroid) @ normal) ** 2)) * scale_m_per_sfm_unit)
    flat = inliers - np.outer((inliers - centroid) @ normal, normal)  # đưa điểm về đúng mặt phẳng
    along, across = axes[0], axes[1]
    order = np.argsort((flat - centroid) @ along)
    a, b = flat[order[0]], flat[order[-1]]
    side = (flat - centroid) @ across
    third = flat[int(np.argmax(np.abs(side)))]
    # Ba điểm sàn gần thẳng hàng (sàn chỉ là một dải hẹp) không dựng được khung sàn: không đề xuất.
    span = np.linalg.norm(b - a)
    if span <= 0 or np.linalg.norm(np.cross(b - a, third - a)) / span < layer:
        return None
    # C–D: cặp điểm xa nhau theo trục còn lại, độc lập với A–B để đoạn kiểm không trùng đoạn đo.
    lateral = np.argsort(side)
    c, d = flat[lateral[0]], flat[lateral[-1]]
    return FloorEstimate(
        floor_points=(a, b, third),
        segment_ab=(a, b),
        segment_cd=(c, d),
        residual_m=residual,
        support_points=int(len(inliers)),
    )
