"""One fail-closed eligibility check shared by review and release workflow."""

from dataclasses import dataclass

from pydantic import ValidationError

from src.models.contracts.collision_quality import (
    CollisionObservationState,
    CollisionPhysicsClaim,
    CollisionQualityReport,
    CollisionQualityResult,
    CollisionSourceSelection,
    validate_collision_source_binding,
)
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.manifests import RuntimeComponentStatus, RuntimeManifest
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import (
    CandidatePackage,
    CollisionPathCoverageDiagnostic,
    ObservedPathResult,
    RuleResult,
    ValidationReport,
)
from src.models.contracts.validation_run import (
    CollisionSupportPolicy,
    ValidationConfig,
    ValidationRunRecord,
    ValidationRunSelection,
)
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.review.validation_runs import ValidationRunError, ValidationRunRepository


@dataclass(frozen=True)
class ValidationEligibility:
    """Verified selected evidence and deterministic blockers for one live candidate."""

    selection: ValidationRunSelection | None
    run: ValidationRunRecord | None
    config: ValidationConfig | None
    report: ValidationReport | None
    runtime_manifest: RuntimeManifest | None
    warning_ids: list[str]
    blockers: list[str]

    @property
    def eligible(self) -> bool:
        return not self.blockers and all(
            value is not None for value in (self.selection, self.run, self.config, self.report, self.runtime_manifest)
        )


def evaluate_validation_eligibility(
    registry: ProjectRegistry,
    job_id: str,
    scene: SceneIR,
    candidate: CandidatePackage,
    *,
    package_scene_revision: str,
    package_scene_ir_checksum: str,
) -> ValidationEligibility:
    """Verify the selected worker proof and apply its exact check/path policy."""
    empty = ValidationEligibility(None, None, None, None, None, [], [])
    blockers: list[str] = []
    if registry.persistence is None:
        return _blocked(empty, "Không có runtime database để xác minh validation worker")
    if candidate.candidate_manifest.scene_revision != package_scene_revision:
        blockers.append("Candidate manifest không khớp revision của gói mô phỏng")
    if candidate.candidate_manifest.scene_ir_checksum != package_scene_ir_checksum:
        blockers.append("Candidate manifest không khớp SceneIR checksum của gói mô phỏng")
    if package_scene_revision != scene.scene_revision or package_scene_ir_checksum != scene.scene_ir_checksum:
        blockers.append("Gói mô phỏng không thuộc SceneIR hiện tại")
    if blockers:
        return _blocked(empty, *blockers)

    repository = ValidationRunRepository(registry.persistence.database, registry.runtime_resolver)
    try:
        selection = repository.get_selection_for_candidate(job_id, candidate.candidate_checksum)
        if selection is None:
            return _blocked(empty, "Chưa có validation run worker được chọn cho candidate hiện tại")
        run = repository.get_run(selection.run_id)
        if (
            run.job_id != job_id
            or run.candidate_checksum != candidate.candidate_checksum
            or run.scene_revision != scene.scene_revision
            or run.scene_ir_checksum != scene.scene_ir_checksum
            or run.validation_config_checksum != selection.validation_config_checksum
            or run.report_checksum != selection.report_checksum
        ):
            return _blocked(empty, "Validation run không khớp job, SceneIR, candidate, config hoặc report hiện tại")
        config = registry.runtime_resolver.load_model(run.validation_config_ref, ValidationConfig)
        report_ref = run.report_ref
        runtime_ref = run.runtime_manifest_ref
        if report_ref is None or runtime_ref is None:
            return _blocked(empty, "Validation run thiếu report hoặc runtime manifest")
        report = registry.runtime_resolver.load_model(report_ref, ValidationReport)
        runtime = registry.runtime_resolver.load_model(runtime_ref, RuntimeManifest)
        verify_content_checksum(config, "config_checksum")
        verify_content_checksum(report, "report_checksum")
        verify_content_checksum(runtime, "runtime_manifest_checksum")
    except (ValidationRunError, ArtifactStoreError, ValidationError, ValueError, OSError) as error:
        return _blocked(empty, f"Không thể xác minh validation evidence: {error}")

    if config.config_checksum != run.validation_config_checksum:
        blockers.append("Validation config checksum không khớp run")
    if report.candidate_checksum != candidate.candidate_checksum:
        blockers.append("Validation report không thuộc candidate hiện tại")
    if report.report_checksum != selection.report_checksum or report.report_checksum != run.report_checksum:
        blockers.append("Validation report không khớp run selection")
    isaac_runtime = runtime.components.get("isaac_sim")
    if isaac_runtime is None or isaac_runtime.status != RuntimeComponentStatus.VERIFIED:
        blockers.append("Runtime manifest không xác nhận Isaac Sim đã được kiểm chứng")
    if report.overall_result != RuleResult.PASS:
        blockers.append(
            f"Validation {report.overall_result.value}: FAIL/ERROR không thể bỏ qua bằng warning acknowledgment"
        )

    blockers.extend(_check_results(config, report))
    path_blockers, warning_ids = _path_results(config, report)
    blockers.extend(path_blockers)
    collision_blockers, collision_warnings = _collision_support_results(
        registry,
        scene,
        candidate,
        config,
        report,
    )
    blockers.extend(collision_blockers)
    warning_ids.extend(collision_warnings)
    return ValidationEligibility(selection, run, config, report, runtime, warning_ids, _unique(blockers))


