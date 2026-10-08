"""Duyệt/phát hành (PRODUCT-10/11) trên gói mô phỏng thật của scene tổng hợp.

ValidationReport ở đây là **fixture** (chưa có Isaac, SIM-06); test chứng minh lifecycle,
ràng buộc checksum và niêm phong, không chứng minh physics.
"""

import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import RuntimeComponent, RuntimeComponentStatus, RuntimeManifest
from src.models.contracts.release import ApprovalDecision, SceneRevisionStatus
from src.models.contracts.validation import (
    ObservedPathResult,
    PathResult,
    RuleResult,
    ValidationCheck,
    ValidationReport,
)
from src.models.contracts.validation_run import (
    ValidationConfig,
    ValidationPathPair,
    ValidationRunOrigin,
    ValidationRunRecord,
    ValidationRunStatus,
)
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.review.simulation_package import build_simulation_package
from src.services.orchestration.review.validation_runs import ValidationRunRepository
from src.services.orchestration.review.workflow import (
    ReviewError,
    decide,
    record_validation_report,
    review_state,
    seal_release,
)
from src.services.orchestration.scene.models import ColliderEditCommand
from src.services.orchestration.scene.objects import add_box_object, apply_object_action, edit_collider
from tests.test_orchestration.test_simulation_package import _scene_job

ZERO = "sha256:" + "0" * 64


def _packaged(tmp_path: Path):  # noqa: ANN202
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    apply_object_action(registry.scene, job.job_id, scene.objects[0].id, "confirm", scene.scene_revision)
    package = build_simulation_package(registry, job.job_id)
    return registry, job, package.candidate.candidate_checksum


def _sealed(model, checksum_field: str):  # noqa: ANN001
    return model.model_copy(update={checksum_field: canonical_content_checksum(model, checksum_field)})


def _report(
    candidate: str,
    overall: RuleResult = RuleResult.PASS,
    *,
    check_results: dict[str, RuleResult] | None = None,
    path_results: list[PathResult] | None = None,
) -> ValidationReport:
    checks = [
        ValidationCheck(check_id=check_id, result=result, evidence_refs=[])
        for check_id, result in (check_results or {"scene_load": RuleResult.PASS}).items()
    ]
    draft = ValidationReport(
        schema_version="1.0",
        candidate_checksum=candidate,
        validator_version="fixture-0",
        environment_versions={"isaac_sim": "fixture"},
        checks=checks,
        path_results=(
            path_results
            if path_results is not None
            else [PathResult(pair_id="pair-1", result=ObservedPathResult.CLEAR, evidence_refs=[])]
        ),
        overall_result=overall,
        report_checksum=ZERO,
    )
    return _sealed(draft, "report_checksum")


def _publish_model(registry, job_id: str, artifact_type: str, uri: str, model) -> ProductArtifactRef:  # noqa: ANN001
    payload = model.model_dump_json(indent=2).encode()
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id=job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    return reference


