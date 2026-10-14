"""Actual OpenUSD authoring checks using a separated environment and object collider."""

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.services.orchestration.scene.editor import SceneEditor
from src.services.scene.editing.commands import confirm_object, move_object
from src.services.simulation.usd.builder import _collect_scene_refs
from tests.test_scene.test_object_aware_composition import case

RUNTIME = Path(os.environ.get("R2S_SCENE_RUNTIME_PYTHON", "data/scene_runtime/bin/python"))


def test_surface_ref_is_kept_in_candidate_geometry_inventory(tmp_path):
    scene, _, _ = case(tmp_path)
    scene = confirm_object(scene, "A")
    item = scene.objects[0]
    surface = item.geometry_ref.model_copy(update={"artifact_type": "ObjectSurfaceMesh"})
    item = item.model_copy(update={"surface_mesh_ref": surface})
    scene = scene.model_copy(update={"objects": [item, scene.objects[1]]})
    _, geometry, colliders = _collect_scene_refs(scene)
    assert surface in geometry and surface not in colliders
    assert item.collider.geometry_ref in colliders
    allowed = SceneEditor.artifact_references(scene)
    assert surface in allowed and scene.environment.object_aware_collision_ref in allowed


@pytest.mark.skipif(not RUNTIME.is_file(), reason="requires isolated usd-core runtime")
def test_authored_background_and_moved_collider_have_independent_stage_transforms(tmp_path):
    scene, compose, blobs = case(tmp_path)
    scene = confirm_object(confirm_object(scene, "A"), "B")
    root = scene.objects[0].transform.model_copy(
        update={
            "translation_xyz": (10, 4, 2),
            "rotation_quaternion_xyzw": (0, 0, np.sqrt(0.5), np.sqrt(0.5)),
        }
    )
    scene = move_object(scene, "A", root)
    background = compose(scene)
    assert len(background.faces) == 24
    env_path = tmp_path / "background.glb"
    env_path.write_bytes(trimesh.Trimesh(background.vertices, background.faces, process=False).export(file_type="glb"))
    items = []
    for item in scene.objects:
        collider_path = tmp_path / (item.id + ".glb")
        collider_path.write_bytes(blobs[item.collider.geometry_ref.artifact_uri])
        local = item.collider.local_transform.model_dump(mode="json")
        if item.id == "A":
            local.update(translation_xyz=[-2, 1, 0.5], rotation_quaternion_xyzw=[0, 0, np.sqrt(0.5), np.sqrt(0.5)])
        items.append(
            dict(
                prim=item.id,
                translation=item.transform.translation_xyz,
                rotation_xyzw=item.transform.rotation_quaternion_xyzw,
                collider=dict(
                    type="CONVEX_DECOMPOSITION",
                    geometry_path=str(collider_path),
                    local_transform=local,
                    part_paths=[],
                    dimensions_xyz_m=None,
                ),
            )
        )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            dict(
                output_dir=str(tmp_path / "usd"),
                ground_plane=False,
                environment=dict(collision_mesh=str(env_path)),
                objects=items,
            )
        )
    )
    subprocess.run(
        [
            str(RUNTIME),
            "src/services/simulation/usd/hybrid_runner.py",
            "--request",
            str(request),
            "--result",
            str(tmp_path / "result.json"),
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
mesh=UsdGeom.Mesh(stage.GetPrimAtPath('/World/Objects/A/Collision/part_000'))
matrix=cache.GetLocalToWorldTransform(mesh.GetPrim())
points=np.array([matrix.Transform(Gf.Vec3d(*map(float,p))) for p in mesh.GetPointsAttr().Get()])
env=UsdGeom.Mesh(stage.GetPrimAtPath('/World/Environment/Collision'))
print(json.dumps(dict(up=str(UsdGeom.GetStageUpAxis(stage)),unit=UsdGeom.GetStageMetersPerUnit(stage),
    env_faces=len(env.GetFaceVertexCountsAttr().Get()),bounds=[points.min(0).tolist(),points.max(0).tolist()],
    env_approx=UsdPhysics.MeshCollisionAPI(env).GetApproximationAttr().Get(),
    ground=bool(stage.GetPrimAtPath('/World/GroundPlane')),
    object_colliders=sum(p.HasAPI(UsdPhysics.CollisionAPI) for p in Usd.PrimRange(stage.GetPrimAtPath('/World/Objects'))))))
"""
    result = subprocess.run(
        [str(RUNTIME), "-c", inspect, str(tmp_path / "usd/scene.usda")],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    inspected = json.loads(result.stdout)
    assert inspected["up"] == "Z" and inspected["unit"] == 1
    assert inspected["env_faces"] == 24 and inspected["env_approx"] == "none"
    assert not inspected["ground"] and inspected["object_colliders"] == 2
    # Child rotation 90deg + parent rotation 90deg; offset rotated by the parent once.
    np.testing.assert_allclose(inspected["bounds"], [[8.5, 1, 1], [9.5, 3, 4]], atol=1e-5)
