"""Bộ xuất USD lai (ADR 0007): chạy `hybrid_runner.py` trong runtime có usd-core, kiểm stage sinh ra.

Runtime nặng (usd-core, trimesh) không có trong `.venv` của app → test gọi runtime qua subprocess như
pipeline thật; không có runtime thì bỏ qua.
"""

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

RUNNER = Path("src/services/simulation/usd/hybrid_runner.py")
RUNTIME = Path(os.environ.get("R2S_SCENE_RUNTIME_PYTHON", "data/scene_runtime/bin/python"))

pytestmark = pytest.mark.skipif(not RUNTIME.is_file(), reason="cần runtime usd-core (data/scene_runtime)")

INSPECT = """
import json, sys
from pxr import Usd, UsdPhysics, UsdSemantics, UsdVol, UsdGeom
stage = Usd.Stage.Open(sys.argv[1])
visual = UsdVol.ParticleField3DGaussianSplat(stage.GetPrimAtPath("/World/Objects/obj_a/Visual"))
coefficients = visual.GetRadianceSphericalHarmonicsCoefficientsAttr()
obj = stage.GetPrimAtPath("/World/Objects/obj_a")
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
    "labels": list(UsdSemantics.LabelsAPI(obj, "class").GetLabelsAttr().Get()),
    "static_rigid": stage.GetPrimAtPath("/World/Objects/rack").HasAPI(UsdPhysics.RigidBodyAPI),
    "env_collision": UsdPhysics.MeshCollisionAPI(stage.GetPrimAtPath("/World/Environment/Collision")).GetApproximationAttr().Get(),
    "translate": list(obj.GetAttribute("xformOp:translate").Get()),
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
    (tmp_path / "env.obj").write_text("v 0 0 0\nv 5 0 0\nv 0 5 0\nf 1 2 3\n")
    request = {
        "output_dir": str(tmp_path / "usd"),
        "environment": {"collision_mesh": str(tmp_path / "env.obj")},
        "objects": [
            {
                "prim": "obj_a",
                "translation": [1.0, 2.0, 0.5],
                "rotation_xyzw": [0, 0, 0, 1],
                "gaussians_ply": str(tmp_path / "obj.ply"),
                "collision_parts": [str(tmp_path / "part.obj")],
                "semantic_class": "pallet",
                "physics": {
                    "dynamic": True,
                    "mass_kg": 25.0,
                    "static_friction": 0.6,
                    "dynamic_friction": 0.5,
                    "restitution": 0.1,
                },
            },
            {
                "prim": "rack",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "box_dims": [1.0, 0.5, 2.0],
                "physics": {"dynamic": False, "static_friction": 0.6, "dynamic_friction": 0.5, "restitution": 0.1},
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
    assert summary["objects"][0] == {"prim": "obj_a", "gaussians": 2, "collision_parts": 1}

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
    assert not stage["static_rigid"]  # vật tĩnh: chỉ collider, không RigidBody
    assert stage["env_collision"] == "none"
    assert stage["translate"] == [1.0, 2.0, 0.5]
