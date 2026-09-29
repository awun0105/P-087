"""REC-06 publish canonical Gaussian PLY + SOG qua codec upstream, giữ raw master."""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import Checksum, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import VisualArtifact
from src.services.reconstruction.adapters.gaussian_scale import (
    GaussianTransformReceipt,
    GaussianTransformRequest,
    SplatTransformSimilarityAdapter,
)
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor
from src.services.reconstruction.rgb.canonical.canonical_poses import CanonicalPoseService
from src.services.reconstruction.rgb.canonical.canonical_visual_models import (
    CanonicalVisualManifest,
    CanonicalVisualRequest,
)
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.canonical.metric_models import MetricConfirmation
from src.services.reconstruction.rgb.frames.frame_set import _sha256
from src.services.reconstruction.rgb.splat.visual import BrushVisualArtifact, SplatInspection


@dataclass(frozen=True)
class CanonicalVisualDependencies:
    """Tái dùng process/storage seams đã qualified; không import track khác."""

    canonicalizer: MetricCanonicalizer
    similarity: SplatTransformSimilarityAdapter
    processor: SplatArtifactProcessor


@dataclass(frozen=True)
class _Context:
    request: CanonicalVisualRequest
    confirmation: MetricConfirmation
    raw: BrushVisualArtifact
    input_checksum: Checksum


@dataclass(frozen=True)
class _Converted:
    receipt: GaussianTransformReceipt
    inspection: SplatInspection
    master: bytes
    delivery: bytes


class CanonicalVisualService:
    """Producer của metric derivative, chưa phải final metric/physics verifier."""

    def __init__(self, dependencies: CanonicalVisualDependencies) -> None:
        self.deps = dependencies
        self.canonicalizer = dependencies.canonicalizer
        self.visuals = self.canonicalizer.deps.visuals

    def execute(self, request: CanonicalVisualRequest, workspace: Path) -> ProductArtifactRef:
        """Kiểm authority/poses trước tạo workspace; publish manifest cuối cùng."""
        context = self._context(request)
        workspace.mkdir(parents=True, exist_ok=False)
        converted = self._convert(context, workspace)
        reference = self._publish(context, converted)
        self.load(reference)
        return reference

    def _context(self, request: CanonicalVisualRequest) -> _Context:
        request = CanonicalVisualRequest.model_validate(request.model_dump())
        record = (
            self.canonicalizer.require_real(request.confirmation_ref)
            if request.execution_scope == "product"
            else self.canonicalizer.load(request.confirmation_ref)
        )
        if (
            request.execution_scope == "synthetic_fixture"
            and record.preview.request.evidence_kind != "synthetic_fixture"
        ):
            raise ValueError("fixture publication cannot bypass real scene metric authority")
        poses = CanonicalPoseService(self.canonicalizer).load(request.canonical_pose_ref)
        if poses.confirmation_ref != request.confirmation_ref:
            raise ValueError("canonical visual and poses require the same confirmation")
        raw = self.visuals.load(record.preview.request.source_visual)
        frames = self.visuals.poses.frames.load(raw.source_frame_set)
        return _Context(request, record, raw, frames.input_manifest_checksum)

    def _convert(self, context: _Context, workspace: Path) -> _Converted:
        source = self.visuals.require(context.raw.master)
        task = GaussianTransformRequest(
            source=source,
            source_checksum=context.raw.master.artifact_checksum,
            transform=context.confirmation.preview.transform,
        )
        receipt = self.deps.similarity.transform(task, workspace / "metric")
        output = workspace / "output"
        output.mkdir()
        shutil.copyfile(workspace / "metric/input.ply", output / "visual.ply")
        expected = _sha256(workspace / "metric/input.ply")
        inspection = self.deps.processor.process_artifact(workspace, context.raw.config.sog_iterations)
        self._check_codec(context, receipt, inspection)
        if _sha256(output / "visual.ply") != expected:
            raise ValueError("SOG packaging changed the canonical Gaussian master")
        self.visuals.require(context.raw.master)
        return _Converted(
            receipt, inspection, (output / "visual.ply").read_bytes(), (output / "scene.sog").read_bytes()
        )

    @staticmethod
    def _check_codec(context: _Context, receipt: GaussianTransformReceipt, inspection: SplatInspection) -> None:
        if receipt.transform != context.confirmation.preview.transform:
            raise ValueError("canonical visual receipt transform mismatch")
        if inspection.revision != "afbc281":
            raise ValueError("unqualified canonical SOG codec revision")
        expected = (context.raw.inspection.num_gaussians, context.raw.inspection.sh_bands)
        if (receipt.num_gaussians, receipt.sh_bands) != expected or (
            inspection.num_gaussians,
            inspection.sh_bands,
        ) != expected:
            raise ValueError("canonical visual changed Gaussian/SH inventory")

    def _publish(self, context: _Context, converted: _Converted) -> ProductArtifactRef:
        master = self._publish_blob(context, ("GaussianPLY", "visual.ply"), converted.master)
        delivery = self._publish_blob(context, ("VisualArtifact", "scene.sog"), converted.delivery)
        payload = dict(
            schema_version="1.0",
            artifact_type="CanonicalVisualManifest",
            request=context.request.model_dump(mode="json"),
            master_ref=master.model_dump(mode="json"),
            visual=_metadata(context, delivery).model_dump(mode="json"),
            transform_receipt=converted.receipt.model_dump(mode="json"),
            inspection=converted.inspection.model_dump(mode="json"),
            artifact_checksum="sha256:" + "0" * 64,
        )
        payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
        manifest = CanonicalVisualManifest.model_validate(payload)
        encoded = manifest.model_dump_json(indent=2).encode() + b"\n"
        return self._publish_blob(context, ("CanonicalVisualManifest", "visual.json"), encoded)

    def _publish_blob(self, context: _Context, spec: tuple[str, str], payload: bytes) -> ProductArtifactRef:
        reference = _reference(context, spec, payload)
        if self.canonicalizer.deps.writer.publish(reference, payload) != reference:
            raise ValueError("artifact writer changed canonical visual identity")
        self.visuals.require(reference)
        return reference

    def load(self, reference: ProductArtifactRef) -> CanonicalVisualManifest:
        """Recheck authority, exact lineage/receipt và mọi bytes; không tự cấp final approval."""
        reference = ProductArtifactRef.model_validate(reference.model_dump())
        if (
            reference.artifact_type != "CanonicalVisualManifest"
            or reference.producer_stage != StageId.METRIC_CANONICALIZE
        ):
            raise ValueError("not a REC-06 canonical visual manifest")
        payload = self.visuals.require(reference).read_bytes()
        manifest = CanonicalVisualManifest.model_validate_json(payload)
        context = self._context(manifest.request)
        if reference != _reference(context, ("CanonicalVisualManifest", "visual.json"), payload):
            raise ValueError("canonical visual manifest identity/provenance mismatch")
        self._check_codec(context, manifest.transform_receipt, manifest.inspection)
        for ref, spec in (
            (manifest.master_ref, ("GaussianPLY", "visual.ply")),
            (manifest.delivery_ref(), ("VisualArtifact", "scene.sog")),
        ):
            blob = self.visuals.require(ref).read_bytes()
            if ref != _reference(context, spec, blob):
                raise ValueError("canonical visual payload identity/provenance mismatch")
        if manifest.visual != _metadata(context, manifest.delivery_ref()):
            raise ValueError("canonical visual metadata differs from confirmed source")
        return manifest


