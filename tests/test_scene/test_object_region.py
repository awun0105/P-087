"""Draft region service integration with real PLY/artifact and shell generation."""

import base64
import io
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.models.contracts.object_membership import ObjectRegionCommand, RegionBox
from src.services.orchestration.scene import membership_regeneration
from src.services.scene.editing.membership import StaleObjectMembershipRevisionError
from tests.test_scene.test_object_correction import _fixture, _source_rows

JOB = "job-fixture-001"
TARGET = "candidate-001"
OTHER = "candidate-002"


@pytest.fixture
def draft(tmp_path, monkeypatch):
    rng = np.random.default_rng(5)
    rows = np.repeat(_source_rows()[:1], 1000)
    xyz = np.concatenate(
        [
            rng.uniform(-0.2, 0.2, (400, 3)) + (1.5, 0.1, 1.1),
            rng.uniform(-0.2, 0.2, (400, 3)) + (2.3, 0.1, 1.1),
            rng.uniform(-0.2, 0.2, (200, 3)) + (1.9, 0.1, 1.1),
        ]
    )
    for axis, name in enumerate(("x", "y", "z")):
        rows[name] = xyz[:, axis]
    labels = np.repeat(np.array([0, 2, -1], dtype=np.int32), [400, 400, 200])
    fixture = _fixture(tmp_path, source_rows=rows, source_labels=labels)
    objects = []
    for item in fixture.scene.objects:
        pose = item.transform.model_copy(update={"rotation_quaternion_xyzw": (0, 0, 2**-0.5, 2**-0.5)})
        objects.append(
            item.model_copy(update={"collider": None, "provenance": {"source_transform": pose.model_dump(mode="json")}})
        )
    scene = fixture.scene.model_copy(update={"objects": objects, "provenance": {"object_geometry": "awaiting_review"}})
    scene = fixture.editor.publish_next(JOB, fixture.scene.scene_revision, scene, "draft-fixture").revision.scene
    monkeypatch.setattr(membership_regeneration, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(membership_regeneration, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
    command = ObjectRegionCommand(
        expected_scene_revision=scene.scene_revision,
        membership_checksum=fixture.membership.labels_ref.artifact_checksum,
        boxes=[RegionBox(op="add", center_m=(0, -0.15, 0), half_extents_m=(0.3, 0.55, 0.3), yaw_rad=0)],
    )
    return registry, scene, command, rows, labels


def files(registry):
    return sorted(registry.runtime_resolver.root.rglob("*"))


def test_preview_is_read_only_and_uses_source_pose(draft):
    from src.services.orchestration.scene.object_region import preview_region

    registry, scene, command, rows, labels = draft
    before = list(registry.runtime_resolver.list_uris(f"artifact://jobs/{JOB}/"))
    preview = preview_region(registry, JOB, TARGET, command)
    assert preview["added_count"] > 0 and preview["removed_count"] == 0
    assert preview["overlaps"][OTHER] > 0
    assert len(preview["added_sample_m"]) <= 20_000
    mesh = trimesh.load(io.BytesIO(base64.b64decode(preview["shell_glb_base64"])), file_type="glb", force="mesh")
    assert mesh.is_watertight and preview["shell_error"] is None
    assert registry.scene.current(JOB).scene == scene
    assert list(registry.runtime_resolver.list_uris(f"artifact://jobs/{JOB}/")) == before
    item = scene.objects[0]
    moved = item.model_copy(update={"transform": item.transform.model_copy(update={"translation_xyz": (20, 30, 40)})})
    changed = registry.scene.publish_next(
        JOB, scene.scene_revision, scene.model_copy(update={"objects": [moved, *scene.objects[1:]]}), "moved-fixture"
    ).revision.scene
    again = preview_region(
        registry, JOB, TARGET, command.model_copy(update={"expected_scene_revision": changed.scene_revision})
    )
    assert {k: v for k, v in preview.items() if k != "scene_revision"} == {
        k: v for k, v in again.items() if k != "scene_revision"
    }


@pytest.mark.parametrize(
    "field,value", [("expected_scene_revision", "rev-999"), ("membership_checksum", "sha256:" + "a" * 64)]
)
def test_preview_rejects_stale_before_writes(draft, field, value):
    from src.services.orchestration.scene.object_region import preview_region

    registry, scene, command, *_ = draft
    with pytest.raises(StaleObjectMembershipRevisionError):
        preview_region(registry, JOB, TARGET, command.model_copy(update={field: value}))
    assert registry.scene.current(JOB).scene == scene


def test_shell_failure_keeps_preview_available(draft, monkeypatch):
    from src.services.orchestration.scene import object_region as module
    from src.services.scene.gaussian_shell import GaussianShellError

    registry, _, command, *_ = draft

    def fail(*args):
        raise GaussianShellError("sparse region")

    monkeypatch.setattr(module, "build_gaussian_shell", fail)
    preview = module.preview_region(registry, JOB, TARGET, command)
    assert preview["shell_glb_base64"] is None and preview["shell_error"] == "sparse region"