def _install_worker_run(
    registry,
    job,
    package,
    report: ValidationReport,
    *,
    required_check_ids: list[str] | None = None,
    warning_check_ids: list[str] | None = None,
    path_pairs: list[ValidationPathPair] | None = None,
    runtime_status: RuntimeComponentStatus = RuntimeComponentStatus.VERIFIED,
) -> None:  # noqa: ANN001
    """Persist worker-shaped evidence; this fixture tests the gate, not live Isaac acceptance."""
    candidate = package.candidate
    assert candidate is not None
    job_id = job.job_id
    repository = ValidationRunRepository(registry.persistence.database, registry.runtime_resolver)
    store = FilesystemArtifactStore(registry.runtime_resolver)
    config_draft = ValidationConfig(
        schema_version="1.0",
        policy_id="review-test-policy-v1",
        required_check_ids=required_check_ids or ["scene_load"],
        warning_check_ids=warning_check_ids or [],
        path_pairs=path_pairs
        if path_pairs is not None
        else [
            ValidationPathPair(
                pair_id="pair-1",
                start_xyz_m=(0.0, 0.0, 0.0),
                goal_xyz_m=(1.0, 0.0, 0.0),
                required=True,
            )
        ],
        config_checksum=ZERO,
    )
    config = _sealed(config_draft, "config_checksum")
    config_ref = _publish_model(
        registry,
        job_id,
        "ValidationConfig",
        repository.config_uri(job_id, config.config_checksum),
        config,
    )
    requested_at = datetime.now(UTC)
    run_id = f"review-run-{uuid4().hex[:12]}"
    queued = _sealed(
        ValidationRunRecord(
            schema_version="1.0",
            run_id=run_id,
            attempt=1,
            job_id=job_id,
            scene_revision=package.scene_revision,
            scene_ir_checksum=package.scene_ir_checksum,
            candidate_checksum=candidate.candidate_checksum,
            validation_config_checksum=config.config_checksum,
            validation_config_ref=config_ref,
            origin=ValidationRunOrigin.WORKER,
            status=ValidationRunStatus.QUEUED,
            requested_at=requested_at,
            run_checksum=ZERO,
        ),
        "run_checksum",
    )
    repository.save_run(queued)
    running_draft = queued.model_copy(
        update={
            "status": ValidationRunStatus.RUNNING,
            "started_at": requested_at + timedelta(seconds=1),
            "worker_id": "review-test-worker",
            "lease_id": run_id,
            "fencing_token": 1,
            "run_checksum": ZERO,
        }
    )
    running = _sealed(running_draft, "run_checksum")
    repository.save_run(running, expected_run_checksum=queued.run_checksum)

    report_ref = _publish_model(
        registry,
        job_id,
        "ValidationReport",
        repository.report_uri(job_id, candidate.candidate_checksum, config.config_checksum, run_id),
        report,
    )
    runtime = _sealed(
        RuntimeManifest(
            schema_version="1.0",
            components={"isaac_sim": RuntimeComponent(status=runtime_status, version="4.2.0-test")},
            runtime_manifest_checksum=ZERO,
        ),
        "runtime_manifest_checksum",
    )
    runtime_ref = _publish_model(
        registry,
        job_id,
        "RuntimeManifest",
        repository.runtime_manifest_uri(job_id, candidate.candidate_checksum, config.config_checksum, run_id),
        runtime,
    )
    log_bytes = f"fixture execution evidence for {run_id}\n".encode()
    log_ref = ProductArtifactRef(
        artifact_type="ValidationExecutionLog",
        schema_version="1.0",
        artifact_uri=repository.execution_log_uri(job_id, candidate.candidate_checksum, config.config_checksum, run_id),
        artifact_checksum=sha256_bytes(log_bytes),
        data_class="derived",
        producer_stage="ST-ISAAC-VALIDATE",
        job_id=job_id,
    )
    store.publish(log_ref, log_bytes)
    completed_draft = running.model_copy(
        update={
            "status": ValidationRunStatus.COMPLETED,
            "completed_at": requested_at + timedelta(seconds=2),
            "report_ref": report_ref,
            "report_checksum": report.report_checksum,
            "runtime_manifest_ref": runtime_ref,
            "execution_log_ref": log_ref,
            "run_checksum": ZERO,
        }
    )
    completed = _sealed(completed_draft, "run_checksum")
    repository.save_run(completed, expected_run_checksum=running.run_checksum)
    repository.select_run(job_id, candidate.candidate_checksum, config.config_checksum, run_id)


def test_without_validation_report_review_is_blocked(tmp_path: Path) -> None:
    registry, job, _ = _packaged(tmp_path)
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert state.validation is None and "validation run worker" in state.blockers[0]
    assert state.isaac_runtime_proof is None


def test_direct_seal_cannot_skip_the_selected_validation_gate(tmp_path: Path) -> None:
    registry, job, _ = _packaged(tmp_path)
    with pytest.raises(ReviewError, match="Chỉ phát hành gói đã được duyệt"):
        seal_release(registry, job.job_id)


@pytest.mark.parametrize(
    "isaac_sim",
    [
        "UNVERIFIED",
        "UNVERIFIED (local environment)",  # định dạng validator SIM-06 ghi khi máy không có Isaac
        "tbd",
        None,  # thiếu khoá isaac_sim
        "4.2.0 (omni detected)",
    ],
)
def test_legacy_report_cannot_claim_runtime_proof_or_review_eligibility(tmp_path: Path, isaac_sim: str | None) -> None:
    registry, job, candidate = _packaged(tmp_path)
    base = _report(candidate)
    versions = {"gpu": "UNVERIFIED"} if isaac_sim is None else {"isaac_sim": isaac_sim}
    draft = base.model_copy(update={"environment_versions": versions, "report_checksum": ZERO})
    report = draft.model_copy(update={"report_checksum": canonical_content_checksum(draft, "report_checksum")})
    record_validation_report(registry, job.job_id, report)

    state = review_state(registry, job.job_id)

    assert state.isaac_runtime_proof is False
    assert state.validation == report  # legacy report remains readable for diagnostics
    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert any("worker" in blocker.lower() for blocker in state.blockers)


