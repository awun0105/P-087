"""Tạo và quản lý các loại ColliderSpec (AABB, OBB, Convex Hull, Simplified Mesh)."""

from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, Field
from scipy.spatial.transform import Rotation

from src.models.contracts.artifacts import Identifier, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import ColliderSpec, ColliderType, SceneObject

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


def _safe_compute_bounds(
    geometry: trimesh.Trimesh | trimesh.PointCloud,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Tính toán bounds và tâm an toàn, chống crash khi mesh suy biến hoặc bounds malformed."""
    try:
        raw_bounds = getattr(geometry, "bounds", None)
        if raw_bounds is not None and len(raw_bounds) == 2:
            min_pt, max_pt = np.asarray(raw_bounds[0]), np.asarray(raw_bounds[1])
            if np.all(np.isfinite(min_pt)) and np.all(np.isfinite(max_pt)):
                diff = max_pt - min_pt
                dims = tuple(max(float(diff[i]), min_dimension_m) for i in range(3))
                center = tuple(float((min_pt[i] + max_pt[i]) / 2.0) for i in range(3))
                return dims, center
    except Exception:
        pass

    # Thử tính trực tiếp từ vertices nếu raw_bounds bị lỗi
    try:
        raw_verts = getattr(geometry, "vertices", None)
        if raw_verts is not None and len(raw_verts) > 0:
            verts = np.asarray(raw_verts)
            finite_mask = np.all(np.isfinite(verts), axis=1)
            valid_verts = verts[finite_mask]
            if len(valid_verts) > 0:
                min_pt = np.min(valid_verts, axis=0)
                max_pt = np.max(valid_verts, axis=0)
                diff = max_pt - min_pt
                dims = tuple(max(float(diff[i]), min_dimension_m) for i in range(3))
                center = tuple(float((min_pt[i] + max_pt[i]) / 2.0) for i in range(3))
                return dims, center
    except Exception:
        pass

    # Fallback an toàn tuyệt đối khi toàn bộ đỉnh đều không hợp lệ
    return (min_dimension_m, min_dimension_m, min_dimension_m), (0.0, 0.0, 0.0)


def _extract_obb_params(
    mesh: trimesh.Trimesh,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
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
    except Exception:
        pass

    # Fallback an toàn sang bounds AABB nếu OBB thất bại hoặc bounds malformed
    dims, center = _safe_compute_bounds(mesh, min_dimension_m=min_dimension_m)
    return dims, center, (0.0, 0.0, 0.0, 1.0)


def generate_collider_from_geometry(
    geometry: trimesh.Trimesh | trimesh.PointCloud,
    collider_type: ColliderType,
    parent_frame: Identifier,
    collider_id: Identifier,
    min_dimension_m: float = MIN_COLLIDER_EXTENT_M,
) -> ColliderSpec:
    """Sinh ColliderSpec từ đối tượng hình học (Trimesh hoặc PointCloud)."""
    raw_verts = getattr(geometry, "vertices", None)
    if raw_verts is None or len(raw_verts) == 0:
        raise ValueError("Geometry không chứa đỉnh nào để sinh collider.")

    if collider_type == ColliderType.OBB and isinstance(geometry, trimesh.Trimesh):
        try:
            extents, trans, rot_q = _extract_obb_params(geometry, min_dimension_m=min_dimension_m)
            req = BoxSpecRequest(
                dimensions_xyz_m=extents,
                parent_frame=parent_frame,
                collider_id=collider_id,
                collider_type=ColliderType.OBB,
                offset_xyz=trans,
                rotation_xyzw=rot_q,
            )
            return create_box_collider(req)
        except Exception:
            pass

    # AABB hoặc fallback an toàn
    dims, center = _safe_compute_bounds(geometry, min_dimension_m=min_dimension_m)
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
                )
        except Exception:
            pass

    # Fallback mặc định an toàn cho box collider kích thước 1m x 1m x 1m
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.0, 1.0, 1.0),
        parent_frame=obj.local_frame,
        collider_id=collider_id,
        collider_type=ColliderType.AABB,
        parameters={"source": "default_box_fallback"},
    )
    return create_box_collider(req)
