"""Privacy gate fail-closed, gắn shared InputManifest identity."""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import (
    InputManifest,
    PrivacyInspectionScope,
    PrivacyResult,
    PrivacyValidationReport,
)
from src.services.reconstruction.rgb.quality import RGBValidationError


@dataclass(frozen=True)
class PrivacyInspectionEvidence:
    """Inspection facts; không có finding chưa đồng nghĩa QA approval."""

    scope: PrivacyInspectionScope
    selected_frame_count: int
    inspected_frame_count: int
    unresolved_findings: tuple[dict[str, object], ...]
    evidence_checksum: str
    approved_copy_checksum: str | None = None


@dataclass(frozen=True)
class PrivacyQAAcceptance:
    """QA decision cho đúng input và inspection evidence."""

    input_manifest_checksum: str
    inspection_evidence_checksum: str
    acceptance_reference: str


@dataclass(frozen=True)
class PrivacyDispatchProof:
    """Shared report kèm inspection/QA evidence để dispatch."""

    report: PrivacyValidationReport
    inspection: PrivacyInspectionEvidence
    acceptance: PrivacyQAAcceptance


@dataclass(frozen=True)
class PrivacyReviewRequest:
    """Typed input cho privacy result decision."""

    manifest: InputManifest
    evidence: PrivacyInspectionEvidence
    acceptance: PrivacyQAAcceptance | None = None


class RGBPrivacyGate:
    """Tạo shared privacy result, không nâng sampled screening lên VERIFIED."""

    def __init__(self, verify_qa_acceptance: Callable[[PrivacyQAAcceptance], bool] | None = None) -> None:
        """Không có QA verifier thì không thể phát VERIFIED_ANONYMIZED."""
        self.verify_qa_acceptance = verify_qa_acceptance

    def evaluate(self, request: PrivacyReviewRequest) -> PrivacyValidationReport:
        """Quarantine findings; VERIFIED cần scope đầy đủ và QA thật."""
        manifest, evidence = request.manifest, request.evidence
        verify_content_checksum(manifest, "input_manifest_checksum")
        self._verify_input(manifest, evidence)
        if evidence.unresolved_findings:
            result = PrivacyResult.QUARANTINED
        elif self._complete(evidence) and self._accepted(request):
            result = PrivacyResult.VERIFIED_ANONYMIZED
        else:
            result = PrivacyResult.PRELIMINARY_SCREENED
        payload = {
            "schema_version": "1.0",
            "input_manifest_checksum": manifest.input_manifest_checksum,
            "inspection_scope": evidence.scope,
            "selected_frame_count": evidence.selected_frame_count,
            "inspected_frame_count": evidence.inspected_frame_count,
            "unresolved_findings": list(evidence.unresolved_findings),
            "result": result,
            "report_checksum": "sha256:" + "0" * 64,
        }
        payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
        return PrivacyValidationReport.model_validate(payload)

    def require_dispatch(self, manifest: InputManifest, proof: PrivacyDispatchProof) -> None:
        """Không dispatch report tách khỏi QA/inspection evidence."""
        verify_content_checksum(manifest, "input_manifest_checksum")
        verify_content_checksum(proof.report, "report_checksum")
        if proof.report.input_manifest_checksum != manifest.input_manifest_checksum:
            raise RGBValidationError(
                "PRIVACY_INPUT_MISMATCH",
                "Privacy report belongs to another input",
                "Rerun privacy validation for this InputManifest",
            )
        expected = self.evaluate(PrivacyReviewRequest(manifest, proof.inspection, proof.acceptance))
        if (
            proof.report.report_checksum != expected.report_checksum
            or expected.result != PrivacyResult.VERIFIED_ANONYMIZED
        ):
            raise RGBValidationError(
                "PRIVACY_NOT_VERIFIED",
                "RGB input is not privacy-cleared",
                "Complete all-frame/approved-copy inspection and obtain QA acceptance",
            )

    @staticmethod
    def _verify_input(manifest: InputManifest, evidence: PrivacyInspectionEvidence) -> None:
        if canonical_content_checksum(asdict(evidence), "evidence_checksum") != evidence.evidence_checksum:
            raise RGBValidationError(
                "PRIVACY_EVIDENCE_MISMATCH",
                "Privacy inspection evidence changed",
                "Restore the approved inspection record",
            )
        if not manifest.input_configuration.rgb_present:
            raise RGBValidationError("RGB_MODALITY_MISSING", "InputManifest has no RGB modality", "Supply an RGB input")
        if manifest.source_rights_attestation.get("attested") is not True:
            raise RGBValidationError(
                "SOURCE_RIGHTS_MISSING",
                "Source rights are not attested",
                "Obtain an explicit source-rights attestation",
            )
        RGBPrivacyGate._verify_scope(evidence)

    @staticmethod
    def _verify_scope(evidence: PrivacyInspectionEvidence) -> None:
        if (
            evidence.selected_frame_count < 1
            or evidence.inspected_frame_count < 1
            or evidence.inspected_frame_count > evidence.selected_frame_count
        ):
            raise RGBValidationError(
                "PRIVACY_SCOPE_INVALID",
                "Privacy inspection counts are invalid",
                "Record selected and inspected counts accurately",
            )
        if (
            evidence.scope == PrivacyInspectionScope.SAMPLED
            and evidence.inspected_frame_count >= evidence.selected_frame_count
        ):
            raise RGBValidationError(
                "PRIVACY_SCOPE_INVALID",
                "Sampled scope contradicts full inspection",
                "Use all_selected_frames for complete inspection",
            )
        if evidence.scope == PrivacyInspectionScope.APPROVED_COPY and (
            evidence.approved_copy_checksum is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", evidence.approved_copy_checksum) is None
        ):
            raise RGBValidationError(
                "PRIVACY_COPY_MISSING",
                "Approved anonymized copy has no checksum",
                "Provide a checksummed approved copy and QA acceptance",
            )

    @staticmethod
    def _complete(evidence: PrivacyInspectionEvidence) -> bool:
        return (
            evidence.scope == PrivacyInspectionScope.ALL_SELECTED_FRAMES
            and evidence.inspected_frame_count == evidence.selected_frame_count
        ) or (evidence.scope == PrivacyInspectionScope.APPROVED_COPY and evidence.inspected_frame_count > 0)

    def _accepted(self, request: PrivacyReviewRequest) -> bool:
        manifest, evidence, acceptance = request.manifest, request.evidence, request.acceptance
        return (
            self.verify_qa_acceptance is not None
            and acceptance is not None
            and bool(acceptance.acceptance_reference.strip())
            and acceptance.input_manifest_checksum == manifest.input_manifest_checksum
            and acceptance.inspection_evidence_checksum == evidence.evidence_checksum
            and self.verify_qa_acceptance(acceptance)
        )


