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
    rows = np.zeros(len(points), dtype=[(name, "<f4") for name in ("x", "y", "z", "opacity")])
    for axis, name in enumerate(("x", "y", "z")):
        rows[name] = points[:, axis]
    rows["opacity"] = 5
    labels = np.repeat([2, 5, -1], [len(grid), len(grid), 1]).astype(np.int32)
    master = tmp_path / "master.ply"
    master.write_bytes(module.gaussian_split.write_gaussian_ply(rows))
    reference = lambda kind: module._reference(
        "job-draft", kind + "/{digest}", kind, module.StageId.SCENE_DECOMPOSE, kind.encode()
    )
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
    class ReachedSegmentation(Exception):
        pass

    def stop(*args, **kwargs):
        raise ReachedSegmentation

    monkeypatch.setattr(module, "_seeds", stop)
    with pytest.raises(ReachedSegmentation):
        draft_inputs.extract("objectgs")
