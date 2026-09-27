"""REC-06 preview → authority-verified confirmation → immutable internal record.

Không có default acceptance verifier. EX-PRODUCT phải nối authenticated Editor
decision trước khi dùng với dữ liệu thật; test verifier không là product authority.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from src.models.contracts.artifacts import Checksum, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.reconstruction.rgb.metric_math import SimilarityTransform
from src.services.reconstruction.rgb.metric_models import (
    MetricAcceptance,
    MetricConfirmation,
    MetricConversionPlan,
    MetricPreview,
    MetricRequest,
    confirmation_record,
)
from src.services.reconstruction.rgb.metric_seed import CameraSeedProposal
from src.services.reconstruction.rgb.publication import ArtifactWriter
from src.services.reconstruction.rgb.visual_publication import VisualResolver


@dataclass(frozen=True)
class MetricDependencies:
    """Inject published-source resolver/storage và decision authority riêng biệt."""

    visuals: VisualResolver
    writer: ArtifactWriter
    verify_acceptance: Callable[[MetricPreview, MetricAcceptance], bool] | None = None


class MetricCanonicalizer:
    """Pha anchor/frame; không emit stage SUCCEEDED hay final ReconstructionBundle."""

    def __init__(self, dependencies: MetricDependencies) -> None:
        self.deps = dependencies

    def preview(self, request: MetricRequest) -> MetricPreview:
        """Resolve actual lineage/bytes; giữ UNCONFIRMED dù math đã tính được."""
        request = MetricRequest.model_validate(request.model_dump())
        visual = self.deps.visuals.load(request.source_visual)
        if request.anchor.source_master != visual.master:
            raise ValueError("anchor is bound to a different visual master")
        for reference in (request.anchor.measurement_ref, request.frame.evidence_ref):
            self.deps.visuals.require(reference)
        transform = SimilarityTransform(
            scale_m_per_sfm_unit=request.anchor.scale(),
            rotation_xyzw=request.frame.rotation_xyzw,
            translation_m=request.frame.translation_m,
        )
        return MetricPreview(request=request, source_camera_poses=visual.source_camera_poses, transform=transform)

    def confirm(self, preview: MetricPreview, acceptance: MetricAcceptance | None) -> MetricConfirmation:
        """Tính đúng scale không thay human confirmation của đúng preview."""
        preview = MetricPreview.model_validate(preview.model_dump())
        if acceptance is None:
            raise ValueError("metric confirmation requires explicit acceptance")
        acceptance = MetricAcceptance.model_validate(acceptance.model_dump())
        self._verify(preview, acceptance)
        return confirmation_record(preview, acceptance)

    def _verify(self, preview: MetricPreview, acceptance: MetricAcceptance) -> None:
        if acceptance.preview_checksum != preview.checksum():
            raise ValueError("stale metric acceptance: review current preview")
        if acceptance.evidence_kind != preview.request.evidence_kind:
            raise ValueError("acceptance evidence kind mismatch")
        if self.deps.verify_acceptance is None:
            raise ValueError("metric acceptance verifier is not configured")
        if self.preview(preview.request) != preview:
            raise ValueError("metric source lineage differs from reviewed preview")
        self.deps.visuals.require(acceptance.decision_ref)
        if self.deps.verify_acceptance(preview, acceptance) is not True:
            raise ValueError("metric acceptance was not authorized for this preview")

    def publish(self, record: MetricConfirmation, job_id: str) -> ProductArtifactRef:
        """Revalidate trước atomic publish; checksum trong path tách mọi revision."""
        record = MetricConfirmation.model_validate(record.model_dump())
        self._verify(record.preview, record.acceptance)
        payload = record.model_dump_json(indent=2).encode() + b"\n"
        reference = _reference(record, payload, job_id)
        if self.deps.writer.publish(reference, payload) != reference:
            raise ValueError("artifact writer changed metric confirmation identity")
        return reference

    def load(self, reference: ProductArtifactRef) -> MetricConfirmation:
        """Typed status/checksum không tự chứng minh approval: recheck authority."""
        reference = ProductArtifactRef.model_validate(reference.model_dump())
        if (
            reference.artifact_type != "RGBMetricConfirmation"
            or reference.producer_stage != StageId.METRIC_CANONICALIZE
        ):
            raise ValueError("not a REC-06 anchor/frame confirmation")
        _require_job_identity(reference)
        payload = self.deps.visuals.require(reference).read_bytes()
        record = MetricConfirmation.model_validate_json(payload)
        if reference.source_provenance != _provenance(record):
            raise ValueError("metric reference provenance differs from record")
        self._verify(record.preview, record.acceptance)
        return record

    def require_real(self, reference: ProductArtifactRef) -> MetricConfirmation:
        """Product consumer phải dùng gate này, không nhận fixture như real metric."""
        record = self.load(reference)
        if record.preview.request.evidence_kind != "real_measurement":
            raise ValueError("synthetic confirmation cannot authorize real metric generation")
        return record

    def conversion_plan(
        self, reference: ProductArtifactRef, source: ProductArtifactRef, applied_record_checksum: Checksum | None = None
    ) -> MetricConversionPlan:
        """Source phải là raw dependency đã bind; derivative không được scale lần hai."""
        if applied_record_checksum is not None:
            raise ValueError("metric transform already applied; refusing double scaling")
        record = self.load(reference)
        allowed = (record.preview.request.anchor.source_master, record.preview.source_camera_poses)
        if source not in allowed:
            raise ValueError("conversion input is not a raw source bound to this confirmation")
        self.deps.visuals.require(source)
        return MetricConversionPlan(
            confirmation_ref=reference,
            confirmation_checksum=record.record_checksum,
            input_ref=source,
            transform=record.preview.transform,
            evidence_kind=record.preview.request.evidence_kind,
        )

    def propose_navigation_seed(self, reference: ProductArtifactRef) -> CameraSeedProposal:
        """Candidate ở camera đầu registered, không hardcode Frame 0 hoặc auto-pass."""
        record = self.load(reference)
        poses = self.deps.visuals.poses.load(record.preview.source_camera_poses)
        # CameraPoseArtifact đã enforce inventory ordered, registered và nonempty.
        first = poses.poses[0]
        return CameraSeedProposal(
            confirmation_ref=reference,
            confirmation_checksum=record.record_checksum,
            source_camera_poses=record.preview.source_camera_poses,
            frame_id=first.frame_id,
            position_world=record.preview.transform.apply_point(first.translation),
            evidence_kind=record.preview.request.evidence_kind,
        )


def _require_job_identity(reference: ProductArtifactRef) -> None:
    """Ref phải tự nhất quán về job vì derivative REC-06 lấy namespace từ job đó.

    Thiếu job_id, hoặc URI trỏ sang job khác, đều cho phép ghi confirmation
    derivative vào namespace của job khác nên phải chặn trước khi resolve bytes.
    """
    job_id = reference.job_id
    if job_id is None or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/"):
        raise ValueError("confirmation job identity is required to namespace REC-06 derivatives")


def _provenance(record: MetricConfirmation) -> dict[str, str]:
    return dict(
        producer_version="rec06-v1",
        evidence_kind=record.preview.request.evidence_kind,
        scope=record.scope,
        record_checksum=record.record_checksum,
        preview_checksum=record.preview.checksum(),
    )


def _reference(record: MetricConfirmation, payload: bytes, job_id: str) -> ProductArtifactRef:
    identity = record.record_checksum.removeprefix("sha256:")
    return ProductArtifactRef(
        artifact_type="RGBMetricConfirmation",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec06/{identity}/confirmation.json",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class="derived",
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
        source_provenance=_provenance(record),
    )
