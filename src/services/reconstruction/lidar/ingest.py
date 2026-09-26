"""REC-08 Service: Tiếp nhận và thẩm định Registered LiDAR, xuất bản LiDARGeometryArtifact."""

import hashlib
import json
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
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
        request.validate_payload()
        payload = request.lidar_file.read_bytes()

        payload_ref = ProductArtifactRef(
            artifact_type="LiDARPayload",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.job_id}/rec08/lidar.{request.geometry_format}",
            artifact_checksum=request.source_input_checksum,
            data_class="derived",
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.job_id,
            source_provenance={
                "source_frame": request.source_frame,
                "geometry_format": request.geometry_format,
            },
        )
        self.writer.publish(payload_ref, payload)

        artifact = LiDARGeometryArtifact(
            artifact_type="LiDARGeometryArtifact",
            schema_version="1.0",
            artifact_uri=payload_ref.artifact_uri,
            artifact_checksum=payload_ref.artifact_checksum,
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

        manifest_bytes = artifact.model_dump_json(indent=2).encode("utf-8") + b"\n"
        manifest_checksum = "sha256:" + hashlib.sha256(manifest_bytes.strip()).hexdigest()
        manifest_ref = ProductArtifactRef(
            artifact_type="LiDARGeometryArtifact",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.job_id}/rec08/lidar_geometry.json",
            artifact_checksum=manifest_checksum,
            data_class="derived",
            producer_stage=StageId.LIDAR_INGEST,
            job_id=request.job_id,
            source_provenance={
                "payload_uri": payload_ref.artifact_uri,
                "ground_truth_assisted": str(request.preprocessing_provenance.ground_truth_assisted),
            },
        )
        self.writer.publish(manifest_ref, manifest_bytes)
        return artifact, manifest_ref


def build_request_from_rec07_manifest(manifest_path: Path, ply_path: Path, job_id: str) -> LiDARIngestRequest:
    """Tự động chuyển đổi kết quả REC-07 thành LiDARIngestRequest cho REC-08."""
    manifest_data = json.loads(manifest_path.read_text())
    output_info = manifest_data["output"]
    req_info = manifest_data["request"]

    uses_gt = manifest_data.get("trajectory_gt_used_for_lidar_prefusion", False)
    deps = [
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

    provenance = PreprocessingProvenance(
        ground_truth_assisted=uses_gt,
        dependencies=deps,
        details={
            "prefusion_manifest_checksum": manifest_data.get("manifest_checksum", ""),
            "point_count": output_info.get("point_count", 0),
        },
    )

    return LiDARIngestRequest(
        job_id=job_id,
        lidar_file=ply_path,
        source_input_checksum=output_info["checksum"],
        geometry_format="ply",
        coordinate_system=CoordinateSystem(unit=req_info.get("unit", "meter")),
        source_frame=req_info.get("source_frame", "os_sensor"),
        preprocessing_provenance=provenance,
    )
