"""Cài đặt các rule audit tĩnh (deterministic preflight rules) cho EX-SIM."""

import hashlib
import math
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import Identifier, ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionSourceSelection,
)
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.scene import (
    ColliderType,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
    SourceCollisionMembership,
)
from src.models.contracts.validation import PreflightRule, PreflightRuleId, RuleResult
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.simulation.mesh_geometry import MeshValidationError, load_mesh_parts

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


def _rotation_matrix(q: tuple[float, float, float, float]) -> tuple[tuple[float, float, float], ...]:
    """Return the rotation matrix for a finite, near-unit xyzw quaternion."""
    magnitude = math.sqrt(sum(value * value for value in q))
    x, y, z, w = (value / magnitude for value in q)
    return (
        (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
        (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
        (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
    )


def _box_world_bounds(obj: SceneObject) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Compute edited box bounds after composing object and collider transforms."""
    center = list(obj.transform.translation_xyz)
    object_rotation = (
        _rotation_matrix(obj.transform.rotation_quaternion_xyzw)
        if _is_valid_quaternion(obj.transform.rotation_quaternion_xyzw)
        else None
    )
    collider = obj.collider
    if collider is None:
        return tuple(center), tuple(center)

    local = collider.local_transform
    local_translation = local.translation_xyz
    if object_rotation is not None and all(math.isfinite(value) for value in local_translation):
        for row in range(3):
            center[row] += sum(object_rotation[row][axis] * local_translation[axis] for axis in range(3))

    dimensions = collider.dimensions_xyz_m
    local_quaternion = local.rotation_quaternion_xyzw
    if (
        collider.collider_type not in {ColliderType.AABB, ColliderType.OBB}
        or dimensions is None
        or len(dimensions) != 3
        or any(not math.isfinite(value) or value <= 0.0 for value in dimensions)
        or object_rotation is None
        or not _is_valid_quaternion(local_quaternion)
    ):
        return tuple(center), tuple(center)

    local_rotation = _rotation_matrix(local_quaternion)
    world_rotation = tuple(
        tuple(
            sum(object_rotation[row][axis] * local_rotation[axis][column] for axis in range(3)) for column in range(3)
        )
        for row in range(3)
    )
    half_extents = tuple(
        sum(abs(world_rotation[row][axis]) * dimensions[axis] / 2.0 for axis in range(3)) for row in range(3)
    )
    return (
        tuple(center[axis] - half_extents[axis] for axis in range(3)),
        tuple(center[axis] + half_extents[axis] for axis in range(3)),
    )


def check_transforms(scene: SceneIR) -> PreflightRule:
    """Kiểm tra pose của object và local collider transform."""
    invalid_ids: list[Identifier] = []
    for obj in scene.objects:
        t = obj.transform
        trans_invalid = any(math.isnan(v) or math.isinf(v) for v in t.translation_xyz)
        rot_invalid = not _is_valid_quaternion(t.rotation_quaternion_xyzw)
        collider_invalid = False
        if obj.collider is not None:
            local = obj.collider.local_transform
            collider_invalid = (
                local.parent_frame != obj.local_frame
                or any(not math.isfinite(value) for value in local.translation_xyz)
                or not _is_valid_quaternion(local.rotation_quaternion_xyzw)
            )
        if trans_invalid or rot_invalid or collider_invalid:
            invalid_ids.append(obj.id)

    if invalid_ids:
        return PreflightRule(
            rule_id=PreflightRuleId.TRANSFORM_INVALID,
            severity=SEVERITY_BLOCKING,
            result=RuleResult.FAIL,
            affected_object_ids=invalid_ids,
            evidence_refs=[],
            remediation="Hiệu chỉnh pose của vật thể và local collider transform hữu hạn, đúng frame.",
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
        low, high = _box_world_bounds(obj)
        is_outside_xy = (
            low[0] < workspace_min_xy[0]
            or high[0] > workspace_max_xy[0]
            or low[1] < workspace_min_xy[1]
            or high[1] > workspace_max_xy[1]
        )
        manual_collider_override = obj.collider is not None and isinstance(
            obj.collider.provenance.get("manual_override"), dict
        )
        # Existing scenes use object z as their legacy anchor. Edited colliders
        # have explicit size/pose overrides, so check their actual lower bound.
        collider_center_z = (low[2] + high[2]) / 2.0
        is_subsurface = low[2] < -0.1 if manual_collider_override else collider_center_z < -0.1
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


def check_collision_source_coverage(
    scene: SceneIR,
    artifact_store_root: Path | None = None,
    artifact_resolver: Callable[[ProductArtifactRef], Path] | None = None,
) -> PreflightRule:
    """Verify exact triangle ownership sidecars without claiming visibility or physics coverage."""
    environment = scene.environment
    source_ref = environment.collision_source_ref
    selection_ref = environment.collision_selection_ref
    if source_ref is None and selection_ref is None:
        raise ValueError("collision source coverage rule requires an explicit source selection")

    def result(
        result: RuleResult,
        remediation: str,
        evidence: list[ProductArtifactRef] | None = None,
        affected: list[Identifier] | None = None,
    ) -> PreflightRule:
        return PreflightRule(
            rule_id=PreflightRuleId.COLLISION_SOURCE_COVERAGE,
            severity=SEVERITY_BLOCKING,
            result=result,
            affected_object_ids=affected or [],
            evidence_refs=evidence or [],
            remediation=remediation,
        )

    if source_ref is None or selection_ref is None:
        return result(RuleResult.FAIL, "Nguồn collision được chọn phải có cả source và selection ref.")
    if artifact_store_root is None and artifact_resolver is None:
        return result(
            RuleResult.ERROR,
            "Không thể xác minh selection và triangle ownership sidecars khi chưa có artifact resolver.",
            [source_ref, selection_ref],
        )

    root = artifact_store_root.resolve() if artifact_store_root is not None else None

    def resolve_artifact(reference: ProductArtifactRef) -> Path:
        if artifact_resolver is not None:
            path = artifact_resolver(reference)
        else:
            assert root is not None
            relative = reference.artifact_uri.removeprefix("artifact://")
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("collision ownership URI escapes artifact store")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if reference.artifact_checksum != f"sha256:{digest}":
            raise ValueError(f"collision ownership checksum mismatch: {reference.artifact_uri}")
        return path

    try:
        if selection_ref.artifact_type != "CollisionSourceSelection":
            raise ValueError("collision selection ref has the wrong artifact type")
        selection_path = resolve_artifact(selection_ref)
        source_path = resolve_artifact(source_ref)
        selection = CollisionSourceSelection.model_validate_json(selection_path.read_bytes())
        verify_content_checksum(selection, "selection_checksum")
        if selection.output_collision_ref != source_ref:
            raise ValueError("selection output differs from SceneEnvironment collision source")
        parts = load_mesh_parts(source_path)
        if len(parts) != 1:
            raise ValueError("selected collision source must contain one indexed triangle mesh")
        triangle_count = len(parts[0][1])
        memberships: dict[int, Identifier] = {}
        owned_object_ids: list[Identifier] = []
        evidence_refs = [source_ref, selection_ref]
        for obj in scene.objects:
            if (
                not obj.active
                or obj.origin != SceneObjectOrigin.RECONSTRUCTED
                or obj.provenance.get("duplicated_from") is not None
            ):
                continue
            region = obj.source_collision
            if (
                region is None
                or region.source_geometry_ref != source_ref
                or region.region_kind != "triangle_indices"
                or region.region_ref is None
            ):
                raise ValueError(f"reconstructed object {obj.id} has no selected-source ownership region")
            membership_path = resolve_artifact(region.region_ref)
            membership = SourceCollisionMembership.model_validate_json(membership_path.read_bytes())
            if (
                membership.object_id != obj.id
                or membership.source_geometry_ref != source_ref
                or membership.extraction_revision != region.extraction_revision
            ):
                raise ValueError(f"ownership sidecar does not match object {obj.id} and selected source")
            for triangle_index in membership.triangle_indices:
                if triangle_index >= triangle_count:
                    raise ValueError(f"object {obj.id} owns triangle outside selected collision mesh")
                existing_owner = memberships.get(triangle_index)
                if existing_owner is not None and existing_owner != obj.id:
                    raise ValueError(f"collision triangle {triangle_index} has ambiguous object ownership")
                memberships[triangle_index] = obj.id
            evidence_refs.append(region.region_ref)
            owned_object_ids.append(obj.id)
    except (ArtifactStoreError, MeshValidationError, OSError, TypeError, ValueError) as error:
        return result(
            RuleResult.ERROR,
            f"Không xác minh được collision source coverage: {error}",
            [source_ref, selection_ref],
        )

    return PreflightRule(
        rule_id=PreflightRuleId.COLLISION_SOURCE_COVERAGE,
        severity=SEVERITY_BLOCKING,
        result=RuleResult.PASS,
        affected_object_ids=sorted(owned_object_ids),
        evidence_refs=evidence_refs,
        remediation=(
            f"Ownership sidecar đã được xác minh cho {len(owned_object_ids)} object; đây chỉ là coverage ánh xạ mesh, "
            "không chứng minh vùng đã được quan sát, vật cản được giữ lại hay đường đi an toàn trong Isaac."
        ),
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

    verified_uris: set[str] = set()

    def verify_once(ref: ProductArtifactRef, obj_id: Identifier) -> None:
        if ref.artifact_uri in verified_uris:
            return
        verified_uris.add(ref.artifact_uri)
        _verify_ref(ref, obj_id)

    verify_once(scene.environment.geometry_ref, "environment")
    for ref in (
        scene.environment.collider_ref,
        scene.environment.collision_source_ref,
        scene.environment.collision_selection_ref,
    ):
        if ref is not None:
            verify_once(ref, "environment")

    for obj in scene.objects:
        if not obj.active:
            continue
        verify_once(obj.geometry_ref, obj.id)
        if obj.collider and obj.collider.geometry_ref:
            verify_once(obj.collider.geometry_ref, obj.id)
        if obj.source_collision is not None and obj.source_collision.region_ref is not None:
            verify_once(obj.source_collision.region_ref, obj.id)

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
