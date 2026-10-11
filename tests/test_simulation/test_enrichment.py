"""Unit và contract tests cho SIM-03 Physics Enrichment."""

import json
from pathlib import Path

import pytest

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.scene import (
    ColliderSpec,
    ColliderType,
    SceneIR,
    Transform,
)
from src.services.simulation.colliders.generator import BoxSpecRequest, create_box_collider
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.preflight.engine import run_preflight

FIXTURE_PATH = Path("fixtures/scene_ir/scene.json")


@pytest.fixture
def base_scene() -> SceneIR:
    """Nạp fixture SceneIR chuẩn."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return SceneIR.model_validate(data)


@pytest.fixture
def uncollided_scene(base_scene: SceneIR) -> SceneIR:
    """Tạo SceneIR trong đó các objects chưa có collider."""
    stripped_objects = [obj.model_copy(update={"collider": None}) for obj in base_scene.objects]
    env_stripped = base_scene.environment.model_copy(update={"collider_ref": None})
    return base_scene.model_copy(
        update={
            "objects": stripped_objects,
            "environment": env_stripped,
            "scene_revision": "rev-001",
        }
    )


def test_enrichment_creates_valid_scene_revision_and_checksum(uncollided_scene: SceneIR) -> None:
    """Enrichment tạo revision mới và tính checksum tự thân hợp lệ."""
    enriched = enrich_scene_physics(uncollided_scene)

    assert enriched.scene_revision == "rev-002"
    assert enriched.provenance.get("previous_revision") == "rev-001"
    assert enriched.provenance.get("producer_stage") == "ST-PHYSICS-ENRICH"

    # Kiểm tra checksum đã đổi so với scene ban đầu
    assert enriched.scene_ir_checksum != uncollided_scene.scene_ir_checksum
    # Kiểm tra checksum tuyệt đối khớp với canonical content
    verify_content_checksum(enriched, "scene_ir_checksum")


def test_enrichment_auto_generates_colliders_for_all_objects(uncollided_scene: SceneIR) -> None:
    """Tự động sinh Box Collider cho mọi vật thể chưa có collider."""
    enriched = enrich_scene_physics(uncollided_scene, auto_generate_missing=True)

    for obj in enriched.objects:
        assert obj.collider is not None
        assert obj.collider.collider_id == f"collider-{obj.id}"
        assert obj.collider.local_transform.parent_frame == obj.local_frame
        assert obj.collider.dimensions_xyz_m is not None
        assert all(d > 0 for d in obj.collider.dimensions_xyz_m)


def test_enrichment_attaches_explicit_colliders(uncollided_scene: SceneIR) -> None:
    """Gắn chính xác ColliderSpec do người dùng/hệ thống cung cấp."""
    target_obj_id = uncollided_scene.objects[0].id
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.5, 2.5, 3.5),
        parent_frame=target_obj_id,
        collider_id=f"custom-col-{target_obj_id}",
        collider_type=ColliderType.OBB,
    )
    custom_col = create_box_collider(req)

    enriched = enrich_scene_physics(
        uncollided_scene,
        colliders=[custom_col],
        auto_generate_missing=True,
    )

    first_obj = next(o for o in enriched.objects if o.id == target_obj_id)
    assert first_obj.collider is not None
    assert first_obj.collider.collider_id == f"custom-col-{target_obj_id}"
    assert first_obj.collider.collider_type == ColliderType.OBB
    assert first_obj.collider.dimensions_xyz_m == (1.5, 2.5, 3.5)


def test_enrichment_rejects_mismatched_parent_frame(uncollided_scene: SceneIR) -> None:
    """Báo lỗi khi parent_frame của collider không khớp với local_frame của object."""
    target_obj_id = uncollided_scene.objects[0].id
    bad_col = ColliderSpec(
        collider_id=target_obj_id,
        collider_type=ColliderType.AABB,
        local_transform=Transform(
            parent_frame="wrong_frame",
            local_frame="col_frame",
            translation_xyz=(0.0, 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        dimensions_xyz_m=(1.0, 1.0, 1.0),
        parameters={},
        provenance={"test": True},
    )

    with pytest.raises(ValueError, match="không khớp với object.local_frame"):
        enrich_scene_physics(uncollided_scene, colliders=[bad_col])


def test_enrichment_rejects_duplicate_colliders(uncollided_scene: SceneIR) -> None:
    """Từ chối nếu danh sách colliders truyền vào chứa 2 collider trùng ID."""
    req = BoxSpecRequest(
        dimensions_xyz_m=(1.0, 1.0, 1.0),
        parent_frame="obj-1",
        collider_id="duplicate-id",
    )
    col1 = create_box_collider(req)
    col2 = create_box_collider(req)

    with pytest.raises(ValueError, match="Trùng lặp collider_id"):
        enrich_scene_physics(uncollided_scene, colliders=[col1, col2])


def test_enrichment_adds_ground_plane_if_missing(uncollided_scene: SceneIR) -> None:
    """Tự động thêm tham chiếu Ground Plane collider nếu môi trường chưa có."""
    enriched = enrich_scene_physics(uncollided_scene, add_ground_plane=True)

    assert enriched.environment.collider_ref is not None
    assert enriched.environment.collider_ref.artifact_type == "ColliderGeometry"
    assert "floor_collider" in enriched.environment.collider_ref.artifact_uri


def test_enriched_scene_passes_deterministic_preflight(uncollided_scene: SceneIR) -> None:
    """Scene sau khi được làm giàu vật lý phải vượt qua kiểm tra tĩnh Deterministic Preflight (SIM-04)."""
    # Trước enrichment: Thiếu collider -> Preflight FAIL
    report_before = run_preflight(uncollided_scene)
    assert report_before.blocking_result == "FAIL"

    # Sau enrichment: Mọi vật thể có collider, sàn có collider -> Preflight PASS
    enriched = enrich_scene_physics(uncollided_scene)
    report_after = run_preflight(enriched)
    assert report_after.blocking_result == "PASS"
