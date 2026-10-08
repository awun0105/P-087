"""Serialized calibration-QA contract fixture consumed fail-closed by downstream code."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.lidar_calibration_qa import LidarCalibrationQAReport, LidarCalibrationQAResult
from src.services.reconstruction.lidar.calibration_qa import is_sensor_package_collision_eligible

FIXTURE = Path(__file__).parents[1] / "fixtures" / "contracts" / "lidar_calibration_qa_v1.json"


def test_s1_consumer_fixture_roundtrips_exact_sources_and_stays_ineligible() -> None:
    report = LidarCalibrationQAReport.model_validate_json(FIXTURE.read_bytes())
    verify_content_checksum(report, "report_checksum")

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert report.package_ref.artifact_checksum == report.input_checksum
    assert report.calibration_ref is not None
    assert report.calibration_ref.artifact_checksum == report.calibration_checksum
    assert report.timing_ref.artifact_checksum == report.timing_checksum
    assert report.intrinsics_ref is not None
    assert report.intrinsics_ref.artifact_checksum == report.intrinsics_checksum
    assert not is_sensor_package_collision_eligible(report)


def test_consumer_contract_rejects_pass_without_projection_evidence() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["result"] = "PASS"

    with pytest.raises(ValidationError, match="PASS requires projection evidence"):
        LidarCalibrationQAReport.model_validate(payload)
