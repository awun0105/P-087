"""Canonical content and package identity proof for Foundation fixtures."""

import json
from pathlib import Path

import pytest

from src.models.contracts.identity import (
    canonical_content_checksum,
    verify_candidate_inventory,
    verify_content_checksum,
)
from src.models.contracts.manifests import InputManifest, JobManifest
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import CandidatePackage, ValidationReport
from src.services.orchestration.artifacts import sha256_file

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _model(model_type: type, relative_path: str):
    """Read a committed fixture with its production contract."""
    return model_type.model_validate_json((FIXTURES / relative_path).read_text(encoding="utf-8"))


def test_canonical_content_is_independent_of_json_formatting() -> None:
    """Whitespace/key order never affect logical SceneIR identity."""
    path = FIXTURES / "scene_ir/scene.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    compact = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    pretty = json.dumps(payload, indent=4)
    first = SceneIR.model_validate_json(compact)
    second = SceneIR.model_validate_json(pretty)
    assert canonical_content_checksum(first, "scene_ir_checksum") == second.scene_ir_checksum
    verify_content_checksum(second, "scene_ir_checksum")


def test_embedded_checksum_excludes_only_itself() -> None:
    """A changed transform invalidates the logical content checksum."""
    scene = _model(SceneIR, "scene_ir/scene.json")
    changed = scene.model_copy(deep=True)
    changed.objects[0].transform.translation_xyz = (1.5, 2.0, 0.0)
    with pytest.raises(ValueError, match="scene_ir_checksum"):
        verify_content_checksum(changed, "scene_ir_checksum")
    with pytest.raises(ValueError, match="missing checksum field"):
        canonical_content_checksum({"foo": "bar"}, "scene_ir_checksum")


def test_embedded_identity_differs_from_published_bytes() -> None:
    """Input content identity and its published JSON byte hash are distinct."""
    manifest = _model(InputManifest, "mock_job/input_manifest.json")
    job = _model(JobManifest, "mock_job/job_manifest.json")
    payload = FIXTURES / "artifact_store/jobs/job-fixture-001/manifests/input_manifest.json"
    verify_content_checksum(manifest, "input_manifest_checksum")
    assert job.stage_artifacts[0].artifact_checksum == sha256_file(payload)
    assert manifest.input_manifest_checksum != sha256_file(payload)


def test_edited_scene_has_stable_object_ids_and_new_identity() -> None:
    """An edit moves one object and invalidates the old scene content identity."""
    before = _model(SceneIR, "scene_ir/scene.json")
    after = _model(SceneIR, "scene_ir/edited_scene.json")
    verify_content_checksum(after, "scene_ir_checksum")
    assert after.scene_revision == "rev-002"
    assert [item.id for item in before.objects] == [item.id for item in after.objects]
    assert before.objects[0].transform.translation_xyz != after.objects[0].transform.translation_xyz
    assert before.scene_ir_checksum != after.scene_ir_checksum


def test_failed_validation_fixture_is_a_real_failure_shape() -> None:
    """PRODUCT can develop failure UI without claiming Isaac execution."""
    report = _model(ValidationReport, "validation_report/failed_validation_report.json")
    verify_content_checksum(report, "report_checksum")
    assert report.overall_result == "FAIL"
    assert report.checks[0].result == "FAIL"
    assert report.path_results[0].result == "ERROR"


def test_candidate_inventory_binds_exact_package_refs() -> None:
    """Manifest checksum inventory must match USD/assets/geometry/colliders."""
    candidate = _model(CandidatePackage, "candidate/candidate_package.json")
    verify_candidate_inventory(candidate)
    verify_content_checksum(candidate, "candidate_checksum")
    changed = candidate.model_copy(deep=True)
    changed.candidate_manifest.artifact_checksums.pop()
    with pytest.raises(ValueError, match="artifact_checksums"):
        verify_candidate_inventory(changed)


def test_object_aware_manifest_is_bound_by_candidate_inventory() -> None:
    candidate = _model(CandidatePackage, "candidate/candidate_package.json")
    reference = candidate.entrypoint_usd.model_copy(
        update={
            "artifact_type": "ObjectAwareEnvironmentManifest",
            "artifact_uri": "artifact://jobs/job-fixture-001/collision/object-aware.json",
            "artifact_checksum": "sha256:" + "f" * 64,
        }
    )
    candidate.candidate_manifest.object_aware_collision_ref = reference
    with pytest.raises(ValueError, match="artifact_checksums"):
        verify_candidate_inventory(candidate)
    candidate.candidate_manifest.artifact_checksums.append(reference.artifact_checksum)
    verify_candidate_inventory(candidate)
    changed = reference.model_copy(update={"artifact_checksum": "sha256:" + "e" * 64})
    candidate.candidate_manifest.object_aware_collision_ref = changed
    with pytest.raises(ValueError, match="artifact_checksums"):
        verify_candidate_inventory(candidate)
