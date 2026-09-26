"""Cài đặt các rule audit tĩnh (deterministic preflight rules) cho EX-SIM."""

import math
from pathlib import Path

from src.models.contracts.artifacts import Identifier, ProductArtifactRef
from src.models.contracts.scene import SceneIR, SceneObject, SceneObjectState
from src.models.contracts.validation import PreflightRule, PreflightRuleId, RuleResult

SEVERITY_BLOCKING: Identifier = "blocking"

FLOOR_SEMANTIC_CLASSES: frozenset[str] = frozenset(
    {
        "floor",
        "ground",
        "ground_plane",
        "floor_plane",
        "surface",
        "deck",
        "walkway",
        "terrain",
        "mat_san",
        "san",
    }
)


def _matches_floor_semantics(val: str) -> bool:
    """Kiểm tra một chuỗi ngữ nghĩa có khớp với định danh sàn hay không."""
    clean = val.strip().lower()
    if clean in FLOOR_SEMANTIC_CLASSES:
        return True
    words = set(clean.replace("-", " ").replace("_", " ").split())
    return any(kw in words for kw in FLOOR_SEMANTIC_CLASSES)


def check_metric_scale(scene: SceneIR) -> PreflightRule:
    """Kiểm tra metric scale đã được xác nhận và có tỷ lệ mét hợp lệ."""
    scale = scene.metric_scale
    if scale.status != "CONFIRMED" or scale.meters_per_unit <= 0.0:
        return PreflightRule(
            rule_id=PreflightRuleId.METRIC_SCALE_MISSING,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=[],
            evidence_refs=[],
            remediation="Cần xác nhận metric_scale (status=CONFIRMED và meters_per_unit > 0).",
        )
    return PreflightRule(
        rule_id=PreflightRuleId.METRIC_SCALE_MISSING,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=[],
        evidence_refs=[],
    )


def _is_floor_object(obj: SceneObject) -> bool:
    """Kiểm tra đối tượng có thuộc ngữ nghĩa mặt sàn hay không.

    Ưu tiên thuộc tính ngữ nghĩa cấu trúc (semantic_class, tags, provenance)
    thay vì chỉ so sánh chuỗi tên/id để chống false negatives và false positives.
    """
    # 1. Nếu có semantic_class tường minh: đây là source of truth cao nhất
    if obj.semantic_class is not None and obj.semantic_class.strip():
        return _matches_floor_semantics(obj.semantic_class)

    # 2. Kiểm tra danh sách tags tường minh
    if obj.tags:
        for tag in obj.tags:
            if _matches_floor_semantics(tag):
                return True

    # 3. Kiểm tra provenance metadata (ví dụ từ SAM2 hoặc scene decomposition)
    prov = obj.provenance or {}
    for key in ("semantic_class", "category", "role", "label", "class_name"):
        val = prov.get(key)
        if isinstance(val, str) and val.strip():
            if _matches_floor_semantics(val):
                return True
    if prov.get("is_floor") is True or prov.get("is_ground") is True:
        return True

    # 4. Fallback chỉ khi hoàn toàn không có metadata ngữ nghĩa: kiểm tra từ khóa trong name/id
    for token in (obj.name, obj.id):
        if _matches_floor_semantics(token):
            return True

    return False


def check_collider_presence(scene: SceneIR) -> PreflightRule:
    """Kiểm tra mọi active SceneObject và environment đều có collider spec hợp lệ."""
    missing_ids: list[Identifier] = []
    has_env_floor_collider = scene.environment.collider_ref is not None
    if not has_env_floor_collider:
        missing_ids.append("environment")

    for obj in scene.objects:
        if not obj.active:
            continue
        if obj.collider is None:
            # Nếu là vật thể sàn và environment đã có floor collider thì hợp lệ
            if has_env_floor_collider and _is_floor_object(obj):
                continue
            missing_ids.append(obj.id)

    if missing_ids:
        return PreflightRule(
            rule_id=PreflightRuleId.COLLIDER_MISSING,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=missing_ids,
            evidence_refs=[],
            remediation="Chạy SIM-02 để sinh collider cho các vật thể active còn thiếu.",
        )
    return PreflightRule(
        rule_id=PreflightRuleId.COLLIDER_MISSING,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=[],
        evidence_refs=[],
    )


def _is_valid_quaternion(q: tuple[float, float, float, float]) -> bool:
    """Kiểm tra quaternion chuẩn hóa và không chứa giá trị bất thường."""
    if any(math.isnan(v) or math.isinf(v) for v in q):
        return False
    norm_sq = sum(v * v for v in q)
    return 0.98 <= norm_sq <= 1.02


