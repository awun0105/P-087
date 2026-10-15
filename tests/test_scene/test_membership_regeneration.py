"""Atomic correction publication with fixture producer output, never GPU acceptance."""

from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from src.models.contracts.object_membership import ObjectMembershipReassignCommand
from src.services.orchestration.scene import membership_regeneration as module
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.orchestration.scene.objectify import ObjectifyResult
from src.services.process_control import ProcessCancelledError
from tests.test_scene.test_object_correction import _fixture, _source_rows


@pytest.mark.parametrize("outcome", ["success", "surface_failure", "cancelled", "stale", "wrong_receipt"])
def test_regeneration_preserves_active_scene_until_fenced_publish(tmp_path, monkeypatch, outcome):
    rows = np.repeat(_source_rows(), 60)
    labels = np.repeat(np.array([0, 0, 1, 1, 2, 2, 3, 3, -1], dtype=np.int32), 60)
    fixture = _fixture(tmp_path, source_rows=rows, source_labels=labels)
    editor = fixture.editor
    base = fixture.scene
    reference = base.environment.geometry_ref.model_copy(update={"artifact_type": "ObjectAwareEnvironmentManifest"})
    base = base.model_copy(
        update={"environment": base.environment.model_copy(update={"object_aware_collision_ref": reference})}
    )
    # Publish the fixture with a moved/rotated Candidate. Source ownership stays unchanged.
    first = base.objects[0]
    edited = first.model_copy(
        update={
            "transform": first.transform.model_copy(
                update={
                    "translation_xyz": (20, 30, 40),
                    "rotation_quaternion_xyzw": (0, 0, 0.6, 0.8),
                }
            )
        }
    )
    base = editor.publish_next(
        "job-fixture-001",
        base.scene_revision,
        base.model_copy(update={"objects": [edited, *base.objects[1:]]}),
        "fixture",
    ).revision.scene
    registry = SimpleNamespace(
        scene=editor, runtime_resolver=editor.resolver, get_job=lambda _: SimpleNamespace(job_id="job-fixture-001")
    )

    def no_post_commit_upload(_):
        raise AssertionError("fallible upload must finish before the SceneIR CAS")

    monkeypatch.setattr(editor.resolver, "sync_up", no_post_commit_upload)
    monkeypatch.setattr(
        module, "job_bundle", lambda *a: SimpleNamespace(canonical_geometry_ref=fixture.membership.source_geometry_ref)
    )
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *a: None)
    monkeypatch.setattr(module, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    command = ObjectMembershipReassignCommand(
        expected_scene_revision=base.scene_revision,
        membership_checksum=fixture.membership.labels_ref.artifact_checksum,
        source_visual_checksum=fixture.membership.source_visual_ref.artifact_checksum,
        source_gaussian_indices=[0],
        source_object_id="candidate-001",
        target_object_id="candidate-002",
    )
    cancel = Event()
    seen = []

    def producer(*args, correction, **kwargs):
        seen.append(correction)
        assert editor.current("job-fixture-001").scene == base
        assert correction.labels[0] == 2
        assert correction.labels[120] == 0  # duplicate owner labels canonicalized, never another object
        assert correction.source_poses[edited.id] == first.source_collision.source_transform
        assert set(correction.membership.label_to_object_id) == {"0", "2", "3"}
        assert correction.evidence_ref.artifact_type == "ObjectMembershipCorrection"
        if outcome == "surface_failure":
            raise RuntimeError("surface quality gate failed")
        if outcome == "cancelled":
            cancel.set()
        if outcome == "stale":
            editor.publish_next("job-fixture-001", base.scene_revision, base, "concurrent-edit")
        environment = base.environment.model_copy(
            update={"membership": correction.membership if outcome != "wrong_receipt" else fixture.membership}
        )
        return ObjectifyResult(environment, base.objects, {"fixture": True})

    monkeypatch.setattr(module, "objectify_with_retry", producer)
    kwargs = dict(command=command, actor_id="fixture-user", expected_revision=base.scene_revision, cancel_event=cancel)
    if outcome == "success":
        revision = module.regenerate_membership(registry, "job-fixture-001", None, tmp_path / "work", **kwargs)
        current = editor.current("job-fixture-001").scene
        assert current.scene_revision == revision != base.scene_revision
        assert current.objects[0].transform == edited.transform
        assert current.objects[0].source_collision == first.source_collision
        assert current.objects[0].physics == first.physics
        assert current.environment.membership.labels_ref != fixture.membership.labels_ref
        assert current.provenance["membership_correction"]["evidence_ref"]
    else:
        errors = {
            "surface_failure": RuntimeError,
            "cancelled": ProcessCancelledError,
            "stale": SceneRevisionConflictError,
            "wrong_receipt": ValueError,
        }
        with pytest.raises(errors[outcome]):
            module.regenerate_membership(registry, "job-fixture-001", None, tmp_path / "work", **kwargs)
        current = editor.current("job-fixture-001").scene
        assert current.environment.membership == base.environment.membership
        assert current.objects == base.objects
        assert (
            current.scene_revision == base.scene_revision
            if outcome != "stale"
            else current.scene_revision != base.scene_revision
        )
    assert len(seen) == 1