def _check_results(config: ValidationConfig, report: ValidationReport) -> list[str]:
    blockers: list[str] = []
    expected = set(config.required_check_ids) | set(config.warning_check_ids)
    seen: set[str] = set()
    for check in report.checks:
        if check.check_id in seen:
            blockers.append(f"Validation check bị lặp: {check.check_id}")
        seen.add(check.check_id)
        if check.check_id not in expected:
            blockers.append(f"Validation có check chưa nằm trong policy: {check.check_id}")
        if check.result != RuleResult.PASS:
            blockers.append(f"Validation check {check.check_id} trả {check.result.value}; cần chạy lại")
    missing = sorted(set(config.required_check_ids) - seen)
    blockers.extend(f"Thiếu validation check bắt buộc: {check_id}" for check_id in missing)
    return blockers


def _path_results(config: ValidationConfig, report: ValidationReport) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warning_ids: list[str] = []
    expected = {pair.pair_id: pair for pair in config.path_pairs}
    seen: set[str] = set()
    for result in report.path_results:
        if result.pair_id in seen:
            blockers.append(f"Validation path pair bị lặp: {result.pair_id}")
        seen.add(result.pair_id)
        pair = expected.get(result.pair_id)
        if pair is None:
            blockers.append(f"Validation có path pair chưa nằm trong policy: {result.pair_id}")
            continue
        if result.result == ObservedPathResult.ERROR:
            blockers.append(f"Validation path {result.pair_id} trả ERROR")
        elif result.result == ObservedPathResult.BLOCKED:
            if pair.required:
                blockers.append(f"Required path {result.pair_id} bị chặn")
            else:
                warning_ids.append(f"path:{result.pair_id}")
    missing = sorted(pair_id for pair_id, pair in expected.items() if pair.required and pair_id not in seen)
    blockers.extend(f"Thiếu required path pair: {pair_id}" for pair_id in missing)
    return blockers, warning_ids


