"""Unit và contract tests cho SIM-05 Candidate OpenUSD Build."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import verify_candidate_inventory, verify_content_checksum
from src.models.contracts.scene import ColliderType, ObjectPhysics, SceneIR
from src.models.contracts.validation import (
    CandidateManifest,
    CandidatePackage,
    PreflightReport,
    PreflightRuleId,
    RuleResult,
)
from src.services.scene.publisher import with_scene_checksum
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.builder import CandidateBuildRequest, build_candidate_package
from src.services.simulation.usd.capabilities import (
    EffectiveExportMode,
    ExportCapabilityReport,
    ExportCapabilityStatus,
    RuntimeQualificationStatus,
    export_requirements,
)
from src.services.simulation.usd.usda import generate_scene_usda

FIXTURE_PATH = Path("fixtures/scene_ir/scene.json")


@pytest.fixture
def base_scene() -> SceneIR:
    """Nạp fixture SceneIR chuẩn."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return SceneIR.model_validate(data)


@pytest.fixture
def physics_scene(base_scene: SceneIR) -> SceneIR:
    """Tạo SceneIR đã được làm giàu vật lý (SIM-03)."""
    return enrich_scene_physics(base_scene)


@pytest.fixture
def pass_preflight_report(physics_scene: SceneIR) -> PreflightReport:
    """Chạy preflight trên physics scene và đảm bảo kết quả PASS."""
    report = run_preflight(physics_scene)
    assert report.blocking_result == RuleResult.PASS
    return report


def test_generate_scene_usda_syntax(physics_scene: SceneIR) -> None:
    """Kiểm tra cú pháp và metadata OpenUSD ASCII (.usda) theo chuẩn Re3Sim/Isaac."""
    usda_text = generate_scene_usda(physics_scene)

    assert "#usda 1.0" in usda_text
    assert 'defaultPrim = "World"' in usda_text
    assert "metersPerUnit = 1.0" in usda_text
    assert 'upAxis = "Z"' in usda_text
    assert 'def Xform "World"' in usda_text
    assert 'def PhysicsScene "PhysicsScene"' in usda_text
    assert 'def Xform "Environment"' in usda_text
    assert 'def Cube "GroundPlane"' in usda_text
    assert 'apiSchemas = ["PhysicsCollisionAPI"]' in usda_text
    assert 'def Xform "Objects"' in usda_text

    # Kiểm tra prim của từng object
    for obj in physics_scene.objects:
        assert f'def Xform "{obj.id.replace("-", "_")}"' in usda_text
        assert 'xformOpOrder = ["xformOp:translate", "xformOp:orient"]' in usda_text


