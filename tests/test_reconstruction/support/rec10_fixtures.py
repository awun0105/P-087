"""Synthetic readiness authority cho publication tests, KHÔNG là REC-06 acceptance."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import MetricScale
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import AlignmentRecord
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.bundle import BundleBuildRequest
from src.services.reconstruction.bundle_validation import BundleDependencies


def reviewed_bundle_fixture(
    writer: FilesystemArtifactStore,
    request: BundleBuildRequest,
    alignment_loader: Callable[[ProductArtifactRef], AlignmentRecord] | None = None,
) -> tuple[BundleDependencies, BundleBuildRequest]:
    """Bind exact fixture inventory; không verify geometry physics hay render quality."""
    request = request.model_copy(
        update={
            "metric_scale": MetricScale(status="CONFIRMED", meters_per_unit=1),
            "canonical_geometry_ref": request.rgb_geometry_ref,
            "provenance": request.provenance | {"evidence_kind": "synthetic_fixture"},
        }
    )
    payload = request.model_dump_json(exclude={"verification_ref"}).encode()
    proof = _proof_ref(request.job_id, payload)
    writer.publish(proof, payload)
    request = request.model_copy(update={"verification_ref": proof})

    def verify(candidate: BundleBuildRequest) -> bool:
        return candidate.verification_ref == proof and json.loads(writer.resolver.require(proof).read_text()) == (
            candidate.model_dump(mode="json", exclude={"verification_ref"})
        )

    return BundleDependencies(writer.resolver.require, verify, alignment_loader), request


def _proof_ref(job_id: str, payload: bytes) -> ProductArtifactRef:
    digest = hashlib.sha256(payload).hexdigest()
    return ProductArtifactRef(
        artifact_type="SyntheticBundleVerification",
        schema_version="1.0",
        data_class="derived",
        artifact_uri=f"artifact://jobs/{job_id}/fixtures/{digest}/bundle-proof.json",
        artifact_checksum="sha256:" + digest,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )


def simple_bundle_fixture(root: Path) -> tuple[FilesystemArtifactStore, BundleDependencies, BundleBuildRequest]:
    """Opaque synthetic bytes chỉ để test ref integrity/consumer contract, không runtime."""
    writer = FilesystemArtifactStore(ArtifactResolver(root / "store"))
    fields = {
        "rgb_frame_refs": ("RGBFrame", StageId.FRAME_EXTRACT),
        "camera_pose_refs": ("CameraPoseArtifact", StageId.CAMERA_POSE),
        "visual_artifact_ref": ("VisualArtifact", StageId.VISUAL_RECON),
        "rgb_geometry_ref": ("RgbGeometry", StageId.RGB_GEOMETRY),
    }
    values = {}
    for field, (kind, stage) in fields.items():
        ref = _publish_fixture(writer, field, (kind, stage))
        values[field] = [ref] if field.endswith("refs") else ref
    request = BundleBuildRequest(
        job_id="audit",
        source_input_checksum="sha256:" + "1" * 64,
        input_configuration={"rgb_present": True, "registered_lidar_present": False},
        **values,
    )
    deps, request = reviewed_bundle_fixture(writer, request)
    return writer, deps, request


def _publish_fixture(writer: FilesystemArtifactStore, name: str, kind_stage: tuple[str, StageId]) -> ProductArtifactRef:
    kind, stage = kind_stage
    payload = ("synthetic fixture " + kind).encode()
    ref = ProductArtifactRef(
        artifact_type=kind,
        schema_version="1.0",
        data_class="derived",
        artifact_uri=f"artifact://jobs/audit/fixtures/{name}.bin",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        producer_stage=stage,
        job_id="audit",
    )
    writer.publish(ref, payload)
    return ref
