"""Các negative proofs của bundle publication trước cross-track handoff."""

from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import MetricScale, MetricScaleStatus
from src.models.contracts.manifests import InputConfiguration, StageId
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.bundle_validation import BundleDependencies
from tests.test_reconstruction.support.rec10_fixtures import simple_bundle_fixture


def unverified_request() -> BundleBuildRequest:
    """Shape hợp lệ không có nghĩa bytes hoặc metric đã hợp lệ."""
    ref = ProductArtifactRef(
        artifact_type="RgbGeometry",
        schema_version="1.0",
        data_class="derived",
        artifact_uri="artifact://jobs/audit/rec05/missing.glb",
        artifact_checksum="sha256:" + "0" * 64,
        producer_stage=StageId.RGB_GEOMETRY,
        job_id="audit",
    )
    return BundleBuildRequest(
        job_id="audit",
        source_input_checksum="sha256:" + "1" * 64,
        input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
        rgb_frame_refs=[ref],
        camera_pose_refs=[ref],
        visual_artifact_ref=ref,
        rgb_geometry_ref=ref,
    )


def test_bundle_does_not_default_confirmed_metric() -> None:
    assert unverified_request().metric_scale.status == MetricScaleStatus.UNCONFIRMED


def test_bundle_does_not_infer_canonical_geometry() -> None:
    assert unverified_request().canonical_geometry_ref is None


def test_bundle_rejects_without_dependency_verification(tmp_path: Path) -> None:
    writer = FilesystemArtifactStore(ArtifactResolver(tmp_path / "store"))
    with pytest.raises(ValueError):
        ReconstructionBundleService(writer).build_and_publish(unverified_request())
    assert not list((tmp_path / "store").rglob("bundle.json"))


@pytest.mark.parametrize(
    "field", ["rgb_frame_refs", "camera_pose_refs", "visual_artifact_ref", "rgb_geometry_ref", "verification_ref"]
)
def test_tampered_payload_prevents_publication(tmp_path: Path, field: str) -> None:
    writer, deps, request = simple_bundle_fixture(tmp_path)
    ref = getattr(request, field)
    ref = ref[0] if isinstance(ref, list) else ref
    writer.resolver.require(ref).write_bytes(b"tampered")
    with pytest.raises((ValueError, RuntimeError)):
        ReconstructionBundleService(writer, deps).build_and_publish(request)
    assert not list((tmp_path / "store").rglob("bundle.json"))


def test_missing_metric_authority_rejected(tmp_path: Path) -> None:
    writer, deps, request = simple_bundle_fixture(tmp_path)
    with pytest.raises(ValueError, match="not authorized"):
        ReconstructionBundleService(writer, BundleDependencies(deps.resolve)).build_and_publish(request)


@pytest.mark.parametrize("change", ["source_input_checksum", "job_id", "geometry_type", "metric_scale"])
def test_review_bound_to_exact_request(tmp_path: Path, change: str) -> None:
    writer, deps, request = simple_bundle_fixture(tmp_path)
    if change == "source_input_checksum":
        request = request.model_copy(update={change: "sha256:" + "2" * 64})
    elif change == "job_id":
        request = request.model_copy(update={change: "other-job"})
    elif change == "geometry_type":
        request = request.model_copy(
            update={"rgb_geometry_ref": request.rgb_geometry_ref.model_copy(update={"artifact_type": "VisualArtifact"})}
        )
    else:
        request = request.model_copy(update={change: MetricScale(status="CONFIRMED", meters_per_unit=2)})
    with pytest.raises(ValueError):
        ReconstructionBundleService(writer, deps).build_and_publish(request)
    assert not list((tmp_path / "store").rglob("bundle.json"))


def test_fixture_bundle_has_resolvable_proof_and_consumer_handoff(tmp_path: Path) -> None:
    from src.services.scene.bundle_consumer import load_reconstruction_bundle

    writer, deps, request = simple_bundle_fixture(tmp_path)
    bundle, ref = ReconstructionBundleService(writer, deps).build_and_publish(request)
    assert bundle.provenance["metric_verification_ref"] == request.verification_ref.model_dump(mode="json")
    assert bundle.provenance["evidence_kind"] == "synthetic_fixture"
    view = load_reconstruction_bundle(ref, writer.resolver)
    assert view.bundle == bundle
