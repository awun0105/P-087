"""Conditional modality metadata proof for the shared InputManifest."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

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
