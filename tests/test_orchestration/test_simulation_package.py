"""Tạo gói mô phỏng từ SceneIR: khoét môi trường, collider hộp, preflight, đóng gói, tải zip.

Fixture proof (bundle mẫu + collision mesh tổng hợp); không phải bằng chứng physics Isaac.
"""

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.config import Settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import ColliderType, SceneObjectState
from src.models.contracts.validation import RuleResult
from src.services.orchestration.review import simulation_package as simulation_package_service
from src.services.orchestration.review.simulation_package import BUILD_CONFIG, build_simulation_package, current_package
from src.services.orchestration.scene.errors import ObjectGeometryNotReadyError
from src.services.orchestration.scene.extraction import extract_scene
from src.services.orchestration.scene.objects import add_box_object, add_catalog_object, apply_object_action
from src.services.scene.collision_ownership import SourceCollisionOwnershipError
from src.services.scene.editing.commands import move_object
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.usd.capabilities import ExportCapabilityStatus
from tests.test_orchestration.test_finalize_flow import _confirmed
from tests.test_orchestration.test_scene_extraction import _FIXTURE, _collision

SCENE_RUNTIME = Path("data/scene_runtime/bin/python")


def _scene_job(tmp_path: Path):  # noqa: ANN202
    registry, job, _ = _confirmed(tmp_path)
    text = _FIXTURE.read_text(encoding="utf-8").replace("job-fixture-001", job.job_id)
    bundle = ReconstructionBundle.model_validate_json(text)
    bundle = bundle.model_copy(update={"canonical_geometry_ref": _collision(registry, job.job_id)})
    settings = Settings(product_scene_runtime_python=None, product_sam2_checkpoint=None)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    return registry, job


