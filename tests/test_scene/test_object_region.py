"""Draft region service integration with real PLY/artifact and shell generation."""

import base64
import io
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.models.contracts.object_membership import ObjectRegionCommand, RegionBox
from src.services.orchestration.scene import membership_regeneration
from src.services.scene.editing.membership import ObjectMembershipValidationError, StaleObjectMembershipRevisionError
from tests.test_scene.test_object_correction import _fixture, _source_rows

JOB = "job-fixture-001"
TARGET = "candidate-001"
OTHER = "candidate-002"


@pytest.fixture
def draft(tmp_path, monkeypatch):
    membership_regeneration._SOURCE_CACHE.clear()
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
            item.model_copy(
                update={
                    "collider": None,
                    "provenance": {
                        "source_transform": pose.model_dump(mode="json"),
                        "shell_error": "old preview failed",
                    },
                }
            )
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


def test_preview_is_read_only_and_uses_source_pose(draft, tmp_path):
    from src.services.orchestration.scene.object_region import preview_region

    registry, scene, command, rows, labels = draft
    before = list(registry.runtime_resolver.list_uris(f"artifact://jobs/{JOB}/"))
    before_files = set(tmp_path.rglob("*"))
    preview = preview_region(registry, JOB, TARGET, command)
    assert preview["added_count"] > 0 and preview["removed_count"] == 0
    assert preview["overlaps"][OTHER] > 0
    assert len(preview["added_sample_m"]) <= 20_000
    mesh = trimesh.load(io.BytesIO(base64.b64decode(preview["shell_glb_base64"])), file_type="glb", force="mesh")
    assert mesh.is_watertight and preview["shell_error"] is None
    assert registry.scene.current(JOB).scene == scene
    assert set(tmp_path.rglob("*")) == before_files
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


def test_apply_updates_membership_and_claimed_objects_without_recentering(draft):
    from scipy.spatial.transform import Rotation

    from src.services.orchestration.scene.object_region import apply_region_draft
    from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply
    from src.services.scene.editing.membership import decode_gaussian_membership_labels

    registry, scene, command, rows, old_labels = draft
    command = command.model_copy(update={"claim_from": [OTHER]})
    result = apply_region_draft(registry, JOB, TARGET, command, actor_id="reviewer")
    updated = result.revision.scene
    assert updated.scene_revision != scene.scene_revision
    manifest = updated.environment.membership
    assert manifest.source_visual_ref == scene.environment.membership.source_visual_ref
    assert manifest.source_geometry_ref == scene.environment.membership.source_geometry_ref
    assert manifest.extraction_revision == scene.environment.membership.extraction_revision
    labels = decode_gaussian_membership_labels(
        registry.runtime_resolver.require(manifest.labels_ref).read_bytes(), manifest
    )
    assert np.count_nonzero(labels == 2) < np.count_nonzero(old_labels == 2)
    for old, item in zip(scene.objects[:2], updated.objects[:2], strict=True):
        assert item.visual_ref != old.visual_ref and item.geometry_ref != old.geometry_ref
        assert item.collider is None and item.provenance.get("shell_error") is None
        assert item.geometry_ref.artifact_type == "ObjectShellMesh"
        local_rows = read_gaussian_ply(registry.runtime_resolver.require(item.visual_ref).read_bytes())
        pose = item.provenance["source_transform"]
        assert pose == old.provenance["source_transform"] and item.transform == old.transform
        reconstructed = (
            Rotation.from_quat(pose["rotation_quaternion_xyzw"]).apply(positions(local_rows)) + pose["translation_xyz"]
        )
        selected = np.isin(labels, [int(k) for k, v in manifest.label_to_object_id.items() if v == item.id])
        np.testing.assert_allclose(reconstructed, positions(rows[selected]), atol=2e-7)
        assert item.primitive_dimensions_xyz_m == pytest.approx(np.maximum(np.ptp(positions(local_rows), axis=0), 0.05))
    assert updated.objects[2] == scene.objects[2]
    evidence = updated.provenance["object_region_edit"]
    assert evidence["actor_id"] == "reviewer"
    import json

    from src.models.contracts.artifacts import ProductArtifactRef

    payload = json.loads(
        registry.runtime_resolver.require(ProductArtifactRef.model_validate(evidence["evidence_ref"])).read_bytes()
    )
    assert payload["command"] == command.model_dump(mode="json")
    assert "added_sample_m" not in payload["preview"]


