"""Draft region service integration with real PLY/artifact and shell generation."""

import base64
import io
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.models.contracts.object_membership import ObjectRegionCommand, RegionBox
from src.services.orchestration.scene import membership_regeneration
from src.services.scene.editing.membership import ObjectMembershipValidationError, StaleObjectMembershipRevisionError
from tests.test_scene.test_object_correction import _fixture, _source_rows
from tests.test_scene.test_object_geometry_build import build, cpu_providers, draft_scene  # noqa: F401

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


@pytest.mark.parametrize("finish", ["success", "cancelled", "failure"])
def test_ready_region_claim_rebuilds_both_owners_without_draft_publication(draft, monkeypatch, finish):
    from src.services.orchestration.scene import object_region as module
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError
    from src.services.process_control import ProcessCancelledError
    from src.services.scene.editing.membership import decode_gaussian_membership_labels

    registry, scene, command, rows, old_labels = draft
    scene = registry.scene.publish_next(
        JOB,
        scene.scene_revision,
        scene.model_copy(update={"provenance": {"object_geometry": "ready"}}),
        "ready-fixture",
    ).revision.scene
    command = command.model_copy(update={"expected_scene_revision": scene.scene_revision, "claim_from": [OTHER]})
    seen = []

    def build(registry_arg, settings, job_id, *, membership_override, object_ids, expected_revision, **kwargs):
        assert registry_arg is registry and job_id == JOB
        assert registry.scene.current(JOB).scene == scene
        assert object_ids == {TARGET, OTHER}
        updated = membership_override
        actual = decode_gaussian_membership_labels(
            registry.runtime_resolver.require(updated.manifest.labels_ref).read_bytes(), updated.manifest
        )
        np.testing.assert_array_equal(actual, updated.labels)
        assert np.count_nonzero(actual == 2) < np.count_nonzero(old_labels == 2)
        assert updated.evidence_ref.artifact_type == "ObjectRegionEdit"
        seen.append(updated)
        if finish == "cancelled":
            raise ProcessCancelledError("cancelled")
        if finish == "failure":
            raise ObjectGeometryBuildError("shell failed", object_id=TARGET)
        return registry.scene.publish_next(
            JOB,
            expected_revision,
            scene.model_copy(
                update={"environment": scene.environment.model_copy(update={"membership": updated.manifest})}
            ),
            "fixture-build",
        ).revision.scene.scene_revision

    monkeypatch.setattr(module, "build_object_geometry", build, raising=False)
    arguments = dict(command=command, actor_id="reviewer", expected_revision=scene.scene_revision)
    if finish == "success":
        revision = module.rebuild_region_ready(registry, None, JOB, Path("fixture-work"), object_id=TARGET, **arguments)
        assert registry.scene.current(JOB).scene.scene_revision == revision
        assert int(revision.split("-")[1]) == int(scene.scene_revision.split("-")[1]) + 1
    else:
        with pytest.raises(ProcessCancelledError if finish == "cancelled" else ObjectGeometryBuildError):
            module.rebuild_region_ready(registry, None, JOB, Path("fixture-work"), object_id=TARGET, **arguments)
        assert registry.scene.current(JOB).scene == scene
    assert len(seen) == 1


def test_ready_queue_validation_rejects_claim_that_discards_an_owner(draft):
    from src.services.orchestration.scene.object_region import validate_region_rebuild

    registry, scene, command, *_ = draft
    scene = registry.scene.publish_next(
        JOB,
        scene.scene_revision,
        scene.model_copy(update={"provenance": {"object_geometry": "ready"}}),
        "ready-fixture",
    ).revision.scene
    command = command.model_copy(
        update={
            "expected_scene_revision": scene.scene_revision,
            "claim_from": [OTHER],
            "boxes": [RegionBox(op="add", center_m=(0, -1, 0), half_extents_m=(1, 2, 1), yaw_rad=0)],
        }
    )
    with pytest.raises(ObjectMembershipValidationError, match="50"):
        validate_region_rebuild(registry, JOB, TARGET, command)


