"""A selected collision source cannot outlive the object-region set it maps."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.orchestration.scene.extraction import use_boxes
from src.services.orchestration.scene.objectify import ObjectifyError, reobjectify


def _registry_with_selected_source() -> SimpleNamespace:
    scene = SimpleNamespace(
        scene_revision="rev-001",
        environment=SimpleNamespace(collision_selection_ref=object()),
    )
    revision = SimpleNamespace(scene=scene)
    repository = SimpleNamespace(current=lambda _job_id: revision)
    return SimpleNamespace(scene=repository)


def test_reobjectification_cannot_replace_objects_after_collision_source_selection(tmp_path: Path) -> None:
    with pytest.raises(ObjectifyError, match="collision source đang được chọn"):
        reobjectify(_registry_with_selected_source(), "job-fixture-001", None, tmp_path)


def test_box_extraction_cannot_replace_objects_after_collision_source_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collision source đang được chọn"):
        use_boxes(_registry_with_selected_source(), "job-fixture-001", None, tmp_path)