@pytest.mark.parametrize("failure", ["ready", "claim_empty", "too_small", "ignored", "unmapped", "stale"])
def test_apply_rejects_before_any_artifact_publish(draft, failure):
    from src.services.orchestration.scene.object_region import apply_region_draft

    registry, scene, command, *_ = draft
    target = TARGET
    if failure == "ready":
        scene = registry.scene.publish_next(
            JOB,
            scene.scene_revision,
            scene.model_copy(update={"provenance": {"object_geometry": "ready"}}),
            "ready-fixture",
        ).revision.scene
        command = command.model_copy(update={"expected_scene_revision": scene.scene_revision})
    elif failure == "claim_empty":
        command = command.model_copy(
            update={
                "claim_from": [OTHER],
                "boxes": [RegionBox(op="add", center_m=(0, -1, 0), half_extents_m=(1, 2, 1), yaw_rad=0)],
            }
        )
    elif failure == "too_small":
        command = command.model_copy(
            update={"boxes": [RegionBox(op="add", center_m=(0, 0, 0), half_extents_m=(0.005, 0.005, 0.005), yaw_rad=0)]}
        )
    elif failure == "ignored":
        first = scene.objects[0].model_copy(update={"provenance": {**scene.objects[0].provenance, "review": "IGNORED"}})
        scene = registry.scene.publish_next(
            JOB,
            scene.scene_revision,
            scene.model_copy(update={"objects": [first, *scene.objects[1:]]}),
            "ignored-fixture",
        ).revision.scene
        command = command.model_copy(update={"expected_scene_revision": scene.scene_revision})
    elif failure == "unmapped":
        target = "missing"
    else:
        command = command.model_copy(update={"expected_scene_revision": "rev-999"})
    before = list(registry.runtime_resolver.list_uris(f"artifact://jobs/{JOB}/"))
    with pytest.raises(ObjectMembershipValidationError):
        apply_region_draft(registry, JOB, target, command, actor_id="reviewer")
    assert list(registry.runtime_resolver.list_uris(f"artifact://jobs/{JOB}/")) == before
    assert registry.scene.current(JOB).scene == scene


def test_apply_records_shell_failure_without_creating_collider(draft, monkeypatch):
    from src.services.orchestration.scene import object_region as module

    registry, scene, command, *_ = draft
    monkeypatch.setattr(module, "_shell", lambda *args: (None, {}, "sparse region"))
    updated = module.apply_region_draft(registry, JOB, TARGET, command, actor_id="reviewer").revision.scene
    item = updated.objects[0]
    assert item.collider is None and item.geometry_ref.artifact_type == "ObjectShellMesh"
    assert item.provenance["shell_error"] == "sparse region"
    assert item.provenance["shell_display"] == "bounding_box_placeholder"


def test_preview_three_hundred_thousand_rows_budget(tmp_path, monkeypatch):
    from time import perf_counter

    from src.services.orchestration.scene.object_region import preview_region

    rng = np.random.default_rng(90)
    rows = np.repeat(_source_rows()[:1], 300_000)
    xyz = rng.uniform(-0.2, 0.2, (len(rows), 3)) + (1.5, 0.1, 1.1)
    for axis, name in enumerate(("x", "y", "z")):
        rows[name] = xyz[:, axis]
    fixture = _fixture(tmp_path, source_rows=rows, source_labels=np.zeros(len(rows), dtype=np.int32))
    item = fixture.scene.objects[0]
    item = item.model_copy(update={"provenance": {"source_transform": item.transform.model_dump(mode="json")}})
    scene = fixture.editor.publish_next(
        JOB,
        fixture.scene.scene_revision,
        fixture.scene.model_copy(update={"objects": [item, *fixture.scene.objects[1:]]}),
        "benchmark-fixture",
    ).revision.scene
    registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
    monkeypatch.setattr(membership_regeneration, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(membership_regeneration, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    command = ObjectRegionCommand(
        expected_scene_revision=scene.scene_revision,
        membership_checksum=fixture.membership.labels_ref.artifact_checksum,
        boxes=[RegionBox(op="add", center_m=(0, 0, 0), half_extents_m=(0.3, 0.3, 0.3), yaw_rad=0)],
    )
    started = perf_counter()
    result = preview_region(registry, JOB, TARGET, command)
    elapsed = perf_counter() - started
    print(f"300k preview elapsed={elapsed:.3f}s")
    assert result["object_gaussian_count"] == 300_000
    assert result["shell_glb_base64"] is not None
    assert result["shell_sample_rows"] <= 100_000
    assert elapsed <= 1.5
