"""Draft extraction stops before expensive geometry providers."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.services.orchestration.scene import objectify as module


@pytest.fixture
def draft_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    grid = np.array(np.meshgrid(*[np.linspace(-0.15, 0.15, 7)] * 3)).reshape(3, -1).T
    points = np.vstack([grid + [2, 3, 1], grid + [-2, 1, 2], [[0, 0, 0]]])
    rows = np.zeros(
        len(points), dtype=[(name, "<f4") for name in ("x", "y", "z", "opacity", "scale_0", "rot_0", "f_dc_0")]
    )
    for axis, name in enumerate(("x", "y", "z")):
        rows[name] = points[:, axis]
    rows["opacity"] = 5
    labels = np.repeat([2, 5, -1], [len(grid), len(grid), 1]).astype(np.int32)
    master = tmp_path / "master.ply"
    master.write_bytes(module.gaussian_split.write_gaussian_ply(rows))

    def reference(kind: str) -> module.ProductArtifactRef:
        return module._reference("job-draft", kind + "/{digest}", kind, module.StageId.SCENE_DECOMPOSE, kind.encode())

    source = reference("GaussianPLY")
    bundle = SimpleNamespace(
        visual_artifact_ref=reference("VisualArtifact"),
        canonical_geometry_ref=reference("CanonicalGeometry"),
        camera_pose_refs=[None],
        rgb_frame_refs=[],
    )
    registry = SimpleNamespace(runtime_resolver=SimpleNamespace(require=lambda ref: master))
    settings = SimpleNamespace(
        product_scene_runtime_python=master,
        product_sam2_checkpoint=master,
        product_scene_timeout_seconds=10,
        product_objectgs_runtime_python=None,
        product_objectgs_repository=None,
        product_objectgs_gsplat_repository=None,
    )
    frame = SimpleNamespace(center=(0, 0, 0), image="image", model_dump=lambda **kwargs: {})
    monkeypatch.setattr(module.Sam2Runtime, "available", lambda self: True)
    monkeypatch.setattr(module, "metric_visual_master", lambda *args: source)
    monkeypatch.setattr(
        module,
        "fit_canonical_floor_model",
        lambda *args: SimpleNamespace(status="supported", fallback_reason=None, profile_checksum="fixture"),
    )
    monkeypatch.setattr(module, "publish_floor_fit_evidence", lambda *args: (None, None))
    monkeypatch.setattr(module, "scene_floor_fit_summary", lambda *args: {"status": "supported"})
    monkeypatch.setattr(module, "camera_views", lambda *args: [frame])
    seeds = [np.array([], dtype=int)] * 6
    seeds[2], seeds[5] = np.flatnonzero(labels == 2), np.flatnonzero(labels == 5)
    monkeypatch.setattr(module, "_seeds", lambda *args, **kwargs: seeds)
    monkeypatch.setattr(
        module.gaussian_split, "assign_floor_gaussians_to_background", lambda data, labels, floor, **kwargs: labels
    )
    published = {}

    def publish(ref: module.ProductArtifactRef, payload: bytes) -> module.ProductArtifactRef:
        published[ref.artifact_uri] = payload
        return ref

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, *args: object, **kwargs: object
    ) -> dict:
        assert name == "lift", f"Draft called {name}"
        assert "geometry_review" not in request["config"]
        np.savez(workspace / "labels.npz", labels=labels)
        return {"views": 1, "masks_per_object": {"2": 1, "5": 1}}

    monkeypatch.setattr(module, "_run", run)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Draft called an expensive geometry provider")

    monkeypatch.setattr(module, "run_prepared_objectgs", forbidden)
    monkeypatch.setattr(module, "package_splat", forbidden)
    monkeypatch.setattr(module, "build_background_collision", forbidden)

    def extract(method: str = "shell") -> module.ObjectifyResult:
        return module.objectify(
            registry,
            SimpleNamespace(job_id="job-draft"),
            bundle,
            settings,
            tmp_path / "attempt",
            publish,
            scene_config={"scene": {"geometry_method": method, "geometry_review": "required"}},
        )

    return SimpleNamespace(extract=extract, bundle=bundle, published=published, labels=labels, source=source)


def test_objectgs_draft_does_not_require_objectgs_runtime(draft_inputs: SimpleNamespace) -> None:
    result = draft_inputs.extract("objectgs")
    assert result.provenance["object_geometry"] == "awaiting_review"
    assert result.provenance["geometry_method"] == "objectgs"
    assert len(result.objects) == 2


def test_draft_objects_have_preview_shells_and_source_poses(draft_inputs: SimpleNamespace) -> None:
    result = draft_inputs.extract()
    assert len(result.objects) == 2
    for number, item in enumerate(result.objects, 1):
        assert item.id == f"candidate-{number:03d}"
        assert item.collider is None
        assert item.surface_mesh_ref is None
        assert item.geometry_ref.artifact_type == "ObjectShellMesh"
        assert item.state == module.SceneObjectState.CANDIDATE
        assert not item.active
        assert item.provenance["source_transform"] == item.transform.model_dump(mode="json")
        assert item.provenance["gaussians"] == 343


def test_draft_shells_are_local_watertight_glbs(draft_inputs: SimpleNamespace) -> None:
    import io

    import trimesh

    result = draft_inputs.extract()
    for item in result.objects:
        mesh = trimesh.load(
            io.BytesIO(draft_inputs.published[item.geometry_ref.artifact_uri]), file_type="glb", force="mesh"
        )
        assert mesh.is_watertight
        # split() already centres rows. Subtracting the world centre twice would break this.
        np.testing.assert_allclose(mesh.bounds.mean(axis=0), 0, atol=0.06)
        assert "solidity" in item.provenance["shell_preview"]["statistics"]
        visual = module.gaussian_split.read_gaussian_ply(draft_inputs.published[item.visual_ref.artifact_uri])
        np.testing.assert_allclose(module.gaussian_split.positions(visual).mean(axis=0), 0, atol=1e-6)


def test_shell_failure_keeps_object_as_display_placeholder(
    draft_inputs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise module.GaussianShellError("fixture QA failure")

    monkeypatch.setattr(module, "build_gaussian_shell", broken, raising=False)
    result = draft_inputs.extract()
    assert len(result.objects) == 2
    for item in result.objects:
        assert item.collider is None
        assert item.provenance["shell_error"] == "fixture QA failure"
        assert item.provenance["shell_display"] == "bounding_box_placeholder"
        assert item.geometry_ref.artifact_type == "ObjectShellMesh"


def test_draft_never_calls_geometry_or_background_providers(draft_inputs: SimpleNamespace) -> None:
    # Fixture providers raise immediately if anything beyond lift is invoked.
    result = draft_inputs.extract()
    assert result.provenance["geometry_review"] == "required"
    assert result.provenance["segmentation_refinement"] == "legacy"
    assert result.provenance["floor_fit"] == {"status": "supported"}
    assert result.provenance["object_gaussians"] == 686
    assert result.provenance["background_gaussians"] == 1
    assert "inpaint_method" not in result.provenance


def test_draft_environment_keeps_full_bundle_and_published_membership(draft_inputs: SimpleNamespace) -> None:
    result = draft_inputs.extract()
    environment = result.environment
    assert environment.visual_ref == draft_inputs.bundle.visual_artifact_ref
    assert environment.geometry_ref == draft_inputs.bundle.canonical_geometry_ref
    assert environment.object_aware_collision_ref is None
    assert environment.collider_ref is None
    assert environment.visual_master_ref is None
    membership = environment.membership
    assert membership.source_visual_ref == draft_inputs.source
    assert membership.label_to_object_id == {"2": "candidate-001", "5": "candidate-002"}
    assert membership.extraction_revision == "rev-001"
    np.testing.assert_array_equal(
        np.frombuffer(draft_inputs.published[membership.labels_ref.artifact_uri], dtype="<i4"), draft_inputs.labels
    )


def test_retry_preserves_sealed_geometry_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}
    monkeypatch.setattr(
        module,
        "load_job_config",
        lambda *args: SimpleNamespace(
            scene={"geometry_method": "shell", "geometry_review": "required", "coacd_threshold": 0.03}
        ),
    )

    def attempt(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs["scene_config"])
        return SimpleNamespace(provenance={})

    monkeypatch.setattr(module, "objectify", attempt)
    module.objectify_with_retry(
        SimpleNamespace(runtime_resolver=None),
        SimpleNamespace(job_id="job-draft", config_checksum="unused"),
        None,
        SimpleNamespace(product_objectify_attempts=1),
        tmp_path,
        None,
    )
    assert captured["scene"] == {"geometry_method": "shell", "geometry_review": "required"}
    assert captured["coacd"] == {"threshold": 0.03}


def test_strict_extraction_error_names_shell_and_objectgs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.scene import extraction

    monkeypatch.setattr(extraction, "job_requires_strict_geometry", lambda *args: True)
    monkeypatch.setattr(extraction, "_sam2_runtime", lambda *args: None)
    with pytest.raises(module.ObjectifyError, match="Job hình học nghiêm ngặt") as error:
        extraction.extract_scene(
            SimpleNamespace(runtime_resolver=None), None, None, SimpleNamespace(product_objectify=False), tmp_path
        )
    assert not error.value.retryable


def test_geometry_entrypoints_accept_shell_without_obsolete_alias() -> None:
    from typing import get_type_hints

    assert not hasattr(module, "job_requires_objectgs")
    for function in (module.objectify_with_retry, module.reobjectify):
        assert "shell" in str(get_type_hints(function)["geometry_method"])


def test_extraction_publishes_draft_with_source_ownership(
    draft_inputs: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.models.contracts.reconstruction import ReconstructionBundle
    from src.services.orchestration.scene import extraction

    result = draft_inputs.extract()
    fixture = Path(__file__).resolve().parents[2] / "fixtures/reconstruction_bundle/manifest.json"
    bundle = ReconstructionBundle.model_validate_json(fixture.read_text().replace("job-fixture-001", "job-draft"))
    scenes = []

    def publish_initial(job_id: str, scene: object) -> SimpleNamespace:
        scenes.append(scene)
        reference = module._reference(job_id, "{digest}.json", "SceneIR", module.StageId.SCENE_DECOMPOSE, b"scene")
        return SimpleNamespace(scene_reference=reference)

    registry = SimpleNamespace(scene=SimpleNamespace(publish_initial=publish_initial))
    monkeypatch.setattr(extraction, "_idempotent_publish", lambda *args: None)
    monkeypatch.setattr(extraction, "_sam2_runtime", lambda *args: SimpleNamespace(available=lambda: True))
    monkeypatch.setattr(extraction, "job_requires_strict_geometry", lambda *args: True)
    monkeypatch.setattr(extraction, "objectify_with_retry", lambda *args: result)
    extraction.extract_scene(
        registry, SimpleNamespace(job_id="job-draft"), bundle, SimpleNamespace(product_objectify=True), tmp_path
    )
    (scene,) = scenes
    assert scene.provenance["object_geometry"] == "awaiting_review"
    assert scene.environment == result.environment
    for item in scene.objects:
        assert item.collider is None
        assert item.source_collision.source_transform == item.transform
        assert item.source_collision.source_geometry_ref == result.environment.geometry_ref