def _collision_support_results(
    registry: ProjectRegistry,
    scene: SceneIR,
    candidate: CandidatePackage,
    config: ValidationConfig,
    report: ValidationReport,
) -> tuple[list[str], list[str]]:
    """Keep an observed CLEAR path distinct from a source-supported safety claim."""
    observed_clear = {item.pair_id for item in report.path_results if item.result == ObservedPathResult.CLEAR}
    manifest = candidate.candidate_manifest
    selected_source = manifest.collision_source_ref is not None or manifest.collision_selection_ref is not None
    required = config.collision_support_policy == CollisionSupportPolicy.REQUIRED or selected_source
    pair_ids = {pair.pair_id for pair in config.path_pairs} if required else observed_clear
    if not pair_ids:
        return [], []

    blockers: list[str] = []
    warning_ids: list[str] = []

    def record_problem(reason: str, pair_id: str | None = None) -> None:
        message = f"Collision support {pair_id}: {reason}" if pair_id else f"Collision support: {reason}"
        if required:
            blockers.append(message)
        else:
            warning_ids.append(f"collision-support:{pair_id or 'unavailable'}")

    quality_ref = report.collision_quality_ref
    if quality_ref is None:
        for pair_id in sorted(pair_ids):
            record_problem("worker chưa gắn CollisionQualityReport vào ValidationReport", pair_id)
        return blockers, warning_ids
    if not selected_source or manifest.collision_selection_ref is None or manifest.collision_source_ref is None:
        record_problem("candidate không có source/selection identity để xác minh report")
        return blockers, warning_ids
    quality_job_id = quality_ref.artifact_uri.removeprefix("artifact://jobs/").partition("/")[0]
    selection_job_id = manifest.collision_selection_ref.artifact_uri.removeprefix("artifact://jobs/").partition("/")[0]
    if quality_job_id != selection_job_id or (quality_ref.job_id is not None and quality_ref.job_id != quality_job_id):
        record_problem("CollisionQualityReport thuộc job khác với source selection")
        return blockers, warning_ids

    try:
        quality = registry.runtime_resolver.load_model(quality_ref, CollisionQualityReport)
        selection = registry.runtime_resolver.load_model(
            manifest.collision_selection_ref,
            CollisionSourceSelection,
        )
        verify_content_checksum(quality, "report_checksum")
        verify_content_checksum(selection, "selection_checksum")
        if quality.candidate_checksum != candidate.candidate_checksum:
            raise ValueError("CollisionQualityReport does not bind the exact exported candidate")
        if (
            quality.effective_collision_ref != scene.environment.collider_ref
            or quality.effective_collision_ref not in candidate.colliders
        ):
            raise ValueError("CollisionQualityReport does not bind the exported effective collider")
        if (
            scene.environment.collision_source_ref != manifest.collision_source_ref
            or scene.environment.collision_selection_ref != manifest.collision_selection_ref
        ):
            raise ValueError("report refs differ from the current SceneIR revision")
        validate_collision_source_binding(
            scene.environment,
            selection,
            quality,
            selection_ref=manifest.collision_selection_ref,
        )
    except (ArtifactStoreError, OSError, TypeError, ValidationError, ValueError) as error:
        record_problem(f"không xác minh được source-bound report ({error})")
        return blockers, warning_ids

    if quality.quality_result != CollisionQualityResult.PASS or quality.physics_claim != CollisionPhysicsClaim.VERIFIED:
        record_problem("report chưa đạt PASS/VERIFIED cho đúng collision candidate")
        return blockers, warning_ids

    support_by_pair = {item.pair_id: item for item in report.collision_path_support}
    for pair_id in sorted(pair_ids):
        support = support_by_pair.get(pair_id)
        if support is None or support.diagnostic_ref is None:
            record_problem("thiếu diagnostic artifact được bound vào candidate và quality report", pair_id)
            continue
        try:
            diagnostic = registry.runtime_resolver.load_model(
                support.diagnostic_ref,
                CollisionPathCoverageDiagnostic,
            )
            if (
                diagnostic.job_id != quality_job_id
                or diagnostic.candidate_checksum != candidate.candidate_checksum
                or diagnostic.effective_collision_ref != quality.effective_collision_ref
                or diagnostic.collision_quality_ref != quality_ref
                or diagnostic.pair_id != pair_id
                or diagnostic.state != support.state
                or diagnostic.observation_ids != support.observation_ids
                or diagnostic.coverage_fraction != support.coverage_fraction
            ):
                raise ValueError("path diagnostic does not match the selected candidate, collider, report or path")
        except (ArtifactStoreError, OSError, TypeError, ValidationError, ValueError) as error:
            record_problem(f"không xác minh được path diagnostic ({error})", pair_id)
            continue
        if (
            support.state != CollisionObservationState.OBSERVED_STATIC
            or support.coverage_fraction != 1.0
            or not support.observation_ids
        ):
            record_problem("thiếu coverage tĩnh đầy đủ; cặp này không được xác nhận CLEAR an toàn", pair_id)
    return blockers, warning_ids


def _blocked(base: ValidationEligibility, *reasons: str) -> ValidationEligibility:
    return ValidationEligibility(
        base.selection,
        base.run,
        base.config,
        base.report,
        base.runtime_manifest,
        base.warning_ids,
        _unique([*base.blockers, *reasons]),
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
