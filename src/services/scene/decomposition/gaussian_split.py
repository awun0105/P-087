"""Tách 3DGS hệ mét thành nền + từng vật (pipeline v2, ADR 0007 chặng 5–6).

Đầu vào: PLY 3DGS hệ mét (quy ước Inria/Brush) và các instance của bước tách vật (chỉ số Gaussian
"hạt giống" mà SAMPro3D bỏ phiếu cho từng vật). Hạt giống chỉ gồm Gaussian đủ đục và được nhìn
thấy; module này lan nhãn sang Gaussian lân cận chưa gán (mờ, bị che) rồi cắt file.

Mỗi vật được ghi trong **hệ toạ độ cục bộ không xoay**: gốc tại tâm hộp bao, trục song song world.
Không xoay vì hệ số SH bậc cao phụ thuộc hướng — giữ nguyên trục thì không phải quay SH, và
`SceneObject.transform` ban đầu chỉ là phép tịnh tiến. NumPy thuần; chạy được trong worker.
"""

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

_PLY_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "int": "i4", "uint": "u4"}
_NUMPY_TO_PLY = {"f4": "float", "f8": "double", "u1": "uchar", "i4": "int", "u4": "uint"}
BACKGROUND = -1


@dataclass(frozen=True)
class SplitConfig:
    """Ngưỡng lan nhãn. Đơn vị mét."""

    grow_radius_m: float = 0.06
    """Gaussian chưa gán cách hạt giống gần nhất không quá chừng này thì theo vật đó."""
    floor_clearance_m: float = 0.04
    """Dưới độ cao này là sàn: không lan nhãn xuống (hạt giống vẫn giữ)."""
    max_scale_m: float = 0.5
    """Gaussian lớn hơn cỡ này là mảng nền (tường, sàn) — không lan nhãn tới."""
    grow_iterations: int = 2
    """Số vòng lan: mỗi vòng thêm tối đa `grow_radius_m`; có trần để nhãn không tràn ra nền."""
    min_object_gaussians: int = 50


@dataclass(frozen=True)
class ObjectPart:
    """Một vật sau khi tách: tâm (world), kích thước hộp bao theo trục world và các hàng PLY cục bộ."""

    index: int
    center: tuple[float, float, float]
    dimensions: tuple[float, float, float]
    rows: np.ndarray


def read_gaussian_ply(payload: bytes) -> np.ndarray:
    """PLY 3DGS nhị phân → mảng có cấu trúc (tên field như trong header)."""
    end = payload.index(b"end_header\n") + len(b"end_header\n")
    header = payload[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("chỉ hỗ trợ PLY binary_little_endian")
    count = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    fields = [(line.split()[2], "<" + _PLY_TYPES[line.split()[1]]) for line in header if line.startswith("property")]
    rows = np.frombuffer(payload, dtype=np.dtype(fields), count=count, offset=end)
    required = {"x", "y", "z", "opacity", "scale_0", "rot_0", "f_dc_0"}
    if not required <= set(rows.dtype.names or ()):
        raise ValueError("PLY không phải 3DGS (thiếu x/y/z/opacity/scale/rot/f_dc)")
    return rows


def write_gaussian_ply(rows: np.ndarray) -> bytes:
    """Mảng có cấu trúc → PLY nhị phân tất định (cùng thứ tự field)."""
    lines = ["ply", "format binary_little_endian 1.0", f"element vertex {len(rows)}"]
    lines += [f"property {_NUMPY_TO_PLY[rows.dtype[name].str[1:]]} {name}" for name in rows.dtype.names or ()]
    lines.append("end_header")
    return ("\n".join(lines) + "\n").encode("ascii") + np.ascontiguousarray(rows).tobytes()


def positions(rows: np.ndarray) -> np.ndarray:
    """Tâm Gaussian (N, 3) float64."""
    return np.stack([rows["x"], rows["y"], rows["z"]], axis=1).astype(np.float64)


def opacities(rows: np.ndarray) -> np.ndarray:
    """Độ đục sau sigmoid."""
    return 1.0 / (1.0 + np.exp(-rows["opacity"].astype(np.float64)))


def working_set(
    rows: np.ndarray, low_xy: np.ndarray, high_xy: np.ndarray, z_range: tuple[float, float], min_opacity: float = 0.3
) -> np.ndarray:
    """Chỉ số Gaussian đủ đục trong vùng làm việc — tập điểm đưa cho bước tách vật."""
    xyz = positions(rows)
    keep = (
        (opacities(rows) >= min_opacity)
        & (xyz[:, 0] > low_xy[0])
        & (xyz[:, 0] < high_xy[0])
        & (xyz[:, 1] > low_xy[1])
        & (xyz[:, 1] < high_xy[1])
        & (xyz[:, 2] > z_range[0])
        & (xyz[:, 2] < z_range[1])
    )
    return np.nonzero(keep)[0]


def label_gaussians(rows: np.ndarray, seeds: list[np.ndarray], config: SplitConfig = SplitConfig()) -> np.ndarray:
    """Nhãn vật cho mọi Gaussian (`BACKGROUND` = nền): hạt giống + lan sang lân cận chưa gán.

    `seeds[i]` là chỉ số (vào `rows`) của các Gaussian thuộc vật i. Hạt giống trùng giữa hai vật
    thuộc về vật đứng trước (bước tách vật đã sắp theo độ tin cậy).
    """
    labels = np.full(len(rows), BACKGROUND, dtype=np.int32)
    for index in reversed(range(len(seeds))):
        labels[seeds[index]] = index
    seeded = np.nonzero(labels != BACKGROUND)[0]
    if not len(seeded):
        return labels
    xyz = positions(rows)
    scale = np.exp(np.stack([rows["scale_0"], rows["scale_1"], rows["scale_2"]], axis=1).astype(np.float64)).max(axis=1)
    eligible = (xyz[:, 2] > config.floor_clearance_m) & (scale <= config.max_scale_m)
    for _ in range(config.grow_iterations):
        free = np.nonzero((labels == BACKGROUND) & eligible)[0]
        if not len(free) or config.grow_radius_m <= 0:
            break
        distance, nearest = cKDTree(xyz[seeded]).query(xyz[free], distance_upper_bound=config.grow_radius_m)
        hit = np.isfinite(distance)
        if not hit.any():
            break
        labels[free[hit]] = labels[seeded[nearest[hit]]]
        seeded = np.nonzero(labels != BACKGROUND)[0]
    return labels


def split(
    rows: np.ndarray, labels: np.ndarray, config: SplitConfig = SplitConfig()
) -> tuple[np.ndarray, list[ObjectPart]]:
    """(hàng nền, danh sách vật). Vật quá ít Gaussian trả về nền."""
    labels = labels.copy()
    xyz = positions(rows)
    parts: list[ObjectPart] = []
    for index in np.unique(labels[labels != BACKGROUND]):
        members = np.nonzero(labels == index)[0]
        if len(members) < config.min_object_gaussians:
            labels[members] = BACKGROUND
            continue
        low, high = xyz[members].min(axis=0), xyz[members].max(axis=0)
        center = (low + high) / 2
        local = rows[members].copy()
        for axis, name in enumerate(("x", "y", "z")):
            local[name] = (xyz[members, axis] - center[axis]).astype(local.dtype[name])
        parts.append(
            ObjectPart(
                index=int(index),
                center=(float(center[0]), float(center[1]), float(center[2])),
                dimensions=tuple(float(max(value, 0.05)) for value in high - low),  # type: ignore[arg-type]
                rows=local,
            )
        )
    return rows[labels == BACKGROUND].copy(), parts
