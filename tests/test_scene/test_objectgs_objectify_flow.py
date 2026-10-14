"""Exercise objectify wiring with fixture GPU outputs and real isolated CPU CoACD.

This is NOT ObjectGS GPU E2E evidence. It protects artifact flow and rejects legacy fallback.
"""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from PIL import Image

from src.config import Settings
from src.services.orchestration.scene import objectify as module
from src.services.scene.decomposition.gaussian_split import write_gaussian_ply
from tests.test_orchestration.test_floor_evidence import _floor_model
from tests.test_orchestration.test_simulation_package import _scene_job

ROOT = Path(__file__).parents[2]
RUNTIME = ROOT / "data/scene_runtime/bin/python"
pytestmark = pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated CoACD runtime is not installed")


@pytest.mark.parametrize("collider_fail", [False, True])
def test_objectgs_surface_reaches_real_coacd_and_publishes_separate_background(tmp_path, monkeypatch, collider_fail):
    registry, job = _scene_job(tmp_path / "registry")
    base = registry.scene.current(job.job_id).scene
    dtype = [
        (name, "<f4")
        for name in [
            "x",
            "y",
            "z",
            "opacity",
            "scale_0",
            "scale_1",
            "scale_2",
            "rot_0",
            "rot_1",
            "rot_2",
            "rot_3",
            "f_dc_0",
            "f_dc_1",
            "f_dc_2",
        ]
    ]
    rows = np.zeros(600, dtype=dtype)
    rng = np.random.default_rng(9)
    rows["x"] = rng.uniform(-1, 1, 600)
    rows["y"] = rng.uniform(-1, 1, 600)
    rows["z"][500:] = rng.uniform(0.2, 1.5, 100)
    rows["rot_0"] = 1
    rows["scale_0"] = rows["scale_1"] = rows["scale_2"] = -4
    master = tmp_path / "master.ply"
    master.write_bytes(write_gaussian_ply(rows))
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (20, 40, 60)).save(frame)
    ref = base.environment.geometry_ref.model_copy(
        update={
            "artifact_type": "GaussianPLY",
            "artifact_uri": f"artifact://jobs/{job.job_id}/test/source.ply",
            "artifact_checksum": "sha256:" + hashlib.sha256(master.read_bytes()).hexdigest(),
        }
    )
    old_require = registry.runtime_resolver.require
    monkeypatch.setattr(
        registry.runtime_resolver,
        "require",
        lambda r: master if r == ref else frame if r == "image" else old_require(r),
    )
    monkeypatch.setattr(module, "metric_visual_master", lambda *a: ref)
    monkeypatch.setattr(module.Sam2Runtime, "available", lambda *a: True)
    camera = SimpleNamespace(center=(0, 0, 3), image="image", model_dump=lambda **kw: {"center": [0, 0, 3]})
    monkeypatch.setattr(module, "camera_views", lambda *a: [camera])
    monkeypatch.setattr(module, "_seeds", lambda *a, **kw: [np.arange(500, 600)])
    monkeypatch.setattr(
        module,
        "fit_canonical_floor_model",
        lambda points, checksum: _floor_model().model_copy(update={"source_checksum": checksum}),
    )
    monkeypatch.setattr(module, "publish_floor_fit_evidence", lambda *a: (None, None))
    monkeypatch.setattr(module, "scene_floor_fit_summary", lambda *a: {})
    published = {}

    def publish(reference, payload):
        published[reference.artifact_uri] = payload
        return reference

    original_run = module._run
    seen = []

    def run(python, script, request, workspace, name, *args, **kwargs):
        seen.append(name)
        if name == "lift":
            labels = np.full(600, -1, dtype=np.int32)
            labels[500:] = 0
            np.savez(workspace / "labels.npz", labels=labels)
            raw = workspace / "mask.npy"
            np.save(raw, np.zeros((8, 8), dtype=np.int32))
            return {
                "views": 1,
                "masks_per_object": [1],
                "objectgs_views": [
                    dict(
                        image_path=str(frame),
                        mask_path=str(raw),
                        width=8,
                        height=8,
                        parameters=[100, 100, 4, 4],
                        center=[0, 0, 3],
                        rotation_xyzw=[0, 0, 0, 1],
                        camera_model="PINHOLE",
                        coordinate_frame="world",
                        distance_unit="m",
                    )
                ],
            }
        if name == "objectgs":
            assert Path(request["runtime"]["python"]) != Path(python)
            surface = workspace / "fixture-surface.glb"
            surface.write_bytes(trimesh.creation.box(extents=[1, 2, 3]).export(file_type="glb"))
            checkpoint = workspace / "fixture-checkpoint.tar.gz"
            checkpoint.write_bytes(b"explicit fixture, not a real ObjectGS checkpoint")
            object_id = next(iter(request["source_poses"]))
            return dict(
                coordinate_frame="object_local",
                distance_unit="m",
                source_membership=request["membership"],
                source_poses=request["source_poses"],
                checkpoint_path=str(checkpoint),
                checkpoint_checksum="sha256:" + hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                dataset_path=str(checkpoint),
                dataset_checksum="sha256:" + hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                objects={
                    object_id: dict(
                        path=str(surface),
                        checksum="sha256:" + hashlib.sha256(surface.read_bytes()).hexdigest(),
                        label=1,
                        vertex_count=8,
                        triangle_count=12,
                        watertight=True,
                    )
                },
            )
        if name == "convex":
            assert all("surface_mesh" in item and "gaussians_ply" not in item for item in request["objects"])
            if collider_fail:
                return {"objects": [{"id": "0", "parts": 0, "error": "fixture failure"}]}
            return original_run(python, script, request, workspace, name, *args, **kwargs)
        if name == "inpaint":
            Path(request["output_ply"]).write_bytes(Path(request["background_ply"]).read_bytes())
            return dict(method="fixture-no-inpaint", original_gaussians=500, inpainted_gaussians=0)
        raise AssertionError(name)

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(
        module,
        "run_prepared_objectgs",
        lambda request, **kwargs: run(
            Path(__import__("sys").executable), None, request.model_dump(mode="json"), tmp_path / "attempt", "objectgs"
        ),
    )

    def package(*a, **kw):
        path = tmp_path / "background.sog"
        path.write_bytes(b"fixture sog")
        return path

    monkeypatch.setattr(module, "package_splat", package)
    settings = Settings(
        product_scene_runtime_python=RUNTIME,
        product_sam2_checkpoint=master,
        product_objectgs_runtime_python=tmp_path / "isolated/python",
        product_objectgs_repository=tmp_path / "objectgs",
        product_objectgs_gsplat_repository=tmp_path / "custom-gsplat",
    )
    bundle = SimpleNamespace(
        canonical_geometry_ref=base.environment.geometry_ref, camera_pose_refs=[None], rgb_frame_refs=[]
    )
    arguments = (registry, job, bundle, settings, tmp_path / "attempt", publish)
    if collider_fail:
        with pytest.raises(module.ObjectifyError, match="fallback is forbidden"):
            module.objectify(*arguments, scene_config={"scene": {"geometry_method": "objectgs"}})
        assert not any("colliders/" in uri for uri in published)
        return
    result = module.objectify(*arguments, scene_config={"scene": {"geometry_method": "objectgs"}})
    assert set(seen) == {"lift", "objectgs", "convex", "inpaint"}
    assert result.environment.geometry_ref == base.environment.geometry_ref
    assert result.environment.collider_ref.artifact_type == "ObjectAwareEnvironmentCollision"
    assert result.environment.object_aware_collision_ref.artifact_type == "ObjectAwareEnvironmentManifest"
    assert result.objects[0].surface_mesh_ref.artifact_type == "ObjectSurfaceMesh"
    assert result.objects[0].collider.geometry_ref.artifact_type == "ObjectCollider"
    assert result.objects[0].collider.parameters["parts"] >= 1
    assert result.provenance["geometry_method"] == "objectgs"
