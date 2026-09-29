"""Số đo từ LiDAR cho điểm click trên 3DGS — chỉ cho dataset mẫu (ADR 0004 §6).

Điểm click (hệ SfM của 3DGS) → world bằng căn chỉnh quỹ đạo camera đã chuẩn bị
(REC-09, GT-assisted) → bắt vào điểm LiDAR gần nhất (REC-08, đã sang world qua cầu
nối tọa độ). Điểm có LiDAR trong `SNAP_RADIUS_M` dùng điểm LiDAR (số đo cảm biến);
point cloud không phủ tới (chỉ gộp một đoạn scan) thì dùng vị trí đã quy đổi mét theo
căn chỉnh — không chặn người dùng, và ghi rõ nguồn từng điểm ở `point_sources`.

Job không có bản ghi hỗ trợ (`demo_lidar_support.json`) thì không có số đo LiDAR;
video thật của người dùng luôn ở trường hợp đó.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel, ProductArtifactRef
from src.models.contracts.reconstruction import LiDARGeometryArtifact
from src.services.reconstruction.alignment.similarity import SimilarityFit, rotation_matrix
from src.services.reconstruction.lidar.cloud_header import read_header

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]

#: Bán kính bắt điểm: residual căn chỉnh (RMS 6,8 cm trên Aisle_CW) + sai số click.
SNAP_RADIUS_M = 0.20
SUPPORT_NAME = "demo_lidar_support.json"


def support_uri(job_id: str) -> str:
    """URI cố định của bản ghi hỗ trợ LiDAR cho một job (publish một lần)."""
    return f"artifact://jobs/{job_id}/rec09/{SUPPORT_NAME}"


class DemoLidarSupport(ContractModel):
    """Bản ghi chuẩn bị offline: căn chỉnh + LiDAR của đúng job này."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["DemoLidarSupport"] = "DemoLidarSupport"
    job_id: str
    camera_poses_checksum: str
    alignment_ref: ProductArtifactRef
    lidar_geometry_ref: ProductArtifactRef
    lidar_metadata_ref: ProductArtifactRef
    assistance: Literal["ground_truth_assisted_dataset_demo"] = "ground_truth_assisted_dataset_demo"


PointSource = Literal["lidar_surface", "trajectory_alignment"]


class LidarDistance(ContractModel):
    """Một phép đo: điểm click sang world, điểm dùng để đo (LiDAR hoặc căn chỉnh) và khoảng cách.

    `snap_offsets_m` là khoảng cách tới điểm LiDAR gần nhất (kể cả khi không bắt được).
    """

    clicked_world: tuple[Vector3, Vector3]
    lidar_points_m: tuple[Vector3, Vector3]
    snap_offsets_m: tuple[FiniteFloat, FiniteFloat]
    point_sources: tuple[PointSource, PointSource]
    distance_m: FiniteFloat = Field(gt=0)


@dataclass(frozen=True)
class LidarAssistContext:
    """Căn chỉnh + point cloud world đã nạp cho một job."""

    support: DemoLidarSupport
    support_ref_checksum: str
    fit: SimilarityFit
    points_world: np.ndarray


def _load_points(path: Path, metadata: LiDARGeometryArtifact) -> np.ndarray:
    """PLY nhị phân little-endian (output REC-07) → toạ độ world theo transform đã khai."""
    with path.open("rb") as stream:
        header = read_header(stream)
        offset = stream.tell()
    if header.encoding != "binary_little_endian":
        raise ValueError("LiDAR demo cần PLY binary_little_endian")
    dtype = np.dtype([(name, "<" + code) for name, code in zip(header.fields, header.codes, strict=True)])
    rows = np.frombuffer(path.read_bytes()[offset:], dtype=dtype, count=header.point_count)
    points = np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(float)
    transform = metadata.declared_transform_to_canonical
    if transform is None or transform.parent_frame != "world":
        raise ValueError("LiDAR chưa có transform sang world")
    rotation = rotation_matrix(transform.rotation_quaternion_xyzw)
    return points @ rotation.T + np.asarray(transform.translation_xyz)


