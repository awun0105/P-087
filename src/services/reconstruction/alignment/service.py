"""Service xác nhận và xuất bản AlignmentRecord giữa RGB và LiDAR (REC-09)."""

import hashlib

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import AlignmentRecord
from src.services.reconstruction.alignment.models import AlignmentRequest
from src.services.reconstruction.rgb.publication import ArtifactWriter


class RgbLidarAlignmentService:
    """Xác nhận transform giữa same-scene RGB và LiDAR artifacts mà không mutate source."""

    def __init__(self, writer: ArtifactWriter) -> None:
        self.writer = writer

    def align(self, request: AlignmentRequest) -> tuple[AlignmentRecord, ProductArtifactRef]:
        """Thẩm định tiền điều kiện, tính toán canonical checksum và xuất bản AlignmentRecord."""
        request = AlignmentRequest.model_validate(request.model_dump())
        self._validate_request(request)
        record = self._build_record(request)
        payload = record.model_dump_json(indent=2).encode() + b"\n"
        ref = self._publish_record(request.job_id, record, payload)
        return record, ref

    def _validate_request(self, request: AlignmentRequest) -> None:
        if not request.same_scene_attestation:
            raise ValueError("RGB and LiDAR must declare the same scene for alignment")
        if request.rgb_geometry_ref.artifact_type != "RgbGeometry":
            raise ValueError("rgb_geometry_ref must be of type RgbGeometry")
        if request.lidar_geometry_ref.artifact_type != "LiDARGeometryArtifact":
            raise ValueError("lidar_geometry_ref must be of type LiDARGeometryArtifact")
        tf = request.transform_target_from_source
        if tf.parent_frame != "world":
            raise ValueError("alignment target frame must be canonical 'world'")

    def _build_record(self, request: AlignmentRequest) -> AlignmentRecord:
        uri = f"artifact://jobs/{request.job_id}/rec09/alignment_record.json"
        data = dict(
            artifact_type="AlignmentRecord",
            schema_version="1.0",
            artifact_uri=uri,
            artifact_checksum="sha256:" + "0" * 64,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=request.job_id,
            source_lidar_checksum=request.lidar_geometry_ref.artifact_checksum,
            target_rgb_geometry_checksum=request.rgb_geometry_ref.artifact_checksum,
            transform_target_from_source=request.transform_target_from_source.model_dump(mode="json"),
            status=request.status.value,
            method=request.method,
            evidence_refs=[r.model_dump(mode="json") for r in request.evidence_refs],
            provenance=request.provenance,
        )
        data["artifact_checksum"] = canonical_content_checksum(data, "artifact_checksum")
        return AlignmentRecord.model_validate(data)

    def _publish_record(self, job_id: str, record: AlignmentRecord, payload: bytes) -> ProductArtifactRef:
        ref = ProductArtifactRef(
            artifact_type="AlignmentRecord",
            schema_version="1.0",
            artifact_uri=record.artifact_uri,
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=job_id,
            source_provenance=record.provenance,
        )
        if self.writer.publish(ref, payload) != ref:
            raise ValueError("artifact writer altered alignment publication identity")
        return ref
