"""Draft geometry publication is fenced; failed builds never replace the active scene."""

from __future__ import annotations

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
    from src.models.contracts.scene import SceneEnvironment, SceneObject, SceneObjectOrigin, SceneObjectState
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
        product_scene_runtime_python=Path("data/scene_runtime/bin/python").resolve(), product_sam2_checkpoint=None
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
