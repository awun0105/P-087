"""Typed artifact usage classes at product and evaluation boundaries."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.manifests import InputManifest, JobManifest
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import EvaluationReport, ValidationReport
from src.services.orchestration.artifacts import ArtifactResolver

FIXTURES = Path(__file__).parents[2] / "fixtures"
CHECKSUM = "sha256:" + "4" * 64


def _reference(data_class: str, uri: str) -> dict[str, object]:
    """Build a ref without relying on URI spelling for its usage class."""
    return {
        "artifact_type": "TestGeometry",
        "schema_version": "1.0",
        "artifact_uri": uri,
        "artifact_checksum": CHECKSUM,
        "data_class": data_class,
        "producer_stage": "ST-INPUT-VALIDATE",
    }


@pytest.mark.parametrize("data_class", ["ground_truth", "evaluation_only"])
@pytest.mark.parametrize(
    "uri", ["artifact://jobs/job-123/evaluation_only/map.ply", "artifact://jobs/job-123/input/map.ply"]
)
def test_product_rejects_raw_gt_or_evaluation_only_under_any_uri(data_class: str, uri: str) -> None:
    """A renamed evaluation reference cannot cross the product boundary."""
    payload = _reference(data_class, uri)
    assert ArtifactRef.model_validate(payload).data_class == data_class
    with pytest.raises(ValidationError, match="data_class"):
        ProductArtifactRef.model_validate(payload)


@pytest.mark.parametrize("data_class", ["product_input", "derived"])
def test_product_allows_safe_class_even_with_evaluation_word_in_uri(data_class: str) -> None:
    """A URI segment is not an authorization rule."""
    uri = "artifact://jobs/job-123/evaluation_only/preview.ply"
    assert ProductArtifactRef.model_validate(_reference(data_class, uri)).data_class == data_class


def test_artifact_reference_accepts_pipeline_runtime_schema_11() -> None:
    payload = _reference("derived", "artifact://jobs/job-123/benchmark/pipeline_runtime.json")
    payload["artifact_type"] = "PipelineRuntimeBenchmark"
    payload["schema_version"] = "1.1"

    reference = ProductArtifactRef.model_validate(payload)

    assert reference.schema_version == "1.1"


@pytest.mark.parametrize("schema_version", ["1.2", "2.0"])
def test_artifact_reference_rejects_unimplemented_schema_version(schema_version: str) -> None:
    payload = _reference("derived", "artifact://jobs/job-123/benchmark/pipeline_runtime.json")
    payload["artifact_type"] = "PipelineRuntimeBenchmark"
    payload["schema_version"] = schema_version

    with pytest.raises(ValidationError, match="schema_version"):
        ProductArtifactRef.model_validate(payload)


def test_unclassified_reference_fails_closed() -> None:
    """Old refs must migrate explicitly rather than receiving a safe default."""
    payload = _reference("derived", "artifact://jobs/job-123/input/map.ply")
    payload.pop("data_class")
    with pytest.raises(ValidationError, match="data_class"):
        ProductArtifactRef.model_validate(payload)


def test_gt_assisted_derived_ref_preserves_lineage() -> None:
    """Derived oracle/debug output is distinct from raw ground truth."""
    payload = _reference("derived", "artifact://jobs/job-123/derived/lidar.ply")
    payload["source_provenance"] = {
        "dependencies": [{"role": "pose", "origin": "ground_truth", "source_checksum": CHECKSUM}],
        "ground_truth_assisted": True,
        "details": {},
    }
    reference = ProductArtifactRef.model_validate(payload)
    assert reference.data_class == ArtifactDataClass.DERIVED
    assert reference.source_provenance["ground_truth_assisted"] is True


def test_evaluator_can_reference_ground_truth() -> None:
    """The low-level/evaluator contract retains raw GT references."""
    reference = json.loads((FIXTURES / "evaluation/ground_truth_ref.json").read_text(encoding="utf-8"))
    assert ArtifactResolver(FIXTURES / "artifact_store").require(ArtifactRef.model_validate(reference)).is_file()
    report = EvaluationReport.model_validate(
        {
            "schema_version": "1.0",
            "subject_type": "reconstruction",
            "subject_id": "reconstruction-123",
            "subject_checksum": CHECKSUM,
            "evaluation_protocol_id": "protocol-123",
            "references_used": [reference],
            "preprocessing_dependencies": [],
            "metrics": [],
            "path_comparisons": [],
            "report_checksum": CHECKSUM,
        }
    )
    assert report.references_used[0].data_class == ArtifactDataClass.GROUND_TRUTH


def test_stage_artifact_requires_class_when_uri_present() -> None:
    """A product job cannot carry an unclassified stage output."""
    payload = json.loads((FIXTURES / "mock_job/job_manifest.json").read_text(encoding="utf-8"))
    payload["stage_artifacts"][0].pop("data_class")
    with pytest.raises(ValidationError, match="data_class"):
        JobManifest.model_validate(payload)


def test_product_handoffs_reject_reclassified_raw_gt() -> None:
    """Scene and validator evidence cannot bypass ProductArtifactRef."""
    scene = json.loads((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    scene["environment"]["geometry_ref"]["data_class"] = "ground_truth"
    with pytest.raises(ValidationError, match="data_class"):
        SceneIR.model_validate(scene)
    report = json.loads((FIXTURES / "validation_report/validation_report.json").read_text(encoding="utf-8"))
    report["checks"][0]["evidence_refs"][0]["data_class"] = "evaluation_only"
    with pytest.raises(ValidationError, match="data_class"):
        ValidationReport.model_validate(report)


def test_input_and_stage_manifest_reject_raw_gt() -> None:
    """Direct URI fields in product manifests follow the same typed rule."""
    input_payload = json.loads((FIXTURES / "mock_job/input_manifest.json").read_text(encoding="utf-8"))
    input_payload["files"][0]["data_class"] = "ground_truth"
    with pytest.raises(ValidationError, match="data_class"):
        InputManifest.model_validate(input_payload)
    job_payload = json.loads((FIXTURES / "mock_job/job_manifest.json").read_text(encoding="utf-8"))
    job_payload["stage_artifacts"][0]["data_class"] = "evaluation_only"
    with pytest.raises(ValidationError, match="data_class"):
        JobManifest.model_validate(job_payload)
