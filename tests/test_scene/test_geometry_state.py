from pathlib import Path

import pytest

from src.models.contracts.scene import SceneIR
from src.services.scene.geometry_state import object_geometry_state


def scene_with_provenance(**entries: object) -> SceneIR:
    value = SceneIR.model_validate_json((Path(__file__).parents[2] / "fixtures/scene_ir/scene.json").read_bytes())
    return value.model_copy(update={"provenance": entries})


def test_scene_without_geometry_key_is_ready_for_legacy_scenes() -> None:
    assert object_geometry_state(scene_with_provenance()) == "ready"


def test_explicit_states_are_returned_unchanged() -> None:
    assert object_geometry_state(scene_with_provenance(object_geometry="awaiting_review")) == "awaiting_review"
    assert object_geometry_state(scene_with_provenance(object_geometry="ready")) == "ready"


@pytest.mark.parametrize("state", ["building", "", None])
def test_unknown_geometry_state_is_an_error(state: object) -> None:
    with pytest.raises(ValueError, match="unknown object_geometry state"):
        object_geometry_state(scene_with_provenance(object_geometry=state))
