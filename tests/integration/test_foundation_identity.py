"""Synthetic handoff and targeted corruption tests across the four tracks."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.check_foundation import _check_handoff_lineage, verify_fixture_references
from src.models.contracts.identity import canonical_content_checksum, verify_candidate_lineage
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.release import SceneRevisionRecord
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import CandidatePackage, ValidationReport
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.artifacts.errors import ArtifactChecksumError, ArtifactNotFoundError

FIXTURES = Path(__file__).parents[2] / "fixtures"
RESOLVER = ArtifactResolver(FIXTURES / "artifact_store")


def _payload(relative_path: str) -> dict[str, object]:
    """Mutate a copy of one fixture, never the committed artifact."""
    return json.loads((FIXTURES / relative_path).read_text(encoding="utf-8"))


def test_synthetic_handoff_chain_uses_one_identity() -> None:
    """REC → SCENE → SIM → PRODUCT works with published synthetic refs."""
    _check_handoff_lineage()
    candidate = CandidatePackage.model_validate(_payload("candidate/candidate_package.json"))
    report = ValidationReport.model_validate(_payload("validation_report/validation_report.json"))
    assert candidate.candidate_checksum == report.candidate_checksum
    verify_fixture_references([candidate, report], RESOLVER)


def test_missing_candidate_artifact_is_detected() -> None:
    """An inventory entry cannot point to an absent USD payload."""
    payload = _payload("candidate/candidate_package.json")
    payload["entrypoint_usd"]["artifact_uri"] = "artifact://jobs/job-fixture-001/simulation/missing.usda"
    candidate = CandidatePackage.model_validate(payload)
    with pytest.raises(ArtifactNotFoundError):
        verify_fixture_references([candidate], RESOLVER)


def test_wrong_byte_checksum_is_detected() -> None:
    """A valid-looking but incorrect SHA-256 cannot cross the handoff."""
    payload = _payload("scene_ir/scene.json")
    payload["environment"]["geometry_ref"]["artifact_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(ArtifactChecksumError):
        verify_fixture_references([SceneIR.model_validate(payload)], RESOLVER)


@pytest.mark.parametrize("field", ["geometry_ref", "asset_ref", "visual_ref"])
def test_missing_scene_object_ref_is_detected(field: str) -> None:
    """The traversal covers required and optional object representations."""
    payload = _payload("scene_ir/scene.json")
    ref = dict(payload["objects"][0]["geometry_ref"])
    ref["artifact_uri"] = f"artifact://jobs/job-fixture-001/scene/missing_{field}.ply"
    payload["objects"][0][field] = ref
    with pytest.raises(ArtifactNotFoundError):
        verify_fixture_references([SceneIR.model_validate(payload)], RESOLVER)


def test_missing_collider_ref_is_detected() -> None:
    """Collider geometry is part of the same logical object handoff."""
    payload = _payload("scene_ir/scene.json")
    payload["objects"][0]["collider"]["geometry_ref"]["artifact_uri"] = (
        "artifact://jobs/job-fixture-001/scene/missing_collider.ply"
    )
    with pytest.raises(ArtifactNotFoundError):
        verify_fixture_references([SceneIR.model_validate(payload)], RESOLVER)


@pytest.mark.parametrize("path", ["alignment_record", "alignment_record.evidence_refs"])
def test_broken_alignment_evidence_is_detected(path: str) -> None:
    """Both the direct alignment payload and nested evidence must resolve."""
    payload = _payload("reconstruction_bundle/mixed_manifest.json")
    target = (
        payload["alignment_record"] if path == "alignment_record" else payload["alignment_record"]["evidence_refs"][0]
    )
    target["artifact_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(ArtifactChecksumError):
        verify_fixture_references([ReconstructionBundle.model_validate(payload)], RESOLVER)


def test_broken_path_evidence_is_detected() -> None:
    """Path evidence is not skipped in favour of top-level check evidence."""
    payload = _payload("validation_report/validation_report.json")
    payload["path_results"][0]["evidence_refs"][0]["artifact_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(ArtifactChecksumError):
        verify_fixture_references([ValidationReport.model_validate(payload)], RESOLVER)


def test_release_candidate_mismatch_is_rejected() -> None:
    """A release-facing record cannot promote a different candidate Y."""
    candidate = CandidatePackage.model_validate(_payload("candidate/candidate_package.json"))
    report = ValidationReport.model_validate(_payload("validation_report/validation_report.json"))
    states = _payload("mock_job/scene_revision_states.json")
    release = SceneRevisionRecord.model_validate(states[3])
    with pytest.raises(ValueError, match="release candidate identity mismatch"):
        verify_candidate_lineage(
            candidate, report, release.model_copy(update={"candidate_checksum": "sha256:" + "0" * 64})
        )


def test_validation_candidate_mismatch_is_rejected() -> None:
    """Report content can be valid while targeting the wrong package."""
    candidate = CandidatePackage.model_validate(_payload("candidate/candidate_package.json"))
    report = ValidationReport.model_validate(_payload("validation_report/validation_report.json"))
    states = _payload("mock_job/scene_revision_states.json")
    release = SceneRevisionRecord.model_validate(states[3])
    wrong = report.model_copy(update={"candidate_checksum": "sha256:" + "0" * 64})
    wrong.report_checksum = canonical_content_checksum(wrong, "report_checksum")
    with pytest.raises(ValueError, match="ValidationReport candidate identity mismatch"):
        verify_candidate_lineage(candidate, wrong, release)


def test_raw_gt_ref_is_still_rejected_by_product_chain() -> None:
    """F-03 classification remains enforced through SceneIR parsing."""
    payload = _payload("scene_ir/scene.json")
    payload["environment"]["geometry_ref"]["data_class"] = "ground_truth"
    with pytest.raises(ValidationError, match="data_class"):
        SceneIR.model_validate(payload)