def check_transforms(scene: SceneIR) -> PreflightRule:
    """Kiểm tra các ma trận vị trí và góc quay quaternion của từng object."""
    invalid_ids: list[Identifier] = []
    for obj in scene.objects:
        t = obj.transform
        trans_invalid = any(math.isnan(v) or math.isinf(v) for v in t.translation_xyz)
        rot_invalid = not _is_valid_quaternion(t.rotation_quaternion_xyzw)
        if trans_invalid or rot_invalid:
            invalid_ids.append(obj.id)

    if invalid_ids:
        return PreflightRule(
            rule_id=PreflightRuleId.TRANSFORM_INVALID,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=invalid_ids,
            evidence_refs=[],
            remediation="Hiệu chỉnh translation và quaternion hữu hạn cho các vật thể lỗi.",
        )
    return PreflightRule(
        rule_id=PreflightRuleId.TRANSFORM_INVALID,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=[],
        evidence_refs=[],
    )


def check_object_bounds(
    scene: SceneIR,
    workspace_min_xy: tuple[float, float] = (-50.0, -50.0),
    workspace_max_xy: tuple[float, float] = (50.0, 50.0),
) -> PreflightRule:
    """Kiểm tra vật thể không nằm ngoài ranh giới bản đồ hoặc lún sâu dưới sàn (z < -0.1)."""
    out_ids: list[Identifier] = []
    for obj in scene.objects:
        if not obj.active:
            continue
        x, y, z = obj.transform.translation_xyz
        is_outside_xy = (
            x < workspace_min_xy[0] or x > workspace_max_xy[0] or y < workspace_min_xy[1] or y > workspace_max_xy[1]
        )
        is_subsurface = z < -0.1
        if is_outside_xy or is_subsurface:
            out_ids.append(obj.id)

    if out_ids:
        return PreflightRule(
            rule_id=PreflightRuleId.OBJECT_OUT_OF_BOUNDS,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=out_ids,
            evidence_refs=[],
            remediation="Điều chỉnh vật thể về trong ranh giới kho và nằm trên mặt sàn z >= 0.",
        )
    return PreflightRule(
        rule_id=PreflightRuleId.OBJECT_OUT_OF_BOUNDS,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=[],
        evidence_refs=[],
    )


def check_object_confirmation(scene: SceneIR) -> PreflightRule:
    """Kiểm tra không còn vật thể active nào ở trạng thái chưa xác nhận (CANDIDATE)."""
    unconfirmed: list[Identifier] = [
        obj.id for obj in scene.objects if obj.active and obj.state == SceneObjectState.CANDIDATE
    ]
    if unconfirmed:
        return PreflightRule(
            rule_id=PreflightRuleId.OBJECT_CONFIRMATION_INCOMPLETE,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=unconfirmed,
            evidence_refs=[],
            remediation="Người dùng cần CONFIRM hoặc IGNORE các candidate objects qua HITL UI.",
        )
    return PreflightRule(
        rule_id=PreflightRuleId.OBJECT_CONFIRMATION_INCOMPLETE,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=[],
        evidence_refs=[],
    )


def check_required_artifacts(
    scene: SceneIR,
    artifact_store_root: Path | None = None,
) -> PreflightRule:
    """Kiểm tra sự tồn tại của các file artifact được tham chiếu (mesh geometry, collider)."""
    if artifact_store_root is None:
        return PreflightRule(
            rule_id=PreflightRuleId.REQUIRED_ARTIFACT_MISSING,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.PASS,
            affected_object_ids=[],
            evidence_refs=[],
        )

    missing_objects: list[Identifier] = []
    missing_refs: list[ProductArtifactRef] = []

    def _verify_ref(ref: ProductArtifactRef, obj_id: Identifier) -> None:
        rel = ref.artifact_uri.replace("artifact://", "")
        file_path = artifact_store_root / rel
        if not file_path.is_file():
            missing_objects.append(obj_id)
            missing_refs.append(ref)

    _verify_ref(scene.environment.geometry_ref, "environment")
    if scene.environment.collider_ref:
        _verify_ref(scene.environment.collider_ref, "environment")

    for obj in scene.objects:
        if not obj.active:
            continue
        _verify_ref(obj.geometry_ref, obj.id)
        if obj.collider and obj.collider.geometry_ref:
            _verify_ref(obj.collider.geometry_ref, obj.id)

    if missing_objects:
        return PreflightRule(
            rule_id=PreflightRuleId.REQUIRED_ARTIFACT_MISSING,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=sorted(list(set(missing_objects))),
            evidence_refs=missing_refs,
            remediation="Kiểm tra artifact store, các artifact trỏ tới không tồn tại trên đĩa.",
        )
    return PreflightRule(
        rule_id=PreflightRuleId.REQUIRED_ARTIFACT_MISSING,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=[],
        evidence_refs=[],
    )
