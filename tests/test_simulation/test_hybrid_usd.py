"""Bộ xuất USD lai (ADR 0007): chạy `hybrid_runner.py` trong runtime có usd-core, kiểm stage sinh ra.

Runtime nặng (usd-core, trimesh) không có trong `.venv` của app → test gọi runtime qua subprocess như
pipeline thật; không có runtime thì bỏ qua.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import trimesh

RUNNER = Path("src/services/simulation/usd/hybrid_runner.py")
RUNTIME = Path(os.environ.get("R2S_SCENE_RUNTIME_PYTHON", "data/scene_runtime/bin/python"))

pytestmark = pytest.mark.skipif(not RUNTIME.is_file(), reason="cần runtime usd-core (data/scene_runtime)")

INSPECT = """
import json, sys
import numpy as np
from pxr import Gf, Usd, UsdPhysics, UsdSemantics, UsdShade, UsdVol, UsdGeom
stage = Usd.Stage.Open(sys.argv[1])
visual = UsdVol.ParticleField3DGaussianSplat(stage.GetPrimAtPath("/World/Objects/obj_a/Visual"))
coefficients = visual.GetRadianceSphericalHarmonicsCoefficientsAttr()
obj = stage.GetPrimAtPath("/World/Objects/obj_a")
rack = stage.GetPrimAtPath("/World/Objects/rack")
rack_collider = stage.GetPrimAtPath("/World/Objects/rack/Collision")
rack_box = stage.GetPrimAtPath("/World/Objects/rack/Collision/box")
rack_material = UsdPhysics.MaterialAPI(stage.GetPrimAtPath("/World/Objects/rack/PhysicsMaterial"))
asset_body = stage.GetPrimAtPath("/World/Objects/asset_obj/Asset/Body")
plain = stage.GetPrimAtPath("/World/Objects/plain")
box_world = UsdGeom.XformCache().GetLocalToWorldTransform(rack_box)
scene_parts = [UsdGeom.Mesh(stage.GetPrimAtPath(f"/World/Objects/scene_parts/Collision/part_{i:03d}")) for i in range(2)]
print(json.dumps({
    "up": str(UsdGeom.GetStageUpAxis(stage)),
    "kg": UsdPhysics.GetStageKilogramsPerUnit(stage),
    "opacities": list(visual.GetOpacitiesAttr().Get()),
    "scales": [list(v) for v in visual.GetScalesAttr().Get()],
    "coefficients": [list(v) for v in coefficients.Get()],
    "element_size": coefficients.GetMetadata("elementSize"),
    "degree": visual.GetRadianceSphericalHarmonicsDegreeAttr().Get(),
    "rigid": obj.HasAPI(UsdPhysics.RigidBodyAPI),
    "mass": UsdPhysics.MassAPI(obj).GetMassAttr().Get(),
    "density": UsdPhysics.MassAPI(obj).GetDensityAttr().Get(),
    "physics_metadata": obj.GetCustomDataByKey("real2sim"),
    "labels": list(UsdSemantics.LabelsAPI(obj, "class").GetLabelsAttr().Get()),
    "static_rigid": rack.HasAPI(UsdPhysics.RigidBodyAPI),
    "static_mass": rack.HasAPI(UsdPhysics.MassAPI),
    "static_material": [rack_material.GetStaticFrictionAttr().Get(), rack_material.GetDynamicFrictionAttr().Get(), rack_material.GetRestitutionAttr().Get()],
    "collider_dims": list(rack_box.GetAttribute("xformOp:scale").Get()),
    "collider_translate": list(rack_collider.GetAttribute("xformOp:translate").Get()),
    "collider_orient": rack_collider.GetAttribute("xformOp:orient").Get().GetReal(),
    "collider_world_origin": list(box_world.Transform(Gf.Vec3d(0, 0, 0))),
    "collider_world_x": list(box_world.Transform(Gf.Vec3d(1, 0, 0))),
    "convex_part_centers": [np.mean(np.asarray(mesh.GetPointsAttr().Get()), axis=0).tolist() for mesh in scene_parts],
    "env_collision": UsdPhysics.MeshCollisionAPI(stage.GetPrimAtPath("/World/Environment/Collision")).GetApproximationAttr().Get(),
    "translate": list(obj.GetAttribute("xformOp:translate").Get()),
    "plain_has_rigid": plain.HasAPI(UsdPhysics.RigidBodyAPI),
    "plain_has_mass": plain.HasAPI(UsdPhysics.MassAPI),
    "plain_has_material": bool(UsdShade.MaterialBindingAPI(plain).GetDirectBinding("physics").GetMaterial()),
    "asset_body_valid": bool(asset_body and asset_body.IsValid()),
}))
"""


def _write_ply(path: Path) -> None:
    """Hai Gaussian SH bậc 1: f_rest xếp theo kênh (R0..2, G0..2, B0..2) như PLY Inria/Brush."""
    names = ["x", "y", "z", "rot_0", "rot_1", "rot_2", "rot_3", "scale_0", "scale_1", "scale_2", "opacity"]
    names += [f"f_dc_{i}" for i in range(3)] + [f"f_rest_{i}" for i in range(9)]
    rows = np.zeros((2, len(names)), dtype=np.float32)
    rows[:, 3] = 1.0  # quaternion đơn vị (w)
    rows[:, 7:10] = np.log(0.1)
    rows[0, 10] = 0.0  # sigmoid(0) = 0.5
    rows[1, 10] = 2.0
    rows[0, 11:14] = [1.0, 2.0, 3.0]
    rows[0, 14:23] = [10, 11, 12, 20, 21, 22, 30, 31, 32]  # R hệ số 1..3, rồi G, rồi B
    header = ["ply", "format binary_little_endian 1.0", "element vertex 2"]
    header += [f"property float {name}" for name in names] + ["end_header"]
    path.write_bytes(("\n".join(header) + "\n").encode() + rows.tobytes())


def test_hybrid_stage_has_gaussians_colliders_physics_and_labels(tmp_path: Path) -> None:
    _write_ply(tmp_path / "obj.ply")
    (tmp_path / "part.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n")
    (tmp_path / "part_2.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n")
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 5 0 0\nv 0 5 0\nf 1 2 3\n")
    parts_scene = trimesh.Scene()
    unit_cube = trimesh.creation.box(extents=(1, 1, 1))
    parts_scene.add_geometry(
        unit_cube.copy(),
        geom_name="left_mesh",
        node_name="left_part",
        transform=trimesh.transformations.translation_matrix([-2, 0, 0]),
    )
    parts_scene.add_geometry(
        unit_cube.copy(),
        geom_name="right_mesh",
        node_name="right_part",
        transform=trimesh.transformations.translation_matrix([2, 0, 0]),
    )
    parts_scene.export(tmp_path / "parts.glb")
    asset_bytes = b"""#usda 1.0
