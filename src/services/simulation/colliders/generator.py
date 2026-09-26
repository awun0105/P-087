"""Tạo và quản lý các loại ColliderSpec (AABB, OBB, Convex Hull, Simplified Mesh)."""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, Field
from scipy.spatial.transform import Rotation

from src.models.contracts.artifacts import Identifier, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import ColliderSpec, ColliderType, SceneObject

logger = logging.getLogger(__name__)

MIN_COLLIDER_EXTENT_M: float = 0.01
DEFAULT_GROUND_PLANE_THICKNESS_M: float = 0.05

DEFAULT_PROVENANCE: dict[str, Any] = {
    "generator": "real2sim-collider-v1.0",
    "donor_references": ["OpenReal2Sim", "splat-transform", "DISCOVERSE", "Re3Sim"],
}


class BoxSpecRequest(BaseModel):
    """Thông số yêu cầu tạo Box collider."""

    dimensions_xyz_m: tuple[float, float, float]
    parent_frame: Identifier
    collider_id: Identifier
    collider_type: ColliderType = ColliderType.AABB
    offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    geometry_ref: ProductArtifactRef | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


def create_box_collider(req: BoxSpecRequest) -> ColliderSpec:
    """Tạo ColliderSpec dạng hộp (AABB hoặc OBB) từ thông số kích thước."""
    if any(not np.isfinite(d) or d <= 0.0 for d in req.dimensions_xyz_m):
        raise ValueError(f"dimensions_xyz_m phải dương và hữu hạn, nhận được: {req.dimensions_xyz_m}")

    local_tf = Transform(
        parent_frame=req.parent_frame,
        local_frame=req.collider_id,
        translation_xyz=req.offset_xyz,
        rotation_quaternion_xyzw=req.rotation_xyzw,
    )
    return ColliderSpec(
        collider_id=req.collider_id,
        collider_type=req.collider_type,
        local_transform=local_tf,
        dimensions_xyz_m=req.dimensions_xyz_m,
        geometry_ref=req.geometry_ref,
        parameters=req.parameters,
        provenance=DEFAULT_PROVENANCE,
    )


def create_ground_plane_collider(
    parent_frame: Identifier = "world",
    collider_id: Identifier = "collider-ground-plane",
    dimensions_xyz_m: tuple[float, float, float] = (100.0, 100.0, DEFAULT_GROUND_PLANE_THICKNESS_M),
) -> ColliderSpec:
    """Tạo Analytic Ground Plane collider phẳng tuyệt đối theo Safeguard 1.

    Độ dày mặc định 0.05m (5cm) tuân thủ tiêu chuẩn engine vật lý (PhysX/Isaac Sim)
    để ngăn hiện tượng xuyên sàn (tunneling) của bánh xe AMR, hoàn toàn tương thích
    với ngưỡng min_dimension_m (0.01m).
    """
    thickness = dimensions_xyz_m[2]
    req = BoxSpecRequest(
        dimensions_xyz_m=dimensions_xyz_m,
        parent_frame=parent_frame,
        collider_id=collider_id,
        collider_type=ColliderType.AABB,
        offset_xyz=(0.0, 0.0, -thickness / 2.0),
        parameters={"analytic_ground_plane": True, "friction": 0.8},
    )
    return create_box_collider(req)


def _matrix_to_quaternion(matrix: np.ndarray) -> tuple[float, float, float, float]:
    """Chuyển đổi ma trận xoay 3x3 sang quaternion (x, y, z, w)."""
    rot = Rotation.from_matrix(matrix)
    q = rot.as_quat()
    return float(q[0]), float(q[1]), float(q[2]), float(q[3])


