"""EX-REC handoff gates; storage và review authority qua explicit ports."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import AlignmentRecord
from src.services.reconstruction.rgb.frame_set import _sha256

if TYPE_CHECKING:
    from src.services.reconstruction.bundle import BundleBuildRequest


@dataclass(frozen=True)
class BundleDependencies:
    """Verifier phải bind all metric derivatives/independent distance vào request.

    Không có default reviewer: bytes tồn tại và caller ghi CONFIRMED không phải
    bằng chứng toàn scene metric. Tests inject synthetic verifier có nhãn rõ.
    """

    resolve: Callable[[ProductArtifactRef], Path]
    verify_metric: Callable[["BundleBuildRequest"], bool] | None = None
    load_alignment: Callable[[ProductArtifactRef], AlignmentRecord] | None = None

    def require(self, reference: ProductArtifactRef, job_id: str) -> Path:
        """Check producer identity + exact bytes, không tin resolver stub trả path."""
        if reference.job_id != job_id or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/"):
            raise ValueError("bundle dependency belongs to another job")
        path = self.resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("bundle dependency missing or checksum mismatch")
        return path


def validate_bundle_sources(request: "BundleBuildRequest", deps: BundleDependencies) -> None:
    """Fail closed trước publication; không làm RGB canonicalization ngầm."""
    scale = request.metric_scale
    if scale.status != "CONFIRMED" or scale.meters_per_unit is None:
        raise ValueError("bundle requires explicitly verified metric scale")
    if not math.isfinite(scale.meters_per_unit) or scale.meters_per_unit != 1.0:
        raise ValueError("canonical meter bundle must use meters_per_unit=1")
    if request.canonical_geometry_ref is None:
        raise ValueError("canonical_geometry_ref must be explicitly selected and verified")
    _validate_roles(request)
    for ref in bundle_references(request):
        deps.require(ref, request.job_id)
    proof = request.verification_ref
    if proof is None or proof.producer_stage != StageId.METRIC_CANONICALIZE:
        raise ValueError("bundle requires immutable metric verification evidence")
    deps.require(proof, request.job_id)
    _validate_alignment(request, deps)
    if deps.verify_metric is None or deps.verify_metric(request) is not True:
        raise ValueError("bundle metric/derivative verification was not authorized")


def bundle_references(request: "BundleBuildRequest") -> list[ProductArtifactRef]:
    """Full declared dependency inventory, kể cả optional sensor depth."""
    refs = [*request.rgb_frame_refs, *request.camera_pose_refs]
    refs.extend(
        ref
        for ref in (
            request.visual_artifact_ref,
            request.rgb_geometry_ref,
            request.lidar_geometry_ref,
            request.canonical_geometry_ref,
        )
        if ref is not None
    )
    if request.depth_frame_set is not None:
        refs.extend(request.depth_frame_set.frame_refs)
    return refs


def _validate_roles(request: "BundleBuildRequest") -> None:
    for ref in request.camera_pose_refs:
        if ref.artifact_type != "CameraPoseArtifact" or ref.producer_stage not in {
            StageId.CAMERA_POSE,
            StageId.METRIC_CANONICALIZE,
        }:
            raise ValueError("bundle camera pose type/stage mismatch")
    for ref in request.rgb_frame_refs:
        if ref.artifact_type != "RGBFrame" or ref.producer_stage not in {StageId.INPUT_VALIDATE, StageId.FRAME_EXTRACT}:
            raise ValueError("bundle RGB frame type/stage mismatch")
    for ref, kind, stage in (
        (request.visual_artifact_ref, "VisualArtifact", StageId.VISUAL_RECON),
        (request.rgb_geometry_ref, "RgbGeometry", StageId.RGB_GEOMETRY),
        (request.lidar_geometry_ref, "LiDARGeometryArtifact", StageId.LIDAR_INGEST),
    ):
        if ref is not None and (ref.artifact_type != kind or ref.producer_stage != stage):
            raise ValueError("bundle artifact type/stage mismatch")
    if not request.input_configuration.rgb_present and (
        request.rgb_frame_refs or request.camera_pose_refs or request.visual_artifact_ref or request.rgb_geometry_ref
    ):
        raise ValueError("RGB artifacts conflict with input configuration")
    if not request.input_configuration.registered_lidar_present and (
        request.lidar_geometry_ref is not None or request.alignment_record is not None
    ):
        raise ValueError("LiDAR artifacts conflict with input configuration")


def _validate_alignment(request: "BundleBuildRequest", deps: BundleDependencies) -> None:
    record = request.alignment_record
    if record is None:
        return
    reference = ProductArtifactRef(
        artifact_type=record.artifact_type,
        schema_version=record.schema_version,
        artifact_uri=record.artifact_uri,
        artifact_checksum=record.artifact_checksum,
        data_class="derived",
        producer_stage=record.producer_stage,
        job_id=record.job_id,
        source_provenance=record.provenance,
    )
    deps.require(reference, request.job_id)
    for evidence in record.evidence_refs:
        deps.require(evidence, request.job_id)
    if deps.load_alignment is None or deps.load_alignment(reference) != record:
        raise ValueError("bundle alignment differs from verified immutable record")
