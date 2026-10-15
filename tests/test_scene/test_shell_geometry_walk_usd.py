"""T-018: shell-built scenes (T-007) through Walk and USD; legacy and ObjectGS-era scenes keep their behaviour."""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from scipy.spatial.transform import Rotation

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.object_geometry import ObjectShellManifest
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.objects import apply_object_action
from src.services.orchestration.scene.physics_collision import effective_collision_for_revision
from src.services.scene.editing.commands import move_object
from src.services.simulation.usd.builder import _collect_scene_refs
from tests.test_scene.test_object_geometry_build import (  # noqa: F401  (pytest fixtures)
    build,
    cpu_providers,
    draft_scene,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "data/scene_runtime/bin/python"
HYBRID_RUNNER = ROOT / "src/services/simulation/usd/hybrid_runner.py"
SQRT_HALF = float(np.sqrt(0.5))
#: candidate-001 starts at (1, 1, 0.2). The e2e move puts it at (2, 1, 0.2) and turns it 90° about z.
MOVED_CENTER = (2.0, 1.0, 0.2)


@pytest.fixture
def ready_shell_scene(draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace) -> SimpleNamespace:  # noqa: F811 (pytest fixture chain)
    """The T-007 draft fixture built into a Ready scene; CoACD is the test double from `cpu_providers`."""
    build(draft_scene)
    return draft_scene


def test_shell_surfaces_are_accepted_by_every_backend_reader(ready_shell_scene: SimpleNamespace) -> None:
    registry, job_id = ready_shell_scene.registry, ready_shell_scene.job_id
    ready = registry.scene.current(job_id).scene
    confirmed = apply_object_action(registry.scene, job_id, ready.objects[0].id, "confirm", ready.scene_revision)
    scene = confirmed.revision.scene
    surface_a, surface_b = (item.surface_mesh_ref for item in scene.objects)
    # Scene contract: the shell is a valid surface_mesh_ref, and the collider stays a separate reference.
    assert surface_a.artifact_type == surface_b.artifact_type == "ObjectShellMesh"
    # USD inventory: only active objects export their surface and collider.
    _, geometry, colliders = _collect_scene_refs(scene)
    assert surface_a in geometry and scene.objects[0].collider.geometry_ref in colliders
    assert surface_b not in geometry
    # Artifact retention: every object keeps its surface referenced, active or not.
    references = SceneEditor.artifact_references(scene)
    assert surface_a in references and surface_b in references
    # Shell manifest: the audit receipt names the same shell mesh that the scene uses as its surface.
    for item in scene.objects:
        ref = ProductArtifactRef.model_validate(item.provenance["shell_manifest_ref"])
        manifest = ObjectShellManifest.model_validate_json(registry.runtime_resolver.require(ref).read_bytes())
        assert manifest.shell_mesh_ref == item.surface_mesh_ref


@pytest.fixture
def ready_with_real_coacd(
    draft_scene: SimpleNamespace,  # noqa: F811 (pytest fixture chain)
    cpu_providers: SimpleNamespace,  # noqa: F811 (pytest fixture chain)
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    """`ready_shell_scene`, but the convex step is the real CoACD from the isolated runtime."""
    from src.services.orchestration.scene import objectify

    fake_run = objectify._run

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, *args: object, **kwargs: object
    ) -> dict:
        provider = cpu_providers.real_run if name == "convex" else fake_run
        return provider(python, script, request, workspace, name, *args, **kwargs)

    monkeypatch.setattr(objectify, "_run", run)
    build(draft_scene)
    return draft_scene


def _footprint(fixture: SimpleNamespace, label: int, margin: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """XY box of one object's source Gaussians, widened by `margin` metres."""
    rows = fixture.rows[fixture.labels == label]
    low = np.array([rows["x"].min(), rows["y"].min()]) - margin
    high = np.array([rows["x"].max(), rows["y"].max()]) + margin
    return low, high


def _count_triangles(
    background, low: np.ndarray, high: np.ndarray, *, z_min: float = -np.inf, z_max: float = np.inf
) -> int:
    """Triangles whose centroid lies over the XY box and inside the height band."""
    centers = background.vertices[background.faces].mean(axis=1)
    over = np.all((centers[:, :2] >= low) & (centers[:, :2] <= high), axis=1)
    return int(np.count_nonzero(over & (centers[:, 2] >= z_min) & (centers[:, 2] <= z_max)))


def _world_points(glb: bytes, pose: Transform, local: Transform | None = None) -> np.ndarray:
    """Vertices of an object-local GLB, through its local transform, then the object pose (world metres)."""
    points = np.asarray(trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh", process=False).vertices, float)
    if local is not None:
        points = Rotation.from_quat(local.rotation_quaternion_xyzw).apply(points) + np.asarray(local.translation_xyz)
    return Rotation.from_quat(pose.rotation_quaternion_xyzw).apply(points) + np.asarray(pose.translation_xyz)


def _moved_pose(transform: Transform) -> Transform:
    return transform.model_copy(
        update={"translation_xyz": MOVED_CENTER, "rotation_quaternion_xyzw": (0.0, 0.0, SQRT_HALF, SQRT_HALF)}
    )


def _confirm_then_move(fixture: SimpleNamespace) -> SimpleNamespace:
    """Confirm candidate-001 (it leaves the background), record the background, then move and turn it."""
    registry, job_id = fixture.registry, fixture.job_id
    ready = registry.scene.current(job_id).scene
    target = ready.objects[0].id
    confirmed = apply_object_action(registry.scene, job_id, target, "confirm", ready.scene_revision).revision.scene
    _, before = effective_collision_for_revision(registry, job_id, confirmed.scene_revision)
    pose = _moved_pose(confirmed.objects[0].transform)
    moved = registry.scene.publish_next(
        job_id, confirmed.scene_revision, move_object(confirmed, target, pose), "move"
    ).revision.scene
    _, after = effective_collision_for_revision(registry, job_id, moved.scene_revision)
    return SimpleNamespace(registry=registry, job_id=job_id, before=before, after=after, moved=moved)


@pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated CoACD runtime data/scene_runtime is not installed")
def test_moved_shell_object_leaves_no_ghost_and_keeps_floor_support(ready_with_real_coacd: SimpleNamespace) -> None:
    fixture = ready_with_real_coacd
    state = _confirm_then_move(fixture)
    before, after, moved = state.before, state.after, state.moved
    # The environment is authored at build time, so moving a confirmed object changes no environment triangle.
    np.testing.assert_array_equal(after.vertices, before.vertices)
    np.testing.assert_array_equal(after.faces, before.faces)
    assert not after.source_remove_mask.any()
    # No ghost: nothing above the floor is left where candidate-001 used to stand.
    old_low, old_high = _footprint(fixture, label=0)
    assert _count_triangles(after, old_low, old_high, z_min=0.1) == 0
    # The floor under the old footprint stays.
    assert _count_triangles(after, old_low, old_high, z_max=0.05) > 0
    # Control: candidate-002 is not confirmed, so it stays in the background; the ghost check must see it.
    other_low, other_high = _footprint(fixture, label=2)
    assert _count_triangles(after, other_low, other_high, z_min=0.1) > 0
    # Walk pose: the collider of candidate-001 follows its new pose, including the 90° turn.
    obj = moved.objects[0]
    shell = _world_points(state.registry.runtime_resolver.require(obj.surface_mesh_ref).read_bytes(), obj.transform)
    collider = _world_points(
        state.registry.runtime_resolver.require(obj.collider.geometry_ref).read_bytes(),
        obj.transform,
        local=obj.collider.local_transform,
    )
    np.testing.assert_allclose((collider.min(axis=0) + collider.max(axis=0)) / 2, MOVED_CENTER, atol=0.03)
    extents = collider.max(axis=0) - collider.min(axis=0)
    # Shell and CoACD grow the 0.24 x 0.32 x 0.4 m source box by up to ~0.09 m per axis on this 0.02 m grid.
    np.testing.assert_allclose(extents, [0.32, 0.24, 0.4], atol=0.12)
    # The 0.32 m side now runs along x; an unturned box would fail this check.
    assert extents[0] > extents[1]
    np.testing.assert_allclose(collider.min(axis=0), shell.min(axis=0), atol=0.05)
    np.testing.assert_allclose(collider.max(axis=0), shell.max(axis=0), atol=0.05)


def test_pose_only_move_queues_no_objectify_work(ready_shell_scene: SimpleNamespace, tmp_path: Path) -> None:
    from src.services.orchestration.scene import objectify_queue

    fixture = ready_shell_scene
    settings = fixture.settings.model_copy(update={"database_url": f"sqlite:///{tmp_path / 'runtime.db'}"})
    registry, job_id = fixture.registry, fixture.job_id
    ready = registry.scene.current(job_id).scene
    target = ready.objects[0].id
    confirmed = apply_object_action(registry.scene, job_id, target, "confirm", ready.scene_revision).revision.scene
    before = objectify_queue.state(registry, settings, job_id)
    registry.scene.publish_next(
        job_id,
        confirmed.scene_revision,
        move_object(confirmed, target, _moved_pose(confirmed.objects[0].transform)),
        "move",
    )
    after = objectify_queue.state(registry, settings, job_id)
    assert after.scene_revision != before.scene_revision
    assert after.status == "idle" and after.operation_id is None and after.requested_at is None
    assert after.model_dump(exclude={"scene_revision"}) == before.model_dump(exclude={"scene_revision"})


_INSPECT = """
import json, sys
import numpy as np
from pxr import Gf, Usd, UsdGeom, UsdPhysics

stage = Usd.Stage.Open(sys.argv[1])
cache = UsdGeom.XformCache()
points, scales = [], []
for prim in Usd.PrimRange(stage.GetPrimAtPath('/World/Objects/candidate_001')):
    if prim.IsA(UsdGeom.Mesh) and prim.HasAPI(UsdPhysics.CollisionAPI):
        matrix = cache.GetLocalToWorldTransform(prim)
        scales.append([float(np.linalg.norm([matrix[r][c] for c in range(3)])) for r in range(3)])
        points.extend(matrix.Transform(Gf.Vec3d(*map(float, p))) for p in UsdGeom.Mesh(prim).GetPointsAttr().Get())
environment = UsdGeom.Mesh(stage.GetPrimAtPath('/World/Environment/Collision'))
points = np.array(points)
print(json.dumps(dict(
    up=str(UsdGeom.GetStageUpAxis(stage)),
    unit=UsdGeom.GetStageMetersPerUnit(stage),
    scales=scales,
    bounds=[points.min(0).tolist(), points.max(0).tolist()],
    environment_faces=len(environment.GetFaceVertexCountsAttr().Get()),
)))
"""


@pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated usd-core runtime data/scene_runtime is not installed")
def test_moved_shell_collider_is_placed_once_in_usd_and_environment_is_not_carved_again(
    ready_with_real_coacd: SimpleNamespace, tmp_path: Path
) -> None:
    state = _confirm_then_move(ready_with_real_coacd)
    registry, obj = state.registry, state.moved.objects[0]
    collider_bytes = registry.runtime_resolver.require(obj.collider.geometry_ref).read_bytes()
    environment_path, collider_path = tmp_path / "environment.glb", tmp_path / "candidate-001.glb"
    environment_path.write_bytes(
        trimesh.Trimesh(state.after.vertices, state.after.faces, process=False).export(file_type="glb")
    )
    collider_path.write_bytes(collider_bytes)
    request_path, result_path = tmp_path / "request.json", tmp_path / "result.json"
    request_path.write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "usd"),
                "ground_plane": False,
                "environment": {"collision_mesh": str(environment_path)},
                "objects": [
                    {
                        "prim": "candidate_001",
                        "translation": obj.transform.translation_xyz,
                        "rotation_xyzw": obj.transform.rotation_quaternion_xyzw,
                        "collider": {
                            "type": "CONVEX_DECOMPOSITION",
                            "geometry_path": str(collider_path),
                            "local_transform": obj.collider.local_transform.model_dump(mode="json"),
                            "part_paths": [],
                            "dimensions_xyz_m": None,
                        },
                    }
                ],
            }
        )
    )
    subprocess.run(
        [str(RUNTIME), str(HYBRID_RUNNER), "--request", str(request_path), "--result", str(result_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    inspected = subprocess.run(
        [str(RUNTIME), "-c", _INSPECT, str(tmp_path / "usd/scene.usda")],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    measured = json.loads(inspected.stdout)
    assert measured["up"] == "Z" and measured["unit"] == 1.0
    assert measured["scales"] and np.allclose(measured["scales"], 1.0, atol=1e-5)  # no scale on the object or stage
    assert measured["environment_faces"] == len(state.after.faces) == len(state.before.faces)
    expected = _world_points(collider_bytes, obj.transform, local=obj.collider.local_transform)
    np.testing.assert_allclose(measured["bounds"], [expected.min(axis=0), expected.max(axis=0)], atol=1e-4)


def test_legacy_scene_without_geometry_key_opens_edits_walks_and_packages_as_before(tmp_path: Path) -> None:
    from src.api.product.artifacts import _require_walk_allowed
    from src.models.contracts.validation import RuleResult
    from src.services.orchestration.review.simulation_package import build_simulation_package
    from src.services.scene.geometry_state import object_geometry_state
    from tests.test_orchestration.test_simulation_package import _scene_job

    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    # Legacy scenes carry no object_geometry key; a missing key means ready.
    assert "object_geometry" not in scene.provenance
    assert object_geometry_state(scene) == "ready"
    _require_walk_allowed(registry, job.job_id)
    (pallet,) = scene.objects
    confirmed = apply_object_action(registry.scene, job.job_id, pallet.id, "confirm", scene.scene_revision)
    confirmed = confirmed.revision.scene
    _, before = effective_collision_for_revision(registry, job.job_id, confirmed.scene_revision)
    x, y, z = pallet.transform.translation_xyz
    pose = pallet.transform.model_copy(
        update={"translation_xyz": (x + 1.0, y, z), "rotation_quaternion_xyzw": (0.0, 0.0, SQRT_HALF, SQRT_HALF)}
    )
    moved = registry.scene.publish_next(
        job.job_id, confirmed.scene_revision, move_object(confirmed, pallet.id, pose), "move"
    ).revision.scene
    _, after = effective_collision_for_revision(registry, job.job_id, moved.scene_revision)
    # Legacy carving follows source triangles, not the edited pose, so a move leaves the Walk environment as it was.
    np.testing.assert_array_equal(after.vertices, before.vertices)
    np.testing.assert_array_equal(after.faces, before.faces)
    package = build_simulation_package(registry, job.job_id)
    assert package.preflight.blocking_result == RuleResult.PASS
    assert package.confirmed_objects == 1


def test_objectgs_era_scene_without_geometry_key_keeps_walk_and_surface_refs(tmp_path: Path) -> None:
    from src.services.scene.editing.commands import confirm_object
    from src.services.scene.geometry_state import object_geometry_state, require_geometry_ready
    from tests.test_scene.test_object_aware_composition import case

    scene, compose, _ = case(tmp_path)
    scene = confirm_object(confirm_object(scene, "A"), "B")
    first = scene.objects[0]
    surface = first.geometry_ref.model_copy(update={"artifact_type": "ObjectSurfaceMesh"})
    scene = scene.model_copy(
        update={"objects": [first.model_copy(update={"surface_mesh_ref": surface}), scene.objects[1]]}
    )
    assert "object_geometry" not in scene.provenance
    assert object_geometry_state(scene) == "ready"
    require_geometry_ready(scene, "Walk")
    before = compose(scene)
    moved = move_object(scene, "A", first.transform.model_copy(update={"translation_xyz": (10, 4, 2)}))
    after = compose(moved)
    np.testing.assert_array_equal(after.vertices, before.vertices)
    np.testing.assert_array_equal(after.faces, before.faces)
    _, geometry, _ = _collect_scene_refs(moved)
    assert surface in geometry


@pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated CoACD/USD runtime data/scene_runtime is not installed")
def test_reviewed_shell_scene_builds_a_sealed_simulation_package(
    ready_with_real_coacd: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed shell must reach the public package builder with its actual collider in the sealed inventory."""
    from src.models.contracts.identity import verify_candidate_inventory, verify_content_checksum
    from src.models.contracts.validation import RuleResult
    from src.services.orchestration.review import simulation_package as service

    fixture = ready_with_real_coacd
    registry, job_id = fixture.registry, fixture.job_id
    ready = registry.scene.current(job_id).scene
    confirmed = apply_object_action(
        registry.scene, job_id, ready.objects[0].id, "confirm", ready.scene_revision
    ).revision.scene
    obj, pending = confirmed.objects
    monkeypatch.setattr(service, "get_settings", lambda: fixture.settings)

    package = service.build_simulation_package(registry, job_id)

    assert package.preflight.blocking_result == RuleResult.PASS, package.preflight.model_dump(mode="json")
    assert package.package_ref is not None and package.candidate is not None
    assert package.source_scene_revision == confirmed.scene_revision
    assert package.confirmed_objects == 1
    candidate = package.candidate
    assert obj.surface_mesh_ref in candidate.geometry
    assert obj.collider.geometry_ref in candidate.colliders
    assert pending.collider.geometry_ref not in candidate.colliders
    verify_candidate_inventory(candidate)
    verify_content_checksum(candidate, "candidate_checksum")
    with zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(package.package_ref).read_bytes())) as archive:
        manifest = json.loads(archive.read("candidate_manifest.json"))
        assert obj.collider.geometry_ref.model_dump(mode="json") in manifest["collider_refs"]
        assert archive.read("scene.usda").startswith(b"#usda 1.0")
    repeated = service.build_simulation_package(registry, job_id)
    assert repeated.package_ref == package.package_ref
    assert registry.scene.current(job_id).scene.scene_revision == package.scene_revision
