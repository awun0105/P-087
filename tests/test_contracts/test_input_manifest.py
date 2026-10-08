"""Conditional modality metadata proof for the shared InputManifest."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import InputManifest

FIXTURE = Path(__file__).parents[2] / "fixtures/mock_job/input_manifest.json"


def _input_payload() -> dict[str, object]:
    """Load the canonical RGB-only input fixture for isolated mutations."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rgb_only_input_does_not_require_lidar_metadata() -> None:
    """RGB-only input stays valid without LiDAR-specific metadata."""
    manifest = InputManifest.model_validate(_input_payload())
    assert manifest.input_configuration.registered_lidar_present is False
    assert manifest.lidar_metadata is None


def test_lidar_input_without_metadata_is_rejected() -> None:
    """The LiDAR modality cannot be announced without unit/frame/status."""
    payload = _input_payload()
    payload["input_configuration"].update(registered_lidar_present=True, declared_same_scene=True)
    with pytest.raises(ValidationError, match="requires lidar_metadata"):
        InputManifest.model_validate(payload)


def test_lidar_input_with_metadata_is_valid() -> None:
    """Generic unit, coordinate frame and registration status survive parsing."""
    payload = _input_payload()
    payload["input_configuration"].update(registered_lidar_present=True, declared_same_scene=True)
    payload["lidar_metadata"] = {"unit": "meter", "coordinate_frame": "sensor", "registration_status": "registered"}
    assert InputManifest.model_validate(payload).lidar_metadata.coordinate_frame == "sensor"


def test_lidar_metadata_without_modality_is_rejected() -> None:
    """Declared metadata cannot contradict the input modality flags."""
    payload = _input_payload()
    payload["lidar_metadata"] = {"unit": "meter", "coordinate_frame": "sensor", "registration_status": "registered"}
    with pytest.raises(ValidationError, match="requires registered_lidar_present"):
        InputManifest.model_validate(payload)


@pytest.mark.parametrize("field", ["unit", "coordinate_frame", "registration_status"])
def test_lidar_metadata_fields_cannot_be_empty(field: str) -> None:
    """A present metadata object must still carry usable generic values."""
    payload = _input_payload()
    payload["input_configuration"].update(registered_lidar_present=True, declared_same_scene=True)
    payload["lidar_metadata"] = {"unit": "meter", "coordinate_frame": "sensor", "registration_status": "registered"}
    payload["lidar_metadata"][field] = ""
    with pytest.raises(ValidationError, match=field):
        InputManifest.model_validate(payload)


def test_rgb_depth_input_does_not_invent_input_depth_encoding_fields() -> None:
    """Depth encoding lives in ReconstructionBundle, not InputManifest."""
    payload = _input_payload()
    payload["input_configuration"]["depth_present"] = True
    assert InputManifest.model_validate(payload).input_configuration.depth_present is True


def test_legacy_manifest_checksum_survives_absent_preparation_provenance() -> None:
    """Adding video preparation metadata must not rewrite checksums of old inputs."""
    current = InputManifest.model_validate(_input_payload())
    legacy_payload = current.model_dump(mode="json")
    legacy_payload.pop("preparation_provenance", None)
    legacy_payload["input_manifest_checksum"] = canonical_content_checksum(legacy_payload, "input_manifest_checksum")

    legacy = InputManifest.model_validate(legacy_payload)
    verify_content_checksum(legacy, "input_manifest_checksum")

    assert legacy.preparation_provenance is None
    assert "preparation_provenance" not in legacy.model_dump(mode="json")


def test_explicit_null_preparation_provenance_remains_part_of_identity() -> None:
    """A producer that explicitly hashes null keeps the same serialized content."""
    payload = InputManifest.model_validate(_input_payload()).model_dump(mode="json")
    payload["preparation_provenance"] = None
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")

    manifest = InputManifest.model_validate(payload)
    verify_content_checksum(manifest, "input_manifest_checksum")

    assert "preparation_provenance" in manifest.model_dump(mode="json")
