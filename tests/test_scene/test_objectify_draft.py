"""Draft extraction stops before expensive geometry providers."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.services.orchestration.scene import objectify as module


@pytest.fixture
def draft_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    def publish(ref, payload):
        published[ref.artifact_uri] = payload
        return ref

    def run(python, script, request, workspace, name, *args, **kwargs):
        assert name == "lift", f"Draft called {name}"
        assert "geometry_review" not in request["config"]
        np.savez(workspace / "labels.npz", labels=labels)
        return {"views": 1, "masks_per_object": {"2": 1, "5": 1}}

    monkeypatch.setattr(module, "_run", run)

    def forbidden(*args, **kwargs):
        pytest.fail("Draft called an expensive geometry provider")

    monkeypatch.setattr(module, "run_prepared_objectgs", forbidden)
    monkeypatch.setattr(module, "package_splat", forbidden)
    monkeypatch.setattr(module, "build_background_collision", forbidden)

    def extract(method="shell"):
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


def test_objectgs_draft_does_not_require_objectgs_runtime(draft_inputs, monkeypatch):
    class ReachedSegmentationError(Exception):
        pass

    def stop(*args, **kwargs):
        raise ReachedSegmentationError

    monkeypatch.setattr(module, "_seeds", stop)
    with pytest.raises(ReachedSegmentationError):
        draft_inputs.extract("objectgs")


def test_draft_objects_have_preview_shells_and_source_poses(draft_inputs):
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


def test_draft_shells_are_local_watertight_glbs(draft_inputs):
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


def test_shell_failure_keeps_object_as_display_placeholder(draft_inputs, monkeypatch):
    def broken(*args, **kwargs):
        raise module.GaussianShellError("fixture QA failure")

    monkeypatch.setattr(module, "build_gaussian_shell", broken, raising=False)
    result = draft_inputs.extract()
    assert len(result.objects) == 2
    for item in result.objects:
        assert item.collider is None
        assert item.provenance["shell_error"] == "fixture QA failure"
        assert item.provenance["shell_display"] == "bounding_box_placeholder"
        assert item.geometry_ref.artifact_type == "ObjectShellMesh"