#: Giá trị `acceptance_reference` đánh dấu proof tự khai, không phải QA acceptance.
SELF_ATTESTED_REFERENCE = "self-attested:uploader"
_SELF_ATTESTATION_FLAGS = ("attested", "rights_to_use_confirmed", "anonymization_confirmed")


class SelfAttestedPrivacyGate(RGBPrivacyGate):
    """Chế độ MVP: người upload tự khai video không chứa khuôn mặt/biển số.

    Owner chốt 2026-09-29 (plan `2026-09-29-mvp-studio-demo.md`): MVP chạy luồng
    upload → 3DGS mà không chờ QA. Report vẫn trung thực: `PRELIMINARY_SCREENED`,
    0 frame được người kiểm tra; không bao giờ phát `VERIFIED_ANONYMIZED`. Gate
    chỉ được bật ở composition root khi deployment chọn chế độ này.
    """

    def issue(self, manifest: InputManifest, selected_frame_count: int) -> PrivacyDispatchProof:
        """Tạo proof tự khai gắn đúng InputManifest; fail-closed nếu thiếu lời khai."""
        verify_content_checksum(manifest, "input_manifest_checksum")
        self._require_attestation(manifest)
        if selected_frame_count < 1:
            raise RGBValidationError(
                "PRIVACY_SCOPE_INVALID", "No RGB frames were selected", "Provide decodable RGB input"
            )
        blank = PrivacyInspectionEvidence(
            PrivacyInspectionScope.SAMPLED, selected_frame_count, 0, (), "sha256:" + "0" * 64
        )
        evidence = PrivacyInspectionEvidence(
            blank.scope,
            blank.selected_frame_count,
            0,
            (),
            canonical_content_checksum(asdict(blank), "evidence_checksum"),
        )
        payload = {
            "schema_version": "1.0",
            "input_manifest_checksum": manifest.input_manifest_checksum,
            "inspection_scope": evidence.scope,
            "selected_frame_count": selected_frame_count,
            "inspected_frame_count": 0,
            "unresolved_findings": [],
            "result": PrivacyResult.PRELIMINARY_SCREENED,
            "report_checksum": "sha256:" + "0" * 64,
        }
        payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
        report = PrivacyValidationReport.model_validate(payload)
        acceptance = PrivacyQAAcceptance(
            manifest.input_manifest_checksum, evidence.evidence_checksum, SELF_ATTESTED_REFERENCE
        )
        return PrivacyDispatchProof(report, evidence, acceptance)

    def require_dispatch(self, manifest: InputManifest, proof: PrivacyDispatchProof) -> None:
        """Chỉ nhận đúng proof do `issue` tạo cho manifest này; findings luôn chặn."""
        verify_content_checksum(manifest, "input_manifest_checksum")
        verify_content_checksum(proof.report, "report_checksum")
        self._require_attestation(manifest)
        expected = self.issue(manifest, proof.inspection.selected_frame_count)
        if (
            proof.report.report_checksum != expected.report.report_checksum
            or proof.inspection != expected.inspection
            or proof.acceptance != expected.acceptance
        ):
            raise RGBValidationError(
                "PRIVACY_NOT_SELF_ATTESTED",
                "Privacy proof is not the uploader self-attestation for this input",
                "Re-upload the video with the privacy attestation checked",
            )

    @staticmethod
    def _require_attestation(manifest: InputManifest) -> None:
        attestation = manifest.source_rights_attestation
        if any(attestation.get(flag) is not True for flag in _SELF_ATTESTATION_FLAGS):
            raise RGBValidationError(
                "PRIVACY_ATTESTATION_MISSING",
                "Uploader did not confirm rights and absence of faces/license plates",
                "Confirm the video has no faces/license plates (or they are blurred) before processing",
            )
