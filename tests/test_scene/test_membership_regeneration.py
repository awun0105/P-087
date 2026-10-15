"""Atomic correction publication with fixture producer output, never GPU acceptance."""

from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from src.models.contracts.object_membership import ObjectMembershipReassignCommand
from src.services.orchestration.scene import membership_regeneration as module
from src.services.orchestration.scene.errors import SceneRevisionConflictError
from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError
from src.services.process_control import ProcessCancelledError
from tests.test_scene.test_object_correction import _fixture, _source_rows


@pytest.mark.parametrize("outcome", ["success", "surface_failure", "cancelled", "stale", "build_failure"])
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

    def producer(*args, membership_override, object_ids, **kwargs):
        correction = membership_override
        seen.append(correction)
        assert editor.current("job-fixture-001").scene == base
        assert correction.labels[0] == 2
        assert correction.labels[120] == 0
        assert object_ids == {"candidate-001", "candidate-002"}
        assert set(correction.manifest.label_to_object_id) == {"0", "2", "3"}
        assert correction.evidence_ref.artifact_type == "ObjectMembershipCorrection"
        if outcome == "surface_failure":
            raise RuntimeError("surface quality gate failed")
        if outcome == "build_failure":
            raise ObjectGeometryBuildError("fixture build failed", object_id="candidate-001")
        if outcome == "cancelled":
            cancel.set()
            raise ProcessCancelledError("cancelled")
        if outcome == "stale":
            editor.publish_next("job-fixture-001", base.scene_revision, base, "concurrent-edit")
        environment = base.environment.model_copy(update={"membership": correction.manifest})
        updated = base.model_copy(
            update={
                "environment": environment,
                "provenance": {
                    **base.provenance,
                    "membership_correction": {"evidence_ref": correction.evidence_ref.model_dump(mode="json")},
                },
            }
        )
        return editor.publish_next(
            "job-fixture-001", kwargs["expected_revision"], updated, "fixture-build"
        ).revision.scene.scene_revision

    monkeypatch.setattr(module, "build_object_geometry", producer, raising=False)
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
            "build_failure": ObjectGeometryBuildError,
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


def test_load_membership_source_preserves_rows_labels_and_floor(tmp_path, monkeypatch):
    rows = _source_rows()
    fixture = _fixture(tmp_path, source_rows=rows)
    registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(module, "above_floor_mask", lambda xyz, _: xyz[:, 2] > 1.05)
    source = module.load_membership_source(registry, "job-fixture-001", fixture.scene)
    np.testing.assert_array_equal(source.rows, rows)
    np.testing.assert_array_equal(source.positions, np.column_stack([rows[name] for name in ("x", "y", "z")]))
    np.testing.assert_array_equal(source.labels, fixture.source_labels)
    np.testing.assert_array_equal(source.floor_protected, rows["z"] <= 1.05)
    assert source.manifest == fixture.membership