def _ready(fixture, monkeypatch):  # noqa: ANN001, ANN202
    from src.services.orchestration.scene import membership_regeneration

    monkeypatch.setattr(membership_regeneration, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(membership_regeneration, "above_floor_mask", lambda xyz, _: xyz[:, 2] > 0.05)
    build(fixture)
    fixture.scene = fixture.registry.scene.current(fixture.job_id).scene
    assert fixture.scene.provenance["object_geometry"] == "ready"
    return fixture.scene


def _command(scene, boxes, claim_from=()):  # noqa: ANN001, ANN202
    from src.models.contracts.object_membership import ObjectRegionCommand

    return ObjectRegionCommand(
        expected_scene_revision=scene.scene_revision,
        membership_checksum=scene.environment.membership.labels_ref.artifact_checksum,
        boxes=boxes,
        claim_from=list(claim_from),
    )


def _box(center, half):  # noqa: ANN001, ANN202
    return {"op": "add", "center_m": center, "half_extents_m": half, "yaw_rad": 0.0}


def _rebuild(fixture, command, **kwargs):  # noqa: ANN001, ANN202
    from src.services.orchestration.scene.object_region import rebuild_region_ready

    return rebuild_region_ready(
        fixture.registry,
        fixture.settings,
        fixture.job_id,
        fixture.workspace / "region",
        object_id="candidate-001",
        command=command,
        actor_id="tester",
        expected_revision=command.expected_scene_revision,
        **kwargs,
    )


def test_ready_region_edit_rebuilds_only_the_edited_object_and_the_environment(
    draft_scene,  # noqa: F811
    cpu_providers,  # noqa: F811
    monkeypatch,  # noqa: F811
) -> None:
    before = _ready(draft_scene, monkeypatch)
    old = {item.id: item for item in before.objects}
    # Trim the three lowest grid layers of candidate-001 (object-local z below -0.11 m).
    command = _command(before, [_box([0, 0, 0.05], [0.2, 0.2, 0.16])])

    revision = _rebuild(draft_scene, command)

    after = draft_scene.registry.scene.current(draft_scene.job_id).scene
    new = {item.id: item for item in after.objects}
    assert revision == after.scene_revision != before.scene_revision
    assert after.provenance["object_geometry"] == "ready"
    assert after.provenance["membership_correction"]["evidence_ref"]["artifact_type"] == "ObjectRegionEdit"
    assert after.environment.membership.labels_ref != before.environment.membership.labels_ref
    assert after.environment.object_aware_collision_ref != before.environment.object_aware_collision_ref
    assert new["candidate-001"].collider.geometry_ref != old["candidate-001"].collider.geometry_ref
    assert new["candidate-001"].provenance["gaussians"] == 990
    # The untouched object keeps its exact geometry and collider.
    assert new["candidate-002"].collider == old["candidate-002"].collider
    assert new["candidate-002"].surface_mesh_ref == old["candidate-002"].surface_mesh_ref
    assert new["candidate-001"].provenance["surface_selection"]["chosen"] == "gaussian_shell"
    assert cpu_providers is not None


def test_claimed_object_is_rebuilt_with_the_edited_object(draft_scene, cpu_providers, monkeypatch) -> None:  # noqa: F811
    before = _ready(draft_scene, monkeypatch)
    old = {item.id: item for item in before.objects}
    # Keep all of candidate-001 and take one grid column (x = -1.88 m local) from candidate-002.
    command = _command(
        before,
        [_box([0, 0, 0], [0.13, 0.17, 0.21]), _box([-1.88, 0, 0], [0.01, 0.17, 0.21])],
        claim_from=["candidate-002"],
    )

    _rebuild(draft_scene, command)

    after = {item.id: item for item in draft_scene.registry.scene.current(draft_scene.job_id).scene.objects}
    assert after["candidate-001"].provenance["gaussians"] == 1287 + 143
    assert after["candidate-002"].provenance["gaussians"] == 1287 - 143
    for object_id in ("candidate-001", "candidate-002"):
        assert after[object_id].collider.geometry_ref != old[object_id].collider.geometry_ref


def test_shell_method_never_runs_objectgs(draft_scene, cpu_providers, monkeypatch) -> None:  # noqa: F811
    from src.services.orchestration.scene import object_geometry_build as module

    before = _ready(draft_scene, monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("ObjectGS must not run for a shell region rebuild")

    monkeypatch.setattr(module, "run_prepared_objectgs", forbidden)
    _rebuild(draft_scene, _command(before, [_box([0, 0, 0.05], [0.2, 0.2, 0.16])]))


@pytest.mark.parametrize("failure", ["stale", "cancelled", "below_minimum"])
def test_failed_region_rebuild_keeps_the_ready_head(draft_scene, cpu_providers, monkeypatch, failure) -> None:  # noqa: F811
    from src.services.process_control import ProcessCancelledError
    from src.services.scene.editing.membership import (
        ObjectMembershipValidationError,
        StaleObjectMembershipRevisionError,
    )

    before = _ready(draft_scene, monkeypatch)
    if failure == "below_minimum":
        command = _command(before, [_box([0, 0, 0.2], [0.02, 0.02, 0.01])])
        expected, kwargs = ObjectMembershipValidationError, {}
    else:
        command = _command(before, [_box([0, 0, 0.05], [0.2, 0.2, 0.16])])
        if failure == "stale":
            command = command.model_copy(update={"expected_scene_revision": "rev-999"})
            expected, kwargs = StaleObjectMembershipRevisionError, {}
        else:
            cancel = Event()
            cancel.set()
            expected, kwargs = ProcessCancelledError, {"cancel_event": cancel}

    with pytest.raises(expected):
        _rebuild(draft_scene, command, **kwargs)

    current = draft_scene.registry.scene.current(draft_scene.job_id).scene
    assert current.scene_revision == before.scene_revision
    assert np.array_equal(
        np.frombuffer(
            draft_scene.registry.runtime_resolver.require(current.environment.membership.labels_ref).read_bytes(),
            dtype="<i4",
        ),
        np.frombuffer(
            draft_scene.registry.runtime_resolver.require(before.environment.membership.labels_ref).read_bytes(),
            dtype="<i4",
        ),
    )


def test_draft_scene_is_refused_by_the_ready_rebuild(draft_scene, monkeypatch) -> None:  # noqa: F811
    from src.services.orchestration.scene import membership_regeneration
    from src.services.orchestration.scene.object_region import validate_region_rebuild
    from src.services.scene.editing.membership import ObjectMembershipValidationError

    monkeypatch.setattr(membership_regeneration, "fit_canonical_floor_model", lambda *args: None)
    command = _command(draft_scene.scene, [_box([0, 0, 0.05], [0.2, 0.2, 0.16])])
    with pytest.raises(ObjectMembershipValidationError, match="Draft"):
        validate_region_rebuild(draft_scene.registry, draft_scene.job_id, "candidate-001", command)