def test_approve_requires_each_warning_then_seals_exact_candidate(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(
        candidate,
        path_results=[PathResult(pair_id="pair-1", result=ObservedPathResult.BLOCKED, evidence_refs=[])],
    )
    _install_worker_run(
        registry,
        job,
        review_state(registry, job.job_id).package,
        report,
        path_pairs=[
            ValidationPathPair(
                pair_id="pair-1",
                start_xyz_m=(0.0, 0.0, 0.0),
                goal_xyz_m=(1.0, 0.0, 0.0),
                required=False,
            )
        ],
    )
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.READY_FOR_REVIEW
    assert state.warning_ids == ["path:pair-1"]

    with pytest.raises(ReviewError, match="chấp nhận từng cảnh báo"):
        decide(registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum, [], None)

    released = decide(
        registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum,
        ["path:pair-1"], None,
    )  # fmt: skip
    assert released.record.status == SceneRevisionStatus.RELEASED
    manifest = released.release
    verify_content_checksum(manifest, "release_manifest_checksum")
    assert manifest.candidate_checksum == candidate and manifest.validation_report_checksum == report.report_checksum
    assert manifest.approval_record.record_checksum == released.approval.record_checksum
    archive = zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(released.release_archive).read_bytes()))
    assert {"scene.usda", "release_manifest.json", "approval_record.json", "validation_report.json"} <= set(
        archive.namelist()
    )
    # Mỗi gói một quyết định.
    with pytest.raises(ReviewError) as error:
        decide(registry, job.job_id, "u-rev", ApprovalDecision.REJECT, candidate, report.report_checksum, [], "x")
    assert error.value.conflict


