"""Gate tự khai của MVP: trung thực về mức kiểm tra và fail-closed khi thiếu lời khai."""

from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import InputManifest, PrivacyResult
from src.services.reconstruction.rgb.preflight.privacy import (
    SELF_ATTESTED_REFERENCE,
    PrivacyDispatchProof,
    PrivacyQAAcceptance,
    SelfAttestedPrivacyGate,
)
from src.services.reconstruction.rgb.preflight.quality import RGBValidationError

ROOT = Path(__file__).resolve().parents[2]


def _manifest(**attestation: object) -> InputManifest:
    payload = InputManifest.model_validate_json(
        (ROOT / "fixtures/mock_job/input_manifest.json").read_text()
    ).model_dump(mode="json")
    payload["source_rights_attestation"] = attestation
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    return InputManifest.model_validate(payload)


_ATTESTED = {"attested": True, "rights_to_use_confirmed": True, "anonymization_confirmed": True}


def test_self_attested_proof_is_preliminary_and_dispatchable() -> None:
    manifest = _manifest(**_ATTESTED)
    gate = SelfAttestedPrivacyGate()
    proof = gate.issue(manifest, 12)
    assert proof.report.result == PrivacyResult.PRELIMINARY_SCREENED
    assert proof.report.inspected_frame_count == 0 and proof.report.selected_frame_count == 12
    assert proof.acceptance.acceptance_reference == SELF_ATTESTED_REFERENCE
    gate.require_dispatch(manifest, proof)


@pytest.mark.parametrize("missing", ["attested", "rights_to_use_confirmed", "anonymization_confirmed"])
def test_missing_attestation_flag_blocks(missing: str) -> None:
    manifest = _manifest(**{**_ATTESTED, missing: False})
    with pytest.raises(RGBValidationError, match="did not confirm"):
        SelfAttestedPrivacyGate().issue(manifest, 3)


def test_proof_for_another_input_or_forged_acceptance_is_rejected() -> None:
    gate = SelfAttestedPrivacyGate()
    manifest = _manifest(**_ATTESTED)
    other = _manifest(**_ATTESTED, declared_owner="someone else")
    with pytest.raises(RGBValidationError, match="not the uploader self-attestation"):
        gate.require_dispatch(manifest, gate.issue(other, 3))
    proof = gate.issue(manifest, 3)
    forged = PrivacyDispatchProof(
        proof.report,
        proof.inspection,
        PrivacyQAAcceptance(manifest.input_manifest_checksum, proof.inspection.evidence_checksum, "qa:someone"),
    )
    with pytest.raises(RGBValidationError, match="not the uploader self-attestation"):
        gate.require_dispatch(manifest, forged)
