"""REC-06 camera derivative: publish bytes đã áp similarity, giữ raw SfM bất biến."""

import hashlib
from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.canonical.metric_math import (
    CanonicalCameraPose,
    SimilarityTransform,
    canonical_camera_pose,
)
from src.services.reconstruction.rgb.canonical.metric_models import EvidenceKind
from src.services.reconstruction.rgb.pose.camera_pose import CameraIntrinsics


class CanonicalCameraPoseArtifact(ContractModel):
    """Manifest nội bộ có lineage; canonical poses không thay raw sparse model."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["CameraPoseArtifact"] = "CameraPoseArtifact"
    source_camera_poses: ProductArtifactRef
    source_frame_set: ProductArtifactRef
    confirmation_ref: ProductArtifactRef
    confirmation_checksum: Checksum
    transform: SimilarityTransform
    evidence_kind: EvidenceKind
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    camera_axes: Literal["x_right_y_down_z_forward"] = "x_right_y_down_z_forward"
    transform_semantics: Literal["parent_from_local"] = "parent_from_local"
    input_frame_ids: list[int]
    unregistered_frame_ids: list[int]
    cameras: list[CameraIntrinsics]
    poses: list[CanonicalCameraPose] = Field(min_length=1)
    artifact_checksum: Checksum

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if canonical_content_checksum(self, "artifact_checksum") != self.artifact_checksum:
            raise ValueError("canonical camera pose content checksum mismatch")
        return self


class CanonicalPoseService:
    """Dùng resolver/writer đã inject; load kiểm cả authority lẫn transform payload."""

    def __init__(self, canonicalizer: MetricCanonicalizer) -> None:
        self.canonicalizer = canonicalizer

    def build(self, confirmation_ref: ProductArtifactRef) -> CanonicalCameraPoseArtifact:
        """Chỉ lấy raw poses từ confirmation; không nhận derivative để scale lần hai."""
        record = self.canonicalizer.load(confirmation_ref)
        source = record.preview.source_camera_poses
        raw = self.canonicalizer.deps.visuals.poses.load(source)
        payload = dict(
            schema_version="1.0",
            artifact_type="CameraPoseArtifact",
            source_camera_poses=source.model_dump(mode="json"),
            source_frame_set=raw.source_frame_set.model_dump(mode="json"),
            confirmation_ref=confirmation_ref.model_dump(mode="json"),
            confirmation_checksum=record.record_checksum,
            transform=record.preview.transform.model_dump(mode="json"),
            evidence_kind=record.preview.request.evidence_kind,
            coordinate_system=CoordinateSystem().model_dump(mode="json"),
            camera_axes=raw.camera_axes,
            transform_semantics=raw.transform_semantics,
            input_frame_ids=raw.input_frame_ids,
            unregistered_frame_ids=raw.unregistered_frame_ids,
            cameras=[camera.model_dump(mode="json") for camera in raw.cameras],
            poses=[canonical_camera_pose(pose, record.preview.transform).model_dump(mode="json") for pose in raw.poses],
            artifact_checksum="sha256:" + "0" * 64,
        )
        payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
        return CanonicalCameraPoseArtifact.model_validate(payload)

    def publish(self, confirmation_ref: ProductArtifactRef) -> ProductArtifactRef:
        """Content-addressed derivative riêng, không overwrite raw poses hoặc revision."""
        artifact = self.build(confirmation_ref)
        payload = artifact.model_dump_json(indent=2).encode() + b"\n"
        reference = _reference(artifact, payload)
        if self.canonicalizer.deps.writer.publish(reference, payload) != reference:
            raise ValueError("artifact writer changed canonical pose identity")
        self.load(reference)
        return reference

    def load(self, reference: ProductArtifactRef) -> CanonicalCameraPoseArtifact:
        """Không tin checksum/provenance tự khai: recompute từ exact confirmed source."""
        reference = ProductArtifactRef.model_validate(reference.model_dump())
        if reference.artifact_type != "CameraPoseArtifact" or reference.producer_stage != StageId.METRIC_CANONICALIZE:
            raise ValueError("not a REC-06 canonical camera pose artifact")
        payload = self.canonicalizer.deps.visuals.require(reference).read_bytes()
        artifact = CanonicalCameraPoseArtifact.model_validate_json(payload)
        if reference != _reference(artifact, payload):
            raise ValueError("canonical pose reference identity/provenance mismatch")
        if artifact != self.build(artifact.confirmation_ref):
            raise ValueError("canonical pose payload differs from confirmed source transform")
        return artifact


def _reference(artifact: CanonicalCameraPoseArtifact, payload: bytes) -> ProductArtifactRef:
    job_id = artifact.confirmation_ref.job_id
    identity = artifact.artifact_checksum.removeprefix("sha256:")
    return ProductArtifactRef(
        artifact_type="CameraPoseArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec06/{identity}/camera_poses.json",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class="derived",
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
        source_provenance=dict(
            producer_version="rec06-canonical-poses-v1",
            evidence_kind=artifact.evidence_kind,
            applied_confirmation_checksum=artifact.confirmation_checksum,
            source_camera_pose_checksum=artifact.source_camera_poses.artifact_checksum,
            applied_transform=artifact.transform.model_dump(mode="json"),
        ),
    )
