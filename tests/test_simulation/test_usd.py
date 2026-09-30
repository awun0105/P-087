"""Unit và contract tests cho SIM-05 Candidate OpenUSD Build."""

import json
from pathlib import Path

import pytest

from src.models.contracts.identity import verify_candidate_inventory, verify_content_checksum
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import PreflightReport, RuleResult
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.builder import CandidateBuildRequest, build_candidate_package
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
    assert 'def Xform "Environment"' in usda_text
    assert 'def Cube "GroundPlane"' in usda_text
    assert 'apiSchemas = ["PhysicsCollisionAPI"]' in usda_text
    assert 'def Xform "Objects"' in usda_text

    # Kiểm tra prim của từng object
    for obj in physics_scene.objects:
        assert f'def Xform "{obj.id.replace("-", "_")}"' in usda_text
        assert 'xformOpOrder = ["xformOp:translate", "xformOp:orient"]' in usda_text


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
