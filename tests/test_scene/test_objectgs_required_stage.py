"""A configured ObjectGS job must never become an environment-only or box fallback success."""

from types import SimpleNamespace

import pytest

from src.config import Settings
from src.services.orchestration.scene import extraction, objectify
from src.services.orchestration.scene.objectify import ObjectifyError


@pytest.mark.parametrize("runtime_available", [True, False])
def test_required_objectgs_failure_never_publishes_a_legacy_scene(tmp_path, monkeypatch, runtime_available):
    published = []
    monkeypatch.setattr(extraction, "job_requires_strict_geometry", lambda *a: True)
    monkeypatch.setattr(extraction, "_idempotent_publish", lambda *a: lambda *args: published.append(args))
    monkeypatch.setattr(extraction, "_sam2_runtime", lambda *a: SimpleNamespace(available=lambda: runtime_available))

    def fail(*a, **kw):
        raise ObjectifyError("required ObjectGS failed", retryable=False)

    monkeypatch.setattr(extraction, "objectify_with_retry", fail)
    with pytest.raises(ObjectifyError):
        extraction.extract_scene(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), Settings(), tmp_path)
    assert not published


def test_explicit_objectgs_choice_fails_before_sam2_if_its_runtime_is_missing(tmp_path):
    with pytest.raises(ObjectifyError, match="isolated runtime/checkouts"):
        objectify.objectify(
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            Settings(),
            tmp_path,
            lambda *a: None,
            scene_config={"scene": {"geometry_method": "objectgs"}},
        )


@pytest.mark.parametrize("operation", ["merge", "reassign"])
def test_objectgs_correction_cannot_invoke_legacy_gaussian_collider_producer(tmp_path, monkeypatch, operation):
    from src.services.orchestration.scene import object_correction
    from src.services.scene.editing.membership import ObjectMembershipValidationError

    scene = SimpleNamespace(environment=SimpleNamespace(object_aware_collision_ref=object()))
    editor = SimpleNamespace(current=lambda job: SimpleNamespace(scene=scene))
    monkeypatch.setattr(object_correction, "validate_object_membership_command", lambda *a: None)

    def forbidden(*a, **kw):
        raise AssertionError("legacy producer must not run")

    monkeypatch.setattr(object_correction, "_run", forbidden)
    function = (
        object_correction.merge_object_candidates
        if operation == "merge"
        else object_correction.reassign_object_membership
    )
    kwargs = dict(actor_id="fixture-user", runtime_python=tmp_path / "python", workspace=tmp_path, timeout_seconds=10)
    if operation == "reassign":
        kwargs.update(view_requests=[], gpu_index=None, lama_checkpoint=None)
    with pytest.raises(ObjectMembershipValidationError, match="OBJECTGS_RETRAIN_REQUIRED"):
        function(editor, "job-test", SimpleNamespace(), **kwargs)


def test_manual_objectgs_smoke_choice_preserves_other_sealed_job_controls(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        objectify,
        "load_job_config",
        lambda *a: SimpleNamespace(scene={"geometry_method": "legacy", "coacd_threshold": 0.03, "sam_batch": 4}),
    )

    def produce(*a, **kw):
        captured.update(kw["scene_config"])
        return "fixture-result"

    monkeypatch.setattr(objectify, "objectify", produce)
    registry = SimpleNamespace(runtime_resolver=None)
    job = SimpleNamespace(job_id="job-test", config_checksum="sha256:" + "a" * 64)
    result = objectify.objectify_with_retry(
        registry,
        job,
        SimpleNamespace(),
        Settings(product_objectify_attempts=1),
        tmp_path,
        lambda *a: None,
        geometry_method="objectgs",
    )
    assert result == "fixture-result"
    assert captured["scene"]["geometry_method"] == "objectgs"
    assert captured["scene"]["sam_batch"] == 4
    assert captured["coacd"]["threshold"] == 0.03
