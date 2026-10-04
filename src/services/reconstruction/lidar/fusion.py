"""Ghép scan LiDAR thô thành đám mây đã đăng ký theo quỹ đạo người dùng nộp (ADR 0009, luồng C).

Mỗi scan nằm trong hệ của cảm biến tại thời điểm quét; pose tương ứng (`map_from_sensor`) đưa nó về hệ cố định của
quỹ đạo. Module chỉ làm đúng việc đó: lọc điểm hỏng và ngoài tầm, áp pose, gộp, lấy thưa theo lưới voxel. Nó không
ước lượng quỹ đạo (LiDAR odometry/SLAM ngoài phạm vi) và không sửa pose.

Viết bằng numpy để chạy được trong worker: runtime của worker không có Open3D (bản offline
`scripts/torwic/prefusion_cloud.py` dùng Open3D trong runtime riêng). Kết quả xác định: cùng đầu vào cho cùng bytes.
"""

import math
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import BinaryIO

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.reconstruction.lidar.cloud_header import read_header

#: Số scan gộp tạm trước mỗi lần lấy thưa, để bộ nhớ không phình theo tổng số scan.
_MERGE_EVERY = 16
_QUATERNION_TOLERANCE = 1e-3


class FusionConfig(ContractModel):
    """Thông số ghép; mặc định theo lượt ghép đã kiểm của REC-07 trên TorWIC (voxel 5 cm, tầm 0,5–50 m)."""

    voxel_size_m: FiniteFloat = Field(default=0.05, gt=0)
    min_range_m: FiniteFloat = Field(default=0.5, ge=0)
    max_range_m: FiniteFloat = Field(default=50.0, gt=0)
    max_scan_points: int = Field(default=2_000_000, gt=0)
    max_merged_points: int = Field(default=20_000_000, gt=0)


@dataclass(frozen=True)
class ScanPose:
    """Pose `map_from_sensor` của một scan: tịnh tiến (mét) và quaternion xyzw đã chuẩn hoá."""

    timestamp: float
    translation: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]


class FusionStats(ContractModel):
    """Số liệu của lượt ghép, đưa vào provenance và hiện cho người dùng."""

    scan_count: int = Field(gt=0)
    input_points: int = Field(gt=0)
    removed_points: int = Field(ge=0)
    point_count: int = Field(gt=0)
    bounds_min: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    bounds_max: tuple[FiniteFloat, FiniteFloat, FiniteFloat]


def parse_trajectory(text: str) -> list[ScanPose]:
    """Quỹ đạo TUM: mỗi dòng `thời_điểm x y z qx qy qz qw`; thời điểm tăng dần, quaternion chuẩn hoá."""
    poses: list[ScanPose] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        try:
            values = [float(part) for part in parts]
        except ValueError as error:
            raise ValueError(f"quỹ đạo dòng {number}: không phải số") from error
        if len(values) != 8 or not all(math.isfinite(value) for value in values):
            raise ValueError(f"quỹ đạo dòng {number}: cần 8 số hữu hạn (thời_điểm x y z qx qy qz qw)")
        norm = math.hypot(*values[4:])
        if abs(norm - 1) > _QUATERNION_TOLERANCE:
            raise ValueError(f"quỹ đạo dòng {number}: quaternion chưa chuẩn hoá")
        if poses and values[0] <= poses[-1].timestamp:
            raise ValueError(f"quỹ đạo dòng {number}: thời điểm phải tăng dần")
        poses.append(
            ScanPose(values[0], (values[1], values[2], values[3]), tuple(value / norm for value in values[4:]))  # type: ignore[arg-type]
        )
    if len(poses) < 2:
        raise ValueError("quỹ đạo cần ít nhất 2 pose")
    return poses


def read_points(stream: BinaryIO, max_points: int) -> np.ndarray:
    """Toạ độ `(N, 3)` float64 của một đám mây PLY/PCD (ascii hoặc binary); kiểm đủ bytes theo header."""
    header = read_header(stream)
    if header.point_count > max_points:
        raise ValueError(f"đám mây có {header.point_count} điểm, vượt giới hạn {max_points}")
    columns = list(header.xyz)
    if header.encoding == "ascii":
        rows = np.loadtxt(stream, dtype=np.float64, usecols=columns, max_rows=header.point_count, ndmin=2)
        if len(rows) != header.point_count:
            raise ValueError("đám mây ascii thiếu dòng so với header")
        return rows
    order = ">" if header.encoding == "binary_big_endian" else "<"
    dtype = np.dtype([(f"f{index}", order + code) for index, code in enumerate(header.codes)])
    payload = stream.read(dtype.itemsize * header.point_count)
    if len(payload) != dtype.itemsize * header.point_count:
        raise ValueError("đám mây bị cắt: số byte ít hơn header khai báo")
    rows = np.frombuffer(payload, dtype=dtype, count=header.point_count)
    return np.stack([rows[f"f{column}"].astype(np.float64) for column in columns], axis=1)


