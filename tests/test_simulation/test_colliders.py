"""Unit tests cho SIM-02 Collider Generation utilities."""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import (
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
    points = trimesh.points.PointCloud(vertices=[[0.0, 0.0, 0.0], [1.0, 2.0, 0.5], [0.5, 1.0, 0.2]])
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
    """Geometry rỗng không có đỉnh phải báo lỗi khi fallback_on_empty=False (mặc định)."""
    empty_pc = trimesh.points.PointCloud(vertices=[])
    with pytest.raises(ValueError, match="không chứa đỉnh nào"):
        generate_collider_from_geometry(
            geometry=empty_pc,
            collider_type=ColliderType.AABB,
            parent_frame="world",
            collider_id="col-empty",
            fallback_on_empty=False,
        )


def test_generate_collider_fallback_on_empty() -> None:
    """Khi fallback_on_empty=True, geometry rỗng không crash mà sử dụng deep fallback an toàn."""
    empty_pc = trimesh.points.PointCloud(vertices=[])
    spec = generate_collider_from_geometry(
        geometry=empty_pc,
        collider_type=ColliderType.AABB,
        parent_frame="world",
        collider_id="col-empty-fallback",
        fallback_on_empty=True,
    )
    assert spec is not None
    assert spec.dimensions_xyz_m == (0.01, 0.01, 0.01)
    assert spec.local_transform.translation_xyz == (0.0, 0.0, 0.0)


def test_generate_collider_all_nan_vertices_fallback() -> None:
    """Geometry chứa toàn bộ đỉnh NaN/Inf kích hoạt deep fallback trong _safe_compute_bounds mà không crash."""
    nan_pc = trimesh.points.PointCloud(vertices=[[float("nan"), float("nan"), float("nan")]])
    spec = generate_collider_from_geometry(
        geometry=nan_pc,
        collider_type=ColliderType.AABB,
        parent_frame="world",
        collider_id="col-nan-fallback",
    )
    assert spec is not None
    assert spec.dimensions_xyz_m == (0.01, 0.01, 0.01)
    assert spec.local_transform.translation_xyz == (0.0, 0.0, 0.0)


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide")
def test_degenerate_coplanar_geometry_safe_fallback() -> None:
    """Hình học phẳng (z=0) không gây lỗi Qhull hay chia cho 0, extents được clamp an toàn."""
    # 4 đỉnh trên mặt phẳng 2D (chiều dày z = 0)
    flat_mesh = trimesh.Trimesh(
        vertices=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        faces=[[0, 1, 2], [0, 2, 3]],
    )
    spec = generate_collider_from_geometry(
        geometry=flat_mesh,
        collider_type=ColliderType.OBB,
        parent_frame="obj-flat",
        collider_id="col-flat",
    )
    assert spec.collider_type in (ColliderType.OBB, ColliderType.AABB)
    assert all(d > 0.0 for d in spec.dimensions_xyz_m)
    # Chiều z bị phẳng phải được clamp tối thiểu 0.01m (1cm)
    assert min(spec.dimensions_xyz_m) >= 0.01


def test_ground_plane_thickness_meets_physics_standard() -> None:
    """Safeguard 1: Độ dày sàn 0.05m (5cm) đáp ứng tiêu chuẩn PhysX chống tunneling."""
    plane = create_ground_plane_collider(parent_frame="world")
    assert plane.dimensions_xyz_m[2] == 0.05
    # Mặt trên sàn phải nằm chính xác tại z = 0.0 (offset_z = -0.025)
    offset_z = plane.local_transform.translation_xyz[2]
    assert pytest.approx(offset_z + plane.dimensions_xyz_m[2] / 2.0) == 0.0


def test_create_box_collider_rejects_nan_or_inf() -> None:
    """Dimensions chứa NaN hoặc Inf phải bị từ chối rõ ràng."""
    req_nan = BoxSpecRequest(
        dimensions_xyz_m=(1.0, float("nan"), 1.0),
        parent_frame="obj-1",
        collider_id="col-1",
    )
    with pytest.raises(ValueError, match="dimensions_xyz_m phải dương và hữu hạn"):
        create_box_collider(req_nan)


def test_malformed_mesh_bounds_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Khi mesh.bounds bị None hoặc malformed, collider generation không crash mà fallback an toàn."""
    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    monkeypatch.setattr(trimesh.Trimesh, "bounds", property(lambda self: None))
    monkeypatch.setattr(trimesh.Trimesh, "bounding_box_oriented", property(lambda self: None))

    spec = generate_collider_from_geometry(
        geometry=mesh,
        collider_type=ColliderType.OBB,
        parent_frame="obj-malformed",
        collider_id="col-malformed",
    )
    assert spec is not None
    assert all(d >= 0.01 for d in spec.dimensions_xyz_m)


def test_corrupt_geometry_file_fallback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Khi file geometry bị hỏng/rác, generate_object_collider tự động fallback sang default box 1m3 và log cảnh báo."""
    bad_file = tmp_path / "corrupt.ply"
    bad_file.write_text("CORRUPT HEADER NOT A VALID PLY OR MESH", encoding="utf-8")

    obj = SceneObject(
        id="object-corrupt-001",
        name="Corrupted Mesh Object",
        state=SceneObjectState.CONFIRMED,
        origin=SceneObjectOrigin.RECONSTRUCTED,
        active=True,
        local_frame="object-corrupt-001",
        transform=Transform(
            parent_frame="world",
            local_frame="object-corrupt-001",
            translation_xyz=(0.0, 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        geometry_ref={
            "artifact_type": "ObjectGeometry",
            "schema_version": "1.0",
            "artifact_uri": "artifact://jobs/job-1/scene/corrupt.ply",
            "artifact_checksum": "sha256:" + "0" * 64,
            "data_class": "derived",
            "producer_stage": "ST-SCENE-DECOMPOSE",
            "job_id": "job-1",
        },
        provenance={"test": True},
    )

    import logging

    with caplog.at_level(logging.WARNING):
        spec = generate_object_collider(obj, geometry_file_path=bad_file)
    assert spec is not None
    assert spec.dimensions_xyz_m == (1.0, 1.0, 1.0)
    assert spec.parameters.get("source") == "default_box_fallback"
    assert any("Không thể load/tạo collider" in record.message for record in caplog.records)


def test_safe_compute_bounds_logs_warning_on_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """Kiểm tra _safe_compute_bounds ghi log cảnh báo khi kích hoạt fallback."""
    import logging

    nan_pc = trimesh.points.PointCloud(vertices=[[float("nan"), float("nan"), float("nan")]])
    with caplog.at_level(logging.WARNING):
        spec = generate_collider_from_geometry(
            geometry=nan_pc,
            collider_type=ColliderType.AABB,
            parent_frame="world",
            collider_id="col-nan-log",
        )
    assert spec is not None
    assert any("Kích hoạt fallback an toàn" in record.message for record in caplog.records)


def test_generate_collider_supports_points_attribute() -> None:
    """Hỗ trợ các đối tượng hình học dùng thuộc tính .points thay vì .vertices."""

    class MockPointCloudWithPoints:
        def __init__(self, points: list[list[float]]) -> None:
            self.points = np.array(points, dtype=float)

    custom_geo = MockPointCloudWithPoints([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]])
    spec = generate_collider_from_geometry(
        geometry=custom_geo,  # type: ignore[arg-type]
        collider_type=ColliderType.AABB,
        parent_frame="world",
        collider_id="col-points-attr",
    )
    assert spec is not None
    assert spec.dimensions_xyz_m == (2.0, 2.0, 2.0)
    assert spec.local_transform.translation_xyz == (2.0, 3.0, 4.0)


def test_fallback_center_preserves_object_position_far_from_origin() -> None:
    """Khi bounds lỗi, fallback box giữ đúng vị trí centroid của đối tượng ở xa gốc toạ độ thay vì nhảy về (0,0,0)."""

    class MockMalformedMeshWithCentroid:
        def __init__(self, centroid: tuple[float, float, float]) -> None:
            self.centroid = np.array(centroid)
            self.bounds = None
            self.vertices = np.array([[float("nan"), float("nan"), float("nan")]])

    geo_far = MockMalformedMeshWithCentroid(centroid=(25.0, 50.0, 10.0))
    spec = generate_collider_from_geometry(
        geometry=geo_far,  # type: ignore[arg-type]
        collider_type=ColliderType.AABB,
        parent_frame="world",
        collider_id="col-far-fallback",
    )
    assert spec is not None
    assert spec.dimensions_xyz_m == (0.01, 0.01, 0.01)
    assert spec.local_transform.translation_xyz == (25.0, 50.0, 10.0)


def test_explicit_user_fallback_center() -> None:
    """Caller có thể chỉ định explicit fallback_center khi geometry rỗng/lỗi."""
    empty_pc = trimesh.points.PointCloud(vertices=[])
    spec = generate_collider_from_geometry(
        geometry=empty_pc,
        collider_type=ColliderType.AABB,
        parent_frame="world",
        collider_id="col-explicit-center",
        fallback_on_empty=True,
        fallback_center=(100.0, -50.0, 2.0),
    )
    assert spec is not None
    assert spec.dimensions_xyz_m == (0.01, 0.01, 0.01)
    assert spec.local_transform.translation_xyz == (100.0, -50.0, 2.0)