def test_legacy_usda_opens_with_physics_scene(physics_scene: SceneIR, tmp_path: Path) -> None:
    runtime = Path(os.environ.get("R2S_SCENE_RUNTIME_PYTHON", "data/scene_runtime/bin/python"))
    if not runtime.is_file():
        pytest.skip("USD scene runtime is unavailable")
    scene_file = tmp_path / "scene.usda"
    scene_file.write_text(generate_scene_usda(physics_scene), encoding="utf-8")

    inspected = subprocess.run(
        [
            str(runtime),
            "-c",
            "import json,sys; from pxr import Usd,UsdPhysics; "
            "s=Usd.Stage.Open(sys.argv[1]); p=s.GetPrimAtPath('/World/PhysicsScene'); "
            "print(json.dumps({'stage': s is not None, 'physics_scene': p.IsA(UsdPhysics.Scene)}))",
            str(scene_file),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert json.loads(inspected.stdout) == {"stage": True, "physics_scene": True}


def test_legacy_box_export_preserves_dimensions_and_collider_local_pose(physics_scene: SceneIR) -> None:
    item = physics_scene.objects[0]
    assert item.collider is not None
    quarter_turn = 0.7071067811865476
    object_transform = item.transform.model_copy(
        update={
            "translation_xyz": (3.0, 4.0, 0.5),
            "rotation_quaternion_xyzw": (0.0, 0.0, quarter_turn, quarter_turn),
        }
    )
    local_transform = item.collider.local_transform.model_copy(
        update={
            "translation_xyz": (0.25, -0.5, 0.3),
            "rotation_quaternion_xyzw": (0.0, 0.0, quarter_turn, quarter_turn),
        }
    )
    collider = item.collider.model_copy(
        update={"dimensions_xyz_m": (2.0, 0.2, 0.4), "local_transform": local_transform}
    )
    edited_item = item.model_copy(update={"transform": object_transform, "collider": collider})
    scene = physics_scene.model_copy(update={"objects": [edited_item, *physics_scene.objects[1:]]})

    usda_text = generate_scene_usda(scene)

    assert "double3 xformOp:scale = (2.0, 0.2, 0.4)" in usda_text
    assert "double3 xformOp:translate = (0.25, -0.5, 0.3)" in usda_text
    assert "quatf xformOp:orient = (0.7071067811865476, 0.0, 0.0, 0.7071067811865476)" in usda_text
    assert 'xformOpOrder = ["xformOp:translate", "xformOp:orient", "xformOp:scale"]' in usda_text
    assert "double3 xformOp:translate = (3.0, 4.0, 0.5)" in usda_text


def test_legacy_usd_exporter_rejects_mesh_without_geometry(physics_scene: SceneIR) -> None:
    """Unsupported mesh colliders must fail instead of becoming an empty USD Mesh prim."""
    item = physics_scene.objects[0]
    assert item.collider is not None
    collider = item.collider.model_copy(update={"collider_type": ColliderType.CONVEX_HULL})
    scene = physics_scene.model_copy(
        update={"objects": [item.model_copy(update={"collider": collider}), *physics_scene.objects[1:]]}
    )

    with pytest.raises(ValueError, match="cannot preserve collider"):
        generate_scene_usda(scene)


def test_legacy_usd_exporter_rejects_dropped_physics_and_assets(physics_scene: SceneIR) -> None:
    item = physics_scene.objects[0]
    physics = ObjectPhysics(
        dynamic=False,
        static_friction=0.5,
        dynamic_friction=0.4,
        restitution=0.0,
        provenance={},
    )
    with_physics = physics_scene.model_copy(
        update={"objects": [item.model_copy(update={"physics": physics}), *physics_scene.objects[1:]]}
    )
    with_asset = physics_scene.model_copy(
        update={
            "objects": [
                item.model_copy(update={"asset_ref": physics_scene.environment.geometry_ref}),
                *physics_scene.objects[1:],
            ]
        }
    )

    with pytest.raises(ValueError, match="ObjectPhysics"):
        generate_scene_usda(with_physics)
    with pytest.raises(ValueError, match="asset dependencies"):
        generate_scene_usda(with_asset)


def test_legacy_usd_exporter_keeps_catalog_provenance_instead_of_rejecting_the_object(physics_scene: SceneIR) -> None:
    """A catalog object without physics is a plain box; its public asset URL is recorded, not referenced."""
    item = physics_scene.objects[0]
    provenance = {
        **item.provenance,
        "catalog_family": "SM_PaletteA",
        "asset_url": 'https://example.test/Assets/Isaac/SM_Pallete "A".usd',
    }
    scene = physics_scene.model_copy(
        update={"objects": [item.model_copy(update={"provenance": provenance}), *physics_scene.objects[1:]]}
    )

    usda_text = generate_scene_usda(scene)

    assert 'string family = "SM_PaletteA"' in usda_text
    assert 'string asset_url = "https://example.test/Assets/Isaac/SM_Pallete \\"A\\".usd"' in usda_text
    assert "references" not in usda_text.lower()
    runtime = Path(os.environ.get("R2S_SCENE_RUNTIME_PYTHON", "data/scene_runtime/bin/python"))
    if runtime.is_file():
        scene_file = Path(tempfile.mkdtemp()) / "scene.usda"
        scene_file.write_text(usda_text, encoding="utf-8")
        inspected = subprocess.run(
            [
                str(runtime),
                "-c",
                "import json,sys; from pxr import Usd; s=Usd.Stage.Open(sys.argv[1]); "
                "p=s.GetPrimAtPath(sys.argv[2]); print(json.dumps(p.GetCustomDataByKey('real2sim')))",
                str(scene_file),
                f"/World/Objects/{item.id.replace('-', '_')}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert json.loads(inspected.stdout) == {
            "catalog": {"asset_url": 'https://example.test/Assets/Isaac/SM_Pallete "A".usd', "family": "SM_PaletteA"}
        }


def test_build_candidate_package_success(
    physics_scene: SceneIR,
    pass_preflight_report: PreflightReport,
    tmp_path: Path,
) -> None:
    """Đóng gói CandidatePackage thành công, xác thực toàn vẹn inventory và checksum."""
    req = CandidateBuildRequest(
        scene=physics_scene,
        preflight_report=pass_preflight_report,
        job_manifest_checksum="sha256:" + "1" * 64,
        build_config={"target_simulator": "isaac_sim_4.2"},
        output_dir=tmp_path / "candidate",
    )

    pkg = build_candidate_package(req)

    # 1. Xác thực schema và các thành phần chính
    assert pkg.candidate_manifest.candidate_id == f"candidate-{physics_scene.scene_id}-{physics_scene.scene_revision}"
    assert pkg.candidate_manifest.scene_revision == physics_scene.scene_revision
    assert pkg.candidate_manifest.scene_ir_checksum == physics_scene.scene_ir_checksum
    assert pkg.candidate_manifest.coordinate_system == physics_scene.coordinate_system
    assert pkg.entrypoint_usd.artifact_type == "OpenUSDEntrypoint"
    assert pkg.entrypoint_usd.artifact_uri.endswith("scene.usda")

    # 2. Xác thực tính bất biến của inventory và checksum
    verify_candidate_inventory(pkg)
    verify_content_checksum(pkg, "candidate_checksum")

    # 3. Kiểm tra file vật lý được ghi đúng
    assert (tmp_path / "candidate" / "scene.usda").is_file()
    assert (tmp_path / "candidate" / "candidate_manifest.json").is_file()


def test_candidate_inventory_binds_selected_collision_source_and_selection(physics_scene: SceneIR) -> None:
    job_id = physics_scene.environment.geometry_ref.job_id
    assert job_id is not None
    source_ref = ProductArtifactRef.model_validate(
        {
            "artifact_type": "LidarCollisionCandidate",
            "schema_version": "1.0",
            "artifact_uri": f"artifact://jobs/{job_id}/collider/lidar.glb",
            "artifact_checksum": "sha256:" + "a" * 64,
            "data_class": "derived",
            "producer_stage": "ST-COLLIDER",
            "job_id": job_id,
        }
    )
    selection_ref = ProductArtifactRef.model_validate(
        {
            "artifact_type": "CollisionSourceSelection",
            "schema_version": "1.0",
            "artifact_uri": f"artifact://jobs/{job_id}/collider/selection.json",
            "artifact_checksum": "sha256:" + "b" * 64,
            "data_class": "derived",
            "producer_stage": "ST-COLLIDER",
            "job_id": job_id,
        }
    )
    environment = physics_scene.environment.model_copy(
        update={
            "collision_source_ref": source_ref,
            "collision_selection_ref": selection_ref,
            "collider_ref": source_ref,
        }
    )
    selected_scene = physics_scene.model_copy(update={"environment": environment, "objects": []}, deep=True)
    selected_scene = SceneIR.model_validate(with_scene_checksum(selected_scene).model_dump(mode="json"))
    report = run_preflight(selected_scene)
    coverage_rule = next(rule for rule in report.rules if rule.rule_id == PreflightRuleId.COLLISION_SOURCE_COVERAGE)
    assert report.blocking_result == RuleResult.ERROR
    assert coverage_rule.result == RuleResult.ERROR

    entrypoint_ref = ProductArtifactRef(
        artifact_type="OpenUSDEntrypoint",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/candidate/scene.usda",
        artifact_checksum="sha256:" + "c" * 64,
        data_class="derived",
        producer_stage="ST-CANDIDATE-BUILD",
        job_id=job_id,
    )
    manifest = CandidateManifest(
        schema_version="1.0",
        candidate_id="candidate-selected-source",
        scene_revision=selected_scene.scene_revision,
        scene_ir_checksum=selected_scene.scene_ir_checksum,
        job_manifest_checksum="sha256:" + "1" * 64,
        coordinate_system=selected_scene.coordinate_system,
        object_transforms=[],
        asset_refs=[],
        collider_refs=[source_ref],
        artifact_checksums=[
            entrypoint_ref.artifact_checksum,
            source_ref.artifact_checksum,
            selection_ref.artifact_checksum,
        ],
        build_config_checksum="sha256:" + "2" * 64,
        collision_source_ref=source_ref,
        collision_selection_ref=selection_ref,
    )
    package = CandidatePackage(
        candidate_manifest=manifest,
        entrypoint_usd=entrypoint_ref,
        assets=[],
        geometry=[],
        colliders=[source_ref],
        candidate_checksum="sha256:" + "3" * 64,
    )
    verify_candidate_inventory(package)


def test_build_candidate_package_rejects_non_pass_preflight(
    physics_scene: SceneIR,
    pass_preflight_report: PreflightReport,
) -> None:
    """Từ chối đóng gói khi Preflight chưa PASS."""
    failed_report = pass_preflight_report.model_copy(update={"blocking_result": RuleResult.FAIL})
    req = CandidateBuildRequest(
        scene=physics_scene,
        preflight_report=failed_report,
        job_manifest_checksum="sha256:" + "1" * 64,
    )

    with pytest.raises(ValueError, match="chưa PASS"):
        build_candidate_package(req)


def test_build_candidate_package_rejects_mismatched_revision(
    physics_scene: SceneIR,
    pass_preflight_report: PreflightReport,
) -> None:
    """Từ chối đóng gói khi scene_revision trong Preflight report lệch với scene."""
    mismatched_report = pass_preflight_report.model_copy(update={"scene_revision": "rev-999"})
    req = CandidateBuildRequest(
        scene=physics_scene,
        preflight_report=mismatched_report,
        job_manifest_checksum="sha256:" + "1" * 64,
    )

    with pytest.raises(ValueError, match="scene_revision.*không khớp"):
        build_candidate_package(req)


def test_build_candidate_package_rejects_mismatched_checksum(
    physics_scene: SceneIR,
    pass_preflight_report: PreflightReport,
) -> None:
    """Từ chối đóng gói khi scene_ir_checksum trong Preflight report lệch với scene."""
    mismatched_report = pass_preflight_report.model_copy(update={"scene_ir_checksum": "sha256:" + "9" * 64})
    req = CandidateBuildRequest(
        scene=physics_scene,
        preflight_report=mismatched_report,
        job_manifest_checksum="sha256:" + "1" * 64,
    )

    with pytest.raises(ValueError, match="scene_ir_checksum không khớp"):
        build_candidate_package(req)


def test_hybrid_entrypoint_and_layers_are_sealed_by_candidate_checksum(
    physics_scene: SceneIR, pass_preflight_report: PreflightReport, tmp_path: Path
) -> None:
    """Pipeline v2: entrypoint USD lai dựng sẵn + các layer của nó nằm trong inventory đã niêm phong."""
    layer = physics_scene.environment.geometry_ref.model_copy(
        update={
            "artifact_type": "OpenUSDLayer",
            "artifact_uri": "artifact://jobs/job-fixture-001/simulation/aa/hybrid/environment.usdc",
            "artifact_checksum": "sha256:" + "a" * 64,
        }
    )

    def build(entrypoint: bytes, layers: list) -> object:
        capability = ExportCapabilityReport(
            scene_revision=physics_scene.scene_revision,
            scene_ir_checksum=physics_scene.scene_ir_checksum,
            status=ExportCapabilityStatus.SUPPORTED,
            effective_mode=EffectiveExportMode.HYBRID,
            builder_version="usd-export-capabilities-v2",
            runtime_qualification=RuntimeQualificationStatus.QUALIFIED,
            runtime_version="test-runtime",
            requirements=export_requirements(physics_scene),
        )
        return build_candidate_package(
            CandidateBuildRequest(
                scene=physics_scene,
                preflight_report=pass_preflight_report,
                job_manifest_checksum="sha256:" + "b" * 64,
                output_dir=tmp_path,
                entrypoint_bytes=entrypoint,
                extra_assets=layers,
                export_mode=EffectiveExportMode.HYBRID,
                export_capability=capability,
            )
        )

    package = build(b"#usda 1.0\n(hybrid)\n", [layer])

    assert (tmp_path / "scene.usda").read_bytes() == b"#usda 1.0\n(hybrid)\n"
    assert layer in package.assets and layer.artifact_checksum in package.candidate_manifest.artifact_checksums
    verify_candidate_inventory(package)
    verify_content_checksum(package, "candidate_checksum")
    # Đổi entrypoint hoặc bỏ layer đều đổi checksum của candidate.
    assert build(b"#usda 1.0\n(other)\n", [layer]).candidate_checksum != package.candidate_checksum
    assert build(b"#usda 1.0\n(hybrid)\n", []).candidate_checksum != package.candidate_checksum