def voxel_downsample(points: np.ndarray, voxel_size: float) -> np.ndarray:
    """Mỗi ô voxel giữ trọng tâm các điểm trong ô; thứ tự kết quả theo chỉ số ô (xác định)."""
    if not len(points):
        return points
    cells = np.floor(points / voxel_size).astype(np.int64)
    _, inverse, counts = np.unique(cells, axis=0, return_inverse=True, return_counts=True)
    sums = np.zeros((len(counts), 3), dtype=np.float64)
    np.add.at(sums, inverse.reshape(-1), points)
    return sums / counts[:, None]


def fuse_scans(scans: Iterable[tuple[np.ndarray, ScanPose]], config: FusionConfig) -> tuple[np.ndarray, FusionStats]:
    """Gộp các scan (điểm trong hệ cảm biến, pose `map_from_sensor`) thành một đám mây trong hệ của quỹ đạo."""
    merged = np.empty((0, 3), dtype=np.float64)
    pending: list[np.ndarray] = []
    scan_count = input_points = removed = 0

    def flush() -> None:
        nonlocal merged
        if pending:
            merged = voxel_downsample(np.concatenate([merged, *pending]), config.voxel_size_m)
            pending.clear()
        if len(merged) > config.max_merged_points:
            raise ValueError("đám mây ghép vượt giới hạn điểm; nộp ít scan hơn hoặc tăng kích thước voxel")

    for points, pose in scans:
        if not len(points) or len(points) > config.max_scan_points:
            raise ValueError("scan rỗng hoặc vượt giới hạn điểm của một scan")
        ranges = np.linalg.norm(points, axis=1)
        valid = np.isfinite(points).all(axis=1) & (ranges >= config.min_range_m) & (ranges <= config.max_range_m)
        kept = points[valid]
        scan_count, input_points, removed = (
            scan_count + 1,
            input_points + len(points),
            removed + len(points) - len(kept),
        )
        if len(kept):
            world = kept @ rotation_matrix(pose.rotation_xyzw).T + np.asarray(pose.translation)
            pending.append(voxel_downsample(world, config.voxel_size_m))
        if len(pending) >= _MERGE_EVERY:
            flush()
    flush()
    if not scan_count or not len(merged):
        raise ValueError("không còn điểm nào sau khi lọc; kiểm tra đơn vị (mét) và tầm đo của scan")
    # Sắp theo toạ độ để bytes đầu ra không phụ thuộc cách chia lô khi gộp.
    merged = merged[np.lexsort((merged[:, 2], merged[:, 1], merged[:, 0]))]
    stats = FusionStats(
        scan_count=scan_count,
        input_points=input_points,
        removed_points=removed,
        point_count=len(merged),
        bounds_min=tuple(float(value) for value in merged.min(axis=0)),  # type: ignore[arg-type]
        bounds_max=tuple(float(value) for value in merged.max(axis=0)),  # type: ignore[arg-type]
    )
    return merged, stats


def ply_chunks(points: np.ndarray) -> Iterator[bytes]:
    """PLY binary little-endian chỉ có `x y z` float32 — định dạng REC-08 nhận."""
    header = (
        f"ply\nformat binary_little_endian 1.0\nelement vertex {len(points)}\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
    )
    yield header.encode("ascii")
    yield np.ascontiguousarray(points, dtype="<f4").tobytes()


def ply_bytes(points: np.ndarray) -> bytes:
    """Toàn bộ file PLY của đám mây đã ghép."""
    if points.ndim != 2 or points.shape[1] != 3 or not len(points):
        raise ValueError("đám mây phải là mảng (N, 3) không rỗng")
    if struct.calcsize("<3f") * len(points) > 2**31:
        raise ValueError("đám mây quá lớn để ghi một file")
    return b"".join(ply_chunks(points))
