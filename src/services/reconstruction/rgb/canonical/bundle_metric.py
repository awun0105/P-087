"""REC-06→10 bridge: real derivative consumers + explicit independent-measurement authority."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.services.reconstruction.bundle import BundleBuildRequest
from src.services.reconstruction.bundle_validation import BundleDependencies, bundle_references
from src.services.reconstruction.rgb.canonical.bundle_metric_models import (
    BundleMetricAcceptance,
    BundleMetricRecord,
    BundleMetricRequest,
)
from src.services.reconstruction.rgb.canonical.canonical_visual import CanonicalVisualService
from src.services.reconstruction.rgb.canonical.metric_verification import (
    CrossArtifactVerificationRequest,
    MetricVerificationService,
)
from src.services.reconstruction.rgb.frames.bundle_frames import bundle_frame_references


@dataclass(frozen=True)
class BundleMetricDependencies:
    """Không default approval: PRODUCT inject reviewer, tests khai báo fixture authority."""

    visuals: CanonicalVisualService
    verify_review: Callable[[BundleMetricRequest, BundleMetricAcceptance], bool] | None = None
    execution_scope: Literal["product", "synthetic_fixture"] = "product"


class BundleMetricVerifier:
    """Recheck review cả lúc publish lẫn lúc REC-10 consume, không chỉ tin status JSON."""

    def __init__(self, dependencies: BundleMetricDependencies) -> None:
        self.deps = dependencies
        self.canonicalizer = dependencies.visuals.canonicalizer
        self.sources = self.canonicalizer.deps.visuals

    def publish(self, request: BundleMetricRequest, acceptance: BundleMetricAcceptance) -> ProductArtifactRef:
        """Review trước kiểm artifacts; không tính math rồi tự cấp quyền cho user."""
        request = BundleMetricRequest.model_validate(request.model_dump())
        acceptance = BundleMetricAcceptance.model_validate(acceptance.model_dump())
        error = self._validate(request, acceptance)
        payload = dict(
            schema_version="1.0",
            artifact_type="ReconstructionMetricVerification",
            scope="canonical_rgb_bundle_metric",
            status="VERIFIED",
            request=request.model_dump(mode="json"),
            acceptance=acceptance.model_dump(mode="json"),
            independent_distance_error_m=error,
            record_checksum="sha256:" + "0" * 64,
        )
        payload["record_checksum"] = canonical_content_checksum(payload, "record_checksum")
        record = BundleMetricRecord.model_validate(payload)
        encoded = record.model_dump_json(indent=2).encode() + b"\n"
        reference = _reference(record, encoded)
        if self.canonicalizer.deps.writer.publish(reference, encoded) != reference:
            raise ValueError("writer changed bundle verification identity")
        self.load(reference)
        return reference

    def load(self, reference: ProductArtifactRef) -> BundleMetricRecord:
        """Revoked authority hoặc changed payload làm proof cũ không còn đủ để publish bundle."""
        if (
            reference.artifact_type != "ReconstructionMetricVerification"
            or reference.producer_stage != StageId.METRIC_CANONICALIZE
        ):
            raise ValueError("not a final RGB metric verification record")
        payload = self.sources.require(reference).read_bytes()
        record = BundleMetricRecord.model_validate_json(payload)
        if reference != _reference(record, payload):
            raise ValueError("bundle verification identity/provenance mismatch")
        if self._validate(record.request, record.acceptance) != record.independent_distance_error_m:
            raise ValueError("bundle metric evidence differs from published measurement result")
        return record

    def verify_bundle(self, bundle: BundleBuildRequest) -> bool:
        """REC-10 verifier port; caller không thể tráo một ref/config sau review."""
        bundle = BundleBuildRequest.model_validate(bundle.model_dump())
        if bundle.verification_ref is None:
            raise ValueError("bundle has no metric proof")
        record = self.load(bundle.verification_ref)
        candidate = bundle.model_copy(update={"verification_ref": None})
        if candidate != record.request.bundle:
            raise ValueError("bundle differs from exact metric-reviewed candidate")
        return True

    def _validate(self, request: BundleMetricRequest, acceptance: BundleMetricAcceptance) -> float:
        self._review(request, acceptance)
        visual = self.deps.visuals.load(request.canonical_visual_ref)
        if visual.request.confirmation_ref != request.confirmation_ref:
            raise ValueError("canonical visual belongs to another confirmation")
        bundle = request.bundle
        if visual.request.execution_scope != request.execution_scope:
            raise ValueError("canonical visual execution scope mismatch")
        if bundle.visual_artifact_ref != visual.delivery_ref() or bundle.camera_pose_refs != [
            visual.request.canonical_pose_ref
        ]:
            raise ValueError("bundle does not reference the verified canonical visual/poses")
        self._inventory(request)
        raw = self.canonicalizer.load(request.confirmation_ref).preview.request.source_visual
        report = MetricVerificationService(self.canonicalizer).verify(
            CrossArtifactVerificationRequest(
                confirmation_ref=request.confirmation_ref,
                visual_ref=raw,
                geometry_ref=bundle.rgb_geometry_ref,
                camera_pose_ref=bundle.camera_pose_refs[0],
                independent_sample=request.independent_sample,
                tolerance_m=request.tolerance_m,
            )
        )
        return report.independent_distance_error_m

    def _review(self, request: BundleMetricRequest, acceptance: BundleMetricAcceptance) -> None:
        if request.execution_scope != self.deps.execution_scope:
            raise ValueError("bundle metric execution scope differs from deployed verifier")
        if acceptance.request_checksum != request.checksum():
            raise ValueError("stale bundle metric review")
        confirmation = (
            self.canonicalizer.require_real if request.execution_scope == "product" else self.canonicalizer.load
        )(request.confirmation_ref)
        kind = confirmation.preview.request.evidence_kind
        if request.execution_scope == "synthetic_fixture" and kind != "synthetic_fixture":
            raise ValueError("fixture verifier cannot authorize product measurements")
        if acceptance.evidence_kind != kind:
            raise ValueError("bundle metric review evidence kind mismatch")
        if self.deps.verify_review is None:
            raise ValueError("independent measurement/review authority is not configured")
        self.sources.require(acceptance.decision_ref)
        self.sources.require(request.independent_sample.measurement_ref)
        if self.deps.verify_review(request, acceptance) is not True:
            raise ValueError("bundle metric review or independent measurement protocol was not authorized")

    def _inventory(self, request: BundleMetricRequest) -> None:
        bundle = request.bundle
        if request.confirmation_ref.job_id != bundle.job_id:
            raise ValueError("confirmation differs from bundle job")
        if bundle.metric_scale.status != "CONFIRMED" or bundle.metric_scale.meters_per_unit != 1.0:
            raise ValueError("canonical bundle must use confirmed meters_per_unit=1")
        confirmation = self.canonicalizer.load(request.confirmation_ref)
        raw = self.sources.load(confirmation.preview.request.source_visual)
        frames = self.sources.poses.frames.load(raw.source_frame_set)
        if bundle.source_input_checksum != frames.input_manifest_checksum:
            raise ValueError("bundle source InputManifest differs from reconstruction lineage")
        if bundle.rgb_frame_refs != bundle_frame_references(frames, bundle.job_id):
            raise ValueError("bundle frame inventory differs from reconstruction source")
        self.sources.poses.frames.materialize(frames)
        deps = BundleDependencies(self.sources.resolve)
        for ref in bundle_references(bundle):
            deps.require(ref, bundle.job_id)


def _reference(record: BundleMetricRecord, payload: bytes) -> ProductArtifactRef:
    identity = record.record_checksum.removeprefix("sha256:")
    job = record.request.bundle.job_id
    return ProductArtifactRef(
        artifact_type=record.artifact_type,
        schema_version="1.0",
        data_class="derived",
        job_id=job,
        artifact_uri=f"artifact://jobs/{job}/rec06/{identity}/bundle-metric.json",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        producer_stage=StageId.METRIC_CANONICALIZE,
        source_provenance={
            "scope": record.scope,
            "evidence_kind": record.acceptance.evidence_kind,
            "request_checksum": record.request.checksum(),
        },
    )