def _dims_and_center_from_extrema(
    min_pt: np.ndarray,
    max_pt: np.ndarray,
    min_dim: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Tính kích thước và tọa độ tâm từ 2 điểm cực trị min/max."""
    diff = max_pt - min_pt
    dims = tuple(max(float(diff[i]), min_dim) for i in range(3))
    center = tuple(float((min_pt[i] + max_pt[i]) / 2.0) for i in range(3))
    return dims, center


def _resolve_fallback_center(
    geometry: Any,
    user_fallback_center: tuple[float, float, float] | None = None,
) -> tuple[float, float, float]:
    """Xác định vị trí tâm an toàn cho fallback box, tránh đặt tùy tiện tại gốc (0,0,0)."""
    if user_fallback_center is not None and all(np.isfinite(user_fallback_center)):
        return user_fallback_center

    raw = getattr(geometry, "vertices", getattr(geometry, "points", None))
    # 1. Thử tính nanmedian từ raw vertices/points nếu có
    if raw is not None:
        try:
            arr = np.asarray(raw, dtype=float)
            if arr.ndim == 2 and arr.shape[1] == 3 and arr.size > 0 and np.any(np.isfinite(arr)):
                with np.errstate(all="ignore"):
                    med = np.nanmedian(arr, axis=0)
                if np.all(np.isfinite(med)):
                    return (float(med[0]), float(med[1]), float(med[2]))
        except Exception:
            pass

    # 2. Thử lấy từ centroid hoặc center_mass (bỏ qua nếu raw tồn tại nhưng rỗng để tránh warning)
    if raw is None or len(raw) > 0:
        for attr in ("centroid", "center_mass"):
            try:
                with np.errstate(all="ignore"):
                    val = getattr(geometry, attr, None)
                if val is not None:
                    arr = np.asarray(val, dtype=float).flatten()
                    if len(arr) == 3 and np.all(np.isfinite(arr)):
                        return (float(arr[0]), float(arr[1]), float(arr[2]))
            except Exception:
                pass

    return (0.0, 0.0, 0.0)


def _safe_compute_bounds(
    geometry: trimesh.Trimesh | trimesh.PointCloud,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
    fallback_center: tuple[float, float, float] | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Tính toán bounds và tâm an toàn, ghi log cảnh báo khi dữ liệu lỗi hoặc suy biến."""
    try:
        raw_bounds = getattr(geometry, "bounds", None)
        if raw_bounds is not None and len(raw_bounds) == 2:
            min_pt, max_pt = np.asarray(raw_bounds[0]), np.asarray(raw_bounds[1])
            if np.all(np.isfinite(min_pt)) and np.all(np.isfinite(max_pt)):
                return _dims_and_center_from_extrema(min_pt, max_pt, min_dimension_m)
    except Exception as exc:
        logger.warning("Không thể đọc bounds từ geometry: %s", exc)

    try:
        raw_verts = getattr(geometry, "vertices", getattr(geometry, "points", None))
        if raw_verts is not None and len(raw_verts) > 0:
            verts = np.asarray(raw_verts)
            valid_verts = verts[np.all(np.isfinite(verts), axis=1)]
            if len(valid_verts) > 0:
                return _dims_and_center_from_extrema(
                    np.min(valid_verts, axis=0),
                    np.max(valid_verts, axis=0),
                    min_dimension_m,
                )
            logger.warning("Geometry không chứa đỉnh hữu hạn (finite) nào.")
    except Exception as exc:
        logger.warning("Không thể tính bounds từ vertices: %s", exc)

    resolved_center = _resolve_fallback_center(geometry, fallback_center)
    logger.warning(
        "Kích hoạt fallback an toàn (%sm) tại tâm %s do không tính được bounds từ geometry.",
        min_dimension_m,
        resolved_center,
    )
    return (min_dimension_m, min_dimension_m, min_dimension_m), resolved_center


def _extract_obb_params(
    mesh: trimesh.Trimesh,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
    fallback_center: tuple[float, float, float] | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float, float]]:
    """Tính kích thước, vị trí offset và góc quay quaternion của OBB."""
    try:
        obb = mesh.bounding_box_oriented
        raw_extents = getattr(obb, "extents", None)
        if raw_extents is not None and len(raw_extents) == 3:
            extents_arr = np.asarray(raw_extents)
            if np.all(np.isfinite(extents_arr)):
                extents = tuple(max(float(x), min_dimension_m) for x in extents_arr)
                tf = getattr(obb, "transform", None)
                if tf is not None and getattr(tf, "shape", None) == (4, 4) and np.all(np.isfinite(tf)):
                    trans = (float(tf[0, 3]), float(tf[1, 3]), float(tf[2, 3]))
                    rot_q = _matrix_to_quaternion(tf[:3, :3])
                    return extents, trans, rot_q
    except Exception as exc:
        logger.warning("Không thể tính OBB từ mesh: %s. Fallback sang AABB bounds.", exc)

    dims, center = _safe_compute_bounds(
        mesh,
        min_dimension_m=min_dimension_m,
        fallback_center=fallback_center,
    )
    return dims, center, (0.0, 0.0, 0.0, 1.0)