def test_simulation_package_does_not_fall_back_from_selected_collision_source(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    source_ref = ProductArtifactRef(
        artifact_type="LidarCollisionCandidate",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/collision/lidar-candidate.glb",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        producer_stage="ST-CANDIDATE-BUILD",
        job_id=job.job_id,
    )
    selection_ref = ProductArtifactRef(
        artifact_type="CollisionSourceSelection",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/collision/selection.json",
        artifact_checksum="sha256:" + "b" * 64,
        data_class="derived",
        producer_stage="ST-CANDIDATE-BUILD",
        job_id=job.job_id,
    )
    selected_scene = scene.model_copy(
        update={
            "environment": scene.environment.model_copy(
                update={"collision_source_ref": source_ref, "collision_selection_ref": selection_ref}
            )
        }
    )

    with pytest.raises(SourceCollisionOwnershipError, match="refusing to fall back"):
        simulation_package_service._carved_environment(registry, selected_scene)


def test_confirmed_objects_become_a_sealed_package(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (pallet,) = scene.objects
    apply_object_action(registry.scene, job.job_id, pallet.id, "confirm", scene.scene_revision)

    package = build_simulation_package(registry, job.job_id)

    assert package.preflight.blocking_result == RuleResult.PASS
    assert package.source_scene_revision == "rev-002" and package.scene_revision == "rev-003"
    assert package.confirmed_objects == 1 and package.carved_triangles > 0
    physics = registry.scene.current(job.job_id).scene
    assert physics.objects[0].collider is not None and physics.environment.collider_ref is not None
    archive = zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(package.package_ref).read_bytes()))
    background_identity = physics.provenance["collision_background_identity"]
    assert background_identity in archive.read("README.txt").decode()
    build_config = {**BUILD_CONFIG, "collision_background_identity": background_identity}
    expected_config_checksum = (
        "sha256:"
        + hashlib.sha256(json.dumps(build_config, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    )
    manifest = json.loads(archive.read("candidate_manifest.json"))
    assert manifest["build_config_checksum"] == expected_config_checksum
    names = set(archive.namelist())
    assert {
        "scene.usda",
        "environment_collision.usda",
        "candidate_manifest.json",
        "preflight_report.json",
        "export_capability.json",
    } <= names
    capability = json.loads(archive.read("export_capability.json"))
    assert capability["status"] == "supported" and capability["effective_mode"] == "legacy_box"
    assert capability["builder_version"] == "usd-export-capabilities-v3"
    usda = archive.read("scene.usda").decode()
    assert "prepend references = @./environment_collision.usda@" in usda and "GroundPlane" in usda
    # Gọi lại trên cùng revision: trả gói cũ, không tạo revision mới.
    again = build_simulation_package(registry, job.job_id)
    assert again.package_ref == package.package_ref
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-003"
    assert current_package(registry, job.job_id) == package


def test_draft_scene_refuses_usd_export_before_recovery_or_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    current = registry.scene.current(job.job_id)
    draft = current.scene.model_copy(
        update={"provenance": {**current.scene.provenance, "object_geometry": "awaiting_review"}}
    )
    monkeypatch.setattr(registry.scene, "current", lambda job_id: current.model_copy(update={"scene": draft}))

    with pytest.raises(ObjectGeometryNotReadyError, match="Cần tạo mesh trước khi xuất USD."):
        build_simulation_package(registry, job.job_id)


def _neighbour_candidate(item, new_id: str):  # noqa: ANN001, ANN202
    """A pending candidate whose source box coincides with `item`'s (as adjacent extracted objects often overlap)."""
    assert item.source_collision is not None
    source = item.source_collision.model_copy(
        update={
            "object_id": new_id,
            "source_transform": item.source_collision.source_transform.model_copy(update={"local_frame": new_id}),
        }
    )
    return item.model_copy(
        update={
            "id": new_id,
            "name": new_id,
            "local_frame": new_id,
            "transform": item.transform.model_copy(update={"local_frame": new_id}),
            "collider": None,
            "source_collision": source,
        },
        deep=True,
    )


def test_overlap_with_a_pending_candidate_no_longer_blocks_export_and_is_reported(tmp_path: Path) -> None:
    """Adjacent extracted objects overlap; confirming one must not fail the export or silently drop a neighbour."""
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (pallet,) = scene.objects
    with_neighbour = scene.model_copy(update={"objects": [pallet, _neighbour_candidate(pallet, "candidate-neighbour")]})
    published = registry.scene.publish_next(job.job_id, scene.scene_revision, with_neighbour, "test_add_neighbour")
    apply_object_action(registry.scene, job.job_id, pallet.id, "confirm", published.revision.scene.scene_revision)

    package = build_simulation_package(registry, job.job_id)

    assert package.preflight.blocking_result == RuleResult.PASS and package.package_ref is not None
    assert package.retained_shared_object_ids == ["candidate-neighbour"]
    assert package.retained_shared_triangles > 0 and package.carved_triangles == 0
    assert current_package(registry, job.job_id) == package
    archive = zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(package.package_ref).read_bytes()))
    readme = archive.read("README.txt").decode()
    assert "candidate-neighbour" in readme and f"{package.retained_shared_triangles:,}" in readme

    # Confirming the neighbour as well resolves the ambiguity: both regions leave the background.
    current = registry.scene.current(job.job_id).scene
    apply_object_action(registry.scene, job.job_id, "candidate-neighbour", "confirm", current.scene_revision)
    resolved = build_simulation_package(registry, job.job_id)
    assert resolved.retained_shared_triangles == 0 and resolved.retained_shared_object_ids == []
    assert resolved.carved_triangles > 0


