"""Publish REC-02 reports qua artifact store được inject."""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.manifests import InputManifest, PrivacyResult, PrivacyValidationReport, StageId
from src.services.reconstruction.rgb.preflight.privacy import PrivacyDispatchProof, RGBPrivacyGate
from src.services.reconstruction.rgb.preflight.quality_models import RGBQualityReport


class ArtifactWriter(Protocol):
    """Interface tối thiểu của artifact store trong deployment."""

    def publish(self, reference: ArtifactRef, payload: bytes) -> ArtifactRef:
        """Tạo logical artifact bất biến theo cách atomic."""


@dataclass(frozen=True)
class _PublishSpec:
    artifact_type: str
    stage: StageId
    path: str
    provenance: dict[str, str]


@dataclass(frozen=True)
class _PrivacyPublication:
    report: PrivacyValidationReport
    job_id: str
    extra_provenance: dict[str, str]


@dataclass(frozen=True)
class VerifiedPrivacyPublication:
    """Publish VERIFIED phải mang QA và inspection evidence."""

    manifest: InputManifest
    proof: PrivacyDispatchProof
    job_id: str


class RGBPreflightPublisher:
    """Tạo byte refs nhưng giữ storage mechanics ngoài EX-REC."""

    def __init__(self, writer: ArtifactWriter, privacy_gate: RGBPrivacyGate | None = None) -> None:
        self.writer = writer
        self.privacy_gate = privacy_gate

    def publish_quality(self, report: RGBQualityReport, job_id: str) -> ProductArtifactRef:
        """Publish quality mask với logical checksum và byte checksum."""
        verify_content_checksum(report, "report_checksum")
        payload = report.model_dump_json(indent=2).encode("utf-8") + b"\n"
        provenance = {
            "source_manifest_checksum": report.source_manifest_checksum,
            "selection_checksum": report.selection_checksum,
            "profile_checksum": report.profile_checksum,
            "report_checksum": report.report_checksum,
            "producer_version": report.producer_version,
        }
        spec = _PublishSpec("RGBQualityReport", StageId.INPUT_VALIDATE, "rec02/quality_report.json", provenance)
        reference = self._reference(job_id, spec, payload)
        return ProductArtifactRef.model_validate(self.writer.publish(reference, payload).model_dump())

    def publish_privacy(self, report: PrivacyValidationReport, job_id: str) -> ProductArtifactRef:
        """Publish PRELIMINARY/QUARANTINED mà không claim clearance."""
        if report.result == PrivacyResult.VERIFIED_ANONYMIZED:
            raise ValueError("verified privacy publication requires QA dispatch proof")
        return self._publish_privacy_report(_PrivacyPublication(report, job_id, {}))

    def publish_verified_privacy(self, request: VerifiedPrivacyPublication) -> ProductArtifactRef:
        """Chỉ publish VERIFIED khi QA verifier chấp nhận proof."""
        if self.privacy_gate is None:
            raise ValueError("QA verifier is unavailable for verified privacy publication")
        self.privacy_gate.require_dispatch(request.manifest, request.proof)
        provenance = {
            "qa_acceptance_reference": request.proof.acceptance.acceptance_reference,
            "inspection_evidence_checksum": request.proof.inspection.evidence_checksum,
        }
        return self._publish_privacy_report(_PrivacyPublication(request.proof.report, request.job_id, provenance))

    def _publish_privacy_report(self, request: _PrivacyPublication) -> ProductArtifactRef:
        verify_content_checksum(request.report, "report_checksum")
        payload = request.report.model_dump_json(indent=2).encode("utf-8") + b"\n"
        provenance = {
            "input_manifest_checksum": request.report.input_manifest_checksum,
            "report_checksum": request.report.report_checksum,
            "inspection_scope": request.report.inspection_scope.value,
            **request.extra_provenance,
        }
        spec = _PublishSpec("PrivacyValidationReport", StageId.PRIVACY_GATE, "rec02/privacy_report.json", provenance)
        reference = self._reference(request.job_id, spec, payload)
        return ProductArtifactRef.model_validate(self.writer.publish(reference, payload).model_dump())

    @staticmethod
    def _reference(job_id: str, spec: _PublishSpec, payload: bytes) -> ProductArtifactRef:
        """Dùng một quy ước URI cho hai report của REC-02."""
        return ProductArtifactRef(
            artifact_type=spec.artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/{spec.path}",
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=spec.stage,
            job_id=job_id,
            source_provenance=spec.provenance,
        )
