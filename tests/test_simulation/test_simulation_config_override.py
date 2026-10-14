"""Validate package controls and inspect USD authored by the independent runtime."""

import io
import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pytest

from src.models.contracts.scene import SceneIR
from src.services.orchestration.review import simulation_package
from src.services.orchestration.scene.objects import apply_object_action
from src.services.scene.publisher import with_scene_checksum
from src.services.simulation.colliders.carve import CarveBox, triangle_mask_in_box
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.builder import CandidateBuildRequest, build_candidate_package
from src.services.simulation.usd.physics_config import physics_build_config
from src.services.simulation.usd.usda import generate_scene_usda
from tests.test_orchestration.test_simulation_package import _scene_job


@pytest.mark.parametrize(
    "values",
    [
        {"ground_plane": "false"},
        {"static_friction": -1},
        {"dynamic_friction": float("nan")},
        {"restitution": 1.1},
        {"carve_margin_m": float("inf")},
        {"carve_margin_m": -0.1},
    ],
)
def test_invalid_build_controls_rejected(values: dict[str, object]) -> None:
    scene = SceneIR.model_validate_json(Path("fixtures/scene_ir/scene.json").read_bytes())
    with pytest.raises(ValueError):
        CandidateBuildRequest(
            scene=scene,
            preflight_report=run_preflight(scene),
            job_manifest_checksum="sha256:" + "1" * 64,
            build_config=values,
        )


def test_default_controls_and_metadata() -> None:
    assert physics_build_config({"builder": "test"}) == dict(
        ground_plane=True, static_friction=0.5, dynamic_friction=0.4, restitution=0.0, carve_margin_m=0.05
    )


def test_custom_margin_changes_selected_triangles() -> None:
    box = CarveBox((0, 0, 0), (0, 0, 0, 1), (1, 1, 1))
    centroids = np.array([[0.6, 0, 0], [0.8, 0, 0]])
    assert triangle_mask_in_box(centroids, box, 0.05).tolist() == [False, False]
    assert triangle_mask_in_box(centroids, box, 0.2).tolist() == [True, False]
    with pytest.raises(ValueError):
        triangle_mask_in_box(centroids, box, float("nan"))


def test_legacy_usda_uses_package_controls(tmp_path: Path) -> None:
    scene = SceneIR.model_validate_json(Path("fixtures/scene_ir/scene.json").read_bytes())
    scene = scene.model_copy(update={"objects": []})
    text = generate_scene_usda(
        scene, build_config=dict(ground_plane=False, static_friction=0.8, dynamic_friction=0.7, restitution=0.2)
    )
    assert '"GroundPlane"' not in text
    assert "physics:staticFriction = 0.8" in text
    assert "physics:dynamicFriction = 0.7" in text
    assert "physics:restitution = 0.2" in text
    runtime = Path("data/scene_runtime/bin/python")
    if runtime.is_file():
        path = tmp_path / "legacy.usda"
        path.write_text(text)
        subprocess.run(
            [
                str(runtime.absolute()),
                "-c",
                "from pxr import Usd; import sys; assert Usd.Stage.Open(sys.argv[1])",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def test_candidate_build_config_changes_exported_usd(tmp_path: Path) -> None:
    scene = SceneIR.model_validate_json(Path("fixtures/scene_ir/scene.json").read_bytes())
    scene = with_scene_checksum(scene.model_copy(update={"objects": []}))
    request = CandidateBuildRequest(
        scene=scene,
        preflight_report=run_preflight(scene),
        job_manifest_checksum="sha256:" + "1" * 64,
        build_config=dict(ground_plane=False, static_friction=0.8, dynamic_friction=0.7, restitution=0.2),
        output_dir=tmp_path,
    )
    package = build_candidate_package(request)
    text = (tmp_path / "scene.usda").read_text()
    assert '"GroundPlane"' not in text
    assert "physics:staticFriction = 0.8" in text
    assert package.candidate_manifest.build_config_checksum


def test_package_controls_bind_export_carve_and_cache(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    item = scene.objects[0]
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", scene.scene_revision)
    controls = dict(ground_plane=False, static_friction=0.8, dynamic_friction=0.7, restitution=0.2, carve_margin_m=0.2)
    package = simulation_package.build_simulation_package(registry, job.job_id, simulation_config=controls)
    assert package.package_ref is not None
    with zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(package.package_ref).read_bytes())) as archive:
        text = archive.read("scene.usda").decode()
    assert '"GroundPlane"' not in text
    assert "physics:staticFriction = 0.8" in text
    assert simulation_package.current_package(registry, job.job_id, simulation_config=controls) == package
    assert simulation_package.current_package(registry, job.job_id, simulation_config={}) is None
    current_scene = registry.scene.current(job.job_id).scene
    custom = simulation_package._carved_environment(registry, current_scene, margin_m=0.2)
    baseline = simulation_package._carved_environment(registry, current_scene)
    assert current_scene.provenance["collision_background_identity"] == custom.identity
    assert custom.identity != baseline.identity


def test_hybrid_global_material_preserves_object_override(tmp_path: Path) -> None:
    runtime = Path("data/scene_runtime/bin/python")
    if not runtime.is_file():
        pytest.skip("independent USD runtime unavailable")
    request = {
        "output_dir": str(tmp_path / "usd"),
        "ground_plane": False,
        "static_friction": 0.8,
        "dynamic_friction": 0.7,
        "restitution": 0.2,
        "objects": [
            {
                "prim": "custom",
                "translation": [0, 0, 0],
                "rotation_xyzw": [0, 0, 0, 1],
                "collider": {
                    "type": "OBB",
                    "dimensions_xyz_m": [1, 1, 1],
                    "local_transform": {"translation_xyz": [0, 0, 0], "rotation_quaternion_xyzw": [0, 0, 0, 1]},
                },
                "physics": {
                    "dynamic": False,
                    "static_friction": 0.3,
                    "dynamic_friction": 0.2,
                    "restitution": 0.1,
                    "provenance": {},
                },
            }
        ],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    subprocess.run(
        [
            str(runtime.absolute()),
            "src/services/simulation/usd/hybrid_runner.py",
            "--request",
            str(path),
            "--result",
            str(tmp_path / "result.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    inspection = """from pxr import Usd, UsdShade
import sys
s = Usd.Stage.Open(sys.argv[1])
assert not s.GetPrimAtPath('/World/GroundPlane')
m = s.GetPrimAtPath('/World/PhysicsMaterial')
assert abs(m.GetAttribute('physics:staticFriction').Get() - 0.8) < 1e-6
assert abs(m.GetAttribute('physics:dynamicFriction').Get() - 0.7) < 1e-6
assert abs(m.GetAttribute('physics:restitution').Get() - 0.2) < 1e-6
p = s.GetPrimAtPath('/World/Objects/custom/Collision/box')
bound, _ = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial(materialPurpose='physics')
assert abs(bound.GetPrim().GetAttribute('physics:staticFriction').Get() - 0.3) < 1e-6
"""
    subprocess.run(
        [str(runtime.absolute()), "-c", inspection, str(tmp_path / "usd/scene.usda")],
        check=True,
        capture_output=True,
        text=True,
    )
