"""REC-08 Service: Tiếp nhận và thẩm định Registered LiDAR, xuất bản LiDARGeometryArtifact."""

import hashlib
import json
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    DependencyOrigin,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
)
from src.services.reconstruction.lidar.models import LiDARIngestRequest
from src.services.reconstruction.rgb.publication import ArtifactWriter


class LiDARIngestService:
    """Service tiếp nhận LiDAR đã đăng ký và xuất bản artifact bất biến."""

    def __init__(self, writer: ArtifactWriter) -> None:
        self.writer = writer

    def ingest(self, request: LiDARIngestRequest) -> tuple[LiDARGeometryArtifact, ProductArtifactRef]:
        """Thẩm định input, xuất bản payload và manifest theo đúng hợp đồng."""
        request = LiDARIngestRequest.model_validate(request.model_dump())
        request.validate_payload()
        payload = request.lidar_file.read_bytes()
        geom_ref = self._publish_payload(request, payload)
        artifact = self._create_artifact(request, geom_ref)
        self._publish_manifest(request, artifact)
        return artifact, geom_ref

    def _publish_payload(self, request: LiDARIngestRequest, payload: bytes) -> ProductArtifactRef:
        ref = ProductArtifactRef(
            artifact_type="LiDARGeometryArtifact",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.job_id}/rec08/lidar.{request.geometry_format}",
            artifact_checksum=request.source_input_checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.job_id,
            source_provenance=request.preprocessing_provenance.model_dump(mode="json"),
        )
        if self.writer.publish(ref, payload) != ref:
            raise ValueError("artifact writer altered LiDAR payload identity")
        return ref

    def _create_artifact(self, request: LiDARIngestRequest, ref: ProductArtifactRef) -> LiDARGeometryArtifact:
        return LiDARGeometryArtifact(
            artifact_type="LiDARGeometryArtifact",
            schema_version="1.0",
            artifact_uri=ref.artifact_uri,
            artifact_checksum=ref.artifact_checksum,
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.job_id,
            source_modality="registered_lidar",
            source_input_checksum=request.source_input_checksum,
            geometry_format=request.geometry_format,
            coordinate_system=request.coordinate_system,
            source_frame=request.source_frame,
            declared_transform_to_canonical=request.declared_transform_to_canonical,
            preprocessing_provenance=request.preprocessing_provenance,
        )

    def _publish_manifest(self, request: LiDARIngestRequest, artifact: LiDARGeometryArtifact) -> ProductArtifactRef:
        manifest_bytes = artifact.model_dump_json(indent=2).encode("utf-8") + b"\n"
        manifest_checksum = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        manifest_ref = ProductArtifactRef(
            artifact_type="LiDARGeometryMetadata",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.job_id}/rec08/lidar_geometry.json",
            artifact_checksum=manifest_checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.job_id,
            source_provenance=request.preprocessing_provenance.model_dump(mode="json"),
        )
        if self.writer.publish(manifest_ref, manifest_bytes) != manifest_ref:
            raise ValueError("artifact writer altered LiDAR metadata identity")
        return manifest_ref


def _build_dependencies(req_info: dict, uses_gt: bool) -> list[PreprocessingDependency]:
    """Trích xuất danh sách dependencies cảm biến và quỹ đạo từ manifest."""
    return [
        PreprocessingDependency(
            role="trajectory",
            origin=DependencyOrigin.GROUND_TRUTH if uses_gt else DependencyOrigin.ESTIMATED,
            source_checksum=req_info["trajectory"]["checksum"],
        ),
        PreprocessingDependency(
            role="calibration",
            origin=DependencyOrigin.SENSOR_INPUT,
            source_checksum=req_info["calibration"]["checksum"],
        ),
    ]


def build_request_from_rec07_manifest(manifest_path: Path, ply_path: Path, job_id: str) -> LiDARIngestRequest:
    """Tự động chuyển đổi kết quả REC-07 thành LiDARIngestRequest cho REC-08."""
    manifest_data = json.loads(manifest_path.read_text())
    output_info, req_info = manifest_data["output"], manifest_data["request"]
    uses_gt = manifest_data.get("trajectory_gt_used_for_lidar_prefusion", False)
    provenance = PreprocessingProvenance(
        ground_truth_assisted=uses_gt,
        dependencies=_build_dependencies(req_info, uses_gt),
        details={"prefusion_manifest_checksum": manifest_data.get("manifest_checksum", "")},
    )
    return LiDARIngestRequest(
        job_id=job_id,
        lidar_file=ply_path,
        source_input_checksum=output_info["checksum"],
        geometry_format="ply",
        coordinate_system=CoordinateSystem(unit=req_info.get("unit", "meter")),
        source_frame=req_info.get("source_frame", "registered_lidar"),
        preprocessing_provenance=provenance,
    )
