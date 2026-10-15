"""Provider request overrides and validation without invoking GPU providers."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.services.orchestration.scene import objectify as module


class StopAfterProvidersError(RuntimeError):
    """Stop the fixture before publication; all provider requests are captured."""


@pytest.mark.parametrize(
    "override",
    [
        None,
        {},
        {
            "scene": {"max_objects": 1, "min_score": 0.8, "max_area": 0.2, "box_margin_m": 0.1, "sam_batch": 4},
            "coacd": {"threshold": 0.03, "max_convex_hull": 3, "preprocess_resolution": 20, "voxel_m": 0.02},
            "inpaint": {"max_new_gaussians": 100, "behind_object_m": 0.07},
        },
        {"scene": {"geometry_review": "required"}},
    ],
)
def test_provider_requests_receive_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: dict | None
) -> None:
    master = tmp_path / "master.ply"
    master.write_bytes(b"fixture")
    rows = np.zeros(2, dtype=[("x", "f4")])
    points = np.zeros((2, 3))
    frame = SimpleNamespace(center=(0, 0, 0), image="image", model_dump=lambda **kwargs: {})
    part = SimpleNamespace(index=0, rows=rows)
    requests: dict[str, dict] = {}
    seed_options: list[dict] = []
    monkeypatch.setattr(module.Sam2Runtime, "available", lambda self: True)
    monkeypatch.setattr(module, "metric_visual_master", lambda *args: "master")
    monkeypatch.setattr(module.gaussian_split, "read_gaussian_ply", lambda payload: rows)
    monkeypatch.setattr(module.gaussian_split, "positions", lambda data: points)
    monkeypatch.setattr(module, "fit_canonical_floor_model", lambda *args: object())
    monkeypatch.setattr(module, "publish_floor_fit_evidence", lambda *args: (None, None))
    monkeypatch.setattr(module, "scene_floor_fit_summary", lambda *args: {})
    monkeypatch.setattr(module, "camera_views", lambda *args: [frame])

    def seeds(*args: object, **kwargs: object) -> list[np.ndarray]:
        seed_options.append(kwargs)
        return [np.array([0])]

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, *args: object, **kwargs: object
    ) -> dict:
        requests[name] = request
        if name == "lift":
            np.savez(workspace / "labels.npz", labels=np.array([0, -1]))
            return {"views": 1}
        return {"objects": []} if name == "convex" else {"method": "fixture"}

    def stop(*args: object, **kwargs: object) -> Path:
        raise StopAfterProvidersError

    monkeypatch.setattr(module, "_seeds", seeds)
    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(
        module.gaussian_split, "assign_floor_gaussians_to_background", lambda data, labels, floor: labels
    )
    monkeypatch.setattr(module.gaussian_split, "split", lambda *args: (rows, [part]))
    monkeypatch.setattr(module.gaussian_split, "write_gaussian_ply", lambda data: b"fixture")
    monkeypatch.setattr(module, "package_splat", stop)
    settings = SimpleNamespace(
        product_scene_runtime_python=master,
        product_sam2_checkpoint=master,
        product_scene_timeout_seconds=10,
        product_lama_checkpoint=None,
        product_geometry_gpu_index=0,
    )
    registry = SimpleNamespace(runtime_resolver=SimpleNamespace(require=lambda ref: master))
    bundle = SimpleNamespace(camera_pose_refs=[None], rgb_frame_refs=[])
    with pytest.raises(StopAfterProvidersError):
        module.objectify(
            registry,
            SimpleNamespace(job_id="fixture"),
            bundle,
            settings,
            tmp_path / "attempt",
            lambda *args: None,
            scene_config=override,
        )
    groups = override or {}
    # The runner falls back to legacy, so the chosen refinement is always sent explicitly.
    # geometry_review routes the job after extraction; the lift runner must never receive it.
    assert requests["lift"]["config"] == {
        "refinement": "legacy",
        **{
            key: value
            for key, value in groups.get("scene", {}).items()
            if key not in {"max_objects", "geometry_review"}
        },
    }
    assert requests["convex"]["config"] == groups.get("coacd", {})
    assert requests["inpaint"]["config"] == groups.get("inpaint", {})
    assert seed_options == (
        [{}] if override is None else [{"max_objects": groups.get("scene", {}).get("max_objects", 60)}]
    )


@pytest.mark.parametrize(
    "override",
    [
        {"scene": {"max_objects": 0}},
        {"scene": {"sam_batch": 0}},
        {"scene": {"min_score": 2}},
        {"coacd": {"voxel_m": float("nan")}},
        {"coacd": {"max_convex_hull": -1}},
        {"inpaint": {"max_new_gaussians": -1}},
        {"inpaint": {"behind_object_m": float("inf")}},
        {"scene": {"unknown": 1}},
        {"scene": {"geometry_review": "later"}},
        {"scene": {"geometry_method": "unknown"}},
    ],
)
def test_invalid_config_rejected_before_runtime(override: dict[str, object], tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        module.objectify(None, None, None, None, tmp_path, None, scene_config=override)


def test_defaults_match_provider_fallbacks() -> None:
    config = module.ObjectifyConfig()
    assert config.scene.max_objects == 60
    assert config.scene.model_dump(exclude={"max_objects"}) == dict(
        refinement="legacy",
        min_score=0.6,
        max_area=0.35,
        box_margin_m=0.15,
        sam_batch=32,
        geometry_method="legacy",
        geometry_review="legacy",
        objectgs_iterations=30000,
        objectgs_background_voxel_m=0.04,
    )
    assert config.coacd.model_dump() == dict(threshold=0.08, max_convex_hull=8, preprocess_resolution=30, voxel_m=0.04)
    assert config.inpaint.model_dump() == dict(max_new_gaussians=400_000, behind_object_m=0.05)


def test_geometry_method_accepts_shell_and_rejects_unknown_values() -> None:
    assert module.SceneObjectifyConfig(geometry_method="shell").geometry_method == "shell"
    with pytest.raises(ValueError):
        module.SceneObjectifyConfig(geometry_method="unknown")


def test_seed_count_override_limits_instances(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    points = np.arange(36).reshape(12, 3)
    instances = [np.arange(start, start + 3) for start in range(0, 12, 3)]
    monkeypatch.setattr(module.gaussian_split, "working_set", lambda *args: np.arange(12))
    monkeypatch.setattr(module.gaussian_split, "positions", lambda rows: points)
    monkeypatch.setattr(module, "run_sam2", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "segment", lambda *args, **kwargs: instances)
    monkeypatch.setattr(module, "box_from_points", lambda *args: SimpleNamespace(dimensions=(0.5, 0.5, 0.5)))
    args = (points, [], points, None, tmp_path, None)
    assert len(module._seeds(*args)) == 4
    limited = module._seeds(*args, max_objects=1)
    assert len(limited) == 1
    np.testing.assert_array_equal(limited[0], instances[0])


def test_retry_preserves_provider_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = {"scene": {"max_objects": 1}}
    seen: list[dict] = []
    result = object()

    def attempt(*args: object, **kwargs: object) -> object:
        seen.append(kwargs)
        if len(seen) == 1:
            raise module.ObjectifyError("transient fixture failure")
        return result

    monkeypatch.setattr(module, "objectify", attempt)
    actual = module.objectify_with_retry(
        None,
        SimpleNamespace(job_id="fixture"),
        None,
        SimpleNamespace(product_objectify_attempts=2),
        tmp_path,
        None,
        scene_config=override,
    )
    assert actual is result
    assert [entry["scene_config"] for entry in seen] == [override, override]


def test_multiview_choice_is_explicit_and_preserves_other_provider_controls(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        module, "load_job_config", lambda *args: SimpleNamespace(scene={"sam_batch": 4, "coacd_threshold": 0.03})
    )

    def objectify(*args, **kwargs):
        captured.update(kwargs["scene_config"])
        return SimpleNamespace(provenance={})

    monkeypatch.setattr(module, "objectify", objectify)
    module.objectify_with_retry(
        SimpleNamespace(runtime_resolver=None),
        SimpleNamespace(job_id="job-test", config_checksum="unused"),
        SimpleNamespace(),
        SimpleNamespace(product_objectify_attempts=1),
        tmp_path,
        lambda ref, data: ref,
        refinement="multiview_v1",
    )
    assert captured["scene"] == {"sam_batch": 4, "refinement": "multiview_v1"}
    assert captured["coacd"] == {"threshold": 0.03}
    assert module.SceneObjectifyConfig().refinement == "legacy"
    with pytest.raises(ValueError):
        module.SceneObjectifyConfig(refinement="unreviewed")


def test_small_volumetric_candidate_retained_without_admitting_planar_wall(tmp_path, monkeypatch):
    from eval.fixtures.segmentation import cases, floor_model
    from tests.test_scene.test_membership_refinement import rows_for

    model = floor_model(cases()[0])
    small = np.array([(x, y, z) for x in np.linspace(0, 0.08, 5) for y in np.linspace(0, 0.08, 5) for z in (0.1, 0.14)])
    wall = small.copy()
    wall[:, 0] += 1
    wall[:, 2] = 0.1
    points = np.vstack([small, wall])
    rows = rows_for(points)
    instances = [np.arange(len(small)), np.arange(len(small), len(points))]
    monkeypatch.setattr(module, "run_sam2", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "segment", lambda *args, **kwargs: instances)
    arguments = (rows, [], np.array([[0, 0, 0]]), None, tmp_path, model)
    assert module._seeds(*arguments) == []
    refined = module._seeds(*arguments, refinement="multiview_v1")
    assert len(refined) == 1
    np.testing.assert_array_equal(refined[0], instances[0])


def test_low_object_survives_prompt_candidate_floor_split_and_membership_encoding(tmp_path, monkeypatch):
    from eval.fixtures.segmentation import cases, floor_model
    from src.services.scene.editing.membership import encode_gaussian_membership_labels
    from src.services.scene.sampro3d.consolidate import Proposal, Sampro3dConfig, select_prompts
    from tests.test_scene.test_membership_refinement import rows_for

    model = floor_model(cases()[0])
    points = np.array(
        [(x, y, z) for x in np.linspace(0, 0.08, 5) for y in np.linspace(0, 0.08, 5) for z in (0.003, 0.004)]
    )
    rows = rows_for(points)
    assert len(select_prompts(points, model)) == 0
    assert len(select_prompts(points, model, Sampro3dConfig(refinement="multiview_v1"))) > 0
    proposal = Proposal(np.arange(3), np.zeros(3, dtype=int), np.ones(3), [np.arange(50)] * 3, [np.arange(50)] * 3)
    monkeypatch.setattr(module, "run_sam2", lambda *args, **kwargs: proposal)
    args = (rows, [], np.array([[0, 0, 0]]), None, tmp_path, model)
    assert module._seeds(*args) == []
    (members,) = module._seeds(*args, refinement="multiview_v1")
    labels = np.full(50, -1, dtype=np.int32)
    labels[members] = 0
    labels = module.gaussian_split.assign_floor_gaussians_to_background(rows, labels, model, refinement=True)
    background, parts = module.gaussian_split.split(rows, labels)
    assert len(background) == 0 and len(parts) == 1 and len(parts[0].rows) == 50
    payload = encode_gaussian_membership_labels(labels, gaussian_count=50, label_to_object_id={"0": "candidate-001"})
    np.testing.assert_array_equal(np.frombuffer(payload, dtype="<i4"), np.zeros(50, dtype=int))
