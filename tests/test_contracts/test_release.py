"""Release invariants and review-state separation tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import canonical_content_checksum, verify_candidate_lineage
from src.models.contracts.release import ReleaseManifest
from src.models.contracts.validation import CandidatePackage, ValidationReport

CHECKSUM = "sha256:" + "5" * 64


def _release_payload(run_type: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "run_type": run_type,
        "project_id": "project-001",
        "scene_version": "scene-001-rev-001",
        "input_manifest_checksum": CHECKSUM,
        "job_manifest_checksum": CHECKSUM,
        "candidate_checksum": CHECKSUM,
        "preflight_report_checksum": CHECKSUM,
        "validation_report_checksum": CHECKSUM,
        "processing_config_checksum": CHECKSUM,
        "software_versions": {"isaac_sim": "UNVERIFIED"},
        "artifact_inventory": [],
        "review_state": "APPROVED",
        "approval_record": {
            "reviewer_id": "duc",
            "approved_at": datetime(2026, 9, 23, tzinfo=UTC),
            "accepted_warning_ids": [],
            "record_checksum": CHECKSUM,
        },
        "release_timestamp": datetime(2026, 9, 23, tzinfo=UTC),
        "release_manifest_checksum": CHECKSUM,
    }


def test_ordinary_release_can_omit_evaluation() -> None:
    """Ordinary product release does not pretend to be benchmark acceptance."""
    release = ReleaseManifest.model_validate(_release_payload("ORDINARY"))
    assert release.evaluation_report_checksum is None


@pytest.mark.parametrize("run_type", ["LOCKED_MVP_ACCEPTANCE", "BENCHMARK"])
def test_locked_release_requires_evaluation(run_type: str) -> None:
    """Locked acceptance and benchmark releases fail without evaluation evidence."""
    with pytest.raises(ValidationError, match="requires an EvaluationReport"):
        ReleaseManifest.model_validate(_release_payload(run_type))


def test_release_inventory_rejects_raw_gt_even_under_input_uri() -> None:
    """Product release inventory enforces class, not the URI's folder name."""
    payload = _release_payload("ORDINARY")
    payload["artifact_inventory"] = [
        {
            "artifact_type": "GroundTruthMap",
            "artifact_uri": "artifact://jobs/job-123/input/map.ply",
            "artifact_checksum": CHECKSUM,
            "data_class": "ground_truth",
        }
    ]
    with pytest.raises(ValidationError, match="data_class"):
        ReleaseManifest.model_validate(payload)


def test_release_inventory_accepts_derived_artifact() -> None:
    """A correctly classified derived artifact remains releasable."""
    payload = _release_payload("ORDINARY")
    payload["artifact_inventory"] = [
        {
            "artifact_type": "Geometry",
            "artifact_uri": "artifact://jobs/job-123/evaluation_only/preview.ply",
            "artifact_checksum": CHECKSUM,
            "data_class": "derived",
        }
    ]
    assert ReleaseManifest.model_validate(payload).artifact_inventory[0].data_class == "derived"


def test_release_manifest_binds_exact_validated_candidate() -> None:
    """Release contract keeps package and validation identities aligned."""
    root = Path(__file__).parents[2] / "fixtures"
    candidate = CandidatePackage.model_validate_json((root / "candidate/candidate_package.json").read_text())
    report = ValidationReport.model_validate_json((root / "validation_report/validation_report.json").read_text())
    payload = _release_payload("ORDINARY")
    payload.update(candidate_checksum=candidate.candidate_checksum, validation_report_checksum=report.report_checksum)
    release = ReleaseManifest.model_validate(payload)
    release.release_manifest_checksum = canonical_content_checksum(release, "release_manifest_checksum")
    verify_candidate_lineage(candidate, report, release)
    release.candidate_checksum = "sha256:" + "0" * 64
    release.release_manifest_checksum = canonical_content_checksum(release, "release_manifest_checksum")
    with pytest.raises(ValueError, match="release candidate identity mismatch"):
        verify_candidate_lineage(candidate, report, release)
