"""ObjectGS build: observations are immutable, masks follow current labels, and failures never fall back silently."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.services.orchestration.scene.objectgs_observations import package_observations, unpack_observations
from tests.test_scene.test_object_geometry_build import draft_scene  # noqa: F401  (pytest fixture)


def view(root: Path, index: int, width: int = 16, height: int = 12) -> dict:
    image = root / f"frame-{index}.png"
    mask = root / f"mask-{index}.npy"
    image.write_bytes(b"png-%d" % index)
    np.save(mask, np.full((height, width), index, dtype=np.int32), allow_pickle=False)
    return {
        "image_path": str(image),
        "mask_path": str(mask),
        "width": width,
        "height": height,
        "center": [0.0, 0.0, 1.0],
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "parameters": [10.0, 10.0, 8.0, 6.0],
        "camera_model": "PINHOLE",
        "coordinate_frame": "world",
        "distance_unit": "m",
    }


def test_package_is_byte_stable_and_round_trips_views_in_order(tmp_path: Path) -> None:
    views = [view(tmp_path, 0), view(tmp_path, 1)]
    payload = package_observations(views)
    assert package_observations(views) == payload
    restored = unpack_observations(payload, tmp_path / "restored")
    assert [Path(item["image_path"]).read_bytes() for item in restored] == [b"png-0", b"png-1"]
    assert int(np.load(restored[1]["mask_path"], allow_pickle=False).max()) == 1
    assert restored[0]["model"] == "PINHOLE"
    assert restored[0]["parameters"] == [10.0, 10.0, 8.0, 6.0]


def test_empty_observation_list_is_a_valid_package(tmp_path: Path) -> None:
    assert unpack_observations(package_observations([]), tmp_path / "empty") == []


def test_undeclared_or_escaping_members_are_rejected(tmp_path: Path) -> None:
    payload = package_observations([view(tmp_path, 0)])
    tampered = io.BytesIO()
    with tarfile.open(fileobj=tampered, mode="w") as archive:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as source:
            for member in source.getmembers():
                archive.addfile(member, source.extractfile(member))
        extra = tarfile.TarInfo("../escape.txt")
        extra.size = 1
        archive.addfile(extra, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        unpack_observations(tampered.getvalue(), tmp_path / "restored")


GRID_ROWS_PER_OBJECT = 9 * 11 * 13


def _sha(payload: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@pytest.fixture
def objectgs(draft_scene, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:  # noqa: F811 (pytest fixture chain)
    """A Draft scene with an ObjectGS observation package and fake runners; no GPU, no real ObjectGS."""
    import trimesh

    from src.models.contracts.manifests import StageId
    from src.services.orchestration.artifacts import FilesystemArtifactStore
    from src.services.orchestration.scene import object_geometry_build as module
    from src.services.orchestration.scene import objectify
    from src.services.orchestration.scene.objectify import _reference

    registry, job_id = draft_scene.registry, draft_scene.job_id
    store = FilesystemArtifactStore(registry.runtime_resolver)
    calls = SimpleNamespace(convex=[], correction=[], objectgs=[], failing=set())
    tmp_path = draft_scene.workspace.parent
    views_dir = tmp_path / "lift-views"
    views_dir.mkdir()
    views = []
    for index in range(2):
        image = views_dir / f"view-{index}.png"
        mask = views_dir / f"view-{index}.labels.npy"
        image.write_bytes(b"rgb-%d" % index)
        # Extraction-time labels are stale on purpose: the build must not reuse them.
        np.save(mask, np.zeros((12, 16), dtype=np.int32), allow_pickle=False)
        views.append(
            {
                "image_path": str(image),
                "mask_path": str(mask),
                "width": 16,
                "height": 12,
                "center": [0.0, 0.0, 1.0],
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "parameters": [10.0, 10.0, 8.0, 6.0],
                "camera_model": "PINHOLE",
                "coordinate_frame": "world",
                "distance_unit": "m",
            }
        )
    payload = package_observations(views)
    observations_ref = _reference(
        job_id, "objects/observations/{digest}.tar", "ObjectGSObservations", StageId.SCENE_DECOMPOSE, payload
    )
    store.publish(observations_ref, payload)

    def publish_draft_provenance(observations: object) -> object:
        scene = registry.scene.current(job_id).scene
        provenance = {**scene.provenance, "geometry_method": "objectgs", "objectgs_observations_ref": observations}
        return registry.scene.publish_next(
            job_id, scene.scene_revision, scene.model_copy(update={"provenance": provenance}), "fixture-objectgs"
        ).revision.scene

    scene = publish_draft_provenance(observations_ref.model_dump(mode="json"))
    monkeypatch.setattr(
        module,
        "load_job_config",
        lambda *args: SimpleNamespace(
            scene={"geometry_method": "objectgs", "coacd_max_convex_hull": 8, "inpaint_max_new_gaussians": 100}
        ),
        raising=False,
    )
    settings = draft_scene.settings.model_copy(
        update={
            "product_objectgs_runtime_python": tmp_path / "objectgs-python",
            "product_objectgs_repository": tmp_path / "objectgs-repo",
            "product_objectgs_gsplat_repository": tmp_path / "gsplat-repo",
        }
    )

    def run(python: Path, script: Path, request: dict, workspace: Path, name: str, *args: object, **kwargs: object):
        if name == "inpaint":
            Path(request["output_ply"]).write_bytes(Path(request["background_ply"]).read_bytes())
            return {"method": "fixture", "original_gaussians": 0, "inpainted_gaussians": 0}
        if name == "correction-observations":
            calls.correction.append(request)
            labels = np.frombuffer(Path(request["labels_path"]).read_bytes(), dtype="<i4")
            output = Path(request["output_dir"])
            output.mkdir(parents=True, exist_ok=False)
            masks, objectgs_views = [], []
            left, right = int(labels[0]), int(labels[GRID_ROWS_PER_OBJECT])
            for number, view in enumerate(request["views"]):
                mask = np.full((view["height"], view["width"]), right, dtype=np.int32)
                mask[:, : view["width"] // 2] = left
                image_path = output / f"{number:06d}.png"
                mask_path = output / f"{number:06d}.npy"
                image_path.write_bytes(Path(view["image_path"]).read_bytes())
                np.save(mask_path, mask, allow_pickle=False)
                masks.append(mask)
                objectgs_views.append(
                    {
                        "image_path": str(image_path),
                        "mask_path": str(mask_path),
                        "width": view["width"],
                        "height": view["height"],
                        "center": view["center"],
                        "rotation_xyzw": view["rotation_xyzw"],
                        "parameters": view["parameters"],
                        "camera_model": "PINHOLE",
                        "coordinate_frame": "world",
                        "distance_unit": "m",
                    }
                )
            counts = {str(label): len(masks) for label in request["label_to_object_id"]}
            return {"views": len(masks), "masks_per_object": counts, "objectgs_views": objectgs_views}
        calls.convex.append(request)
        result = []
        for item in request["objects"]:
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

    def fake_objectgs(
        request,
        *,
        cancel_event=None,
        progress=None,
        evidence_dir=None,
        surface_artifact_callback=None,
        raise_on_quality_failure=True,
    ):
        calls.objectgs.append(request)
        if calls.fail is not None:
            raise calls.fail
        receipt = fake_receipt(request, surface_artifact_callback, tmp_path / "objectgs-output", calls.failing)
        if raise_on_quality_failure and any(not item["quality_passed"] for item in receipt["objects"].values()):
            raise RuntimeError("ObjectGS surface quality gate failed")
        return receipt

    calls.fail = None
    monkeypatch.setattr(module, "run_prepared_objectgs", fake_objectgs)
    return SimpleNamespace(
        draft=draft_scene,
        registry=registry,
        job_id=job_id,
        settings=settings,
        scene=scene,
        calls=calls,
        store=store,
        tmp_path=tmp_path,
        publish_draft_provenance=publish_draft_provenance,
    )


def fake_receipt(request, surface_artifact_callback, workspace: Path, failing: set[str]) -> dict:
    """Shaped like `run_prepared_objectgs`: per-object QA reports and surfaces, all accepted."""
    workspace.mkdir(parents=True, exist_ok=True)
    checkpoint = workspace / "objectgs-checkpoint.tar.gz"
    checkpoint.write_bytes(b"fixture checkpoint")
    dataset = workspace / "objectgs-dataset.tar.gz"
    dataset.write_bytes(b"fixture dataset")
    import trimesh

    objects = {}
    for label, object_id in enumerate(sorted(set(request.membership.label_to_object_id.values())), start=1):
        raw = trimesh.creation.box(extents=(0.2, 0.3, 0.4)).export(file_type="glb")
        surface = trimesh.creation.box(extents=(0.22, 0.32, 0.42)).export(file_type="glb")
        raw_path = workspace / f"label-{label}-raw.glb"
        raw_path.write_bytes(raw)
        surface_path = workspace / f"label-{label}.glb"
        surface_path.write_bytes(surface)
        quality = {
            "object_id": object_id,
            "passed": object_id not in failing,
            "reasons": [] if object_id not in failing else ["open_boundary"],
            "source_checksum": _sha(raw),
            "result_checksum": _sha(surface),
            "inferred_faces": 0,
        }
        repair = {"object_id": object_id, "source_checksum": _sha(raw), "result_checksum": _sha(surface)}
        reports = {}
        for kind, report in (("quality_report", quality), ("repair_report", repair)):
            report_path = workspace / f"label-{label}-{kind}.json"
            payload = json.dumps(report, sort_keys=True).encode()
            report_path.write_bytes(payload)
            reports[kind + "_path"] = str(report_path)
            reports[kind + "_checksum"] = _sha(payload)
        item = {
            "label": label,
            "path": str(surface_path),
            "checksum": _sha(surface),
            "raw_path": str(raw_path),
            "raw_checksum": _sha(raw),
            "vertex_count": 8,
            "triangle_count": 12,
            "watertight": True,
            "quality_passed": object_id not in failing,
            "quality_reasons": [] if object_id not in failing else ["open_boundary"],
            "producer_provenance": {"fixture": True},
            **reports,
        }
        if surface_artifact_callback is not None:
            item["evidence_refs"] = surface_artifact_callback(object_id, item)
        objects[object_id] = item
    return {
        "upstream_commit": "a" * 40,
        "gsplat_commit": "b" * 40,
        "glm_commit": None,
        "config_checksum": "sha256:" + "c" * 64,
        "export_config": {},
        "runtime": {"fixture": True},
        "coordinate_frame": "object_local",
        "distance_unit": "m",
        "source_membership": request.membership.model_dump(mode="json"),
        "source_poses": {key: pose.model_dump(mode="json") for key, pose in request.source_poses.items()},
        "checkpoint_path": str(checkpoint),
        "checkpoint_checksum": _sha(checkpoint.read_bytes()),
        "dataset_path": str(dataset),
        "dataset_checksum": _sha(dataset.read_bytes()),
        "objects": objects,
    }


def build_objectgs(fixture: SimpleNamespace, **kwargs: object) -> str:
    from src.services.orchestration.scene.object_geometry_build import build_object_geometry

    return build_object_geometry(
        fixture.registry,
        fixture.settings,
        fixture.job_id,
        expected_revision=fixture.scene.scene_revision,
        workspace=fixture.tmp_path / "build",
        **kwargs,
    )


def test_objectgs_only_trains_selected_objects_and_preserves_original_membership(objectgs: SimpleNamespace) -> None:
    from src.services.scene.editing.commands import ignore_object

    source_membership = objectgs.scene.environment.membership
    reviewed = ignore_object(objectgs.scene, "candidate-001")
    objectgs.scene = objectgs.registry.scene.publish_next(
        objectgs.job_id, objectgs.scene.scene_revision, reviewed, "fixture-keep-window"
    ).revision.scene
    build_objectgs(objectgs)
    request = objectgs.calls.objectgs[0]
    assert request.membership.label_to_object_id == {"2": "candidate-002"}
    labels = np.frombuffer(request.source_labels.read_bytes(), dtype="<i4")
    assert set(labels) == {-1, 2}
    ready = objectgs.registry.scene.current(objectgs.job_id).scene
    assert ready.environment.membership == source_membership
    assert ready.objects[0].collider is None
    assert ready.objects[1].collider is not None


def test_objectgs_build_uses_objectgs_surfaces_and_publishes_evidence(objectgs: SimpleNamespace) -> None:
    from src.models.contracts.artifacts import ProductArtifactRef
    from src.models.contracts.object_geometry import ObjectSurfaceManifest

    phases: list[str] = []
    revision = build_objectgs(objectgs, progress=phases.append)
    scene = objectgs.registry.scene.current(objectgs.job_id).scene
    assert scene.scene_revision == revision != objectgs.scene.scene_revision
    assert phases == ["shell", "objectgs", "quality", "collider", "environment", "publish"]
    assert len(objectgs.calls.objectgs) == 1 and len(objectgs.calls.objectgs[0].views) == 2
    surfaces = {item["surface_mesh"] for item in objectgs.calls.convex[0]["objects"]}
    assert len(surfaces) == 2 and all("label-" in path for path in surfaces)
    for item in scene.objects:
        assert item.provenance["surface_selection"] == {"chosen": "objectgs"}
        assert item.surface_mesh_ref.artifact_type == "ObjectSurfaceMesh"
        assert item.collider.provenance["surface_origin"] == "objectgs_v1"
        manifest_ref = ProductArtifactRef.model_validate(item.provenance["objectgs_surface_manifest_ref"])
        manifest = ObjectSurfaceManifest.model_validate_json(
            objectgs.registry.runtime_resolver.require(manifest_ref).read_bytes()
        )
        assert manifest.quality["passed"] is True
        evidence = item.provenance["objectgs_evidence"]["surface_evidence"]
        assert {"surface", "quality_report", "repair_report", "raw"} <= set(evidence)


def test_global_objectgs_failure_keeps_scene_and_builds_no_colliders(objectgs: SimpleNamespace) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError

    objectgs.calls.fail = RuntimeError("ObjectGS train exited with status 1")
    before = objectgs.registry.scene.current(objectgs.job_id).scene
    with pytest.raises(ObjectGeometryBuildError, match="ObjectGS"):
        build_objectgs(objectgs)
    assert objectgs.registry.scene.current(objectgs.job_id).scene == before
    assert objectgs.calls.convex == []


def test_missing_objectgs_runtime_fails_before_touching_the_scene(objectgs: SimpleNamespace) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError

    objectgs.settings = objectgs.settings.model_copy(
        update={"product_objectgs_runtime_python": None, "product_objectgs_repository": None}
    )
    before = objectgs.registry.scene.current(objectgs.job_id).scene
    with pytest.raises(ObjectGeometryBuildError, match="runtime"):
        build_objectgs(objectgs)
    assert objectgs.registry.scene.current(objectgs.job_id).scene == before
    assert objectgs.calls.objectgs == [] and objectgs.calls.correction == []


def test_masks_handed_to_objectgs_follow_the_current_labels(objectgs: SimpleNamespace) -> None:
    from PIL import Image

    from src.models.contracts.manifests import StageId
    from src.services.orchestration.scene.objectify import _reference

    registry, job_id = objectgs.registry, objectgs.job_id
    scene = registry.scene.current(job_id).scene
    membership = scene.environment.membership
    labels = np.frombuffer(
        objectgs.registry.runtime_resolver.require(membership.labels_ref).read_bytes(), dtype="<i4"
    ).copy()
    row = int(np.flatnonzero(labels == 0)[0])
    labels[row] = 2  # Draft edit: move one candidate-001 row to candidate-002
    payload = labels.astype("<i4").tobytes()
    labels_ref = objectgs.store.publish(
        _reference(job_id, "test-relabel/{digest}.i32le", "ObjectMembershipLabels", StageId.SCENE_DECOMPOSE, payload),
        payload,
    )
    edited = scene.model_copy(
        update={
            "environment": scene.environment.model_copy(
                update={"membership": membership.model_copy(update={"labels_ref": labels_ref})}
            )
        }
    )
    registry.scene.publish_next(job_id, scene.scene_revision, edited, "fixture-relabel")
    objectgs.scene = registry.scene.current(job_id).scene
    build_objectgs(objectgs)
    masks = [np.asarray(Image.open(view.mask_path)) for view in objectgs.calls.objectgs[0].views]
    assert objectgs.calls.correction and objectgs.calls.correction[0]["labels_path"]
    # Edited row sits in the left half of view 0, which must now carry the new owner's compact id (2).
    assert np.all(masks[0][:, :8] == 2)
    assert not np.any(masks[0] == 1), "stale extraction-time masks were reused"


def test_shell_geometry_never_calls_objectgs(objectgs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.scene import object_geometry_build as module

    monkeypatch.setattr(
        module,
        "load_job_config",
        lambda *args: SimpleNamespace(scene={"geometry_method": "shell", "coacd_max_convex_hull": 8}),
        raising=False,
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("shell geometry called ObjectGS")

    monkeypatch.setattr(module, "run_prepared_objectgs", forbidden)
    build_objectgs(objectgs)
    scene = objectgs.registry.scene.current(objectgs.job_id).scene
    assert all(item.provenance["surface_selection"] == {"chosen": "gaussian_shell"} for item in scene.objects)


@pytest.mark.parametrize("damage", ["checksum", "missing"])
def test_damaged_observation_reference_fails_before_objectgs(objectgs: SimpleNamespace, damage: str) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError

    reference = objectgs.scene.provenance["objectgs_observations_ref"]
    if damage == "checksum":
        objectgs.scene = objectgs.publish_draft_provenance({**reference, "artifact_checksum": "sha256:" + "0" * 64})
    else:
        objectgs.scene = objectgs.publish_draft_provenance(None)
    with pytest.raises(ObjectGeometryBuildError, match="(?i)quan sát"):
        build_objectgs(objectgs)
    assert objectgs.calls.objectgs == []


def test_objectgs_build_rejects_partial_object_ids(objectgs: SimpleNamespace) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError

    with pytest.raises(ObjectGeometryBuildError, match="toàn bộ"):
        build_objectgs(objectgs, object_ids={"candidate-001"})
    assert objectgs.calls.objectgs == []


def test_failing_objectgs_surface_falls_back_to_its_shell_with_a_recorded_reason(objectgs: SimpleNamespace) -> None:
    objectgs.calls.failing = {"candidate-002"}
    build_objectgs(objectgs)
    scene = objectgs.registry.scene.current(objectgs.job_id).scene
    accepted = next(item for item in scene.objects if item.id == "candidate-001")
    fallback = next(item for item in scene.objects if item.id == "candidate-002")
    assert accepted.provenance["surface_selection"] == {"chosen": "objectgs"}
    assert accepted.surface_mesh_ref.artifact_type == "ObjectSurfaceMesh"
    assert accepted.collider.provenance["surface_origin"] == "objectgs_v1"
    assert "objectgs_surface_manifest_ref" in accepted.provenance
    assert fallback.provenance["surface_selection"] == {
        "chosen": "gaussian_shell",
        "reason": "objectgs_quality_failed",
        "quality_reasons": ["open_boundary"],
    }
    assert fallback.surface_mesh_ref.artifact_type == "ObjectShellMesh"
    assert fallback.collider.provenance["surface_origin"] == "gaussian_shell_v1"
    assert "objectgs_surface_manifest_ref" not in fallback.provenance
    evidence = fallback.provenance["objectgs_evidence"]["surface_evidence"]
    assert {"raw", "quality_report", "repair_report", "surface"} <= set(evidence)
    paths = [item["surface_mesh"] for request in objectgs.calls.convex for item in request["objects"]]
    assert any(path.endswith("label-1.glb") for path in paths)
    assert any(path.endswith("candidate-002-shell.glb") for path in paths)


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (RuntimeError("CUDA out of memory while training"), True),
        (OSError("disk full while writing the checkpoint"), True),
        (ValueError("ObjectGS receipt does not bind the job"), False),
    ],
)
def test_global_objectgs_errors_offer_shell_and_say_whether_to_retry(
    objectgs: SimpleNamespace, error: Exception, retryable: bool
) -> None:
    from src.services.orchestration.scene.object_geometry_build import ObjectGeometryBuildError

    objectgs.calls.fail = error
    before = objectgs.registry.scene.current(objectgs.job_id).scene
    with pytest.raises(ObjectGeometryBuildError) as raised:
        build_objectgs(objectgs)
    assert raised.value.retryable is retryable
    assert "geometry_method" in str(raised.value) and "shell" in str(raised.value)
    assert objectgs.registry.scene.current(objectgs.job_id).scene == before
    assert objectgs.calls.convex == []


def test_cancelled_objectgs_run_propagates_and_keeps_the_scene(objectgs: SimpleNamespace) -> None:
    from src.services.process_control import ProcessCancelledError

    objectgs.calls.fail = ProcessCancelledError("cancelled by the operator")
    before = objectgs.registry.scene.current(objectgs.job_id).scene
    with pytest.raises(ProcessCancelledError):
        build_objectgs(objectgs)
    assert objectgs.registry.scene.current(objectgs.job_id).scene == before