def _provenance(context: _Context) -> dict:
    return dict(
        producer_version="rec06-canonical-visual-v1",
        scope="metric_derivative_only",
        evidence_kind=context.confirmation.preview.request.evidence_kind,
        source_visual=context.confirmation.preview.request.source_visual.model_dump(mode="json"),
        source_master=context.raw.master.model_dump(mode="json"),
        confirmation_ref=context.request.confirmation_ref.model_dump(mode="json"),
        canonical_pose_ref=context.request.canonical_pose_ref.model_dump(mode="json"),
        measurement_ref=context.confirmation.preview.request.anchor.measurement_ref.model_dump(mode="json"),
        frame_evidence_ref=context.confirmation.preview.request.frame.evidence_ref.model_dump(mode="json"),
        applied_confirmation_checksum=context.confirmation.record_checksum,
        applied_transform=context.confirmation.preview.transform.model_dump(mode="json"),
        coordinate_system=CoordinateSystem().model_dump(mode="json"),
        brush_compatibility_proof=False,
    )


def _reference(context: _Context, spec: tuple[str, str], payload: bytes) -> ProductArtifactRef:
    kind, name = spec
    job_id = context.request.confirmation_ref.job_id
    digest = hashlib.sha256(payload).hexdigest()
    identity = context.confirmation.record_checksum.removeprefix("sha256:")
    return ProductArtifactRef(
        artifact_type=kind,
        schema_version="1.0",
        data_class="derived",
        job_id=job_id,
        artifact_uri=f"artifact://jobs/{job_id}/rec06/{identity}/{digest}/{name}",
        artifact_checksum="sha256:" + digest,
        producer_stage=StageId.VISUAL_RECON if kind == "VisualArtifact" else StageId.METRIC_CANONICALIZE,
        source_provenance=_provenance(context)
        | {"format": {"GaussianPLY": "gaussian_ply", "VisualArtifact": "sog"}.get(kind, "json")},
    )


def _metadata(context: _Context, delivery: ProductArtifactRef) -> VisualArtifact:
    return VisualArtifact(
        artifact_type="VisualArtifact",
        schema_version="1.0",
        artifact_uri=delivery.artifact_uri,
        artifact_checksum=delivery.artifact_checksum,
        producer_stage=StageId.VISUAL_RECON,
        job_id=delivery.job_id,
        format="sog",
        producer="brush-splat-transform",
        producer_version=f"{context.raw.brush_version}/3.6.6-afbc281",
        coordinate_system=CoordinateSystem(),
        source_input_checksum=context.input_checksum,
        provenance=_provenance(context) | {"format": "sog"},
    )
