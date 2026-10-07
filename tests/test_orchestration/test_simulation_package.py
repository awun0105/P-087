"""Tạo gói mô phỏng từ SceneIR: khoét môi trường, collider hộp, preflight, đóng gói, tải zip.

Fixture proof (bundle mẫu + collision mesh tổng hợp); không phải bằng chứng physics Isaac.
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path

from src.config import Settings
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.validation import RuleResult
from src.services.orchestration.review.simulation_package import BUILD_CONFIG, build_simulation_package, current_package
from src.services.orchestration.scene.extraction import extract_scene
from src.services.orchestration.scene.objects import add_box_object, apply_object_action
from tests.test_orchestration.test_finalize_flow import _confirmed
from tests.test_orchestration.test_scene_extraction import _FIXTURE, _collision


def _scene_job(tmp_path: Path):  # noqa: ANN202
    registry, job, _ = _confirmed(tmp_path)
    text = _FIXTURE.read_text(encoding="utf-8").replace("job-fixture-001", job.job_id)
    bundle = ReconstructionBundle.model_validate_json(text)
    bundle = bundle.model_copy(update={"canonical_geometry_ref": _collision(registry, job.job_id)})
    settings = Settings(product_scene_runtime_python=None, product_sam2_checkpoint=None)
    extract_scene(registry, job, bundle, settings, tmp_path / "work")
    return registry, job


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
    assert {"scene.usda", "environment_collision.usda", "candidate_manifest.json", "preflight_report.json"} <= names
    usda = archive.read("scene.usda").decode()
    assert "prepend references = @./environment_collision.usda@" in usda and "GroundPlane" in usda
    # Gọi lại trên cùng revision: trả gói cũ, không tạo revision mới.
    again = build_simulation_package(registry, job.job_id)
    assert again.package_ref == package.package_ref
    assert registry.scene.current(job.job_id).scene.scene_revision == "rev-003"
    assert current_package(registry, job.job_id) == package


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
