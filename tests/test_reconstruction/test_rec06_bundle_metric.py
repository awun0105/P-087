"""Final RGB metric bridge: fixture authorizer và process stubs, real immutable producer/consumer chain."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.services.reconstruction.bundle import ReconstructionBundleService
from src.services.reconstruction.bundle_validation import BundleDependencies
from src.services.reconstruction.rgb.canonical.bundle_metric import BundleMetricVerifier
from src.services.scene.bundle_consumer import load_reconstruction_bundle
from tests.test_reconstruction.support.rec06_bundle_metric_fixture import evidence, fixture


def test_canonical_pipeline_bundle_consumed_by_scene(tmp_path: Path) -> None:
    (verifier, acceptance), request, resolver = fixture(tmp_path)
    proof = verifier.publish(request, acceptance)
    bundle_request = request.bundle.model_copy(update={"verification_ref": proof})
    service = ReconstructionBundleService(
        verifier.canonicalizer.deps.writer,
        BundleDependencies(resolver.require, verifier.verify_bundle),
    )
    bundle, ref = service.build_and_publish(bundle_request)
    view = load_reconstruction_bundle(ref, resolver)
    assert view.bundle == bundle and view.visual.read_bytes() == b"fixture SOG"
    assert bundle.visual_artifact_ref.producer_stage == "ST-VISUAL-RECON"
    assert bundle.camera_pose_refs[0].producer_stage == "ST-METRIC-CANONICALIZE"
    assert bundle.provenance["metric_verification_ref"] == proof.model_dump(mode="json")
    assert bundle.provenance["evidence_kind"] == "synthetic_fixture"
    assert len(view.rgb_frames) == 4 and len(view.camera_poses) == 1


@pytest.mark.parametrize("mode", ["missing", "reject", "product"])
def test_no_default_or_fixture_product_authority(tmp_path: Path, mode: str) -> None:
    (verifier, acceptance), request, _ = fixture(tmp_path)
    changes = {"verify_review": None} if mode == "missing" else {"verify_review": lambda candidate, review: False}
    if mode == "product":
        changes = {"execution_scope": "product"}
    verifier = BundleMetricVerifier(replace(verifier.deps, **changes))
    with pytest.raises(ValueError, match="not configured|not authorized|execution scope"):
        verifier.publish(request, acceptance)
    assert not list((tmp_path / "store").rglob("bundle-metric.json"))


def test_changed_tolerance_requires_new_review(tmp_path: Path) -> None:
    (verifier, acceptance), request, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="stale bundle metric review"):
        verifier.publish(request.model_copy(update={"tolerance_m": 0.5}), acceptance)


@pytest.mark.parametrize("target", ["visual", "geometry", "poses", "measurement", "decision"])
def test_changed_payload_revokes_existing_proof(tmp_path: Path, target: str) -> None:
    (verifier, acceptance), request, resolver = fixture(tmp_path)
    proof = verifier.publish(request, acceptance)
    ref = {
        "visual": request.bundle.visual_artifact_ref,
        "geometry": request.bundle.rgb_geometry_ref,
        "poses": request.bundle.camera_pose_refs[0],
        "measurement": request.independent_sample.measurement_ref,
        "decision": acceptance.decision_ref,
    }[target]
    resolver.require(ref).write_bytes(b"changed")
    with pytest.raises((ValueError, RuntimeError)):
        verifier.verify_bundle(request.bundle.model_copy(update={"verification_ref": proof}))


def test_revoked_review_is_rechecked(tmp_path: Path) -> None:
    (verifier, acceptance), request, _ = fixture(tmp_path)
    proof = verifier.publish(request, acceptance)
    revoked = BundleMetricVerifier(replace(verifier.deps, verify_review=lambda candidate, review: False))
    with pytest.raises(ValueError, match="not authorized"):
        revoked.verify_bundle(request.bundle.model_copy(update={"verification_ref": proof}))


@pytest.mark.parametrize(
    "field", ["source_input_checksum", "rgb_frame_refs", "visual_artifact_ref", "camera_pose_refs"]
)
def test_candidate_cannot_swap_artifacts_after_review(tmp_path: Path, field: str) -> None:
    (verifier, acceptance), request, _ = fixture(tmp_path)
    proof = verifier.publish(request, acceptance)
    changes = {
        "source_input_checksum": "sha256:" + "b" * 64,
        "rgb_frame_refs": [],
        "visual_artifact_ref": None,
        "camera_pose_refs": [],
    }
    bundle = request.bundle.model_copy(update={"verification_ref": proof, field: changes[field]})
    with pytest.raises(ValueError, match="exact metric-reviewed candidate"):
        verifier.verify_bundle(bundle)


def test_review_does_not_override_distance_or_source_checks(tmp_path: Path) -> None:
    (verifier, acceptance), request, _ = fixture(tmp_path)
    sample = request.independent_sample.model_copy(update={"distance_m": 0.8})
    changed = request.model_copy(update={"independent_sample": sample})
    decision = evidence(verifier.canonicalizer, "review-bad-distance", {"request_checksum": changed.checksum()})
    review = acceptance.model_copy(update={"request_checksum": changed.checksum(), "decision_ref": decision})
    with pytest.raises(ValueError, match="exceeds tolerance"):
        verifier.publish(changed, review)


@pytest.mark.parametrize("field", ["source_input_checksum", "rgb_frame_refs", "visual_artifact_ref"])
def test_review_cannot_authorize_wrong_lineage(tmp_path: Path, field: str) -> None:
    (verifier, acceptance), request, _ = fixture(tmp_path)
    changes = {
        "source_input_checksum": "sha256:" + "b" * 64,
        "rgb_frame_refs": [],
        "visual_artifact_ref": request.confirmation_ref,
    }
    changed = request.model_copy(update={"bundle": request.bundle.model_copy(update={field: changes[field]})})
    decision = evidence(verifier.canonicalizer, "wrong-lineage", {"request_checksum": changed.checksum()})
    review = acceptance.model_copy(update={"request_checksum": changed.checksum(), "decision_ref": decision})
    with pytest.raises(ValueError, match="InputManifest|inventory|canonical visual"):
        verifier.publish(changed, review)
