"""Contract tests for manifests and reconstruction fixtures."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.manifests import InputManifest, JobManifest, RuntimeManifest
from src.models.contracts.reconstruction import (
    LiDARGeometryArtifact,
    ReconstructionBundle,
    VisualArtifact,
)
from src.models.contracts.release import SceneRevisionRecord

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _fixture_text(relative_path: str) -> str:
    return (FIXTURES / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["manifest.json", "rgb_depth_manifest.json", "mixed_manifest.json"])
def test_reconstruction_bundle_fixtures_are_valid(name: str) -> None:
    """EX-SCENE can deserialize RGB-only and mixed handoff fixtures."""
    bundle = ReconstructionBundle.model_validate_json(_fixture_text(f"reconstruction_bundle/{name}"))

    assert bundle.canonical_geometry_ref.artifact_checksum.startswith("sha256:")
    assert bundle.coordinate_system.world_frame == "world"


def test_rgb_depth_requires_matching_sensor_depth_metadata() -> None:
    """Optional depth is explicit and never inferred from RGB geometry."""
    payload = json.loads(_fixture_text("reconstruction_bundle/rgb_depth_manifest.json"))
    depth = payload.pop("depth_frame_set")
    with pytest.raises(ValidationError, match="depth_present"):
        ReconstructionBundle.model_validate(payload)
    payload["depth_frame_set"] = depth
    payload["depth_frame_set"]["scale_to_meter"] = 0.002
    assert ReconstructionBundle.model_validate(payload).depth_frame_set.scale_to_meter == 0.002


@pytest.mark.parametrize(
    ("storage_dtype", "storage_format", "scale_to_meter"),
    [("uint16", "png", 0.001), ("uint16", "png", 0.002), ("float32", "exr", 1.0)],
)
def test_depth_metadata_is_provider_neutral(storage_dtype: str, storage_format: str, scale_to_meter: float) -> None:
    """Sensor depth metadata is declared by the producer, not fixed to TorWIC."""
    payload = json.loads(_fixture_text("reconstruction_bundle/rgb_depth_manifest.json"))
    payload["depth_frame_set"].update(
        storage_dtype=storage_dtype, storage_format=storage_format, scale_to_meter=scale_to_meter
    )
    depth = ReconstructionBundle.model_validate(payload).depth_frame_set
    assert depth is not None
    assert (depth.storage_dtype, depth.storage_format, depth.scale_to_meter) == (
        storage_dtype,
        storage_format,
        scale_to_meter,
    )


@pytest.mark.parametrize("scale_to_meter", [0, -0.001, float("inf"), float("nan")])
def test_depth_scale_must_be_positive_and_finite(scale_to_meter: float) -> None:
    """Non-metric or invalid depth scaling cannot cross the shared handoff."""
    payload = json.loads(_fixture_text("reconstruction_bundle/rgb_depth_manifest.json"))
    payload["depth_frame_set"]["scale_to_meter"] = scale_to_meter
    with pytest.raises(ValidationError, match="scale_to_meter"):
        ReconstructionBundle.model_validate(payload)


def test_depth_cannot_be_declared_without_rgb() -> None:
    """The optional depth profile is paired with RGB in the Foundation contract."""
    payload = json.loads(_fixture_text("reconstruction_bundle/rgb_depth_manifest.json"))
    payload["input_configuration"]["rgb_present"] = False
    with pytest.raises(ValidationError, match=r"RGB\+Depth"):
        ReconstructionBundle.model_validate(payload)


def test_reconstruction_bundle_roundtrip_is_deterministic() -> None:
    """The shared handoff survives JSON serialization without field drift."""
    bundle = ReconstructionBundle.model_validate_json(_fixture_text("reconstruction_bundle/rgb_depth_manifest.json"))
    serialized = bundle.model_dump_json()
    assert ReconstructionBundle.model_validate_json(serialized).model_dump_json() == serialized


def test_mixed_bundle_binds_confirmed_alignment() -> None:
    """Mixed fixture binds the exact RGB and LiDAR geometry checksums."""
    bundle = ReconstructionBundle.model_validate_json(_fixture_text("reconstruction_bundle/mixed_manifest.json"))

    assert bundle.alignment_record is not None
    assert bundle.alignment_record.source_lidar_checksum == bundle.lidar_geometry_ref.artifact_checksum
    assert bundle.alignment_record.target_rgb_geometry_checksum == bundle.rgb_geometry_ref.artifact_checksum
    assert bundle.lidar_geometry_ref.source_provenance["ground_truth_assisted"] is False


@pytest.mark.parametrize("origin", ["estimated", "external"])
def test_mixed_bundle_accepts_non_gt_pose_dependency(origin: str) -> None:
    """Estimated or external poses must not be mislabeled as trajectory GT."""
    payload = json.loads(_fixture_text("reconstruction_bundle/mixed_manifest.json"))
    source = payload["lidar_geometry_ref"]["source_provenance"]
    source["dependencies"] = [{"role": "pose", "origin": origin, "source_checksum": "sha256:" + "7" * 64}]
    assert ReconstructionBundle.model_validate(payload).lidar_geometry_ref.source_provenance == source


def test_gt_dependency_propagates_to_mixed_bundle() -> None:
    """A GT-assisted LiDAR ref requires matching generic bundle provenance."""
    payload = json.loads(_fixture_text("reconstruction_bundle/mixed_manifest.json"))
    source = payload["lidar_geometry_ref"]["source_provenance"]
    source["dependencies"] = [{"role": "pose", "origin": "ground_truth", "source_checksum": "sha256:" + "8" * 64}]
    with pytest.raises(ValidationError, match="ground_truth_assisted must match"):
        ReconstructionBundle.model_validate(payload)
    source["ground_truth_assisted"] = True
    with pytest.raises(ValidationError, match="GT-assisted LiDAR bundle"):
        ReconstructionBundle.model_validate(payload)
    payload["provenance"]["ground_truth_assisted"] = True
    assert ReconstructionBundle.model_validate(payload).provenance["ground_truth_assisted"] is True


def test_mixed_bundle_rejects_missing_or_misclassified_lidar_lineage() -> None:
    """A LiDAR reference cannot silently omit or mislabel its dependencies."""
    payload = json.loads(_fixture_text("reconstruction_bundle/mixed_manifest.json"))
    source = payload["lidar_geometry_ref"].pop("source_provenance")
    with pytest.raises(ValidationError, match="requires preprocessing provenance"):
        ReconstructionBundle.model_validate(payload)
    source["ground_truth_assisted"] = True
    payload["lidar_geometry_ref"]["source_provenance"] = source
    with pytest.raises(ValidationError, match="ground_truth_assisted must match"):
        ReconstructionBundle.model_validate(payload)


def test_mixed_bundle_without_alignment_is_rejected() -> None:
    """Mixed modality cannot cross the boundary without confirmed alignment."""
    with pytest.raises(ValidationError, match="RGB bundle requires|confirmed alignment"):
        ReconstructionBundle.model_validate_json(_fixture_text("invalid/mixed_bundle_missing_alignment.json"))


def test_visual_and_lidar_artifact_fixtures_are_valid() -> None:
    """Visual abstraction and LiDAR provenance validate independently."""
    visual = VisualArtifact.model_validate_json(_fixture_text("reconstruction_bundle/visual_artifact.json"))
    lidar = LiDARGeometryArtifact.model_validate_json(_fixture_text("reconstruction_bundle/lidar_artifact.json"))

    assert visual.format == "real2sim.synthetic.visual.v1"
    assert visual.provenance["brush_compatibility_proof"] is False
    assert lidar.preprocessing_provenance.ground_truth_assisted is False


def test_gt_assisted_lidar_requires_explicit_provenance() -> None:
    """An artifact produced from GT poses must carry a traceable dependency."""
    payload = json.loads(_fixture_text("reconstruction_bundle/lidar_artifact.json"))
    lineage = payload["preprocessing_provenance"]
    lineage["dependencies"] = [{"role": "pose", "origin": "ground_truth"}]
    with pytest.raises(ValidationError, match="source_checksum"):
        LiDARGeometryArtifact.model_validate(payload)
    lineage["dependencies"][0]["source_checksum"] = "sha256:" + "8" * 64
    with pytest.raises(ValidationError, match="ground_truth_assisted must match"):
        LiDARGeometryArtifact.model_validate(payload)
    lineage["ground_truth_assisted"] = True
    assert LiDARGeometryArtifact.model_validate(payload).preprocessing_provenance.ground_truth_assisted


def test_mock_job_and_runtime_manifests_are_valid() -> None:
    """Orchestration can deserialize synthetic input, job and runtime manifests."""
    input_manifest = InputManifest.model_validate_json(_fixture_text("mock_job/input_manifest.json"))
    job_manifest = JobManifest.model_validate_json(_fixture_text("mock_job/job_manifest.json"))
    runtime = RuntimeManifest.model_validate_json(_fixture_text("mock_job/runtime_manifest.json"))

    assert job_manifest.input_manifest_checksum == input_manifest.input_manifest_checksum
    assert job_manifest.runtime_manifest_checksum == runtime.runtime_manifest_checksum
    assert all(component.status == "UNVERIFIED" for component in runtime.components.values())


def test_mock_product_lifecycle_restarts_after_scene_edit() -> None:
    """PRODUCT mock snapshots use typed workflow state outside SceneIR."""
    snapshots = json.loads(_fixture_text("mock_job/scene_revision_states.json"))
    states = [SceneRevisionRecord.model_validate(item) for item in snapshots]

    assert [state.status for state in states] == ["DRAFT", "CANDIDATE_READY", "READY_FOR_REVIEW", "APPROVED", "DRAFT"]
    assert states[-1].scene_revision == "rev-002"
    assert states[-1].validation_report_checksum is None
    assert states[-1].approval_record_checksum is None
