"""Số đo từ LiDAR cho điểm click trên 3DGS — chỉ cho dataset mẫu (ADR 0004 §6).

Điểm click (hệ SfM của 3DGS) → world bằng căn chỉnh quỹ đạo camera đã chuẩn bị
(REC-09, GT-assisted) → bắt vào điểm LiDAR gần nhất (REC-08, đã sang world qua cầu
nối tọa độ). Khoảng cách tính giữa hai điểm LiDAR đã bắt, nên là số đo cảm biến;
căn chỉnh chỉ dùng để tìm đúng chỗ trên point cloud.

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


class LidarDistance(ContractModel):
    """Một phép đo: điểm click sang world, điểm LiDAR đã bắt và khoảng cách."""

    clicked_world: tuple[Vector3, Vector3]
    lidar_points_m: tuple[Vector3, Vector3]
    snap_offsets_m: tuple[FiniteFloat, FiniteFloat]
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
        """Bắt hai điểm vào LiDAR; điểm xa bề mặt quá bán kính thì từ chối."""
        clicked = (context.fit.apply(point_a), context.fit.apply(point_b))
        snapped: list[tuple[float, float, float]] = []
        offsets: list[float] = []
        for label, point in zip(("thứ nhất", "thứ hai"), clicked, strict=True):
            gaps = np.linalg.norm(context.points_world - np.asarray(point), axis=1)
            index = int(gaps.argmin())
            if gaps[index] > SNAP_RADIUS_M:
                raise ValueError(
                    f"Điểm {label} cách bề mặt LiDAR {gaps[index] * 100:.0f} cm; chọn lại trên bề mặt rõ nét"
                )
            snapped.append(tuple(float(value) for value in context.points_world[index]))  # type: ignore[arg-type]
            offsets.append(float(gaps[index]))
        distance = math.dist(snapped[0], snapped[1])
        if distance <= 0:
            raise ValueError("hai điểm bắt vào cùng một điểm LiDAR; chọn hai đầu xa nhau hơn")
        return LidarDistance(
            clicked_world=clicked,
            lidar_points_m=(snapped[0], snapped[1]),  # type: ignore[arg-type]
            snap_offsets_m=(offsets[0], offsets[1]),
            distance_m=distance,
        )