def generate_collider_from_geometry(
    geometry: trimesh.Trimesh | trimesh.PointCloud,
    collider_type: ColliderType,
    parent_frame: Identifier,
    collider_id: Identifier,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
    fallback_on_empty: bool = False,
    fallback_center: tuple[float, float, float] | None = None,
) -> ColliderSpec:
    """Sinh ColliderSpec từ đối tượng hình học (Trimesh hoặc PointCloud)."""
    raw_verts = getattr(geometry, "vertices", getattr(geometry, "points", None))
    if (raw_verts is None or len(raw_verts) == 0) and not fallback_on_empty:
        raise ValueError("Geometry không chứa đỉnh nào để sinh collider.")

    if collider_type == ColliderType.OBB and isinstance(geometry, trimesh.Trimesh):
        try:
            extents, trans, rot_q = _extract_obb_params(
                geometry,
                min_dimension_m=min_dimension_m,
                fallback_center=fallback_center,
            )
            req = BoxSpecRequest(
                dimensions_xyz_m=extents,
                parent_frame=parent_frame,
                collider_id=collider_id,
                collider_type=ColliderType.OBB,
                offset_xyz=trans,
                rotation_xyzw=rot_q,
            )
            return create_box_collider(req)
        except Exception as exc:
            logger.warning("Lỗi khi tạo OBB collider: %s. Fallback sang AABB.", exc)

    dims, center = _safe_compute_bounds(
        geometry,
        min_dimension_m=min_dimension_m,
        fallback_center=fallback_center,
    )
    req = BoxSpecRequest(
        dimensions_xyz_m=dims,
        parent_frame=parent_frame,
        collider_id=collider_id,
        collider_type=ColliderType.AABB,
        offset_xyz=center,
    )
    return create_box_collider(req)


def generate_object_collider(
    obj: SceneObject,
    geometry_file_path: Path | None = None,
    preferred_type: ColliderType = ColliderType.AABB,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
) -> ColliderSpec:
    """Sinh collider cho SceneObject tuân thủ Safeguard 2 (ưu tiên Box)."""
    collider_id = f"collider-{obj.id}"

    # Safeguard 2: Ưu tiên primitive_dimensions_xyz_m
    if obj.primitive_dimensions_xyz_m is not None:
        req = BoxSpecRequest(
            dimensions_xyz_m=obj.primitive_dimensions_xyz_m,
            parent_frame=obj.local_frame,
            collider_id=collider_id,
            collider_type=ColliderType.AABB,
            parameters={"source": "primitive_dimensions"},
        )
        return create_box_collider(req)

    # Đọc file mesh nếu được cung cấp (bọc trong try-except để phòng ngừa crash khi mesh hỏng)
    if geometry_file_path is not None and geometry_file_path.is_file():
        try:
            loaded = trimesh.load(str(geometry_file_path))
            if isinstance(loaded, (trimesh.Trimesh, trimesh.PointCloud)):
                return generate_collider_from_geometry(
                    geometry=loaded,
                    collider_type=preferred_type,
                    parent_frame=obj.local_frame,
                    collider_id=collider_id,
                    min_dimension_m=min_dimension_m,
                    fallback_on_empty=True,
                )
        except Exception as exc:
            logger.warning("Không thể load/tạo collider từ file '%s': %s", geometry_file_path, exc)

    # Fallback mặc định an toàn cho box collider kích thước 1m x 1m x 1m
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.0, 1.0, 1.0),
        parent_frame=obj.local_frame,
        collider_id=collider_id,
        collider_type=ColliderType.AABB,
        parameters={"source": "default_box_fallback"},
    )
    return create_box_collider(req)
