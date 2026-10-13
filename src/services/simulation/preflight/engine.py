"""Engine thực thi deterministic preflight rules và phát hành PreflightReport."""

from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import Identifier, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import PreflightReport, PreflightRule, PreflightRuleId, RuleResult
from src.services.scene.representation_composition import scene_representations
from src.services.scene.representation_integrity import representation_issues
from src.services.simulation.preflight.rules import (
    check_collider_presence,
    check_collision_source_coverage,
    check_metric_scale,
    check_object_bounds,
    check_object_confirmation,
    check_required_artifacts,
    check_transforms,
)

DEFAULT_RULESET_VERSION: Identifier = "1.0"
SCHEMA_VERSION: str = "1.0"


def evaluate_blocking_result(rules: list[PreflightRule]) -> RuleResult:
    """Xác định kết quả chặn: ERROR và FAIL không bao giờ được quy đổi thành PASS."""
    has_error = any(r.result == RuleResult.ERROR for r in rules)
    if has_error:
        return RuleResult.ERROR

    has_fail = any(r.result == RuleResult.FAIL for r in rules)
    if has_fail:
        return RuleResult.FAIL

    return RuleResult.PASS


def run_preflight(
    scene: SceneIR,
    ruleset_version: Identifier = DEFAULT_RULESET_VERSION,
    artifact_store_root: Path | None = None,
    artifact_resolver: Callable[[ProductArtifactRef], Path] | None = None,
) -> PreflightReport:
    """Thực thi toàn bộ các quy tắc preflight tĩnh và niêm phong PreflightReport."""
    rules: list[PreflightRule] = [
        check_metric_scale(scene),
        check_collider_presence(scene),
        check_transforms(scene),
        check_object_bounds(scene),
        check_object_confirmation(scene),
        check_required_artifacts(scene, artifact_store_root=artifact_store_root),
    ]
    if scene.environment.collision_source_ref is not None or scene.environment.collision_selection_ref is not None:
        rules.append(
            check_collision_source_coverage(
                scene,
                artifact_store_root=artifact_store_root,
                artifact_resolver=artifact_resolver,
            )
        )

    if any(item.source_visual_required or item.readiness_blockers for item in scene_representations(scene)):
        resolve = artifact_resolver
        if resolve is None and artifact_store_root is not None:

            def resolve(ref: ProductArtifactRef) -> Path:
                return artifact_store_root / ref.artifact_uri.removeprefix("artifact://")

        issues = representation_issues(scene, resolve)
        rules.append(
            PreflightRule(
                rule_id=PreflightRuleId.REPRESENTATION_INCOMPLETE,
                severity="blocking",
                result=RuleResult.FAIL if issues else RuleResult.PASS,
                affected_object_ids=sorted({object_id for object_id, _ in issues}),
                evidence_refs=[],
                remediation="; ".join(f"{object_id}: {code}" for object_id, code in issues) or None,
            )
        )
    blocking_result = evaluate_blocking_result(rules)

    placeholder_checksum = "sha256:" + "0" * 64
    candidate_report = PreflightReport(
        schema_version=SCHEMA_VERSION,
        scene_revision=scene.scene_revision,
        scene_ir_checksum=scene.scene_ir_checksum,
        ruleset_version=ruleset_version,
        rules=rules,
        blocking_result=blocking_result,
        report_checksum=placeholder_checksum,
    )

    actual_checksum = canonical_content_checksum(candidate_report, "report_checksum")
    return candidate_report.model_copy(update={"report_checksum": actual_checksum})
