"""Draft geometry publication is fenced; failed builds never replace the active scene."""

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_stale_revision_is_rejected_before_reading_artifacts(tmp_path: Path) -> None:
    from src.services.orchestration.scene.object_geometry_build import build_object_geometry
    from src.services.scene.editing.membership import StaleObjectMembershipRevisionError

    registry = SimpleNamespace(
        scene=SimpleNamespace(current=lambda _: SimpleNamespace(scene=SimpleNamespace(scene_revision="rev-002")))
    )
    with pytest.raises(StaleObjectMembershipRevisionError):
        build_object_geometry(registry, None, "job-test", expected_revision="rev-001", workspace=tmp_path)


@pytest.mark.parametrize("missing_membership", [True, False])
def test_full_build_requires_membership_and_draft(tmp_path: Path, missing_membership: bool) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError, build_object_geometry

    scene = SimpleNamespace(
        scene_revision="rev-001",
        environment=SimpleNamespace(membership=None if missing_membership else object()),
        provenance={"object_geometry": "ready"},
    )
    registry = SimpleNamespace(scene=SimpleNamespace(current=lambda _: SimpleNamespace(scene=scene)))
    with pytest.raises(ObjectGeometryBuildError):
        build_object_geometry(registry, None, "job-test", expected_revision="rev-001", workspace=tmp_path)