def test_failed_preflight_reports_without_new_revision(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    # Vật cản đặt chìm dưới sàn → OBJECT_OUT_OF_BOUNDS chặn đóng gói.
    add_box_object(registry.scene, job.job_id, scene.scene_revision, "Chìm", (0.5, 0.5, 0.5), (1.0, 1.0, -1.0))

    package = build_simulation_package(registry, job.job_id)

    assert package.preflight.blocking_result == RuleResult.FAIL
    assert package.package_ref is None and package.candidate is None
    failed = [rule.rule_id for rule in package.preflight.rules if rule.result == RuleResult.FAIL]
    assert "OBJECT_OUT_OF_BOUNDS" in [str(rule) for rule in failed]
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-002"
    assert current_package(registry, job.job_id) is None


def test_unsupported_convex_export_returns_capability_block_without_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    enriched = enrich_scene_physics(scene)
    item = enriched.objects[0]
    collider = item.collider.model_copy(
        update={"collider_type": ColliderType.CONVEX_DECOMPOSITION, "geometry_ref": None, "dimensions_xyz_m": None}
    )
    draft = enriched.model_copy(
        update={
            "objects": [
                item.model_copy(update={"active": True, "state": SceneObjectState.CONFIRMED, "collider": collider})
            ]
        }
    )
    registry.scene.publish_next(job.job_id, scene.scene_revision, draft, "test_unsupported_convex")
    current_revision = registry.scene.current(job.job_id).scene.scene_revision
    monkeypatch.setattr(
        simulation_package_service,
        "get_settings",
        lambda: SimpleNamespace(product_scene_runtime_python=None),
    )

    package = build_simulation_package(registry, job.job_id)

    assert package.export_capability is not None
    assert package.export_capability.status == ExportCapabilityStatus.BLOCKED
    assert {issue.code for issue in package.export_capability.blockers} >= {
        "USD_RUNTIME_UNQUALIFIED",
        "COLLIDER_GEOMETRY_REF_MISSING",
    }
    assert package.candidate is None and package.package_ref is None
    assert registry.scene.current(job.job_id).scene.scene_revision == current_revision
    assert current_package(registry, job.job_id) is None


@pytest.mark.parametrize("failure_mode", ["runner_exception", "malformed_summary"])
def test_runner_failure_blocks_before_scene_revision_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_mode: str
) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    enriched = enrich_scene_physics(scene)
    item = enriched.objects[0]
    collider = item.collider.model_copy(
        update={
            "collider_type": ColliderType.CONVEX_DECOMPOSITION,
            "geometry_ref": scene.environment.geometry_ref,
            "dimensions_xyz_m": None,
        }
    )
    draft = enriched.model_copy(
        update={
            "objects": [
                item.model_copy(update={"active": True, "state": SceneObjectState.CONFIRMED, "collider": collider})
            ]
        }
    )
    registry.scene.publish_next(job.job_id, scene.scene_revision, draft, "test_hybrid_runner_failure")
    edited = registry.scene.current(job.job_id).scene
    apply_object_action(registry.scene, job.job_id, edited.objects[0].id, "confirm", edited.scene_revision)
    source_scene = registry.scene.current(job.job_id).scene
    assert source_scene.objects[0].collider is not None
    assert source_scene.objects[0].collider.collider_type == ColliderType.CONVEX_DECOMPOSITION
    runtime = tmp_path / "python"
    runtime.touch()
    monkeypatch.setattr(simulation_package_service, "_hybrid_runtime_python", lambda: runtime)
    monkeypatch.setattr(simulation_package_service, "_qualify_hybrid_runtime", lambda _python: (True, "26.8.0"))

    if failure_mode == "runner_exception":

        def failed_export(*_args: object, **_kwargs: object) -> dict[str, bytes]:
            raise ValueError("simulated invalid USD composition")

        monkeypatch.setattr(simulation_package_service, "_hybrid_layers", failed_export)
    else:

        def malformed_summary(command: list[str], **_kwargs: object) -> SimpleNamespace:
            result_path = Path(command[command.index("--result") + 1])
            result_path.write_text("[]", encoding="utf-8")
            return SimpleNamespace(returncode=0, stderr=b"")

        monkeypatch.setattr(simulation_package_service.subprocess, "run", malformed_summary)

    package = build_simulation_package(registry, job.job_id)

    assert package.export_capability is not None
    assert package.export_capability.status == ExportCapabilityStatus.BLOCKED
    assert [issue.code for issue in package.export_capability.blockers] == ["USD_EXPORT_FAILED"]
    assert package.candidate is None and package.package_ref is None
    assert registry.scene.current(job.job_id).scene.scene_revision == source_scene.scene_revision


