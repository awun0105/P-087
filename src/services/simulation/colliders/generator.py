"""Tạo và quản lý các loại ColliderSpec (AABB, OBB, Convex Hull, Simplified Mesh)."""

from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial.transform import Rotation
import trimesh

from src.models.contracts.artifacts import Identifier, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import ColliderSpec, ColliderType, SceneObject

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
    if any(d <= 0.0 for d in req.dimensions_xyz_m):
        raise ValueError(f"dimensions_xyz_m phải dương, nhận được: {req.dimensions_xyz_m}")

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
) -> ColliderSpec:
    """Tạo Analytic Ground Plane collider phẳng tuyệt đối theo Safeguard 1."""
    req = BoxSpecRequest(
        dimensions_xyz_m=(100.0, 100.0, 0.05),
        parent_frame=parent_frame,
        collider_id=collider_id,
        collider_type=ColliderType.AABB,
        offset_xyz=(0.0, 0.0, -0.025),
        parameters={"analytic_ground_plane": True, "friction": 0.8},
    )
    return create_box_collider(req)


def _matrix_to_quaternion(matrix: np.ndarray) -> tuple[float, float, float, float]:
    """Chuyển đổi ma trận xoay 3x3 sang quaternion (x, y, z, w)."""
    rot = Rotation.from_matrix(matrix)
    q = rot.as_quat()
    return float(q[0]), float(q[1]), float(q[2]), float(q[3])


def _extract_obb_params(
    mesh: trimesh.Trimesh,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float, float]]:
    """Tính kích thước, vị trí offset và góc quay quaternion của OBB."""
    obb = mesh.bounding_box_oriented
    extents = tuple(max(float(x), 0.01) for x in obb.extents)
    tf = obb.transform
    trans = (float(tf[0, 3]), float(tf[1, 3]), float(tf[2, 3]))
    rot_q = _matrix_to_quaternion(tf[:3, :3])
    return extents, trans, rot_q


def generate_collider_from_geometry(
    geometry: trimesh.Trimesh | trimesh.PointCloud,
    collider_type: ColliderType,
    parent_frame: Identifier,
    collider_id: Identifier,
) -> ColliderSpec:
    """Sinh ColliderSpec từ đối tượng hình học (Trimesh hoặc PointCloud)."""
    if len(geometry.vertices) == 0:
        raise ValueError("Geometry không chứa đỉnh nào để sinh collider.")

    if collider_type == ColliderType.OBB and isinstance(geometry, trimesh.Trimesh):
        extents, trans, rot_q = _extract_obb_params(geometry)
        req = BoxSpecRequest(
            dimensions_xyz_m=extents,
            parent_frame=parent_frame,
            collider_id=collider_id,
            collider_type=ColliderType.OBB,
            offset_xyz=trans,
            rotation_xyzw=rot_q,
        )
        return create_box_collider(req)

    # AABB hoặc fallback cho PointCloud
    bounds = geometry.bounds
    dims = tuple(max(float(bounds[1][i] - bounds[0][i]), 0.01) for i in range(3))
    center = tuple(float((bounds[0][i] + bounds[1][i]) / 2.0) for i in range(3))

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

    # Đọc file mesh nếu được cung cấp
    if geometry_file_path is not None and geometry_file_path.is_file():
        loaded = trimesh.load(str(geometry_file_path))
        if isinstance(loaded, (trimesh.Trimesh, trimesh.PointCloud)):
            return generate_collider_from_geometry(
                geometry=loaded,
                collider_type=preferred_type,
                parent_frame=obj.local_frame,
                collider_id=collider_id,
            )

    # Fallback mặc định an toàn cho box collider kích thước 1m x 1m x 1m
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.0, 1.0, 1.0),
        parent_frame=obj.local_frame,
        collider_id=collider_id,
        collider_type=ColliderType.AABB,
        parameters={"source": "default_box_fallback"},
    )
    return create_box_collider(req)

