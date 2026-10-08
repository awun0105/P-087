"""Unit tests cho SIM-04 Deterministic Preflight rules và engine."""

import json
import math
from pathlib import Path

import pytest

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.scene import SceneIR, SceneObjectState
from src.models.contracts.validation import PreflightRuleId, RuleResult
from src.services.simulation.preflight import run_preflight
from src.services.simulation.preflight.rules import check_object_bounds, check_transforms

FIXTURES = Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def valid_scene() -> SceneIR:
    """Fixture SceneIR hợp lệ chuẩn."""
    payload = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    return SceneIR.model_validate(payload)


def test_preflight_on_valid_scene_fixture_passes(valid_scene: SceneIR) -> None:
    """SceneIR fixture chuẩn phải vượt qua toàn bộ các rule preflight."""
    artifact_root = FIXTURES / "artifact_store"
    report = run_preflight(valid_scene, artifact_store_root=artifact_root)

    assert report.blocking_result == RuleResult.PASS
    assert all(r.result == RuleResult.PASS for r in report.rules)
    assert report.scene_revision == valid_scene.scene_revision
    assert report.scene_ir_checksum == valid_scene.scene_ir_checksum
    verify_content_checksum(report, "report_checksum")


def test_preflight_fails_when_metric_scale_unconfirmed(valid_scene: SceneIR) -> None:
    """Thiếu metric scale đã xác nhận phải chặn quy trình (METRIC_SCALE_MISSING)."""
    corrupt = valid_scene.model_copy(deep=True)
    corrupt.metric_scale.status = "UNCONFIRMED"

    report = run_preflight(corrupt)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.METRIC_SCALE_MISSING)
    assert rule.result == RuleResult.FAIL
    assert rule.remediation is not None


def test_preflight_fails_when_active_object_collider_missing(valid_scene: SceneIR) -> None:
    """Vật thể active thiếu collider phải kích hoạt COLLIDER_MISSING."""
    corrupt = valid_scene.model_copy(deep=True)
    target_obj = corrupt.objects[0]
    target_obj.collider = None

    report = run_preflight(corrupt)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.COLLIDER_MISSING)
    assert rule.result == RuleResult.FAIL
    assert target_obj.id in rule.affected_object_ids


def test_preflight_fails_when_environment_collider_missing(valid_scene: SceneIR) -> None:
    """Môi trường thiếu collider_ref phải kích hoạt COLLIDER_MISSING."""
    corrupt = valid_scene.model_copy(deep=True)
    corrupt.environment.collider_ref = None

    report = run_preflight(corrupt)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.COLLIDER_MISSING)
    assert rule.result == RuleResult.FAIL
    assert "environment" in rule.affected_object_ids


def test_preflight_fails_when_transform_invalid(valid_scene: SceneIR) -> None:
    """Quaternion không chuẩn hóa hoặc translation NaN phải kích hoạt TRANSFORM_INVALID."""
    corrupt = valid_scene.model_copy(deep=True)
    corrupt.objects[0].transform.rotation_quaternion_xyzw = (0.0, 0.0, 0.0, 0.5)

    report = run_preflight(corrupt)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.TRANSFORM_INVALID)
    assert rule.result == RuleResult.FAIL
    assert corrupt.objects[0].id in rule.affected_object_ids


def test_preflight_fails_when_object_out_of_bounds(valid_scene: SceneIR) -> None:
    """Vật thể lún sâu dưới sàn (z < -0.1) phải kích hoạt OBJECT_OUT_OF_BOUNDS."""
    corrupt = valid_scene.model_copy(deep=True)
    corrupt.objects[0].transform.translation_xyz = (1.0, 2.0, -0.5)

    report = run_preflight(corrupt)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.OBJECT_OUT_OF_BOUNDS)
    assert rule.result == RuleResult.FAIL
    assert corrupt.objects[0].id in rule.affected_object_ids