def test_membership_source_cache_is_bounded_and_never_shares_edited_labels(tmp_path, monkeypatch):
    module._SOURCE_CACHE.clear()
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(module, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    sources = []
    for index in range(3):
        rows = _source_rows()
        rows["x"] += index
        fixture = _fixture(tmp_path / str(index), source_rows=rows)
        registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
        source = module.load_membership_source(registry, "job-fixture-001", fixture.scene)
        again = module.load_membership_source(registry, "job-fixture-001", fixture.scene)
        assert again.rows is source.rows and again.positions is source.positions
        assert not source.rows.flags.writeable and not source.positions.flags.writeable
        source.labels[:] = -1
        np.testing.assert_array_equal(again.labels, fixture.source_labels)
        sources.append(source)
    # Ngân sách byte: mặc định 1 GiB nên ba PLY nhỏ đều nằm trong cache.
    assert len(module._SOURCE_CACHE) == 3


def test_source_cache_evicts_oldest_entries_over_the_byte_budget(tmp_path, monkeypatch):
    module._SOURCE_CACHE.clear()
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(module, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    monkeypatch.setattr(module, "_source_cache_budget", lambda: 1)
    first = _fixture(tmp_path / "first", source_rows=_source_rows())
    second_rows = _source_rows()
    second_rows["x"] += 5
    second = _fixture(tmp_path / "second", source_rows=second_rows)
    for fixture in (first, second):
        registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
        module.load_membership_source(registry, "job-fixture-001", fixture.scene)
    # Mục mới nhất luôn được giữ; mục cũ hơn bị bỏ khi vượt ngân sách.
    assert len(module._SOURCE_CACHE) == 1
    (only_key,) = module._SOURCE_CACHE
    assert only_key[1] == second.membership.source_visual_ref.artifact_checksum


def test_cold_read_of_one_job_does_not_block_another_job(tmp_path, monkeypatch):
    import threading

    module._SOURCE_CACHE.clear()
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(module, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    real_load = module._load_membership_source
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_first_read(resolver, membership, *, protect_floor):
        calls.append(membership.source_visual_ref.artifact_checksum)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
        return real_load(resolver, membership, protect_floor=protect_floor)

    monkeypatch.setattr(module, "_load_membership_source", slow_first_read)
    slow = _fixture(tmp_path / "slow", source_rows=_source_rows())
    other_rows = _source_rows()
    other_rows["x"] += 3
    other = _fixture(tmp_path / "other", source_rows=other_rows)
    slow_registry = SimpleNamespace(scene=slow.editor, runtime_resolver=slow.editor.resolver)
    other_registry = SimpleNamespace(scene=other.editor, runtime_resolver=other.editor.resolver)

    first = threading.Thread(target=module.load_membership_source, args=(slow_registry, "job-slow", slow.scene))
    first.start()
    assert started.wait(10)
    second_done = threading.Event()

    def second() -> None:
        module.load_membership_source(other_registry, "job-other", other.scene)
        second_done.set()

    threading.Thread(target=second, daemon=True).start()
    assert second_done.wait(5), "a cold read in progress must not hold the cache lock for other jobs"
    release.set()
    first.join(10)
    assert not first.is_alive()


def test_concurrent_requests_for_one_source_read_the_ply_once(tmp_path, monkeypatch):
    import threading

    module._SOURCE_CACHE.clear()
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *args: None)
    monkeypatch.setattr(module, "above_floor_mask", lambda xyz, _: np.ones(len(xyz), dtype=bool))
    real_load = module._load_membership_source
    started, release = threading.Event(), threading.Event()
    reads = []

    def slow_read(resolver, membership, *, protect_floor):
        reads.append(1)
        started.set()
        assert release.wait(10)
        return real_load(resolver, membership, protect_floor=protect_floor)

    monkeypatch.setattr(module, "_load_membership_source", slow_read)
    fixture = _fixture(tmp_path, source_rows=_source_rows())
    registry = SimpleNamespace(scene=fixture.editor, runtime_resolver=fixture.editor.resolver)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(module.load_membership_source(registry, "job-fixture-001", fixture.scene))
        )
        for _ in range(3)
    ]
    threads[0].start()
    assert started.wait(10)
    for thread in threads[1:]:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(reads) == 1
    assert len(results) == 3
    assert all(item.rows is results[0].rows for item in results)


def test_brush_correction_uses_real_partial_builder_and_preserves_other_objects(tmp_path, monkeypatch):
    from tests.test_scene.test_object_geometry_build import _ready_override, cpu_providers, draft_scene

    fixture = draft_scene.__wrapped__(tmp_path, monkeypatch)
    cpu_providers.__wrapped__(monkeypatch)
    _ready_override(fixture)
    before = fixture.scene
    monkeypatch.setattr(
        module,
        "job_bundle",
        lambda *a: SimpleNamespace(canonical_geometry_ref=before.environment.membership.source_geometry_ref),
    )
    first = before.objects[0]
    # Legacy Ready scenes have the immutable extraction pose in source_collision.
    provenance = dict(first.provenance)
    provenance.pop("source_transform")
    first = first.model_copy(
        update={
            "provenance": provenance,
            "transform": first.transform.model_copy(update={"translation_xyz": (10, 20, 30)}),
        }
    )
    before = fixture.registry.scene.publish_next(
        fixture.job_id,
        before.scene_revision,
        before.model_copy(update={"objects": [first, *before.objects[1:]]}),
        "legacy-ready",
    ).revision.scene
    command = ObjectMembershipReassignCommand(
        expected_scene_revision=before.scene_revision,
        membership_checksum=before.environment.membership.labels_ref.artifact_checksum,
        source_visual_checksum=before.environment.membership.source_visual_ref.artifact_checksum,
        source_gaussian_indices=[0],
        source_object_id=first.id,
        target_object_id=None,
    )
    phases = []
    revision = module.regenerate_membership(
        fixture.registry,
        fixture.job_id,
        fixture.settings,
        fixture.workspace,
        command=command,
        actor_id="reviewer",
        expected_revision=before.scene_revision,
        progress=phases.append,
    )
    after = fixture.registry.scene.current(fixture.job_id).scene
    assert after.scene_revision == revision
    assert after.objects[1:] == before.objects[1:]
    assert after.objects[0].transform == first.transform
    assert after.objects[0].provenance["source_transform"] == first.source_collision.source_transform.model_dump(
        mode="json"
    )
    assert after.objects[0].provenance["gaussians"] == (fixture.labels == 0).sum() - 1
    assert phases == ["shell", "quality", "collider", "environment", "publish"]
