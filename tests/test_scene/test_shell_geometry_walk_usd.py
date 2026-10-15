"""T-018: shell-built scenes (T-007) through Walk and USD; legacy and ObjectGS-era scenes keep their behaviour."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.object_geometry import ObjectShellManifest
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.objects import apply_object_action
from src.services.simulation.usd.builder import _collect_scene_refs
from tests.test_scene.test_object_geometry_build import (  # noqa: F401  (pytest fixtures)
    build,
    cpu_providers,
    draft_scene,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "data/scene_runtime/bin/python"


@pytest.fixture
def ready_shell_scene(draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace) -> SimpleNamespace:  # noqa: F811 (pytest fixture chain)
    """The T-007 draft fixture built into a Ready scene; CoACD is the test double from `cpu_providers`."""
    build(draft_scene)
    return draft_scene


def test_shell_surfaces_are_accepted_by_every_backend_reader(ready_shell_scene: SimpleNamespace) -> None:
    registry, job_id = ready_shell_scene.registry, ready_shell_scene.job_id
    ready = registry.scene.current(job_id).scene
    confirmed = apply_object_action(registry.scene, job_id, ready.objects[0].id, "confirm", ready.scene_revision)
    scene = confirmed.revision.scene
    surface_a, surface_b = (item.surface_mesh_ref for item in scene.objects)
    # Scene contract: the shell is a valid surface_mesh_ref, and the collider stays a separate reference.
    assert surface_a.artifact_type == surface_b.artifact_type == "ObjectShellMesh"
    # USD inventory: only active objects export their surface and collider.
    _, geometry, colliders = _collect_scene_refs(scene)
    assert surface_a in geometry and scene.objects[0].collider.geometry_ref in colliders
    assert surface_b not in geometry
    # Artifact retention: every object keeps its surface referenced, active or not.
    references = SceneEditor.artifact_references(scene)
    assert surface_a in references and surface_b in references
    # Shell manifest: the audit receipt names the same shell mesh that the scene uses as its surface.
    for item in scene.objects:
        ref = ProductArtifactRef.model_validate(item.provenance["shell_manifest_ref"])
        manifest = ObjectShellManifest.model_validate_json(registry.runtime_resolver.require(ref).read_bytes())
        assert manifest.shell_mesh_ref == item.surface_mesh_ref
