"""Capability gates keep unsupported SceneIR features out of sealed USD packages."""

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

import numpy as np
import pytest
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import ColliderType, MassSource, ObjectPhysics, SceneIR
from src.services.orchestration.review.simulation_package import _qualify_hybrid_runtime
from src.services.simulation import mesh_geometry
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.usd.capabilities import (
    EffectiveExportMode,
    ExportCapabilityStatus,
    RuntimeQualificationStatus,
    assess_export_capabilities,
    export_requirements,
    select_export_mode,
)

FIXTURE_PATH = Path("fixtures/scene_ir/scene.json")


@pytest.fixture
def box_scene() -> SceneIR:
    """A box-only legacy scene with generated colliders and no authored ObjectPhysics."""

    return enrich_scene_physics(SceneIR.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8")))


def _with_collider(scene: SceneIR, collider_type: ColliderType, geometry_ref: ProductArtifactRef | None) -> SceneIR:
    item = scene.objects[0]
    collider = item.collider.model_copy(
        update={"collider_type": collider_type, "geometry_ref": geometry_ref, "dimensions_xyz_m": None}
    )
    first = item.model_copy(update={"collider": collider})
    return scene.model_copy(update={"objects": [first, *scene.objects[1:]]})


def test_box_only_scene_uses_legacy_mode_without_usd_runtime(box_scene: SceneIR) -> None:
    requirements = export_requirements(box_scene)

    assert requirements.collider_types == [ColliderType.AABB]
    assert select_export_mode(requirements) == EffectiveExportMode.LEGACY_BOX
    report = assess_export_capabilities(box_scene, runtime_qualified=False)
    assert report.status == ExportCapabilityStatus.SUPPORTED
    assert report.runtime_qualification == RuntimeQualificationStatus.NOT_REQUIRED


def test_convex_scene_without_runtime_is_blocked(box_scene: SceneIR) -> None:
    scene = _with_collider(box_scene, ColliderType.CONVEX_DECOMPOSITION, None)

    report = assess_export_capabilities(scene, runtime_qualified=False)

    assert report.effective_mode == EffectiveExportMode.HYBRID
    assert report.status == ExportCapabilityStatus.BLOCKED
    assert {item.code for item in report.blockers} >= {
        "USD_RUNTIME_UNQUALIFIED",
        "COLLIDER_GEOMETRY_REF_MISSING",
    }


def test_convex_scene_with_unresolved_geometry_ref_is_blocked(box_scene: SceneIR) -> None:
    scene = _with_collider(box_scene, ColliderType.CONVEX_DECOMPOSITION, box_scene.environment.geometry_ref)

    def missing_artifact(_reference: ProductArtifactRef) -> Path:
        raise FileNotFoundError("test fixture deliberately absent")

    report = assess_export_capabilities(scene, runtime_qualified=True, resolve_artifact=missing_artifact)

    assert report.status == ExportCapabilityStatus.BLOCKED
    assert "COLLIDER_GEOMETRY_REF_INVALID" in {item.code for item in report.blockers}


def test_mesh_ref_without_topology_is_blocked(
    box_scene: SceneIR, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _with_collider(box_scene, ColliderType.CONVEX_DECOMPOSITION, box_scene.environment.geometry_ref)
    empty_path = tmp_path / "empty.glb"
    empty_path.write_bytes(b"fixture")
    monkeypatch.setattr(
        mesh_geometry.trimesh,
        "load",
        lambda *_args, **_kwargs: trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=[]),
    )

    report = assess_export_capabilities(
        scene,
        runtime_qualified=True,
        resolve_artifact=lambda _reference: empty_path,
    )

    assert report.status == ExportCapabilityStatus.BLOCKED
    assert "COLLIDER_GEOMETRY_HAS_NO_TOPOLOGY" in {item.code for item in report.blockers}


def test_dynamic_object_without_mass_is_blocked(box_scene: SceneIR) -> None:
    item = box_scene.objects[0]
    physics = ObjectPhysics(
        dynamic=True,
        mass_kg=1.0,
        mass_source=MassSource.USER,
        static_friction=0.5,
        dynamic_friction=0.4,
        restitution=0.0,
        provenance={},
    ).model_copy(update={"mass_kg": None, "mass_source": None})
    scene = box_scene.model_copy(
        update={"objects": [item.model_copy(update={"physics": physics}), *box_scene.objects[1:]]}
    )

    report = assess_export_capabilities(scene, runtime_qualified=True)

    assert report.effective_mode == EffectiveExportMode.HYBRID
    assert report.status == ExportCapabilityStatus.BLOCKED
    assert "DYNAMIC_MASS_MISSING" in {item.code for item in report.blockers}


def test_hybrid_export_supports_local_collider_offset_and_obb_dimensions(box_scene: SceneIR) -> None:
    item = box_scene.objects[0]
    physics = ObjectPhysics(
        dynamic=False,
        static_friction=0.5,
        dynamic_friction=0.4,
        restitution=0.0,
        provenance={},
    )
    transform = item.collider.local_transform.model_copy(
        update={
            "translation_xyz": (0.1, 0.0, 0.0),
            "rotation_quaternion_xyzw": (0.0, 0.0, 0.7071067811865476, 0.7071067811865476),
        }
    )
    collider = item.collider.model_copy(
        update={"collider_type": ColliderType.OBB, "dimensions_xyz_m": (0.3, 0.4, 0.5), "local_transform": transform}
    )
    scene = box_scene.model_copy(
        update={"objects": [item.model_copy(update={"physics": physics, "collider": collider}), *box_scene.objects[1:]]}
    )

    report = assess_export_capabilities(scene, runtime_qualified=True)

    assert report.effective_mode == EffectiveExportMode.HYBRID
    assert report.status == ExportCapabilityStatus.SUPPORTED
    assert not report.blockers


def test_hybrid_export_blocks_asset_with_unsupported_geometry_format(box_scene: SceneIR) -> None:
    item = box_scene.objects[0].model_copy(update={"asset_ref": box_scene.environment.geometry_ref})
    scene = box_scene.model_copy(update={"objects": [item, *box_scene.objects[1:]]})

    report = assess_export_capabilities(scene, runtime_qualified=True)

    assert report.effective_mode == EffectiveExportMode.HYBRID
    assert "EXTERNAL_ASSET_FORMAT_UNSUPPORTED" in {item.code for item in report.blockers}


def test_self_contained_usd_asset_is_capability_supported(box_scene: SceneIR, tmp_path: Path) -> None:
    payload = b'#usda 1.0\n( defaultPrim = "Asset" )\ndef Xform "Asset" {}\n'
    asset_path = tmp_path / "asset.usda"
    asset_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    reference = ProductArtifactRef(
        artifact_type="UsdAsset",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{box_scene.scene_id}/assets/{digest}.usda",
        artifact_checksum=f"sha256:{digest}",
        data_class="derived",
        producer_stage="ST-ASSET-IMPORT",
        job_id=box_scene.scene_id,
    )
    item = box_scene.objects[0].model_copy(update={"asset_ref": reference})
    scene = box_scene.model_copy(update={"objects": [item, *box_scene.objects[1:]]})

    report = assess_export_capabilities(scene, runtime_qualified=True, resolve_artifact=lambda _ref: asset_path)

    assert report.effective_mode == EffectiveExportMode.HYBRID
    assert report.status == ExportCapabilityStatus.SUPPORTED
    assert not report.blockers


def test_asset_checksum_mismatch_is_blocked(box_scene: SceneIR, tmp_path: Path) -> None:
    asset_path = tmp_path / "asset.usda"
    asset_path.write_text('#usda 1.0\ndef Xform "Asset" {}\n', encoding="utf-8")
    reference = ProductArtifactRef(
        artifact_type="UsdAsset",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{box_scene.scene_id}/assets/asset.usda",
        artifact_checksum="sha256:" + "0" * 64,
        data_class="derived",
        producer_stage="ST-ASSET-IMPORT",
        job_id=box_scene.scene_id,
    )
    item = box_scene.objects[0].model_copy(update={"asset_ref": reference})
    scene = box_scene.model_copy(update={"objects": [item, *box_scene.objects[1:]]})

    report = assess_export_capabilities(scene, runtime_qualified=True, resolve_artifact=lambda _ref: asset_path)

    assert report.status == ExportCapabilityStatus.BLOCKED
    assert "EXTERNAL_ASSET_REF_INVALID" in {issue.code for issue in report.blockers}


def test_python_file_presence_does_not_qualify_usd_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    python = tmp_path / "python"
    python.touch()

    def failed_probe(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 1, stdout="", stderr="missing pxr")

    monkeypatch.setattr("src.services.orchestration.review.simulation_package.subprocess.run", failed_probe)

    qualified, version = _qualify_hybrid_runtime(python)

    assert not qualified and version is None


def test_probe_records_usd_version_and_required_capabilities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    python = tmp_path / "python"
    python.touch()
    capabilities_found = [
        "triangle_mesh_collision",
        "convex_mesh_collision",
        "rigid_body_mass",
        "physics_material",
        "collider_local_transform",
        "physics_source_metadata",
        "semantic_labels",
        "gaussian_particle_field",
        "meters_z_up",
    ]

    def successful_probe(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        Path(command[-1]).write_text(
            '{"qualified":true,"usd_version":"26.5.0","capabilities":' + json.dumps(capabilities_found) + "}",
            encoding="utf-8",
        )
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("src.services.orchestration.review.simulation_package.subprocess.run", successful_probe)
    assert _qualify_hybrid_runtime(python) == (True, "26.5.0")