@pytest.mark.parametrize(
    ("dimensions", "expected"),
    [
        ((2.0, 0.2, 0.4), RuleResult.FAIL),
        ((0.2, 0.2, 0.4), RuleResult.PASS),
    ],
)
def test_preflight_bounds_use_composed_rotated_box_collider(
    valid_scene: SceneIR, dimensions: tuple[float, float, float], expected: RuleResult
) -> None:
    scene = valid_scene.model_copy(deep=True)
    obj = scene.objects[0]
    quarter_turn = (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5))
    obj.transform = obj.transform.model_copy(
        update={
            "translation_xyz": (49.2, 0.0, 0.5),
            "rotation_quaternion_xyzw": quarter_turn,
        }
    )
    assert obj.collider is not None
    local_transform = obj.collider.local_transform.model_copy(
        update={
            "translation_xyz": (0.5, 0.0, 0.0),
            "rotation_quaternion_xyzw": quarter_turn,
        }
    )
    obj.collider = obj.collider.model_copy(update={"dimensions_xyz_m": dimensions, "local_transform": local_transform})

    rule = check_object_bounds(scene)

    assert rule.result == expected
    assert (obj.id in rule.affected_object_ids) is (expected == RuleResult.FAIL)


def test_preflight_transform_rule_checks_local_collider_pose(valid_scene: SceneIR) -> None:
    scene = valid_scene.model_copy(deep=True)
    obj = scene.objects[0]
    assert obj.collider is not None
    local_transform = obj.collider.local_transform.model_copy(update={"rotation_quaternion_xyzw": (0.0, 0.0, 0.0, 0.5)})
    obj.collider = obj.collider.model_copy(update={"local_transform": local_transform})

    rule = check_transforms(scene)

    assert rule.result == RuleResult.FAIL
    assert obj.id in rule.affected_object_ids


def test_preflight_manual_collider_override_checks_vertical_extent(valid_scene: SceneIR) -> None:
    scene = valid_scene.model_copy(deep=True)
    obj = scene.objects[0]
    obj.transform = obj.transform.model_copy(update={"translation_xyz": (1.0, 2.0, 0.2)})
    assert obj.collider is not None
    local_transform = obj.collider.local_transform.model_copy(update={"translation_xyz": (0.0, 0.0, -0.11)})
    collider = obj.collider.model_copy(
        update={
            "dimensions_xyz_m": (0.2, 0.2, 0.4),
            "local_transform": local_transform,
            "provenance": {**obj.collider.provenance, "manual_override": {"operation": "collider_edit"}},
        }
    )
    obj.collider = collider

    rule = check_object_bounds(scene)

    assert rule.result == RuleResult.FAIL
    assert obj.id in rule.affected_object_ids


def test_preflight_fails_when_object_confirmation_incomplete(valid_scene: SceneIR) -> None:
    """Vật thể còn ở trạng thái CANDIDATE phải kích hoạt OBJECT_CONFIRMATION_INCOMPLETE."""
    corrupt = valid_scene.model_copy(deep=True)
    corrupt.objects[0].state = SceneObjectState.CANDIDATE

    report = run_preflight(corrupt)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.OBJECT_CONFIRMATION_INCOMPLETE)
    assert rule.result == RuleResult.FAIL
    assert corrupt.objects[0].id in rule.affected_object_ids


def test_preflight_fails_when_required_artifact_missing(valid_scene: SceneIR, tmp_path: Path) -> None:
    """Tham chiếu tới artifact không tồn tại trên đĩa phải kích hoạt REQUIRED_ARTIFACT_MISSING."""
    empty_store = tmp_path / "empty_store"
    empty_store.mkdir()

    report = run_preflight(valid_scene, artifact_store_root=empty_store)
    assert report.blocking_result == RuleResult.FAIL

    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.REQUIRED_ARTIFACT_MISSING)
    assert rule.result == RuleResult.FAIL
    assert len(rule.affected_object_ids) > 0


