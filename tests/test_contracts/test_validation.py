"""Contract tests for validation and evaluation isolation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.validation import EvaluationReport, PreflightRule, ValidationReport

FIXTURES = Path(__file__).parents[2] / "fixtures"
CHECKSUM = "sha256:" + "4" * 64


def test_validation_report_fixture_is_structured() -> None:
    """EX-PRODUCT receives structured checks and observed path results."""
    report = ValidationReport.model_validate_json(
        (FIXTURES / "validation_report/validation_report.json").read_text(encoding="utf-8")
    )

    assert report.overall_result == "PASS"
    assert report.checks[0].check_id == "ISAAC_LOAD"
    assert report.path_results[0].result == "CLEAR"


def test_required_route_blocked_is_not_a_preflight_rule() -> None:
    """Route blocking belongs to Isaac/Product validation, not static preflight."""
    with pytest.raises(ValidationError, match="rule_id"):
        PreflightRule.model_validate(
            {
                "rule_id": "REQUIRED_ROUTE_BLOCKED",
                "severity": "blocking",
                "result": "FAIL",
                "affected_object_ids": [],
                "evidence_refs": [],
            }
        )


def test_expected_path_label_is_rejected_from_validation_report() -> None:
    """Isaac validation cannot read or serialize a hidden expected label."""
    with pytest.raises(ValidationError, match="expected_result"):
        ValidationReport.model_validate_json(
            (FIXTURES / "invalid/validation_with_expected_label.json").read_text(encoding="utf-8")
        )


def test_evaluation_report_owns_expected_path_comparison() -> None:
    """Only EvaluationReport compares observed and locked expected results."""
    report = EvaluationReport.model_validate(
        {
            "schema_version": "1.0",
            "subject_type": "candidate_package",
            "subject_id": "candidate-001",
            "subject_checksum": CHECKSUM,
            "evaluation_protocol_id": "locked-protocol-tbd",
            "references_used": [],
            "preprocessing_dependencies": [],
            "metrics": [],
            "path_comparisons": [
                {
                    "pair_id": "pair-001",
                    "observed_result": "CLEAR",
                    "expected_result": "CLEAR",
                    "agreement": True,
                }
            ],
            "report_checksum": CHECKSUM,
        }
    )

    assert report.path_comparisons[0].agreement is True