def test_edit_after_release_starts_new_draft(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    decide(registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum, [], None)
    scene = registry.scene.current(job.job_id).scene
    add_box_object(registry.scene, job.job_id, scene.scene_revision, "Thùng mới", (0.5, 0.5, 0.5), (2, 2, 0.25))
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.DRAFT and state.release is None and state.approval is None


def test_collider_edit_builds_new_candidate_and_does_not_reuse_old_validation(tmp_path: Path) -> None:
    registry, job, old_candidate = _packaged(tmp_path)
    stale_report = _report(old_candidate)
    record_validation_report(registry, job.job_id, stale_report)
    old_state = review_state(registry, job.job_id)
    assert old_state.package is not None
    assert old_state.validation == stale_report

    scene = registry.scene.current(job.job_id).scene
    item = scene.objects[0]
    assert item.collider is not None and item.collider.dimensions_xyz_m is not None
    x, y, z = item.collider.dimensions_xyz_m
    edit_collider(
        registry.scene,
        job.job_id,
        ColliderEditCommand(
            expected_scene_revision=scene.scene_revision,
            object_id=item.id,
            dimensions_xyz_m=(x * 1.1, y * 1.1, z * 1.1),
            local_translation_xyz_m=(0.05, 0.0, 0.6),
        ),
    )
    new_package = build_simulation_package(registry, job.job_id)
    assert new_package.candidate is not None
    new_candidate = new_package.candidate.candidate_checksum
    assert new_candidate != old_candidate
    assert new_package.carved_triangles == old_state.package.carved_triangles
    assert new_package.retained_shared_triangles == old_state.package.retained_shared_triangles
    assert new_package.retained_shared_object_ids == old_state.package.retained_shared_object_ids

    new_state = review_state(registry, job.job_id)

    assert new_state.record.scene_revision == new_package.scene_revision
    assert new_state.record.candidate_checksum == new_candidate
    assert new_state.validation is None
    assert new_state.approval is None


def test_reject_needs_reason_and_blocks_release(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    with pytest.raises(ReviewError, match="lý do"):
        decide(registry, job.job_id, "u-rev", ApprovalDecision.REJECT, candidate, report.report_checksum, [], "  ")
    rejected = decide(
        registry, job.job_id, "u-rev", ApprovalDecision.REJECT, candidate, report.report_checksum, [], "Kệ lệch 20 cm"
    )
    assert rejected.record.status == SceneRevisionStatus.REJECTED and rejected.approval.reason == "Kệ lệch 20 cm"
    with pytest.raises(ReviewError):
        seal_release(registry, job.job_id)


def test_stale_screen_wrong_candidate_and_failed_validation(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    with pytest.raises(ReviewError):
        record_validation_report(registry, job.job_id, _report("sha256:" + "ab" * 32))
    report = _report(candidate, overall=RuleResult.FAIL)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert any("FAIL/ERROR" in blocker for blocker in state.blockers)
    with pytest.raises(ReviewError) as error:
        decide(registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum, [], None)
    assert error.value.conflict


@pytest.mark.parametrize(
    ("required", "observed", "expected_status"),
    [
        (True, ObservedPathResult.BLOCKED, SceneRevisionStatus.CANDIDATE_READY),
        (False, ObservedPathResult.BLOCKED, SceneRevisionStatus.READY_FOR_REVIEW),
        (False, ObservedPathResult.ERROR, SceneRevisionStatus.CANDIDATE_READY),
    ],
)
def test_required_and_optional_path_results_follow_the_bound_policy(
    tmp_path: Path,
    required: bool,
    observed: ObservedPathResult,
    expected_status: SceneRevisionStatus,
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    package = review_state(registry, job.job_id).package
    report = _report(
        candidate,
        path_results=[PathResult(pair_id="pair-1", result=observed, evidence_refs=[])],
    )
    pair = ValidationPathPair(
        pair_id="pair-1",
        start_xyz_m=(0.0, 0.0, 0.0),
        goal_xyz_m=(1.0, 0.0, 0.0),
        required=required,
    )
    _install_worker_run(registry, job, package, report, path_pairs=[pair])

    state = review_state(registry, job.job_id)

    assert state.record.status == expected_status
    if not required and observed == ObservedPathResult.BLOCKED:
        assert state.warning_ids == ["path:pair-1"]
    else:
        assert state.warning_ids == []
        assert state.blockers


def test_required_check_completeness_unknown_checks_and_errors_block_review(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    package = review_state(registry, job.job_id).package
    report = _report(
        candidate,
        check_results={"unexpected_check": RuleResult.PASS, "optional_capture": RuleResult.ERROR},
    )
    _install_worker_run(
        registry,
        job,
        package,
        report,
        required_check_ids=["scene_load"],
        warning_check_ids=["optional_capture"],
        path_pairs=[],
    )

    state = review_state(registry, job.job_id)

    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert any("Thiếu validation check bắt buộc: scene_load" in blocker for blocker in state.blockers)
    assert any("chưa nằm trong policy" in blocker for blocker in state.blockers)
    assert any("optional_capture trả ERROR" in blocker for blocker in state.blockers)


def test_configured_zero_paths_is_valid_when_required_checks_pass(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    package = review_state(registry, job.job_id).package
    report = _report(candidate, path_results=[])
    _install_worker_run(registry, job, package, report, path_pairs=[])

    state = review_state(registry, job.job_id)

    assert state.record.status == SceneRevisionStatus.READY_FOR_REVIEW
    assert state.warning_ids == [] and state.blockers == []
    assert state.isaac_runtime_proof is True


@pytest.mark.parametrize(
    ("observations", "expected_blocker"),
    [
        ([], "Thiếu required path pair: pair-1"),
        (
            [
                PathResult(pair_id="pair-1", result=ObservedPathResult.CLEAR, evidence_refs=[]),
                PathResult(pair_id="pair-1", result=ObservedPathResult.CLEAR, evidence_refs=[]),
                PathResult(pair_id="unconfigured", result=ObservedPathResult.CLEAR, evidence_refs=[]),
            ],
            "Validation path pair bị lặp: pair-1",
        ),
    ],
)
def test_missing_duplicate_or_unknown_path_results_block_review(
    tmp_path: Path, observations: list[PathResult], expected_blocker: str
) -> None:
    registry, job, candidate = _packaged(tmp_path)
    package = review_state(registry, job.job_id).package
    _install_worker_run(registry, job, package, _report(candidate, path_results=observations))

    state = review_state(registry, job.job_id)

    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert any(expected_blocker in blocker for blocker in state.blockers)


def test_unverified_runtime_manifest_blocks_even_when_report_claims_a_version(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    package = review_state(registry, job.job_id).package
    _install_worker_run(
        registry,
        job,
        package,
        _report(candidate),
        runtime_status=RuntimeComponentStatus.UNVERIFIED,
    )

    state = review_state(registry, job.job_id)

    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert state.isaac_runtime_proof is False
    assert any("Runtime manifest" in blocker for blocker in state.blockers)
