from pathlib import Path

import pytest

from src.models.contracts.scene import SceneIR
from src.services.orchestration.scene.errors import ObjectGeometryNotReadyError, SceneEditRejectedError
from src.services.scene.geometry_state import object_geometry_state, require_geometry_ready


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


def test_awaiting_review_rejects_with_code_and_names_the_action() -> None:
    with pytest.raises(ObjectGeometryNotReadyError) as raised:
        require_geometry_ready(scene_with_provenance(object_geometry="awaiting_review"), "sửa vùng vật")
    assert raised.value.code == "OBJECT_GEOMETRY_NOT_READY"
    assert isinstance(raised.value, SceneEditRejectedError)
    assert str(raised.value) == "Cần tạo mesh trước khi sửa vùng vật."


@pytest.mark.parametrize("provenance", [{"object_geometry": "ready"}, {}])
def test_ready_or_legacy_scene_passes_the_geometry_gate(provenance: dict) -> None:
    require_geometry_ready(scene_with_provenance(**provenance), "sửa vùng vật")