class LidarAssist:
    """Nạp bản ghi hỗ trợ của job và đo khoảng cách LiDAR cho cặp điểm click."""

    def __init__(self, resolve: Callable[[ProductArtifactRef], Path], exists: Callable[[str], bool]) -> None:
        self.resolve = resolve
        self.exists = exists

    def _read(self, reference: ProductArtifactRef) -> bytes:
        return self.resolve(reference).read_bytes()

    def load(self, job_id: str, support_ref: ProductArtifactRef | None) -> LidarAssistContext | None:
        """None khi job không có hỗ trợ LiDAR (video người dùng)."""
        if support_ref is None:
            return None
        support = DemoLidarSupport.model_validate_json(self._read(support_ref))
        if support.job_id != job_id:
            raise ValueError("bản ghi LiDAR thuộc job khác")
        alignment = json.loads(self._read(support.alignment_ref))
        if alignment.get("artifact_type") != "SfmWorldTrajectoryAlignment" or alignment.get("target_frame") != "world":
            raise ValueError("căn chỉnh không phải SfM → world")
        if alignment["inputs"]["camera_poses_checksum"] != support.camera_poses_checksum:
            raise ValueError("căn chỉnh dựng từ camera pose khác của job")
        metadata = LiDARGeometryArtifact.model_validate_json(self._read(support.lidar_metadata_ref))
        if metadata.artifact_checksum != support.lidar_geometry_ref.artifact_checksum:
            raise ValueError("metadata LiDAR không khớp point cloud")
        points = _load_points(self.resolve(support.lidar_geometry_ref), metadata)
        return LidarAssistContext(
            support, support_ref.artifact_checksum, SimilarityFit.model_validate(alignment["fit"]), points
        )

    @staticmethod
    def measure(context: LidarAssistContext, point_a: Vector3, point_b: Vector3) -> LidarDistance:
        """Bắt từng điểm vào LiDAR nếu có trong bán kính, không thì dùng vị trí theo căn chỉnh."""
        clicked = (context.fit.apply(point_a), context.fit.apply(point_b))
        used: list[tuple[float, float, float]] = []
        offsets: list[float] = []
        sources: list[PointSource] = []
        for point in clicked:
            gaps = np.linalg.norm(context.points_world - np.asarray(point), axis=1)
            index = int(gaps.argmin())
            offsets.append(float(gaps[index]))
            if gaps[index] <= SNAP_RADIUS_M:
                used.append(tuple(float(value) for value in context.points_world[index]))  # type: ignore[arg-type]
                sources.append("lidar_surface")
            else:
                used.append(point)
                sources.append("trajectory_alignment")
        distance = math.dist(used[0], used[1])
        if distance <= 0:
            raise ValueError("Hai điểm trùng nhau sau khi đo; chọn hai đầu xa nhau hơn")
        return LidarDistance(
            clicked_world=clicked,
            lidar_points_m=(used[0], used[1]),  # type: ignore[arg-type]
            snap_offsets_m=(offsets[0], offsets[1]),
            point_sources=(sources[0], sources[1]),
            distance_m=distance,
        )


#: Vị trí mục tiêu (mét, theo hướng đi d và phương ngang p, tính từ camera gốc) của 7 điểm
#: demo: A, B, C, D rồi 3 điểm sàn. A–B dài 2 m, C–D 1,5 m (đều ≥ 0,5 m và qua ngưỡng Q2).
_DEMO_TARGETS = (
    (1.5, 0.0),
    (3.5, 0.0),
    (1.5, 0.8),
    (3.0, 0.8),
    (1.2, -0.7),
    (3.8, -0.7),
    (2.5, 0.9),
)
_FLOOR_BAND_M = 0.03
_TARGET_TOLERANCE_M = 0.15
_MIN_FLOOR_POINTS = 5000


def _inverse(fit: SimilarityFit, point: np.ndarray) -> Vector3:
    """world → SfM (nghịch đảo phép đồng dạng)."""
    local = rotation_matrix(fit.rotation_xyzw).T @ ((point - np.asarray(fit.translation)) / fit.scale)
    return tuple(float(value) for value in local)  # type: ignore[return-value]


def demo_points(context: LidarAssistContext, camera_centers_sfm: list[Vector3]) -> list[Vector3]:
    """7 điểm demo (hệ SfM) lấy từ điểm LiDAR trên sàn, phía trước camera mà LiDAR phủ dày.

    Mô phỏng người dùng click: điểm nằm đúng bề mặt LiDAR và trong vùng camera đã quay
    (nên có trên 3DGS). Không đủ điểm sàn quanh quỹ đạo thì báo lỗi, không bịa điểm.
    """
    cameras = np.array([context.fit.apply(point) for point in camera_centers_sfm])
    floor = context.points_world[np.abs(context.points_world[:, 2]) < _FLOOR_BAND_M]
    if len(cameras) < 2 or not len(floor):
        raise ValueError("Không đủ camera hoặc điểm sàn LiDAR để tự chọn điểm")
    coverage = [
        int(((gaps > 1.0) & (gaps < 4.0)).sum())
        for gaps in (np.linalg.norm(floor[:, :2] - camera[:2], axis=1) for camera in cameras)
    ]
    base = next((index for index, count in enumerate(coverage) if count >= _MIN_FLOOR_POINTS), None)
    if base is None:
        raise ValueError("LiDAR không phủ đủ mặt sàn quanh quỹ đạo camera để tự chọn điểm")
    ahead = cameras[min(base + 10, len(cameras) - 1)] - cameras[base]
    if np.linalg.norm(ahead[:2]) < 0.1:
        raise ValueError("Camera gần như đứng yên; không xác định được hướng đi")
    direction = np.array([ahead[0], ahead[1], 0.0]) / np.linalg.norm(ahead[:2])
    across = np.array([-direction[1], direction[0], 0.0])
    origin = np.array([cameras[base][0], cameras[base][1], 0.0])
    chosen: list[Vector3] = []
    for forward, side in _DEMO_TARGETS:
        target = origin + forward * direction + side * across
        gaps = np.linalg.norm(floor - target, axis=1)
        index = int(gaps.argmin())
        if gaps[index] > _TARGET_TOLERANCE_M:
            raise ValueError("Vùng sàn phía trước camera thiếu điểm LiDAR; không tự chọn được")
        chosen.append(_inverse(context.fit, floor[index]))
    return chosen
