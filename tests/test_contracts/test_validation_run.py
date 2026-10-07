"""Versioned operational validation contracts preserve the report identity."""

import json
from pathlib import Path

from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.validation import ValidationReport
from src.models.contracts.validation_run import ValidationConfig

FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_adding_run_contract_does_not_change_existing_report_checksum_or_fields() -> None:
    payload = json.loads((FIXTURES / "validation_report/validation_report.json").read_text(encoding="utf-8"))
    report = ValidationReport.model_validate(payload)

    verify_content_checksum(report, "report_checksum")
    assert report.report_checksum == canonical_content_checksum(report, "report_checksum")
    assert set(report.model_dump(mode="json")) == set(payload)


def test_validation_config_round_trip_keeps_public_policy_identity() -> None:
    config = ValidationConfig(
        schema_version="1.0",
        policy_id="warehouse-basic-v1",
        required_check_ids=["ISAAC_LOAD"],
        warning_check_ids=[],
        path_pairs=[],
        config_checksum="sha256:" + "0" * 64,
    )
    checksum = canonical_content_checksum(config, "config_checksum")
    sealed = config.model_copy(update={"config_checksum": checksum})

    decoded = ValidationConfig.model_validate_json(sealed.model_dump_json())
    assert decoded == sealed
    assert decoded.config_checksum == canonical_content_checksum(decoded, "config_checksum")