def test_hybrid_zip_contains_verified_relative_asset_and_no_physics_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    item = scene.objects[0]
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", scene.scene_revision)
    scene = registry.scene.current(job.job_id).scene
    (item,) = scene.objects
    payload = b"""#usda 1.0
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
    digest = hashlib.sha256(payload).hexdigest()
    asset_ref = ProductArtifactRef(
        artifact_type="UsdAsset",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/assets/{digest}.usda",
        artifact_checksum=f"sha256:{digest}",
        data_class="derived",
        producer_stage="ST-ASSET-IMPORT",
        job_id=job.job_id,
    )
    registry.scene.store.publish(asset_ref, payload)
    with_asset = scene.model_copy(update={"objects": [item.model_copy(update={"asset_ref": asset_ref})]})
    registry.scene.publish_next(job.job_id, scene.scene_revision, with_asset, "test_add_usd_asset")
    runtime = Path("data/scene_runtime/bin/python")
    monkeypatch.setattr(
        simulation_package_service,
        "get_settings",
        lambda: Settings(product_scene_runtime_python=runtime, product_sam2_checkpoint=None),
    )

    package = build_simulation_package(registry, job.job_id)

    assert package.candidate is not None and package.package_ref is not None
    assert asset_ref in package.candidate.assets
    archive_bytes = registry.runtime_resolver.require(package.package_ref).read_bytes()
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    asset_path = f"assets/{digest}.usda"
    assert archive.read(asset_path) == payload
    assert "usd_export_summary.json" in archive.namelist()
    summary = json.loads(archive.read("usd_export_summary.json"))
    exported = next(obj for obj in summary["objects"] if obj["prim"] == item.id.replace("-", "_"))
    assert "physics" not in exported
    assert summary["external_assets"] == [
        {"prim": item.id.replace("-", "_"), "path": asset_path, "checksum": asset_ref.artifact_checksum}
    ]
    object_layer = next(name for name in archive.namelist() if name.startswith("objects/") and name.endswith(".usdc"))
    assert b"../assets/" in archive.read(object_layer)

    extracted = tmp_path / "unpacked"
    archive.extractall(extracted)
    inspection = subprocess.run(
        [
            str(runtime),
            "-c",
            "import json,sys; from pxr import Usd,UsdPhysics; s=Usd.Stage.Open(sys.argv[1]); p=s.GetPrimAtPath(sys.argv[2]); print(json.dumps({'stage': bool(s), 'asset': s.GetPrimAtPath(sys.argv[2] + '/Asset/Body').IsValid(), 'rigid': p.HasAPI(UsdPhysics.RigidBodyAPI), 'mass': p.HasAPI(UsdPhysics.MassAPI)}))",
            str(extracted / "scene.usda"),
            f"/World/Objects/{item.id.replace('-', '_')}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stage = json.loads(inspection.stdout)
    assert stage == {"stage": True, "asset": True, "rigid": False, "mass": False}


@pytest.mark.skipif(not SCENE_RUNTIME.is_file(), reason="cần runtime usd-core (data/scene_runtime)")
def test_catalog_asset_ships_as_its_box_with_provenance_instead_of_blocking_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A catalog asset's public URL cannot be sealed; the package keeps its box and says where the asset lives."""
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (pallet,) = scene.objects
    apply_object_action(registry.scene, job.job_id, pallet.id, "confirm", scene.scene_revision)
    current = registry.scene.current(job.job_id).scene
    add_catalog_object(registry.scene, job.job_id, current.scene_revision, "SM_BarelPlastic_A", (-1.5, -1.0, 0.0))
    scene = registry.scene.current(job.job_id).scene
    barrel = next(item for item in scene.objects if item.provenance.get("operation") == "add_catalog_asset")
    apply_object_action(registry.scene, job.job_id, barrel.id, "confirm", scene.scene_revision)
    monkeypatch.setattr(
        simulation_package_service,
        "get_settings",
        lambda: Settings(product_scene_runtime_python=SCENE_RUNTIME, product_sam2_checkpoint=None),
    )

    package = build_simulation_package(registry, job.job_id)

    assert package.preflight.blocking_result == RuleResult.PASS and package.package_ref is not None
    archive = zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(package.package_ref).read_bytes()))
    capability = json.loads(archive.read("export_capability.json"))
    assert capability["status"] == "supported" and capability["requirements"]["external_assets"] is False
    assert [(notice["code"], notice["affected_object_ids"]) for notice in capability["notices"]] == [
        ("CATALOG_ASSET_EXPORTED_AS_BOX", [barrel.id])
    ]
    assert (
        barrel.id in archive.read("README.txt").decode() and "real2sim:catalog" in archive.read("README.txt").decode()
    )
    summary = json.loads(archive.read("usd_export_summary.json"))
    exported = next(obj for obj in summary["objects"] if obj["prim"] == barrel.id.replace("-", "_"))
    expected = {"family": "SM_BarelPlastic_A", "asset_url": barrel.provenance["asset_url"]}
    assert exported["catalog"] == expected and summary["external_assets"] == []

    extracted = tmp_path / "unpacked"
    archive.extractall(extracted)
    inspection = subprocess.run(
        [
            str(SCENE_RUNTIME),
            "-c",
            "import json,sys; from pxr import Usd,UsdPhysics; s=Usd.Stage.Open(sys.argv[1]); p=s.GetPrimAtPath(sys.argv[2]); print(json.dumps({'catalog': p.GetCustomDataByKey('real2sim')['catalog'], 'rigid': p.HasAPI(UsdPhysics.RigidBodyAPI), 'layers': [layer.identifier for layer in s.GetUsedLayers()]}))",
            str(extracted / "scene.usda"),
            f"/World/Objects/{barrel.id.replace('-', '_')}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stage = json.loads(inspection.stdout)
    assert stage["catalog"] == expected and stage["rigid"] is True
    assert not any(barrel.provenance["asset_url"] in layer for layer in stage["layers"])


def test_candidate_zip_recovers_legacy_owner_and_exports_current_rotated_pose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    source_scene = registry.scene.current(job.job_id).scene
    (source_object,) = source_scene.objects
    source_owner = source_object.source_collision
    assert source_owner is not None
    source_scene_ref = registry.scene.revision(job.job_id, source_scene.scene_revision).scene_reference
    source_scene_bytes = registry.runtime_resolver.require(source_scene_ref).read_bytes()
    source_geometry_bytes = registry.runtime_resolver.require(source_scene.environment.geometry_ref).read_bytes()

    legacy_object = source_object.model_copy(update={"source_collision": None}, deep=True)
    legacy_scene = source_scene.model_copy(update={"objects": [legacy_object]}, deep=True)
    legacy_revision = registry.scene.publish_next(
        job.job_id, source_scene.scene_revision, legacy_scene, "test_legacy_without_source_collision"
    ).revision.scene
    rotated_transform = legacy_object.transform.model_copy(
        update={
            "translation_xyz": (3.0, 2.5, 0.3),
            "rotation_quaternion_xyzw": (0.0, 0.0, 0.7071067811865476, 0.7071067811865476),
        }
    )
    moved_scene = move_object(legacy_revision, legacy_object.id, rotated_transform)
    moved_revision = registry.scene.publish_next(
        job.job_id, legacy_revision.scene_revision, moved_scene, "test_move_and_rotate"
    ).revision.scene
    apply_object_action(registry.scene, job.job_id, legacy_object.id, "confirm", moved_revision.scene_revision)
    confirmed_scene = registry.scene.current(job.job_id).scene
    (confirmed_object,) = confirmed_scene.objects
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
    asset_digest = hashlib.sha256(asset_bytes).hexdigest()
    asset_ref = ProductArtifactRef(
        artifact_type="UsdAsset",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job.job_id}/assets/{asset_digest}.usda",
        artifact_checksum=f"sha256:{asset_digest}",
        data_class="derived",
        producer_stage="ST-ASSET-IMPORT",
        job_id=job.job_id,
    )
    registry.scene.store.publish(asset_ref, asset_bytes)
    with_asset = confirmed_scene.model_copy(
        update={"objects": [confirmed_object.model_copy(update={"asset_ref": asset_ref}, deep=True)]}, deep=True
    )
    registry.scene.publish_next(job.job_id, confirmed_scene.scene_revision, with_asset, "test_add_usd_asset")
    current_legacy = registry.scene.current(job.job_id).scene
    current_legacy_ref = registry.scene.revision(job.job_id, current_legacy.scene_revision).scene_reference
    current_legacy_bytes = registry.runtime_resolver.require(current_legacy_ref).read_bytes()

    runtime = Path("data/scene_runtime/bin/python")
    monkeypatch.setattr(
        simulation_package_service,
        "get_settings",
        lambda: Settings(product_scene_runtime_python=runtime, product_sam2_checkpoint=None),
    )
    package = build_simulation_package(registry, job.job_id)

    assert package.candidate is not None and package.package_ref is not None
    assert package.source_scene_revision == current_legacy.scene_revision
    assert package.scene_revision != current_legacy.scene_revision
    exported_scene = registry.scene.current(job.job_id).scene
    (exported_object,) = exported_scene.objects
    assert exported_object.source_collision == source_owner
    assert exported_scene.provenance["source_collision_ownership_recovered"] == {
        source_object.id: source_scene.scene_revision
    }
    assert registry.runtime_resolver.require(source_scene_ref).read_bytes() == source_scene_bytes
    assert (
        registry.runtime_resolver.require(source_scene.environment.geometry_ref).read_bytes() == source_geometry_bytes
    )
    assert registry.runtime_resolver.require(current_legacy_ref).read_bytes() == current_legacy_bytes

    archive = zipfile.ZipFile(io.BytesIO(registry.runtime_resolver.require(package.package_ref).read_bytes()))
    assert archive.testzip() is None
    names = set(archive.namelist())
    assert {"candidate_manifest.json", "scene.usda", "environment.usdc", "usd_export_summary.json"} <= names
    manifest = json.loads(archive.read("candidate_manifest.json"))
    assert manifest["scene_revision"] == package.scene_revision
    assert manifest["scene_ir_checksum"] == package.scene_ir_checksum
    extracted = tmp_path / "legacy-recovery-package"
    archive.extractall(extracted)
    inspect = """
import json, sys
import numpy as np
from pxr import Gf, Usd, UsdGeom
stage = Usd.Stage.Open(sys.argv[1])
obj = stage.GetPrimAtPath(sys.argv[2])
matrix = UsdGeom.XformCache().GetLocalToWorldTransform(obj)
origin = matrix.Transform(Gf.Vec3d(0, 0, 0))
axis_x = matrix.Transform(Gf.Vec3d(1, 0, 0)) - origin
mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Environment/Collision"))
points = np.asarray(mesh.GetPointsAttr().Get())
faces = np.asarray(mesh.GetFaceVertexIndicesAttr().Get()).reshape(-1, 3)
centroids = points[faces].mean(axis=1)
print(json.dumps({
    "object_origin": list(origin),
    "object_axis_x": list(axis_x),
    "environment_faces": len(faces),
    "environment_centroid_z": centroids[:, 2].tolist(),
    "asset_valid": stage.GetPrimAtPath(sys.argv[2] + "/Asset/Body").IsValid(),
}))
"""
    inspected = subprocess.run(
        [
            str(runtime),
            "-c",
            inspect,
            str(extracted / "scene.usda"),
            f"/World/Objects/{source_object.id.replace('-', '_')}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stage = json.loads(inspected.stdout)
    assert stage["environment_faces"] == package.environment_triangles == 12
    assert package.carved_triangles > 0
    assert np.all(np.abs(stage["environment_centroid_z"]) <= 0.02)
    assert stage["object_origin"] == pytest.approx([3.0, 2.5, 0.3])
    assert stage["object_axis_x"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)
    assert stage["asset_valid"] is True
    repeated = build_simulation_package(registry, job.job_id)
    assert repeated.package_ref == package.package_ref
    assert registry.scene.current(job.job_id).scene.scene_revision == package.scene_revision


def test_unavailable_legacy_owner_history_blocks_package_without_publishing_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    source_scene = registry.scene.current(job.job_id).scene
    (item,) = source_scene.objects
    legacy = source_scene.model_copy(
        update={"objects": [item.model_copy(update={"source_collision": None}, deep=True)]}, deep=True
    )
    legacy_revision = registry.scene.publish_next(
        job.job_id, source_scene.scene_revision, legacy, "test_legacy_without_source_collision"
    ).revision.scene
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", legacy_revision.scene_revision)
    current = registry.scene.current(job.job_id).scene
    monkeypatch.setattr(registry.scene, "revision", lambda _job_id, _revision: None)

    with pytest.raises(ValueError, match="require source collision ownership"):
        build_simulation_package(registry, job.job_id)

    assert registry.scene.current(job.job_id).scene.scene_revision == current.scene_revision
    assert current_package(registry, job.job_id) is None


def test_duplicate_object_does_not_trigger_history_walk_for_ownership_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate owns no source region; walking every revision for it makes each export O(n²)."""
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (item,) = scene.objects
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", scene.scene_revision)
    confirmed = registry.scene.current(job.job_id).scene
    apply_object_action(registry.scene, job.job_id, item.id, "duplicate", confirmed.scene_revision)
    current = registry.scene.current(job.job_id).scene
    assert any(candidate.provenance.get("duplicated_from") for candidate in current.objects)
    calls: list[str] = []
    original = registry.scene.revision
    monkeypatch.setattr(
        registry.scene, "revision", lambda job_id, revision: calls.append(revision) or original(job_id, revision)
    )

    recovered, sources = simulation_package_service._recover_legacy_source_ownership(registry, job.job_id, current)

    assert recovered is current and sources == {}
    assert calls == []


def test_legacy_recovery_does_not_assign_ownership_of_a_different_object_that_reuses_the_id(tmp_path: Path) -> None:
    """Re-extraction reuses candidate-001 for another object; its ownership must not come from the old one."""
    registry, job = _scene_job(tmp_path)
    source_scene = registry.scene.current(job.job_id).scene
    (item,) = source_scene.objects
    assert item.source_collision is not None
    other_geometry = item.geometry_ref.model_copy(
        update={"artifact_uri": f"artifact://jobs/{job.job_id}/scene/other-object-geometry.glb"}
    )
    registry.scene.store.publish(other_geometry, registry.runtime_resolver.require(item.geometry_ref).read_bytes())
    replaced = item.model_copy(update={"source_collision": None, "geometry_ref": other_geometry}, deep=True)
    reextracted = source_scene.model_copy(update={"objects": [replaced]}, deep=True)
    published = registry.scene.publish_next(job.job_id, source_scene.scene_revision, reextracted, "test_reextract")
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", published.revision.scene.scene_revision)
    current = registry.scene.current(job.job_id).scene

    with pytest.raises(ValueError, match="require source collision ownership"):
        build_simulation_package(registry, job.job_id)

    assert registry.scene.current(job.job_id).scene.scene_revision == current.scene_revision


def _legacy_job_without_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN202
    """A job extracted before ownership existed: rev-001 has reconstructed objects without source_collision."""
    from src.services.orchestration.scene import extraction as scene_extraction

    with monkeypatch.context() as patcher:
        patcher.setattr(scene_extraction, "bind_source_collision_ownership", lambda objects, _ref, _revision: objects)
        registry, job = _scene_job(tmp_path)
    assert registry.scene.current(job.job_id).scene.objects[0].source_collision is None
    return registry, job


def test_legacy_scene_recovers_ownership_from_the_extraction_revision_not_the_moved_pose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing scenes predate ownership; the original artifact still holds the pose the object was extracted at."""
    registry, job = _legacy_job_without_ownership(tmp_path / "legacy", monkeypatch)
    root = registry.scene.current(job.job_id).scene
    (item,) = root.objects
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", root.scene_revision)
    confirmed = registry.scene.current(job.job_id).scene
    moved = move_object(confirmed, item.id, item.transform.model_copy(update={"translation_xyz": (4.0, 0.5, 0.3)}))
    registry.scene.publish_next(job.job_id, confirmed.scene_revision, moved, "test_move")
    current = registry.scene.current(job.job_id).scene

    recovered, sources = simulation_package_service._recover_legacy_source_ownership(registry, job.job_id, current)

    (owned,) = recovered.objects
    assert sources == {item.id: "rev-001"}
    assert owned.source_collision is not None and owned.source_collision.extraction_revision == "rev-001"
    assert owned.source_collision.source_transform == item.transform
    assert owned.transform.translation_xyz == (4.0, 0.5, 0.3)

    reference_registry, reference_job = _scene_job(tmp_path / "reference")
    reference = reference_registry.scene.current(reference_job.job_id).scene
    apply_object_action(reference_registry.scene, reference_job.job_id, item.id, "confirm", reference.scene_revision)
    expected = simulation_package_service._carved_environment(
        reference_registry, reference_registry.scene.current(reference_job.job_id).scene
    )
    background = simulation_package_service._carved_environment(registry, recovered)
    assert background.carved_triangles == expected.carved_triangles > 0
    assert background.identity == expected.identity


def test_legacy_recovery_accepts_the_first_revision_of_a_reextraction_but_not_other_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _legacy_job_without_ownership(tmp_path, monkeypatch)
    root = registry.scene.current(job.job_id).scene
    (item,) = root.objects
    other_geometry = item.geometry_ref.model_copy(
        update={"artifact_uri": f"artifact://jobs/{job.job_id}/scene/reextracted-geometry.glb"}
    )
    registry.scene.store.publish(other_geometry, registry.runtime_resolver.require(item.geometry_ref).read_bytes())
    reextracted = root.model_copy(
        update={"objects": [item.model_copy(update={"geometry_ref": other_geometry}, deep=True)]}, deep=True
    )
    published = registry.scene.publish_next(job.job_id, root.scene_revision, reextracted, "objectify")
    revision = published.revision.scene
    moved = move_object(revision, item.id, item.transform.model_copy(update={"translation_xyz": (1.5, 1.5, 0.3)}))
    registry.scene.publish_next(job.job_id, revision.scene_revision, moved, "test_move")
    current = registry.scene.current(job.job_id).scene

    _, sources = simulation_package_service._recover_legacy_source_ownership(registry, job.job_id, current)

    assert sources == {item.id: "rev-002"}


def test_legacy_recovery_follows_restored_from_to_the_revision_that_extracted_the_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restore republishes an older object set; its origin is the restored revision, not the one before it."""
    from src.services.orchestration.scene.objects import restore_revision

    registry, job = _legacy_job_without_ownership(tmp_path, monkeypatch)
    root = registry.scene.current(job.job_id).scene
    (item,) = root.objects
    other_geometry = item.geometry_ref.model_copy(
        update={"artifact_uri": f"artifact://jobs/{job.job_id}/scene/second-extraction.glb"}
    )
    registry.scene.store.publish(other_geometry, registry.runtime_resolver.require(item.geometry_ref).read_bytes())
    second_pose = item.transform.model_copy(update={"translation_xyz": (2.0, 2.0, 0.3)})
    second_set = root.model_copy(
        update={
            "objects": [item.model_copy(update={"geometry_ref": other_geometry, "transform": second_pose}, deep=True)]
        },
        deep=True,
    )
    registry.scene.publish_next(job.job_id, "rev-001", second_set, "objectify")  # rev-002
    registry.scene.publish_next(job.job_id, "rev-002", root, "use_boxes")  # rev-003: the first set again
    restore_revision(registry.scene, job.job_id, "rev-003", "rev-002")  # rev-004
    restored = registry.scene.current(job.job_id).scene
    assert restored.provenance["restored_from"] == "rev-002"
    moved = move_object(restored, item.id, second_pose.model_copy(update={"translation_xyz": (7.0, 7.0, 0.3)}))
    registry.scene.publish_next(job.job_id, "rev-004", moved, "test_move")
    current = registry.scene.current(job.job_id).scene

    recovered, sources = simulation_package_service._recover_legacy_source_ownership(registry, job.job_id, current)

    (owned,) = recovered.objects
    assert sources == {item.id: "rev-002"}
    assert owned.source_collision is not None and owned.source_collision.source_transform == second_pose


def test_legacy_owner_from_different_geometry_history_blocks_candidate(tmp_path: Path) -> None:
    registry, job = _scene_job(tmp_path)
    source_scene = registry.scene.current(job.job_id).scene
    (item,) = source_scene.objects
    source_geometry = registry.runtime_resolver.require(source_scene.environment.geometry_ref).read_bytes()
    original_ref = source_scene.environment.geometry_ref
    alternate_ref = original_ref.model_copy(
        update={"artifact_uri": f"artifact://jobs/{job.job_id}/scene/collision-alias.glb"}
    )
    registry.scene.store.publish(alternate_ref, source_geometry)
    legacy = source_scene.model_copy(
        update={
            "objects": [item.model_copy(update={"source_collision": None}, deep=True)],
            "environment": source_scene.environment.model_copy(update={"geometry_ref": alternate_ref}),
        },
        deep=True,
    )
    legacy_revision = registry.scene.publish_next(
        job.job_id, source_scene.scene_revision, legacy, "test_legacy_source_geometry_changed"
    ).revision.scene
    apply_object_action(registry.scene, job.job_id, item.id, "confirm", legacy_revision.scene_revision)
    current = registry.scene.current(job.job_id).scene

    with pytest.raises(ValueError, match="require source collision ownership"):
        build_simulation_package(registry, job.job_id)

    assert registry.scene.current(job.job_id).scene.scene_revision == current.scene_revision
    assert current_package(registry, job.job_id) is None


def test_cached_candidate_is_not_reused_after_builder_version_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job = _scene_job(tmp_path)
    scene = registry.scene.current(job.job_id).scene
    (pallet,) = scene.objects
    apply_object_action(registry.scene, job.job_id, pallet.id, "confirm", scene.scene_revision)
    first = build_simulation_package(registry, job.job_id)

    monkeypatch.setitem(BUILD_CONFIG, "builder", "test-builder-version-change")
    assert current_package(registry, job.job_id) is None
    second = build_simulation_package(registry, job.job_id)

    assert first.package_ref is not None and second.package_ref is not None
    assert second.package_ref != first.package_ref
    assert second.source_scene_revision == first.scene_revision
    assert second.scene_revision != first.scene_revision
    assert registry.scene.current(job.job_id).scene.scene_revision == second.scene_revision
