"""Candidate manifests must retain the project-owned coordinate convention."""

import pytest
from pydantic import ValidationError

from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.validation import CandidateManifest

CHECKSUM = "sha256:" + "4" * 64


def _candidate_payload() -> dict[str, object]:
    """Build a minimal candidate inventory without simulator-native coordinates."""
    return {
        "schema_version": "1.0",
        "candidate_id": "candidate-fixture-001",
        "scene_revision": "rev-001",
        "scene_ir_checksum": CHECKSUM,
        "job_manifest_checksum": CHECKSUM,
        "coordinate_system": CoordinateSystem().model_dump(),
        "object_transforms": [],
        "asset_refs": [],
        "collider_refs": [],
        "artifact_checksums": [],
        "build_config_checksum": CHECKSUM,
    }


def test_canonical_candidate_manifest_roundtrips() -> None:
    """EX-SIM publishes and EX-PRODUCT reads one canonical coordinate model."""
    candidate = CandidateManifest.model_validate(_candidate_payload())
    assert candidate.coordinate_system == CoordinateSystem()
    assert CandidateManifest.model_validate_json(candidate.model_dump_json()) == candidate


@pytest.mark.parametrize(("field", "value"), [("unit", "feet"), ("up_axis", "Y"), ("handedness", "left")])
def test_candidate_rejects_noncanonical_coordinates(field: str, value: str) -> None:
    """Simulator-native coordinates must be converted before candidate sealing."""
    payload = _candidate_payload()
    payload["coordinate_system"][field] = value
    with pytest.raises(ValidationError, match=field):
        CandidateManifest.model_validate(payload)


def test_candidate_rejects_duplicate_coordinate_fields() -> None:
    """Legacy free-form unit/up_axis fields cannot compete with CoordinateSystem."""
    payload = _candidate_payload()
    payload["unit"] = "meter"
    with pytest.raises(ValidationError, match="unit"):
        CandidateManifest.model_validate(payload)
