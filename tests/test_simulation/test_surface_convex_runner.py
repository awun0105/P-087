"""Exercise the real isolated CoACD runtime, including disconnected-leg gap conservation."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import trimesh

ROOT = Path(__file__).parents[2]
RUNTIME = Path(os.environ.get("PR05_COLLIDER_PYTHON", ROOT / "data/scene_runtime/bin/python"))
pytestmark = pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated CoACD runtime is not installed")


def request(tmp_path):
    legs = []
    for x in [-1.0, 1.0]:
        mesh = trimesh.creation.box(extents=[0.3, 0.5, 2.0])
        mesh.apply_translation([x, 0.7, 1.0])
        legs.append(mesh)
    payload = trimesh.util.concatenate(legs).export(file_type="glb")
    source = tmp_path / "surface.glb"
    source.write_bytes(payload)
    return dict(
        id="table",
        surface_mesh=str(source),
        surface_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        coordinate_frame="object_local",
        distance_unit="m",
        output_glb=str(tmp_path / "collider.glb"),
    )


def run(tmp_path, item, config=None, fail=False):
    code = """
import importlib.util, json, sys
spec=importlib.util.spec_from_file_location("convex_runner", "src/services/simulation/colliders/convex_runner.py")
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
if sys.argv[3] == 'fail':
 def broken(*a, **kw): raise RuntimeError('injected CoACD failure')
 r.coacd.run_coacd=broken
result=r.build_one(json.loads(sys.argv[1]), json.loads(sys.argv[2]))
print('RESULT='+json.dumps(result))
"""
    output = subprocess.run(
        [str(RUNTIME), "-c", code, json.dumps(item), json.dumps(config or {}), "fail" if fail else "ok"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert output.returncode == 0, output.stderr
    return json.loads(
        next(line.removeprefix("RESULT=") for line in output.stdout.splitlines() if line.startswith("RESULT="))
    )


def test_real_coacd_preserves_two_legs_gap_frame_and_metric_dimensions(tmp_path):
    item = request(tmp_path)
    result = run(tmp_path, item)
    assert "error" not in result
    assert result["parts"] == 2
    scene = trimesh.load(item["output_glb"], force="scene", process=False)
    assert len(scene.geometry) == 2
    mesh = scene.to_geometry()
    np.testing.assert_allclose(mesh.bounds, [[-1.15, 0.45, 0], [1.15, 0.95, 2]], atol=1e-5)
    for hull in scene.geometry.values():
        # No convex part may cross x=0 and obstruct the space between the legs.
        assert hull.bounds[1, 0] < 0 or hull.bounds[0, 0] > 0
        assert hull.is_watertight
    assert result["volume_m3"] == pytest.approx(0.6, abs=1e-4)


@pytest.mark.parametrize("failure", ["coacd", "checksum", "frame", "budget", "open"])
def test_invalid_surface_never_publishes_a_fallback_or_stale_collider(tmp_path, failure):
    item = request(tmp_path)
    output = Path(item["output_glb"])
    output.write_bytes(b"stale collider")
    config = {}
    if failure == "checksum":
        item["surface_checksum"] = "sha256:" + "0" * 64
    if failure == "frame":
        item.pop("coordinate_frame")
    if failure == "budget":
        config["max_convex_hull"] = 1
    if failure == "open":
        source = trimesh.load(item["surface_mesh"], force="mesh", process=False)
        source.update_faces(np.arange(len(source.faces)) != 0)
        payload = source.export(file_type="glb")
        Path(item["surface_mesh"]).write_bytes(payload)
        item["surface_checksum"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    result = run(tmp_path, item, config, fail=failure == "coacd")
    assert result["error"]
    assert result["parts"] == 0
    assert not output.exists()


def test_real_coacd_preserves_void_under_connected_concave_table(tmp_path):
    from scipy.spatial import ConvexHull

    from src.services.scene.object_aware_geometry import build_background_collision

    cells = []
    for x in range(-10, 10):
        for y in range(-2, 3):
            for z in range(23):
                if x < -7 or x >= 7 or z >= 20:
                    cells.append([x, y, z])
    points = (np.asarray(cells) + 0.5) * 0.1
    surface = build_background_collision(points, np.zeros(len(points), dtype=np.int32), set(), voxel_m=0.1)
    mesh = trimesh.Trimesh(surface.vertices, surface.faces, process=False)
    assert mesh.is_watertight
    payload = mesh.export(file_type="glb")
    source = tmp_path / "concave.glb"
    source.write_bytes(payload)
    item = dict(
        id="connected-table",
        surface_mesh=str(source),
        surface_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        coordinate_frame="object_local",
        distance_unit="m",
        output_glb=str(tmp_path / "table.glb"),
    )
    result = run(tmp_path, item, dict(threshold=0.02, max_convex_hull=8))
    assert "error" not in result and result["parts"] >= 2
    scene = trimesh.load(item["output_glb"], force="scene", process=False)
    equations = [ConvexHull(hull.vertices).equations for hull in scene.geometry.values()]

    def collides(point):
        return any(np.all(eq[:, :3] @ point + eq[:, 3] <= 1e-6) for eq in equations)

    assert all(not collides(np.array([0, 0.05, z])) for z in [0.5, 1, 1.7])
    assert collides(np.array([-0.85, 0.05, 1])) and collides(np.array([0.85, 0.05, 1]))
    assert collides(np.array([0, 0.05, 2.15]))
