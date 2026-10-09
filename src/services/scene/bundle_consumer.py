"""Đọc handoff EX-REC từ immutable artifact refs cho EX-SCENE."""

import json
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import ArtifactRef, ProductArtifactRef
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.reconstruction import AlignmentRecord, AlignmentStatus, ReconstructionBundle
from src.services.orchestration.artifacts.store import ArtifactResolver
from src.services.reconstruction.alignment.models import AlignmentRequest


@dataclass(frozen=True)
class ValidatedBundleView:
    """Bundle và các payload đã được xác minh trước khi chạy extraction."""

    bundle: ReconstructionBundle
    rgb_frames: tuple[Path, ...]
    camera_poses: tuple[Path, ...]
    canonical_geometry: Path
    visual: Path | None
    rgb_geometry: Path | None
    lidar_geometry: Path | None
    depth_frames: tuple[Path, ...]


def _require_ref(reference: ArtifactRef, resolver: ArtifactResolver, job_id: str) -> Path:
    """Không cho phép ref của job khác đi vào scene prediction."""
    if reference.job_id != job_id or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/"):
        raise ValueError(f"cross-job artifact reference: {reference.artifact_uri}")
    return resolver.require(reference)


def _optional_ref(reference: ProductArtifactRef | None, resolver: ArtifactResolver, job_id: str) -> Path | None:
    """Resolve optional product payload khi được khai báo."""
    return _require_ref(reference, resolver, job_id) if reference is not None else None


def load_reconstruction_bundle(reference: ArtifactRef, resolver: ArtifactResolver) -> ValidatedBundleView:
    """Fail closed với schema, logical checksum và mọi byte ref trước processing."""
    if reference.artifact_type != "ReconstructionBundle" or reference.data_class != "derived":
        raise ValueError("expected derived ReconstructionBundle artifact reference")
    bundle = resolver.load_model(reference, ReconstructionBundle)
    verify_content_checksum(bundle, "artifact_checksum")
    job_id = bundle.job_id
    if reference.job_id != job_id or reference.artifact_uri != bundle.artifact_uri:
        raise ValueError("ReconstructionBundle publication identity mismatch")
    frames = tuple(_require_ref(item, resolver, job_id) for item in bundle.rgb_frame_refs)
    poses = tuple(_require_ref(item, resolver, job_id) for item in bundle.camera_pose_refs)
    depth = bundle.depth_frame_set
    depth_frames = tuple(_require_ref(item, resolver, job_id) for item in depth.frame_refs) if depth else ()
    if bundle.alignment_record is not None:
        alignment = bundle.alignment_record
        alignment_ref = ArtifactRef(
            artifact_type=alignment.artifact_type,
            schema_version=alignment.schema_version,
            artifact_uri=alignment.artifact_uri,
            artifact_checksum=alignment.artifact_checksum,
            data_class="derived",
            producer_stage=alignment.producer_stage,
            job_id=alignment.job_id,
            source_provenance=alignment.provenance,
        )
        alignment_path = _require_ref(alignment_ref, resolver, job_id)
        for item in alignment.evidence_refs:
            _require_ref(item, resolver, job_id)
        payload = json.loads(alignment_path.read_bytes())
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "request"}
            or payload["schema_version"] != "1.0"
        ):
            raise ValueError("invalid published alignment evidence payload")
        request = AlignmentRequest.model_validate(payload["request"])
        if (
            request.status != AlignmentStatus.CONFIRMED
            or not request.same_scene_attestation
            or not request.evidence_refs
        ):
            raise ValueError("published alignment evidence lacks confirmation or same-scene proof")
        if (
            request.job_id != job_id
            or request.rgb_geometry_ref != bundle.rgb_geometry_ref
            or request.lidar_geometry_ref != bundle.lidar_geometry_ref
            or alignment.transform_target_from_source != request.transform_target_from_source
        ):
            raise ValueError("published alignment evidence differs from ReconstructionBundle bindings")
        published_alignment = AlignmentRecord(
            artifact_type=alignment_ref.artifact_type,
            schema_version=alignment_ref.schema_version,
            artifact_uri=alignment_ref.artifact_uri,
            artifact_checksum=alignment_ref.artifact_checksum,
            producer_stage=alignment_ref.producer_stage,
            job_id=request.job_id,
            source_lidar_checksum=request.lidar_geometry_ref.artifact_checksum,
            target_rgb_geometry_checksum=request.rgb_geometry_ref.artifact_checksum,
            transform_target_from_source=request.transform_target_from_source,
            status=request.status,
            method=request.method,
            evidence_refs=request.evidence_refs,
            provenance=request.provenance,
        )
        if published_alignment != alignment:
            raise ValueError("embedded AlignmentRecord differs from its published evidence bytes")
    return ValidatedBundleView(
        bundle=bundle,
        rgb_frames=frames,
        camera_poses=poses,
        canonical_geometry=_require_ref(bundle.canonical_geometry_ref, resolver, job_id),
        visual=_optional_ref(bundle.visual_artifact_ref, resolver, job_id),
        rgb_geometry=_optional_ref(bundle.rgb_geometry_ref, resolver, job_id),
        lidar_geometry=_optional_ref(bundle.lidar_geometry_ref, resolver, job_id),
        depth_frames=depth_frames,
    )