(
    defaultPrim = "Asset"
    metersPerUnit = 1
    upAxis = "Z"
)
def Xform "Asset"
{
    def Cube "Body"
    {
        double size = 1
    }
}
"""
    (tmp_path / "asset.usda").write_bytes(asset_bytes)
    asset_checksum = "sha256:" + hashlib.sha256(asset_bytes).hexdigest()
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "obj_a",
                "translation": [1.0, 2.0, 0.5],
                "rotation_xyzw": [0, 0, 0, 1],
                "gaussians_ply": str(tmp_path / "obj.ply"),
                "collider": {
                    "type": "CONVEX_DECOMPOSITION",
                    "geometry_path": None,
                    "part_paths": [str(tmp_path / "part.obj"), str(tmp_path / "part_2.obj")],
                    "dimensions_xyz_m": None,
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "semantic_class": "pallet",
                "physics": {
                    "dynamic": True,
                    "mass_kg": 25.0,
                    "mass_source": "user",
                    "density_kg_m3": 400.0,
                    "static_friction": 0.6,
                    "dynamic_friction": 0.5,
                    "restitution": 0.1,
                    "provenance": {"entry": "test"},
                },
            },
            {
                "prim": "rack",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "OBB",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [1.25, 0.75, 2.0],
                    "local_transform": {
                        "translation_xyz": [0.25, -0.5, 0.3],
                        "rotation_quaternion_xyzw": [0, 0, 0.7071067811865476, 0.7071067811865476],
                    },
                },
                "physics": {
                    "dynamic": False,
                    "mass_kg": None,
                    "mass_source": None,
                    "density_kg_m3": None,
                    "static_friction": 0.8,
                    "dynamic_friction": 0.35,
                    "restitution": 0.2,
                    "provenance": {"entry": "static-test"},
                },
            },
            {
                "prim": "plain",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "AABB",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [0.5, 0.75, 1.0],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "physics": None,
            },
            {
                "prim": "scene_parts",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "CONVEX_DECOMPOSITION",
                    "geometry_path": str(tmp_path / "parts.glb"),
                    "part_paths": [],
                    "dimensions_xyz_m": None,
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "physics": None,
            },
            {
                "prim": "asset_obj",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "AABB",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [1, 1, 1],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "asset_source_path": str(tmp_path / "asset.usda"),
                "asset_package_path": "assets/" + asset_checksum.removeprefix("sha256:") + ".usda",
                "asset_checksum": asset_checksum,
                "physics": None,
            },
        ],
    }
    (tmp_path / "request.json").write_text(json.dumps(request))
    subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(tmp_path / "request.json"), "--result", str(tmp_path / "r.json")],
        check=True,
        timeout=120,
    )
    summary = json.loads((tmp_path / "r.json").read_text())
    assert summary["objects"][0]["prim"] == "obj_a"
    assert summary["objects"][0]["collider_type"] == "CONVEX_DECOMPOSITION"
    assert summary["objects"][0]["collision_parts"] == 2
    assert summary["objects"][1]["collider_dimensions_xyz_m"] == [1.25, 0.75, 2.0]
    assert summary["objects"][3]["collision_parts"] == 2
    assert summary["external_assets"] == [
        {
            "prim": "asset_obj",
            "path": "assets/" + asset_checksum.removeprefix("sha256:") + ".usda",
            "checksum": asset_checksum,
        }
    ]
    packaged_asset = tmp_path / "usd" / "assets" / (asset_checksum.removeprefix("sha256:") + ".usda")
    assert packaged_asset.read_bytes() == asset_bytes
    object_layer = (tmp_path / "usd" / "objects" / "asset_obj.usdc").read_bytes()
    assert b"../assets/" in object_layer

    inspected = subprocess.run(
        [str(RUNTIME), "-c", INSPECT, str(tmp_path / "usd" / "scene.usda")],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stage = json.loads(inspected.stdout)
    assert stage["up"] == "Z" and stage["kg"] == 1.0
    assert stage["opacities"] == pytest.approx([0.5, 1 / (1 + np.exp(-2.0))], rel=1e-5)
    assert stage["scales"][0] == pytest.approx([0.1, 0.1, 0.1], rel=1e-5)
    # SH: [Gaussian][hệ số][RGB] — hệ số 1 của Gaussian 0 = (R0, G0, B0) = (10, 20, 30)
    assert stage["element_size"] == 4 and stage["degree"] == 1
    assert stage["coefficients"][0] == [1.0, 2.0, 3.0]
    assert stage["coefficients"][1] == [10.0, 20.0, 30.0]
    assert stage["coefficients"][3] == [12.0, 22.0, 32.0]
    assert stage["rigid"] and stage["mass"] == 25.0 and stage["labels"] == ["pallet"]
    assert stage["density"] == 400.0
    assert stage["physics_metadata"]["physics"]["mass_source"] == "user"
    assert stage["physics_metadata"]["physics"]["provenance"] == {"entry": "test"}
    assert not stage["static_rigid"] and not stage["static_mass"]
    assert stage["static_material"] == pytest.approx([0.8, 0.35, 0.2])
    assert stage["collider_dims"] == pytest.approx([1.25, 0.75, 2.0])
    assert stage["collider_translate"] == pytest.approx([0.25, -0.5, 0.3])
    assert stage["collider_orient"] == pytest.approx(0.70710678)
    assert stage["collider_world_origin"] == pytest.approx([0.25, -0.5, 0.3])
    assert stage["collider_world_x"] == pytest.approx([0.25, 0.75, 0.3])
    assert np.asarray(stage["convex_part_centers"]) == pytest.approx(np.asarray([[-2, 0, 0], [2, 0, 0]]))
    assert stage["env_collision"] == "none"
    assert stage["translate"] == [1.0, 2.0, 0.5]
    assert not stage["plain_has_rigid"] and not stage["plain_has_mass"] and not stage["plain_has_material"]
    assert stage["asset_body_valid"]


def test_convex_collider_does_not_fall_back_to_box(tmp_path: Path) -> None:
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "obj_a",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "CONVEX_DECOMPOSITION",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [1, 1, 1],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "physics": None,
            }
        ],
    }
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(request_path), "--result", str(tmp_path / "r.json")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "r.json").exists()


def test_convex_collider_rejects_degenerate_mesh_topology(tmp_path: Path) -> None:
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    (tmp_path / "bad.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 1 3\n", encoding="utf-8")
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "obj_a",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "CONVEX_DECOMPOSITION",
                    "geometry_path": str(tmp_path / "bad.obj"),
                    "part_paths": [],
                    "dimensions_xyz_m": None,
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "physics": None,
            }
        ],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(request_path), "--result", str(tmp_path / "r.json")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "r.json").exists()


def test_asset_relative_path_escape_is_rejected(tmp_path: Path) -> None:
    asset = tmp_path / "asset.usda"
    asset.write_text('#usda 1.0\ndef Xform "Asset" {}\n', encoding="utf-8")
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "obj_a",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "AABB",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [1, 1, 1],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "asset_source_path": str(asset),
                "asset_package_path": "assets/../escape.usda",
                "asset_checksum": "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest(),
                "physics": None,
            }
        ],
    }
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(request_path), "--result", str(tmp_path / "r.json")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "r.json").exists()


def test_asset_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    asset = tmp_path / "asset.usda"
    asset.write_text('#usda 1.0\ndef Xform "Asset" {}\n', encoding="utf-8")
    payload_checksum = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "obj_a",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "AABB",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [1, 1, 1],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "asset_source_path": str(asset),
                "asset_package_path": "assets/" + payload_checksum.removeprefix("sha256:") + ".usda",
                "asset_checksum": "sha256:" + "0" * 64,
                "physics": None,
            }
        ],
    }
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(request_path), "--result", str(tmp_path / "r.json")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "r.json").exists()


GROUND_INSPECT = """
import json, sys
from pxr import Usd, UsdGeom
stage = Usd.Stage.Open(sys.argv[1])
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.guide])
box = cache.ComputeWorldBound(stage.GetPrimAtPath("/World/GroundPlane")).ComputeAlignedRange()
print(json.dumps({"min": list(box.GetMin()), "max": list(box.GetMax())}))
"""


def test_ground_plane_top_surface_is_at_z_zero(tmp_path: Path) -> None:
    """Translate must precede scale in xformOpOrder, otherwise the 2 cm slab is offset by 0.0098 m."""
    request = {"output_dir": str(tmp_path / "usd"), "ground_plane": True, "environment": {}, "objects": []}
    (tmp_path / "request.json").write_text(json.dumps(request))
    subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(tmp_path / "request.json"), "--result", str(tmp_path / "r.json")],
        check=True,
        timeout=120,
    )

    inspected = subprocess.run(
        [str(RUNTIME), "-c", GROUND_INSPECT, str(tmp_path / "usd" / "scene.usda")],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    box = json.loads(inspected.stdout)
    assert box["max"][2] == pytest.approx(0.0, abs=1e-6)
    assert box["min"][2] == pytest.approx(-0.02, abs=1e-6)
    assert box["max"][0] - box["min"][0] == pytest.approx(200.0)


CATALOG_INSPECT = """
import json, sys
from pxr import Usd
stage = Usd.Stage.Open(sys.argv[1])
prim = stage.GetPrimAtPath("/World/Objects/asset_001")
print(json.dumps({"real2sim": prim.GetCustomDataByKey("real2sim"), "layers": [layer.identifier for layer in stage.GetUsedLayers()]}))
"""


def _catalog_request(tmp_path: Path, catalog: object) -> Path:
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "asset_001",
                "translation": [0, 0, 0.1],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "AABB",
                    "geometry_path": None,
                    "part_paths": [],
                    "dimensions_xyz_m": [1.2, 1.0, 0.2],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "physics": {
                    "dynamic": True,
                    "mass_kg": 25.0,
                    "mass_source": "catalog_default",
                    "static_friction": 0.6,
                    "dynamic_friction": 0.5,
                    "restitution": 0.1,
                    "provenance": {},
                },
                "catalog": catalog,
            }
        ],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def test_catalog_provenance_is_recorded_next_to_physics_without_referencing_the_asset(tmp_path: Path) -> None:
    """The public asset URL travels as metadata only: a composition arc would make the package non-hermetic."""
    catalog = {"family": "SM_PaletteA", "asset_url": "https://example.test/Assets/Isaac/SM_PaletteA_01.usd"}
    request_path = _catalog_request(tmp_path, catalog)
    subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(request_path), "--result", str(tmp_path / "r.json")],
        check=True,
        timeout=120,
    )

    summary = json.loads((tmp_path / "r.json").read_text())
    assert summary["objects"][0]["catalog"] == catalog
    assert summary["external_assets"] == []
    inspected = subprocess.run(
        [str(RUNTIME), "-c", CATALOG_INSPECT, str(tmp_path / "usd" / "scene.usda")],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stage = json.loads(inspected.stdout)
    assert stage["real2sim"]["catalog"] == catalog
    assert stage["real2sim"]["physics"]["mass_source"] == "catalog_default"
    assert all("example.test" not in layer for layer in stage["layers"])


@pytest.mark.parametrize(
    "catalog",
    [{"family": "SM_PaletteA"}, {"family": "SM_PaletteA", "asset_url": ""}, {"family": 3, "asset_url": "x"}, "text"],
)
def test_malformed_catalog_provenance_is_rejected(tmp_path: Path, catalog: object) -> None:
    request_path = _catalog_request(tmp_path, catalog)
    completed = subprocess.run(
        [str(RUNTIME), str(RUNNER), "--request", str(request_path), "--result", str(tmp_path / "r.json")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode != 0 and not (tmp_path / "r.json").exists()
