"""REC-09 explicit authority + byte checks; không tự xác nhận alignment từ extrinsics."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import AlignmentRecord, AlignmentStatus
from src.services.reconstruction.alignment.models import AlignmentRequest
from src.services.reconstruction.alignment.transforms import validated_transform
from src.services.reconstruction.rgb.frames.frame_set import _sha256
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter


class RgbLidarAlignmentService:
    """Inject resolver/authority; flags và job ID không thay physical same-scene proof."""

    def __init__(
        self,
        writer: ArtifactWriter,
        resolve: Callable[[ProductArtifactRef], Path] | None = None,
        verify_confirmation: Callable[[AlignmentRequest], bool] | None = None,
    ) -> None:
        self.writer, self.resolve, self.verify_confirmation = writer, resolve, verify_confirmation

    def align(self, request: AlignmentRequest) -> tuple[AlignmentRecord, ProductArtifactRef]:
        """Resolve mọi source/evidence trước khi xuất immutable confirmed record."""
        request = AlignmentRequest.model_validate(request.model_dump())
        self._validate_request(request)
        payload = (
            json.dumps(
                {"schema_version": "1.0", "request": request.model_dump(mode="json")}, sort_keys=True, indent=2
            ).encode()
            + b"\n"
        )
        identity = hashlib.sha256(payload).hexdigest()
        reference = ProductArtifactRef(
            artifact_type="AlignmentRecord",
            schema_version="1.0",
            data_class="derived",
            artifact_uri=f"artifact://jobs/{request.job_id}/rec09/{identity}/alignment_evidence.json",
            artifact_checksum="sha256:" + identity,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=request.job_id,
            source_provenance=request.provenance,
        )
        if self.writer.publish(reference, payload) != reference:
            raise ValueError("artifact writer altered alignment publication identity")
        self._require(reference)
        return _record(request, reference), reference

    def _require(self, reference: ProductArtifactRef) -> Path:
        if self.resolve is None:
            raise ValueError("alignment byte resolver is not configured")
        path = self.resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("alignment source/evidence missing or checksum mismatch")
        return path

    def _validate_request(self, request: AlignmentRequest) -> None:
        transform = validated_transform(request.transform_target_from_source)
        if transform.parent_frame != "world":
            raise ValueError("alignment target frame must be canonical 'world'")
        for ref, kind, stage in (
            (request.rgb_geometry_ref, "RgbGeometry", StageId.RGB_GEOMETRY),
            (request.lidar_geometry_ref, "LiDARGeometryArtifact", StageId.LIDAR_INGEST),
        ):
            if ref.artifact_type != kind or ref.producer_stage != stage:
                raise ValueError("alignment geometry artifact type/stage mismatch")
            self._validate_job(ref, request.job_id)
        if not request.same_scene_attestation:
            raise ValueError("alignment requires verified same scene evidence")
        if request.status != AlignmentStatus.CONFIRMED or not request.evidence_refs:
            raise ValueError("alignment requires explicit confirmation and evidence")
        if self.verify_confirmation is None:
            raise ValueError("alignment confirmation verifier is not configured")
        for ref in (request.rgb_geometry_ref, request.lidar_geometry_ref, *request.evidence_refs):
            self._validate_job(ref, request.job_id)
            self._require(ref)
        if self.verify_confirmation(request) is not True:
            raise ValueError("alignment scene/frame/confirmation evidence was not authorized")

    @staticmethod
    def _validate_job(reference: ProductArtifactRef, job_id: str) -> None:
        if reference.job_id != job_id or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/"):
            raise ValueError("artifact job_id does not match alignment publication job")

    def load(self, reference: ProductArtifactRef) -> AlignmentRecord:
        """Đọc lại request đã checksum, recheck authority và bind metadata cùng bytes."""
        reference = ProductArtifactRef.model_validate(reference.model_dump())
        if reference.artifact_type != "AlignmentRecord" or reference.producer_stage != StageId.RGB_LIDAR_ALIGN:
            raise ValueError("not an alignment record reference")
        payload = json.loads(self._require(reference).read_text())
        if set(payload) != {"schema_version", "request"} or payload["schema_version"] != "1.0":
            raise ValueError("invalid alignment evidence payload")
        request = AlignmentRequest.model_validate(payload["request"])
        self._validate_job(reference, request.job_id)
        if reference.source_provenance != request.provenance:
            raise ValueError("alignment reference provenance mismatch")
        self._validate_request(request)
        return _record(request, reference)


def _record(request: AlignmentRequest, reference: ProductArtifactRef) -> AlignmentRecord:
    return AlignmentRecord(
        artifact_type="AlignmentRecord",
        schema_version="1.0",
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id=request.job_id,
        source_lidar_checksum=request.lidar_geometry_ref.artifact_checksum,
        target_rgb_geometry_checksum=request.rgb_geometry_ref.artifact_checksum,
        transform_target_from_source=request.transform_target_from_source,
        status=request.status,
        method=request.method,
        evidence_refs=request.evidence_refs,
        provenance=request.provenance,
    )
