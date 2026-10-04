"""Lightweight fixture consumers for all cross-track handoff boundaries."""

from pathlib import Path

from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import ValidationReport
from src.services.orchestration.artifacts import ArtifactResolver

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures"
RESOLVER = ArtifactResolver(FIXTURES / "artifact_store")


def _load(relative_path: str) -> str:
    return (FIXTURES / relative_path).read_text(encoding="utf-8")


def test_scene_consumes_reconstruction_fixture_without_conversion() -> None:
    """REC -> SCENE fixture refs resolve directly with matching checksums."""
    bundle = ReconstructionBundle.model_validate_json(_load("reconstruction_bundle/mixed_manifest.json"))
    references = [
        *bundle.rgb_frame_refs,
        *bundle.camera_pose_refs,
        bundle.visual_artifact_ref,
        bundle.rgb_geometry_ref,
        bundle.lidar_geometry_ref,
        bundle.canonical_geometry_ref,
    ]

    assert all(RESOLVER.require(reference).is_file() for reference in references if reference)


def test_scene_consumes_rgb_depth_fixture_with_resolved_depth() -> None:
    """Optional sensor-depth refs are checksum-resolvable across the boundary."""
    bundle = ReconstructionBundle.model_validate_json(_load("reconstruction_bundle/rgb_depth_manifest.json"))
    assert bundle.depth_frame_set is not None
    assert bundle.depth_frame_set.provenance["ground_truth"] is False
    assert all(RESOLVER.require(ref).is_file() for ref in bundle.depth_frame_set.frame_refs)


def test_sim_consumes_scene_fixture_without_conversion() -> None:
    """SCENE -> SIM fixture refs resolve directly with matching checksums."""
    scene = SceneIR.model_validate_json(_load("scene_ir/scene.json"))
    references = [
        scene.environment.geometry_ref,
        scene.environment.collider_ref,
        *(item.geometry_ref for item in scene.objects),
        *(item.collider.geometry_ref for item in scene.objects if item.collider is not None),
    ]

    assert all(RESOLVER.require(reference).is_file() for reference in references if reference)


def test_product_consumes_validation_fixture_without_expected_labels() -> None:
    """SIM -> PRODUCT evidence resolves and contains observed results only."""
    report = ValidationReport.model_validate_json(_load("validation_report/validation_report.json"))
    evidence = [reference for check in report.checks for reference in check.evidence_refs]

    assert all(RESOLVER.require(reference).is_file() for reference in evidence)
    assert all("expected" not in result.model_dump() for result in report.path_results)
