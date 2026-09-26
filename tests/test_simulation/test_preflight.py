"""Unit tests cho SIM-04 Deterministic Preflight rules và engine."""

import json
from pathlib import Path

import pytest

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.scene import SceneIR, SceneObjectState
from src.models.contracts.validation import PreflightRuleId, RuleResult
from src.services.simulation.preflight import run_preflight

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
