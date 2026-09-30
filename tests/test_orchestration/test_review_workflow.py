"""Duyệt/phát hành (PRODUCT-10/11) trên gói mô phỏng thật của scene tổng hợp.

ValidationReport ở đây là **fixture** (chưa có Isaac, SIM-06); test chứng minh lifecycle,
ràng buộc checksum và niêm phong, không chứng minh physics.
"""

import io
import zipfile
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.release import ApprovalDecision, SceneRevisionStatus
from src.models.contracts.validation import PathResult, RuleResult, ValidationCheck, ValidationReport
from src.services.orchestration.review.workflow import (
    ReviewError,
    decide,
    record_validation_report,
    review_state,
    seal_release,
)
from src.services.orchestration.scene.objects import add_box_object, apply_object_action
from src.services.orchestration.simulation_package import build_simulation_package
from tests.test_orchestration.test_simulation_package import _scene_job

ZERO = "sha256:" + "0" * 64


def _packaged(tmp_path: Path):  # noqa: ANN202
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    apply_object_action(registry.scene, job.job_id, scene.objects[0].id, "confirm", scene.scene_revision)
    package = build_simulation_package(registry, job.job_id)
    return registry, job, package.candidate.candidate_checksum


def _report(candidate: str, overall: RuleResult = RuleResult.PASS, warning: bool = False) -> ValidationReport:
    checks = [ValidationCheck(check_id="scene_load", result=RuleResult.PASS, evidence_refs=[])]
    if warning:
        checks.append(ValidationCheck(check_id="penetration_minor", result=RuleResult.FAIL, evidence_refs=[]))
    draft = ValidationReport(
        schema_version="1.0",
        candidate_checksum=candidate,
        validator_version="fixture-0",
        environment_versions={"isaac_sim": "fixture"},
        checks=checks,
        path_results=[PathResult(pair_id="pair-1", result="CLEAR", evidence_refs=[])],
        overall_result=overall,
        report_checksum=ZERO,
    )
    return draft.model_copy(update={"report_checksum": canonical_content_checksum(draft, "report_checksum")})


def test_without_validation_report_review_is_blocked(tmp_path: Path) -> None:
    registry, job, _ = _packaged(tmp_path)
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.CANDIDATE_READY
    assert state.validation is None and "SIM-06" in state.blockers[0]


def test_approve_requires_each_warning_then_seals_exact_candidate(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate, warning=True)
    record_validation_report(registry, job.job_id, report)
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.READY_FOR_REVIEW
    assert state.warning_ids == ["penetration_minor"]

    with pytest.raises(ReviewError, match="chấp nhận từng cảnh báo"):
        decide(registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum, [], None)

    released = decide(
        registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum,
        ["penetration_minor"], None,
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
    record_validation_report(registry, job.job_id, report)
    decide(registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum, [], None)
    scene = registry.scene.current(job.job_id).scene
    add_box_object(registry.scene, job.job_id, scene.scene_revision, "Thùng mới", (0.5, 0.5, 0.5), (2, 2, 0.25))
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.DRAFT and state.release is None and state.approval is None


def test_reject_needs_reason_and_blocks_release(tmp_path: Path) -> None:
    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    record_validation_report(registry, job.job_id, report)
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
    record_validation_report(registry, job.job_id, report)
    state = review_state(registry, job.job_id)
    assert state.record.status == SceneRevisionStatus.DRAFT and "FAIL" in state.blockers[0]
    with pytest.raises(ReviewError) as error:
        decide(registry, job.job_id, "u-rev", ApprovalDecision.APPROVE, candidate, report.report_checksum, [], None)
    assert error.value.conflict
