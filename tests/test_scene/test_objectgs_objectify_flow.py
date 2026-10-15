"""Exercise objectify wiring with fixture GPU outputs and real isolated CPU CoACD.

This is NOT ObjectGS GPU E2E evidence. It protects artifact flow and rejects legacy fallback.
"""

import hashlib
import json
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


@pytest.mark.parametrize("corrected", [False, True])
@pytest.mark.parametrize("collider_fail", [False, True])
@pytest.mark.parametrize("refinement", ["legacy", "multiview_v1"])
def test_objectgs_surface_reaches_real_coacd_and_publishes_separate_background(
    tmp_path, monkeypatch, collider_fail, refinement, corrected
):
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
        if name in {"lift", "correction-observations"}:
            labels = np.full(600, -1, dtype=np.int32)
            labels[500:] = 0
            np.savez(workspace / "labels.npz", labels=labels)
            raw = workspace / "mask.npy"
            np.save(raw, np.zeros((8, 8), dtype=np.int32))
            return {
                "views": 1,
                "masks_per_object": {"0": 1} if name == "correction-observations" else [1],
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
            from src.services.scene.surface_mesh import process_surface

            _, quality, repair = process_surface(trimesh.creation.box(extents=[1, 2, 3]), voxel_size_m=0.01)
            checksum = "sha256:" + hashlib.sha256(surface.read_bytes()).hexdigest()
            for report in (quality, repair):
                report.update(object_id=object_id, source_checksum=checksum, result_checksum=checksum)
            quality_path, repair_path = workspace / "quality.json", workspace / "repair.json"
            quality_path.write_text(json.dumps(quality))
            repair_path.write_text(json.dumps(repair))
            return dict(
                upstream_commit=module.OBJECTGS_COMMIT,
                gsplat_commit="b" * 40,
                config_checksum="sha256:" + "c" * 64,
                export_config={
                    "voxel_size_m": 0.01,
                    "depth_trunc_m": 10.0,
                    "num_cluster": 1,
                    "mesh_variant": "raw_fuse",
                },
                runtime={"fixture": True},
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
                        quality_passed=True,
                        raw_path=str(surface),
                        raw_checksum="sha256:" + hashlib.sha256(surface.read_bytes()).hexdigest(),
                        quality_report_path=str(quality_path),
                        quality_report_checksum="sha256:" + hashlib.sha256(quality_path.read_bytes()).hexdigest(),
                        repair_report_path=str(repair_path),
                        repair_report_checksum="sha256:" + hashlib.sha256(repair_path.read_bytes()).hexdigest(),
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

    def prepared(request, **kwargs):
        receipt = run(
            Path(__import__("sys").executable), None, request.model_dump(mode="json"), tmp_path / "attempt", "objectgs"
        )
        for object_id, item in receipt["objects"].items():
            item["producer_provenance"] = {
                key: receipt.get(key) for key in ("runtime", "export_config", "upstream_commit", "gsplat_commit")
            }
            item["producer_provenance"].update(
                training_config_checksum=receipt["config_checksum"],
                source_world_from_object=receipt["source_poses"][object_id],
            )
            item["evidence_refs"] = kwargs["surface_artifact_callback"](object_id, item)
        return receipt

    monkeypatch.setattr(module, "run_prepared_objectgs", prepared)

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
        canonical_geometry_ref=base.environment.geometry_ref,
        camera_pose_refs=[base.environment.geometry_ref.model_copy(update={"artifact_type": "CameraPoses"})],
        rgb_frame_refs=[],
    )
    arguments = (registry, job, bundle, settings, tmp_path / "attempt", publish)
    extra = {}
    if corrected:
        from src.models.contracts.coordinates import CoordinateSystem, Transform
        from src.models.contracts.object_membership import ObjectMembershipArtifact
        from src.services.scene.editing.membership import encode_gaussian_membership_labels

        labels = np.full(600, -1, dtype=np.int32)
        labels[500:] = 0
        label_payload = encode_gaussian_membership_labels(
            labels, gaussian_count=600, label_to_object_id={"0": "stable-object"}
        )
        labels_ref = ref.model_copy(
            update={
                "artifact_type": "ObjectMembershipLabels",
                "artifact_checksum": "sha256:" + hashlib.sha256(label_payload).hexdigest(),
            }
        )
        membership = ObjectMembershipArtifact(
            source_visual_ref=ref,
            source_geometry_ref=bundle.canonical_geometry_ref,
            labels_ref=labels_ref,
            extraction_revision="rev-source",
            coordinate_system=CoordinateSystem(),
            gaussian_count=600,
            label_to_object_id={"0": "stable-object"},
        )
        pose = Transform(
            parent_frame="world",
            local_frame="stable-object",
            translation_xyz=(3, 4, 5),
            rotation_quaternion_xyzw=(0, 0, 0, 1),
        )
        extra["correction"] = module.CorrectedMembership(membership, labels, {"stable-object": pose})
        monkeypatch.setattr(module, "_seeds", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must bypass SAM")))
    if collider_fail:
        with pytest.raises(module.ObjectifyError, match="fallback is forbidden"):
            module.objectify(
                *arguments, scene_config={"scene": {"geometry_method": "objectgs", "refinement": refinement}}, **extra
            )
        assert not any("colliders/" in uri for uri in published)
        return
    result = module.objectify(
        *arguments, scene_config={"scene": {"geometry_method": "objectgs", "refinement": refinement}}, **extra
    )
    assert set(seen) == {"correction-observations" if corrected else "lift", "objectgs", "convex", "inpaint"}
    if corrected:
        assert result.objects[0].id == "stable-object"
        assert result.objects[0].transform == pose
        assert result.environment.membership.extraction_revision == "rev-source"
        from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply

        local = read_gaussian_ply(published[result.objects[0].visual_ref.artifact_uri])
        np.testing.assert_allclose(
            positions(local) + np.asarray(pose.translation_xyz), positions(rows[500:]), atol=1e-6
        )
    assert result.provenance["segmentation_refinement"] == refinement
    assert result.environment.geometry_ref == base.environment.geometry_ref
    assert result.environment.collider_ref.artifact_type == "ObjectAwareEnvironmentCollision"
    assert result.environment.object_aware_collision_ref.artifact_type == "ObjectAwareEnvironmentManifest"
    assert result.objects[0].surface_mesh_ref.artifact_type == "ObjectSurfaceMesh"
    assert result.objects[0].collider.geometry_ref.artifact_type == "ObjectCollider"
    assert result.objects[0].collider.parameters["parts"] >= 1
    assert result.provenance["geometry_method"] == "objectgs"
    provenance = result.objects[0].surface_mesh_ref.source_provenance
    assert provenance["runtime"] == {"fixture": True}
    assert provenance["training_config_checksum"] == "sha256:" + "c" * 64
    assert provenance["source_world_from_object"]["local_frame"] == result.objects[0].id
    if corrected and refinement == "legacy":
        # Full correction orchestration with fixture GPU output and actual CPU
        # CoACD. Active SceneIR uses real published bytes and the shared compositor.
        from src.models.contracts.object_membership import ObjectMembershipReassignCommand
        from src.services.orchestration.artifacts import FilesystemArtifactStore
        from src.services.orchestration.scene import membership_regeneration as correction_module
        from src.services.scene.collision_ownership import bind_source_collision_ownership
        from src.services.scene.editing.commands import confirm_object, move_object
        from src.services.scene.effective_collision import compose_effective_collision
        from src.services.simulation.usd.builder import _collect_scene_refs

        store = FilesystemArtifactStore(registry.runtime_resolver)
        for uri, payload in published.items():
            # All fixture refs share the same job/stage envelope; checksum binds bytes.
            store.publish(
                ref.model_copy(
                    update={"artifact_uri": uri, "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest()}
                ),
                payload,
            )
        store.publish(ref, master.read_bytes())
        objects = bind_source_collision_ownership(result.objects, bundle.canonical_geometry_ref, "rev-source")
        draft = base.model_copy(update={"objects": objects, "environment": result.environment})
        current = registry.scene.publish_next(job.job_id, base.scene_revision, draft, "fixture-objectgs").revision.scene
        object_id = current.objects[0].id
        pose = current.objects[0].transform.model_copy(
            update={"translation_xyz": (20, 30, 40), "rotation_quaternion_xyzw": (0, 0, 0.6, 0.8)}
        )
        current = registry.scene.publish_next(
            job.job_id, current.scene_revision, move_object(current, object_id, pose), "move"
        ).revision.scene
        monkeypatch.setattr(correction_module, "job_bundle", lambda *a: bundle)
        command = ObjectMembershipReassignCommand(
            expected_scene_revision=current.scene_revision,
            membership_checksum=current.environment.membership.labels_ref.artifact_checksum,
            source_visual_checksum=ref.artifact_checksum,
            source_gaussian_indices=[500 + int(np.argmax(rows["z"][500:]))],
            source_object_id=object_id,
            target_object_id=None,
        )
        old_membership = current.environment.membership
        correction_module.regenerate_membership(
            registry,
            job.job_id,
            settings,
            tmp_path / "correction",
            command=command,
            actor_id="fixture",
            expected_revision=current.scene_revision,
        )
        regenerated = registry.scene.current(job.job_id).scene
        assert regenerated.scene_revision != current.scene_revision
        assert regenerated.provenance["object_pipeline_evidence"]["artifact_type"] == "ObjectPipelineEvidence"
        assert regenerated.objects[0].transform == pose
        assert regenerated.environment.membership.labels_ref != old_membership.labels_ref
        assert regenerated.environment.object_aware_collision_ref != current.environment.object_aware_collision_ref
        assert (
            len(read_gaussian_ply(registry.runtime_resolver.require(regenerated.objects[0].visual_ref).read_bytes()))
            == 99
        )
        confirmed = confirm_object(regenerated, object_id)

        def read(reference):
            return registry.runtime_resolver.require(reference).read_bytes()

        source = read(bundle.canonical_geometry_ref)
        background = compose_effective_collision(confirmed, bundle.canonical_geometry_ref, source, read)
        moved = move_object(confirmed, object_id, pose.model_copy(update={"translation_xyz": (25, 35, 45)}))
        after_move = compose_effective_collision(moved, bundle.canonical_geometry_ref, source, read)
        np.testing.assert_array_equal(after_move.vertices, background.vertices)
        np.testing.assert_array_equal(after_move.faces, background.faces)
        assert not after_move.source_remove_mask.any()  # authored environment is never carved twice
        assert moved.environment.object_aware_collision_ref == regenerated.environment.object_aware_collision_ref
        _, geometry_refs, collider_refs = _collect_scene_refs(moved)
        assert moved.objects[0].surface_mesh_ref in geometry_refs
        assert moved.objects[0].collider.geometry_ref in collider_refs
        assert moved.objects[0].source_collision == current.objects[0].source_collision
        from src.services.orchestration.scene.errors import SceneRevisionConflictError
        from src.services.orchestration.scene.physics_collision import effective_collision_for_revision

        committed = registry.scene.publish_next(
            job.job_id, regenerated.scene_revision, moved, "confirm-move"
        ).revision.scene
        _, walk_background = effective_collision_for_revision(
            registry, job.job_id, committed.scene_revision, preview_pending=True
        )
        np.testing.assert_allclose(walk_background.vertices, after_move.vertices)
        np.testing.assert_array_equal(walk_background.faces, after_move.faces)
        with pytest.raises(SceneRevisionConflictError):
            effective_collision_for_revision(registry, job.job_id, current.scene_revision)

        import subprocess

        env_path, collider_path = tmp_path / "corrected-env.glb", tmp_path / "corrected-object.glb"
        env_path.write_bytes(
            trimesh.Trimesh(walk_background.vertices, walk_background.faces, process=False).export(file_type="glb")
        )
        collider_path.write_bytes(read(committed.objects[0].collider.geometry_ref))
        request_path = tmp_path / "corrected-usd-request.json"
        request_path.write_text(
            json.dumps(
                {
                    "output_dir": str(tmp_path / "corrected-usd"),
                    "ground_plane": False,
                    "environment": {"collision_mesh": str(env_path)},
                    "objects": [
                        {
                            "prim": "Corrected",
                            "translation": committed.objects[0].transform.translation_xyz,
                            "rotation_xyzw": committed.objects[0].transform.rotation_quaternion_xyzw,
                            "collider": {
                                "type": "CONVEX_DECOMPOSITION",
                                "geometry_path": str(collider_path),
                                "local_transform": committed.objects[0].collider.local_transform.model_dump(
                                    mode="json"
                                ),
                                "part_paths": [],
                                "dimensions_xyz_m": None,
                            },
                        }
                    ],
                }
            )
        )
        subprocess.run(
            [
                str(RUNTIME),
                str(ROOT / "src/services/simulation/usd/hybrid_runner.py"),
                "--request",
                str(request_path),
                "--result",
                str(tmp_path / "corrected-usd-result.json"),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        inspect = """
import json,sys
import numpy as np
from pxr import Gf,Usd,UsdGeom,UsdPhysics
stage=Usd.Stage.Open(sys.argv[1])
cache=UsdGeom.XformCache()
world=[]
for prim in Usd.PrimRange(stage.GetPrimAtPath('/World/Objects/Corrected')):
    if prim.IsA(UsdGeom.Mesh) and prim.HasAPI(UsdPhysics.CollisionAPI):
        mesh=UsdGeom.Mesh(prim)
        matrix=cache.GetLocalToWorldTransform(prim)
        world.extend(matrix.Transform(Gf.Vec3d(*map(float,p))) for p in mesh.GetPointsAttr().Get())
points=np.array(world)
env=UsdGeom.Mesh(stage.GetPrimAtPath('/World/Environment/Collision'))
print(json.dumps(dict(up=str(UsdGeom.GetStageUpAxis(stage)),unit=UsdGeom.GetStageMetersPerUnit(stage),bounds=[points.min(0).tolist(),points.max(0).tolist()],env_faces=len(env.GetFaceVertexCountsAttr().Get()))))
"""
        inspection = subprocess.run(
            [str(RUNTIME), "-c", inspect, str(tmp_path / "corrected-usd/scene.usda")],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        measured = json.loads(inspection.stdout)
        assert measured["up"] == "Z" and measured["unit"] == 1
        assert measured["env_faces"] == len(walk_background.faces)
        np.testing.assert_allclose(measured["bounds"], [[23.9, 34.24, 43.5], [26.1, 35.76, 46.5]], atol=1e-5)
