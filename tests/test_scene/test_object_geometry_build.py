"""Draft geometry publication is fenced; failed builds never replace the active scene."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_stale_revision_is_rejected_before_reading_artifacts(tmp_path: Path) -> None:
    from src.services.orchestration.scene.object_geometry_build import build_object_geometry
    from src.services.scene.editing.membership import StaleObjectMembershipRevisionError

    registry = SimpleNamespace(
        scene=SimpleNamespace(current=lambda _: SimpleNamespace(scene=SimpleNamespace(scene_revision="rev-002")))
    )
    with pytest.raises(StaleObjectMembershipRevisionError):
        build_object_geometry(registry, None, "job-test", expected_revision="rev-001", workspace=tmp_path)


@pytest.mark.parametrize("missing_membership", [True, False])
def test_full_build_requires_membership_and_draft(tmp_path: Path, missing_membership: bool) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError, build_object_geometry

    scene = SimpleNamespace(
        scene_revision="rev-001",
        environment=SimpleNamespace(membership=None if missing_membership else object()),
        provenance={"object_geometry": "ready"},
    )
    registry = SimpleNamespace(scene=SimpleNamespace(current=lambda _: SimpleNamespace(scene=scene)))
    with pytest.raises(ObjectGeometryBuildError):
        build_object_geometry(registry, None, "job-test", expected_revision="rev-001", workspace=tmp_path)


@pytest.fixture
def draft_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    import numpy as np

    from src.config import Settings
    from src.models.contracts.coordinates import CoordinateSystem, Transform
    from src.models.contracts.object_membership import ObjectMembershipArtifact
    from src.models.contracts.scene import (
        ObjectPhysics,
        SceneEnvironment,
        SceneObject,
        SceneObjectOrigin,
        SceneObjectState,
    )
    from src.services.orchestration.artifacts import FilesystemArtifactStore
    from src.services.orchestration.scene import object_geometry_build as module
    from src.services.orchestration.scene.objectify import _reference
    from src.services.scene.collision_ownership import bind_source_collision_ownership
    from src.services.scene.decomposition import gaussian_split
    from tests.test_orchestration.test_floor_evidence import _floor_model
    from tests.test_orchestration.test_simulation_package import _scene_job
    from tests.test_scene.test_object_correction import _source_rows

    registry, job = _scene_job(tmp_path / "registry")
    base = registry.scene.current(job.job_id).scene
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(kind: str, payload: bytes, tail: str) -> module.ProductArtifactRef:
        from src.models.contracts.manifests import StageId

        return store.publish(_reference(job.job_id, tail, kind, StageId.SCENE_DECOMPOSE, payload), payload)

    grid = (
        np.array(np.meshgrid(np.linspace(-0.12, 0.12, 9), np.linspace(-0.16, 0.16, 11), np.linspace(-0.2, 0.2, 13)))
        .reshape(3, -1)
        .T
    )
    centers = [(1, 1, 0.2), (-1, 1, 0.2)]
    floor = np.array([[x, y, 0] for x in np.linspace(-2, 2, 21) for y in np.linspace(-1, 2, 16)])
    points = np.vstack([grid + center for center in centers] + [floor])
    rows = np.zeros(len(points), dtype=_source_rows().dtype)
    for axis, name in enumerate(("x", "y", "z")):
        rows[name] = points[:, axis]
    rows["opacity"] = 5
    rows["rot_0"] = 1
    labels = np.r_[np.full(len(grid), 0), np.full(len(grid), 2), np.full(len(floor), -1)].astype(np.int32)
    source = publish("GaussianPLY", gaussian_split.write_gaussian_ply(rows), "test-source/{digest}.ply")
    labels_ref = publish("ObjectMembershipLabels", labels.astype("<i4").tobytes(), "test-labels/{digest}.i32le")
    mapping = {"0": "candidate-001", "2": "candidate-002"}
    membership = ObjectMembershipArtifact(
        source_visual_ref=source,
        source_geometry_ref=base.environment.geometry_ref,
        extraction_revision=base.scene_revision,
        coordinate_system=CoordinateSystem(),
        gaussian_count=len(rows),
        labels_ref=labels_ref,
        label_to_object_id=mapping,
    )
    preview = publish("ObjectShellMesh", b"preview", "test-preview/{digest}.glb")
    objects = []
    for index, center in enumerate(centers, 1):
        object_id = f"candidate-{index:03d}"
        pose = Transform(
            parent_frame="world", local_frame=object_id, translation_xyz=center, rotation_quaternion_xyzw=(0, 0, 0, 1)
        )
        objects.append(
            SceneObject(
                id=object_id,
                name=f"Object {index}",
                state=SceneObjectState.CANDIDATE,
                origin=SceneObjectOrigin.RECONSTRUCTED,
                active=False,
                local_frame=object_id,
                transform=pose,
                visual_ref=preview,
                geometry_ref=preview,
                primitive_dimensions_xyz_m=(0.24, 0.32, 0.4),
                provenance={"source_transform": pose.model_dump(mode="json")},
                physics=ObjectPhysics(
                    dynamic=True,
                    mass_kg=18,
                    mass_source="user",
                    static_friction=0.8,
                    dynamic_friction=0.6,
                    restitution=0.1,
                    provenance={"fixture": True},
                )
                if index == 1
                else None,
            )
        )
    objects = bind_source_collision_ownership(objects, base.environment.geometry_ref, membership.extraction_revision)
    draft = base.model_copy(
        update={
            "objects": objects,
            "environment": SceneEnvironment(
                visual_ref=base.environment.visual_ref,
                geometry_ref=base.environment.geometry_ref,
                membership=membership,
            ),
            "provenance": {"object_geometry": "awaiting_review", "geometry_method": "shell"},
        }
    )
    scene = registry.scene.publish_next(job.job_id, base.scene_revision, draft, "fixture-draft").revision.scene
    bundle = SimpleNamespace(
        canonical_geometry_ref=base.environment.geometry_ref, camera_pose_refs=[None], rgb_frame_refs=[]
    )
    # Full models and artifact bytes are real; expensive providers are replaced in subsequent tests.
    monkeypatch.setattr(module, "job_bundle", lambda *args: bundle, raising=False)
    monkeypatch.setattr(
        module,
        "load_job_config",
        lambda *args: SimpleNamespace(
            scene={"geometry_method": "shell", "coacd_max_convex_hull": 8, "inpaint_max_new_gaussians": 100}
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "fit_canonical_floor_model",
        lambda points, checksum: _floor_model().model_copy(update={"source_checksum": checksum}),
        raising=False,
    )
    monkeypatch.setattr(module, "camera_views", lambda *args: [], raising=False)
    settings = Settings(
        product_scene_runtime_python=Path("data/scene_runtime/bin/python").absolute(), product_sam2_checkpoint=None
    )
    return SimpleNamespace(
        registry=registry,
        job_id=job.job_id,
        scene=scene,
        rows=rows,
        labels=labels,
        settings=settings,
        workspace=tmp_path / "build",
    )


def test_fine_shell_manifest_is_source_bound_and_qa_passed(draft_scene: SimpleNamespace) -> None:
    from src.services.orchestration.scene import object_geometry_build as module

    selected = draft_scene.scene.objects[0]
    refs = {}

    def publish(ref: module.ProductArtifactRef, payload: bytes) -> module.ProductArtifactRef:
        refs[ref.artifact_uri] = payload
        return ref

    mesh, manifest_ref, _ = module._build_shell(
        selected,
        draft_scene.rows[draft_scene.labels == 0],
        draft_scene.scene.environment.membership,
        draft_scene.workspace,
        publish,
    )
    from src.models.contracts.object_geometry import ObjectShellManifest

    manifest = ObjectShellManifest.model_validate_json(refs[manifest_ref.artifact_uri])
    assert mesh.artifact_type == "ObjectShellMesh"
    assert manifest.quality["passed"] is True
    assert manifest.source_membership == draft_scene.scene.environment.membership
    assert manifest.source_world_from_object == selected.transform
    assert manifest.voxel_m == 0.02
    assert "solidity" in manifest.statistics


def test_zero_part_shell_collider_fails_without_new_revision(
    draft_scene: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.scene import object_geometry_build as module
    from src.services.orchestration.scene import objectify
    from src.services.orchestration.scene.object_geometry_steps import SurfaceInput

    def run(*args: object, **kwargs: object) -> dict:
        return {"objects": [{"id": "candidate-001", "parts": 0}]}

    monkeypatch.setattr(objectify, "_run", run)
    item = SurfaceInput(
        "candidate-001",
        draft_scene.workspace / "shell.glb",
        "sha256:" + "0" * 64,
        draft_scene.workspace / "collider.glb",
    )
    with pytest.raises(module.ObjectGeometryBuildError, match="Gaussian shell collider generation failed"):
        module._build_colliders(
            [item], draft_scene.settings, {}, draft_scene.workspace, lambda ref, payload: ref, draft_scene.job_id
        )
    assert draft_scene.registry.scene.current(draft_scene.job_id).scene == draft_scene.scene


@pytest.fixture
def cpu_providers(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from src.services.orchestration.scene import objectify

    real_run = objectify._run

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, *args: object, **kwargs: object
    ) -> dict:
        if name == "inpaint":
            Path(request["output_ply"]).write_bytes(Path(request["background_ply"]).read_bytes())
            return {"method": "fixture", "original_gaussians": 336, "inpainted_gaussians": 0}
        import trimesh

        result = []
        for item in request["objects"]:
            # Test double for CoACD only; integration below runs the real provider.
            mesh = trimesh.load(item["surface_mesh"], force="mesh")
            Path(item["output_glb"]).write_bytes(mesh.export(file_type="glb"))
            result.append({"id": item["id"], "parts": 1})
        return {"objects": result}

    def package(source: Path, workspace: Path, *args: object, **kwargs: object) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        output = workspace / "background.sog"
        output.write_bytes(b"fixture SOG")
        return output

    monkeypatch.setattr(objectify, "_run", run)
    monkeypatch.setattr(objectify, "package_splat", package)
    return SimpleNamespace(real_run=real_run)


def test_environment_build_removes_object_cells(draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace) -> None:
    import trimesh

    from src.services.orchestration.artifacts import FilesystemArtifactStore
    from src.services.orchestration.scene import object_geometry_build as module
    from src.services.scene.decomposition.gaussian_split import positions
    from tests.test_scene.test_object_aware_geometry import ray

    fixture = draft_scene
    store = FilesystemArtifactStore(fixture.registry.runtime_resolver)
    environment = module._build_environment(
        fixture.registry,
        fixture.settings,
        fixture.job_id,
        fixture.scene,
        fixture.rows,
        fixture.labels,
        module.ObjectifyConfig(),
        fixture.workspace,
        store.publish,
        None,
    )
    assert environment.object_aware_collision_ref is not None
    assert environment.membership == fixture.scene.environment.membership
    mesh = trimesh.load(fixture.registry.runtime_resolver.require(environment.collider_ref), force="mesh")
    # Downward ray from each object's centre reaches inferred floor, not residual object cells.
    for item in fixture.scene.objects:
        point = positions(fixture.rows[fixture.labels == (0 if item.id.endswith("001") else 2)]).mean(axis=0)
        assert ray(mesh, point, [0, 0, -1]) > 0.1
    assert fixture.registry.scene.current(fixture.job_id).scene == fixture.scene


def build(fixture: SimpleNamespace, **kwargs: object) -> str:
    from src.services.orchestration.scene.object_geometry_build import build_object_geometry

    return build_object_geometry(
        fixture.registry,
        fixture.settings,
        fixture.job_id,
        expected_revision=fixture.scene.scene_revision,
        workspace=fixture.workspace,
        **kwargs,
    )


def test_draft_build_publishes_ready_and_preserves_user_state(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace
) -> None:
    from src.models.contracts.object_geometry import ObjectShellManifest
    from src.models.contracts.scene import ColliderType

    phases = []
    revision = build(draft_scene, progress=phases.append)
    scene = draft_scene.registry.scene.current(draft_scene.job_id).scene
    assert scene.scene_revision == revision != draft_scene.scene.scene_revision
    assert scene.provenance["object_geometry"] == "ready"
    assert scene.provenance["geometry_build"]["built_object_ids"] == ["candidate-001", "candidate-002"]
    assert phases == ["shell", "quality", "collider", "environment", "publish"]
    assert scene.environment.object_aware_collision_ref is not None
    for before, item in zip(draft_scene.scene.objects, scene.objects, strict=True):
        assert item.collider.collider_type == ColliderType.CONVEX_DECOMPOSITION
        assert item.surface_mesh_ref.artifact_type == "ObjectShellMesh"
        assert item.transform == before.transform
        assert item.state == before.state and item.active == before.active
        assert item.name == before.name and item.physics == before.physics
        assert item.source_collision == before.source_collision
        assert item.provenance["surface_selection"] == {"chosen": "gaussian_shell"}
        ref = item.provenance["shell_manifest_ref"]
        from src.models.contracts.artifacts import ProductArtifactRef

        manifest = ObjectShellManifest.model_validate_json(
            draft_scene.registry.runtime_resolver.require(ProductArtifactRef.model_validate(ref)).read_bytes()
        )
        assert manifest.quality["passed"] is True
        assert manifest.provenance["surface_origin"] == "gaussian_shell_v1"


@pytest.mark.parametrize("phase", ["quality", "collider", "environment", "publish"])
def test_cancelled_build_never_publishes(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, phase: str
) -> None:
    from threading import Event

    from src.services.process_control import ProcessCancelledError

    cancel = Event()

    def progress(current: str) -> None:
        if current == phase:
            cancel.set()

    with pytest.raises(ProcessCancelledError):
        build(draft_scene, cancel_event=cancel, progress=progress)
    assert draft_scene.registry.scene.current(draft_scene.job_id).scene == draft_scene.scene


@pytest.mark.parametrize("reason", ["placeholder", "qa", "missing_frame"])
def test_shell_failure_keeps_draft_without_obb(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    from src.services.orchestration.scene import object_geometry_build as module

    if reason == "qa":

        def broken(*args: object, **kwargs: object) -> None:
            raise module.GaussianShellError("fixture QA failed")

        monkeypatch.setattr(module, "build_gaussian_shell", broken)
    else:
        item = draft_scene.scene.objects[0]
        provenance = dict(item.provenance)
        if reason == "placeholder":
            provenance["shell_error"] = "fixture placeholder"
        else:
            provenance.pop("source_transform")
        updated = item.model_copy(update={"provenance": provenance})
        draft_scene.scene = draft_scene.registry.scene.publish_next(
            draft_scene.job_id,
            draft_scene.scene.scene_revision,
            draft_scene.scene.model_copy(update={"objects": [updated, draft_scene.scene.objects[1]]}),
            "fixture-error",
        ).revision.scene
    with pytest.raises(module.ObjectGeometryBuildError) as error:
        build(draft_scene)
    assert error.value.object_id == "candidate-001"
    assert draft_scene.registry.scene.current(draft_scene.job_id).scene == draft_scene.scene
    assert all(item.collider is None for item in draft_scene.scene.objects)


@pytest.mark.parametrize("review", ["IGNORED", "DELETED", "MERGED"])
def test_review_tombstones_keep_review_and_receive_colliders(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, review: str
) -> None:
    item = draft_scene.scene.objects[0]
    ignored = item.model_copy(update={"provenance": {**item.provenance, "review": review}})
    draft_scene.scene = draft_scene.registry.scene.publish_next(
        draft_scene.job_id,
        draft_scene.scene.scene_revision,
        draft_scene.scene.model_copy(update={"objects": [ignored, draft_scene.scene.objects[1]]}),
        "fixture-review",
    ).revision.scene
    build(draft_scene)
    scene = draft_scene.registry.scene.current(draft_scene.job_id).scene
    first = scene.objects[0]
    assert first.collider is not None
    assert first.surface_mesh_ref.artifact_type == "ObjectShellMesh"
    assert first.provenance["review"] == review
    assert first.state == ignored.state and first.active == ignored.active
    assert first.transform == ignored.transform
    assert first.source_collision == ignored.source_collision
    assert first.physics == ignored.physics and first.name == ignored.name
    assert scene.objects[1].collider is not None
    assert scene.provenance["geometry_build"]["built_object_ids"] == ["candidate-001", "candidate-002"]


def test_source_frame_wins_over_moved_pose(draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace) -> None:
    import numpy as np
    import trimesh

    original = draft_scene.scene
    build(draft_scene)
    ready = draft_scene.registry.scene.current(draft_scene.job_id).scene
    bounds = trimesh.load(
        draft_scene.registry.runtime_resolver.require(ready.objects[0].geometry_ref), force="mesh"
    ).bounds
    moved = original.objects[0].model_copy(
        update={
            "transform": original.objects[0].transform.model_copy(
                update={"translation_xyz": (20, 30, 40), "rotation_quaternion_xyzw": (0, 0, 0.6, 0.8)}
            )
        }
    )
    draft_scene.scene = draft_scene.registry.scene.publish_next(
        draft_scene.job_id,
        ready.scene_revision,
        original.model_copy(update={"objects": [moved, original.objects[1]]}),
        "fixture-moved-draft",
    ).revision.scene
    build(draft_scene)
    rebuilt = draft_scene.registry.scene.current(draft_scene.job_id).scene
    np.testing.assert_allclose(
        trimesh.load(
            draft_scene.registry.runtime_resolver.require(rebuilt.objects[0].geometry_ref), force="mesh"
        ).bounds,
        bounds,
    )
    assert rebuilt.objects[0].transform == moved.transform


@pytest.mark.parametrize("outcome", ["concurrent_edit", "fenced", "environment_failure"])
def test_failed_publication_or_environment_keeps_committed_head(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from src.services.orchestration.scene import object_geometry_build as module
    from src.services.orchestration.scene.errors import SceneRevisionConflictError

    expected = draft_scene.scene

    def progress(phase: str) -> None:
        nonlocal expected
        if phase == "environment" and outcome == "concurrent_edit":
            changed = expected.model_copy(update={"provenance": {**expected.provenance, "concurrent_edit": True}})
            expected = draft_scene.registry.scene.publish_next(
                draft_scene.job_id, expected.scene_revision, changed, "concurrent-edit"
            ).revision.scene

    def broken(*args: object, **kwargs: object) -> None:
        raise module.ObjectifyError("fixture environment failure")

    if outcome == "environment_failure":
        monkeypatch.setattr(module, "_build_environment", broken)
    error_type = module.ObjectGeometryBuildError if outcome == "environment_failure" else SceneRevisionConflictError
    with pytest.raises(error_type):
        build(draft_scene, progress=progress, commit_guard=(lambda tx: False) if outcome == "fenced" else None)
    assert draft_scene.registry.scene.current(draft_scene.job_id).scene == expected


@pytest.mark.parametrize("target", ["source", "labels"])
def test_corrupt_source_artifact_fails_before_shell(
    draft_scene: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    from src.services.orchestration.scene import object_geometry_build as module

    resolver = draft_scene.registry.runtime_resolver
    membership = draft_scene.scene.environment.membership
    reference = membership.source_visual_ref if target == "source" else membership.labels_ref
    broken = draft_scene.workspace.parent / "corrupt"
    broken.write_bytes(b"corrupt")
    original = resolver.require
    monkeypatch.setattr(resolver, "require", lambda ref: broken if ref == reference else original(ref))
    with pytest.raises(module.ObjectGeometryBuildError, match="checksum"):
        build(draft_scene)
    assert draft_scene.registry.scene.current(draft_scene.job_id).scene == draft_scene.scene


def test_rotated_source_frame_is_used_for_shell(draft_scene: SimpleNamespace) -> None:
    import io

    import numpy as np
    import trimesh

    from src.services.orchestration.scene import object_geometry_build as module

    item = draft_scene.scene.objects[0]
    pose = item.transform.model_copy(update={"rotation_quaternion_xyzw": (0, 0, 2**-0.5, 2**-0.5)})
    item = item.model_copy(update={"provenance": {"source_transform": pose.model_dump(mode="json")}})
    payloads = {}

    def publish(ref: module.ProductArtifactRef, payload: bytes) -> module.ProductArtifactRef:
        payloads[ref.artifact_uri] = payload
        return ref

    mesh_ref, _, _ = module._build_shell(
        item,
        draft_scene.rows[draft_scene.labels == 0],
        draft_scene.scene.environment.membership,
        draft_scene.workspace,
        publish,
    )
    mesh = trimesh.load(io.BytesIO(payloads[mesh_ref.artifact_uri]), file_type="glb", force="mesh")
    np.testing.assert_allclose(mesh.bounds.mean(axis=0), 0, atol=0.03)
    # Closing/dilation expands the two sides by up to about 0.08 m on this grid.
    np.testing.assert_allclose(mesh.extents, [0.32, 0.24, 0.4], atol=0.1)
    assert mesh.extents[0] > mesh.extents[1]


def test_full_build_rejects_zero_part_collider_before_environment(
    draft_scene: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.scene import object_geometry_build as module
    from src.services.orchestration.scene import objectify

    def run(python: Path, script: Path, request: dict, *args: object, **kwargs: object) -> dict:
        assert script == objectify.CONVEX_RUNNER
        return {"objects": [{"id": item["id"], "parts": 0} for item in request["objects"]]}

    monkeypatch.setattr(objectify, "_run", run)
    with pytest.raises(module.ObjectGeometryBuildError, match="Gaussian shell collider generation failed"):
        build(draft_scene)
    assert draft_scene.registry.scene.current(draft_scene.job_id).scene == draft_scene.scene


RUNTIME = Path(__file__).resolve().parents[2] / "data/scene_runtime/bin/python"


@pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated CoACD runtime data/scene_runtime is not installed")
def test_real_coacd_builds_ready_scene(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.scene import objectify

    fake_run = objectify._run

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, *args: object, **kwargs: object
    ) -> dict:
        provider = cpu_providers.real_run if name == "convex" else fake_run
        return provider(python, script, request, workspace, name, *args, **kwargs)

    monkeypatch.setattr(objectify, "_run", run)
    build(draft_scene)
    scene = draft_scene.registry.scene.current(draft_scene.job_id).scene
    assert scene.provenance["object_geometry"] == "ready"
    for item in scene.objects:
        assert 0 < item.collider.parameters["parts"] <= 8


@pytest.mark.skipif(not RUNTIME.is_file(), reason="isolated CoACD runtime data/scene_runtime is not installed")
def test_open_bottom_shell_real_coacd_budget_and_bounds(
    tmp_path: Path, record_property: Callable[[str, object], None]
) -> None:
    import time

    import numpy as np
    import trimesh

    from src.services.orchestration.artifacts import sha256_bytes
    from src.services.orchestration.scene.object_geometry_steps import SurfaceInput, run_surface_colliders
    from src.services.scene.gaussian_shell import ShellParams, build_gaussian_shell
    from tests.test_scene.test_gaussian_shell import BOX_HIGH, BOX_LOW, open_face_points

    points = open_face_points(np.random.default_rng(19), BOX_LOW, BOX_HIGH, 20000, axis=2, side=0)
    params = ShellParams()
    shell = build_gaussian_shell(points, None, params)
    source_mesh = trimesh.Trimesh(shell.vertices, shell.faces, process=False)
    payload = source_mesh.export(file_type="glb")
    path = tmp_path / "shell.glb"
    path.write_bytes(payload)
    output = tmp_path / "collider.glb"
    maximum = 8
    started = time.perf_counter()
    result = run_surface_colliders(
        RUNTIME,
        [SurfaceInput("open-bottom", path, sha256_bytes(payload), output)],
        {"max_convex_hull": maximum},
        tmp_path,
        120,
        None,
        surface_label="Gaussian shell",
    )
    elapsed = time.perf_counter() - started
    parts = result["open-bottom"]["parts"]
    collider = trimesh.load(output, force="mesh")
    np.testing.assert_allclose(collider.bounds, source_mesh.bounds, atol=2 * params.voxel_m)
    assert 0 < parts <= maximum
    record_property("coacd_parts", parts)
    record_property("coacd_seconds", elapsed)
    record_property("solidity", shell.statistics["solidity"])
    print(
        f"open-bottom: CoACD parts={parts}/{maximum}, elapsed={elapsed:.3f}s, solidity={shell.statistics['solidity']:.6f}"
    )


def test_missing_source_ownership_is_bound_to_extraction_pose(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace
) -> None:
    original = draft_scene.scene.objects[0]
    moved = original.model_copy(
        update={
            "source_collision": None,
            "transform": original.transform.model_copy(update={"translation_xyz": (20, 30, 40)}),
        }
    )
    draft_scene.scene = draft_scene.registry.scene.publish_next(
        draft_scene.job_id,
        draft_scene.scene.scene_revision,
        draft_scene.scene.model_copy(update={"objects": [moved, draft_scene.scene.objects[1]]}),
        "fixture-no-ownership",
    ).revision.scene
    build(draft_scene)
    scene = draft_scene.registry.scene.current(draft_scene.job_id).scene
    assert scene.objects[0].transform == moved.transform
    assert scene.objects[0].source_collision.source_transform == original.transform
    assert (
        scene.objects[0].source_collision.extraction_revision
        == draft_scene.scene.environment.membership.extraction_revision
    )


@pytest.mark.parametrize("review", ["IGNORED", "DELETED"])
def test_reviewed_build_composes_source_collision_and_restores_deleted_object(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, review: str
) -> None:
    import numpy as np
    import trimesh

    from src.models.contracts.scene import SceneIR, SceneObjectState
    from src.services.orchestration.scene.objects import apply_object_action
    from src.services.scene.effective_collision import CarvedBackground, compose_effective_collision

    first, second = draft_scene.scene.objects
    reviewed = first.model_copy(
        update={
            "provenance": {**first.provenance, "review": review},
            "transform": first.transform.model_copy(update={"translation_xyz": (20, 30, 40)}),
        }
    )
    # A confirmed second object leaves only the first object's review-dependent source restoration.
    confirmed = second.model_copy(update={"state": SceneObjectState.CONFIRMED, "active": True})
    draft_scene.scene = draft_scene.registry.scene.publish_next(
        draft_scene.job_id,
        draft_scene.scene.scene_revision,
        draft_scene.scene.model_copy(update={"objects": [reviewed, confirmed]}),
        "fixture-reviewed-draft",
    ).revision.scene
    build(draft_scene)
    scene = draft_scene.registry.scene.current(draft_scene.job_id).scene
    resolve = draft_scene.registry.runtime_resolver.require
    source_ref = scene.environment.geometry_ref
    source_payload = resolve(source_ref).read_bytes()
    baseline = trimesh.load(resolve(scene.environment.collider_ref), force="mesh", process=False)
    collider = trimesh.load(resolve(scene.objects[0].collider.geometry_ref), force="mesh", process=False)

    def compose(value: SceneIR) -> CarvedBackground:
        return compose_effective_collision(value, source_ref, source_payload, lambda ref: resolve(ref).read_bytes())

    def assert_source_restored(result: CarvedBackground) -> None:
        assert len(result.faces) == len(baseline.faces) + len(collider.faces)
        restored_points = result.vertices[result.faces[len(baseline.faces) :]].reshape(-1, 3)
        # The immutable source pose wins over the edited pose at (20, 30, 40).
        expected_bounds = collider.bounds + np.asarray(first.source_collision.source_transform.translation_xyz)
        np.testing.assert_allclose(
            [restored_points.min(axis=0), restored_points.max(axis=0)], expected_bounds, atol=1e-6
        )

    result = compose(scene)
    if review == "IGNORED":
        assert_source_restored(result)
    else:
        assert len(result.faces) == len(baseline.faces)
        np.testing.assert_allclose(result.vertices[result.faces], baseline.vertices[baseline.faces])
        restored = apply_object_action(
            draft_scene.registry.scene, draft_scene.job_id, first.id, "restore", scene.scene_revision
        ).revision.scene
        assert restored.objects[0].collider == scene.objects[0].collider
        assert_source_restored(compose(restored))


def test_explicit_object_ids_build_only_requested_reviewed_objects(
    draft_scene: SimpleNamespace, cpu_providers: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.scene import object_geometry_build as module

    first, second = draft_scene.scene.objects
    ignored = first.model_copy(update={"provenance": {**first.provenance, "review": "IGNORED"}})
    draft_scene.scene = draft_scene.registry.scene.publish_next(
        draft_scene.job_id,
        draft_scene.scene.scene_revision,
        draft_scene.scene.model_copy(update={"objects": [ignored, second]}),
        "fixture-ignored",
    ).revision.scene
    build(draft_scene)
    draft_scene.scene = draft_scene.registry.scene.current(draft_scene.job_id).scene
    build_shell = module._build_shell
    seen = []

    def shell(item: module.SceneObject, *args: object, **kwargs: object) -> tuple:
        seen.append(item.id)
        return build_shell(item, *args, **kwargs)

    monkeypatch.setattr(module, "_build_shell", shell)
    build(draft_scene, object_ids={first.id})
    current = draft_scene.registry.scene.current(draft_scene.job_id).scene
    assert seen == [first.id]
    assert current.provenance["geometry_build"]["built_object_ids"] == [first.id]
    assert current.objects[0].provenance["review"] == "IGNORED"
    assert current.objects[0].collider is not None
    assert current.objects[1] == draft_scene.scene.objects[1]