def test_error_and_fail_cannot_become_pass(valid_scene: SceneIR) -> None:
    """Quy tắc bất biến: Chỉ khi 100% rules PASS thì blocking_result mới là PASS."""
    corrupt = valid_scene.model_copy(deep=True)
    corrupt.objects[0].collider = None
    corrupt.objects[1].state = SceneObjectState.CANDIDATE

    report = run_preflight(corrupt)
    assert report.blocking_result != RuleResult.PASS
    assert report.blocking_result == RuleResult.FAIL


def test_floor_detected_by_semantic_class(valid_scene: SceneIR) -> None:
    """Đối tượng có semantic_class='surface' hoặc 'floor' được nhận diện là sàn, không gây false negative."""
    scene = valid_scene.model_copy(deep=True)
    # Tìm đối tượng floor trong fixture và đổi id/name sang định danh không chứa chữ 'floor'/'ground'
    floor_obj = next(o for o in scene.objects if "floor" in o.id)
    floor_obj.id = "obj-alpha-001"
    floor_obj.name = "Custom Warehouse Surface Area"
    floor_obj.semantic_class = "surface"
    floor_obj.collider = None

    artifact_root = FIXTURES / "artifact_store"
    report = run_preflight(scene, artifact_store_root=artifact_root)
    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.COLLIDER_MISSING)
    assert rule.result == RuleResult.PASS
    assert "obj-alpha-001" not in rule.affected_object_ids


def test_floor_detected_by_tags_or_provenance(valid_scene: SceneIR) -> None:
    """Đối tượng có tag trong tags hoặc thuộc tính trong provenance được nhận diện là sàn."""
    scene = valid_scene.model_copy(deep=True)
    floor_obj = next(o for o in scene.objects if "floor" in o.id)
    floor_obj.id = "obj-deck-42"
    floor_obj.name = "Loading Bay Deck"
    floor_obj.tags = ["deck", "walkway"]
    floor_obj.provenance = {"category": "mat_san", "is_floor": True}
    floor_obj.collider = None

    artifact_root = FIXTURES / "artifact_store"
    report = run_preflight(scene, artifact_store_root=artifact_root)
    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.COLLIDER_MISSING)
    assert rule.result == RuleResult.PASS
    assert "obj-deck-42" not in rule.affected_object_ids


def test_non_floor_object_without_collider_triggers_failure(valid_scene: SceneIR) -> None:
    """Vật thể không phải sàn (ví dụ: rack, pallet) thiếu collider vẫn bị bắt lỗi COLLIDER_MISSING chính xác."""
    scene = valid_scene.model_copy(deep=True)
    pallet = next(o for o in scene.objects if "pallet" in o.id)
    pallet.id = "obj-storage-99"
    pallet.name = "Storage Unit Surface Structure"  # Chứa từ surface nhưng semantic_class là pallet
    pallet.semantic_class = "pallet"
    pallet.collider = None

    report = run_preflight(scene)
    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.COLLIDER_MISSING)
    assert rule.result == RuleResult.FAIL
    assert "obj-storage-99" in rule.affected_object_ids


def test_generic_name_floor_object_recognized_via_tags_or_semantic_class(valid_scene: SceneIR) -> None:
    """Đối tượng có tên chung chung (ví dụ: 'Object_01') nhưng có tags hoặc semantic_class là sàn vẫn PASS."""
    scene = valid_scene.model_copy(deep=True)
    floor_obj = next(o for o in scene.objects if "floor" in o.id)
    floor_obj.id = "Object_01"
    floor_obj.name = "Object_01"  # Hoàn toàn không chứa từ 'floor' hay 'ground' trong tên/ID
    floor_obj.semantic_class = "floor"
    floor_obj.tags = ["surface", "walkway"]
    floor_obj.collider = None

    artifact_root = FIXTURES / "artifact_store"
    report = run_preflight(scene, artifact_store_root=artifact_root)
    rule = next(r for r in report.rules if r.rule_id == PreflightRuleId.COLLIDER_MISSING)
    assert rule.result == RuleResult.PASS
    assert "Object_01" not in rule.affected_object_ids
