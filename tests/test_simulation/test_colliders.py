"""Unit tests cho SIM-02 Collider Generation utilities."""

import pytest
import trimesh

from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
)
from src.services.simulation.colliders import (
    BoxSpecRequest,
    create_box_collider,
    create_ground_plane_collider,
    generate_collider_from_geometry,
    generate_object_collider,
)


def test_create_box_collider_valid() -> None:
    """Tạo Box collider hợp lệ với kích thước dương."""
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.2, 0.8, 1.5),
        parent_frame="object-rack-001",
        collider_id="collider-rack-001",
        collider_type=ColliderType.AABB,
    )
    spec = create_box_collider(req)

    assert spec.collider_id == "collider-rack-001"
    assert spec.collider_type == ColliderType.AABB
    assert spec.dimensions_xyz_m == (1.2, 0.8, 1.5)
    assert spec.local_transform.parent_frame == "object-rack-001"
    assert spec.local_transform.local_frame == "collider-rack-001"


def test_create_box_collider_rejects_non_positive_dimensions() -> None:
    """Kích thước collider <= 0 phải báo lỗi rõ ràng."""
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.0, -0.5, 1.0),
        parent_frame="object-001",
        collider_id="collider-001",
    )
    with pytest.raises(ValueError, match="dimensions_xyz_m phải dương"):
        create_box_collider(req)


def test_create_ground_plane_collider_safeguard1() -> None:
    """Safeguard 1: Mặt sàn tĩnh dùng Analytic Ground Plane phẳng tuyệt đối."""
    plane = create_ground_plane_collider(parent_frame="world")

    assert plane.collider_type == ColliderType.AABB
    assert plane.dimensions_xyz_m[2] <= 0.1  # chiều dày mỏng
    assert plane.parameters.get("analytic_ground_plane") is True
    assert plane.local_transform.parent_frame == "world"


def test_generate_aabb_from_trimesh() -> None:
    """Sinh AABB từ Trimesh box chuẩn xác về kích thước và tâm."""
    box = trimesh.creation.box(extents=(2.0, 1.0, 3.0))
    spec = generate_collider_from_geometry(
        geometry=box,
        collider_type=ColliderType.AABB,
        parent_frame="obj-box",
        collider_id="col-box",
    )

    assert spec.collider_type == ColliderType.AABB
    assert pytest.approx(spec.dimensions_xyz_m[0], abs=1e-2) == 2.0
    assert pytest.approx(spec.dimensions_xyz_m[1], abs=1e-2) == 1.0
    assert pytest.approx(spec.dimensions_xyz_m[2], abs=1e-2) == 3.0


def test_generate_obb_from_rotated_mesh() -> None:
    """Sinh OBB từ mesh có góc xoay, đảm bảo quaternion chuẩn hóa."""
    box = trimesh.creation.box(extents=(1.5, 0.5, 2.0))
    # Xoay quanh trục Z 45 độ
    matrix = trimesh.transformations.rotation_matrix(angle=0.785, direction=[0, 0, 1])
    box.apply_transform(matrix)

    spec = generate_collider_from_geometry(
        geometry=box,
        collider_type=ColliderType.OBB,
        parent_frame="obj-rot",
        collider_id="col-rot",
    )

    assert spec.collider_type == ColliderType.OBB
    assert len(spec.dimensions_xyz_m) == 3
    q = spec.local_transform.rotation_quaternion_xyzw
    norm_sq = sum(v * v for v in q)
    assert 0.98 <= norm_sq <= 1.02


def test_generate_collider_from_pointcloud() -> None:
    """Sinh AABB hợp lệ từ PointCloud."""
    points = trimesh.points.PointCloud(
        vertices=[[0.0, 0.0, 0.0], [1.0, 2.0, 0.5], [0.5, 1.0, 0.2]]
    )
    spec = generate_collider_from_geometry(
        geometry=points,
        collider_type=ColliderType.AABB,
        parent_frame="obj-pc",
        collider_id="col-pc",
    )

    assert spec.collider_type == ColliderType.AABB
    assert spec.dimensions_xyz_m == (1.0, 2.0, 0.5)


def test_generate_object_collider_safeguard2_priority() -> None:
    """Safeguard 2: Ưu tiên Box từ primitive_dimensions_xyz_m cho SceneObject."""
    obj = SceneObject(
        id="object-pallet-101",
        name="Warehouse Pallet",
        state=SceneObjectState.CONFIRMED,
        origin=SceneObjectOrigin.RECONSTRUCTED,
        active=True,
        local_frame="object-pallet-101",
        transform=Transform(
            parent_frame="world",
            local_frame="object-pallet-101",
            translation_xyz=(2.0, 3.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        geometry_ref={
            "artifact_type": "ObjectGeometry",
            "schema_version": "1.0",
            "artifact_uri": "artifact://jobs/job-1/scene/pallet.ply",
            "artifact_checksum": "sha256:" + "1" * 64,
            "data_class": "derived",
            "producer_stage": "ST-SCENE-DECOMPOSE",
            "job_id": "job-1",
        },
        primitive_dimensions_xyz_m=(1.2, 0.8, 0.15),
        provenance={"test": True},
    )

    spec = generate_object_collider(obj)
    assert spec.dimensions_xyz_m == (1.2, 0.8, 0.15)
    assert spec.local_transform.parent_frame == obj.local_frame

    # Gắn trực tiếp collider vào SceneObject không gây lỗi model_validator
    enriched_obj = obj.model_copy(update={"collider": spec})
    assert enriched_obj.collider is not None
    assert enriched_obj.collider.local_transform.parent_frame == enriched_obj.local_frame


def test_generate_collider_rejects_empty_geometry() -> None:
    """Geometry rỗng không có đỉnh phải báo lỗi."""
    empty_pc = trimesh.points.PointCloud(vertices=[])
    with pytest.raises(ValueError, match="không chứa đỉnh nào"):
        generate_collider_from_geometry(
            geometry=empty_pc,
            collider_type=ColliderType.AABB,
            parent_frame="world",
            collider_id="col-empty",
        )

