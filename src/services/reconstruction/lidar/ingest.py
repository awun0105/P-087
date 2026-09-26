"""REC-08 Service: Tiếp nhận và thẩm định Registered LiDAR, xuất bản LiDARGeometryArtifact."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    DependencyOrigin,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
)
from src.services.reconstruction.lidar.models import (
    LiDARIngestRequest,
    PrefusedLiDARSource,
    compute_file_checksum,
    inspect_point_cloud,
)
from src.services.reconstruction.rgb.publication import ArtifactWriter


@dataclass(frozen=True)
class LiDARIngestResult:
    """Giữ metadata ref để caller handoff không phải tự đoán URI."""

    artifact: LiDARGeometryArtifact
    geometry_ref: ProductArtifactRef
    metadata_ref: ProductArtifactRef


class LiDARIngestService:
    """Service tiếp nhận LiDAR đã đăng ký và xuất bản artifact bất biến."""

    def __init__(self, writer: ArtifactWriter) -> None:
        self.writer = writer

    def ingest(self, request: LiDARIngestRequest) -> tuple[LiDARGeometryArtifact, ProductArtifactRef]:
        """Compatibility wrapper; caller cần metadata dùng ingest_with_metadata."""
        result = self.ingest_with_metadata(request)
        return result.artifact, result.geometry_ref

    def ingest_with_metadata(self, request: LiDARIngestRequest) -> LiDARIngestResult:
        """Validate payload, giữ source identity trước publication và trả đủ refs."""
        request = LiDARIngestRequest.model_validate(request.model_dump())
        request.validate_payload()
        payload = request.lidar_file.read_bytes()
        if "sha256:" + hashlib.sha256(payload).hexdigest() != request.source_input_checksum:
            raise ValueError("LiDAR payload changed during ingest")
        geom_ref = self._publish_payload(request, payload)
        artifact = self._create_artifact(request, geom_ref)
        metadata_ref = self._publish_manifest(request, artifact)
        return LiDARIngestResult(artifact, geom_ref, metadata_ref)

    def _publish_payload(self, request: LiDARIngestRequest, payload: bytes) -> ProductArtifactRef:
        ref = ProductArtifactRef(
            artifact_type="LiDARGeometryArtifact",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{request.job_id}/rec08/{_identity(request)}/lidar.{request.geometry_format}",
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
            artifact_uri=f"artifact://jobs/{request.job_id}/rec08/{_identity(request)}/lidar_geometry.json",
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
    origin = DependencyOrigin(req_info["pose_origin"])
    if uses_gt != (origin == DependencyOrigin.GROUND_TRUTH):
        raise ValueError("prefusion ground-truth flag disagrees with pose origin")
    dependencies = [
        PreprocessingDependency(
            role="pose",
            origin=origin,
            source_checksum=req_info["trajectory"]["checksum"],
        )
    ]
    for role in ("calibration", "timestamps", "coordinate_evidence"):
        dependencies.append(
            PreprocessingDependency(
                role=role, origin=DependencyOrigin.SENSOR_INPUT, source_checksum=req_info[role]["checksum"]
            )
        )
    for scan in req_info["scans"]:
        dependencies.append(
            PreprocessingDependency(role="scan", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=scan["checksum"])
        )
    return dependencies


def build_request_from_rec07_manifest(manifest_path: Path, ply_path: Path, job_id: str) -> LiDARIngestRequest:
    """Legacy API từ chối implicit canonical promotion; dùng native preparation reader."""
    inspect_rec07_preparation(manifest_path, ply_path)
    raise ValueError("prefusion coordinates UNVERIFIED; canonical coordinate evidence/conversion required")


def _identity(request: LiDARIngestRequest) -> str:
    """Local filesystem path không tham gia portable publication identity."""
    record = request.model_dump(mode="json", exclude={"lidar_file", "min_points", "max_points"})
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspect_rec07_preparation(manifest_path: Path, ply_path: Path) -> PrefusedLiDARSource:
    """Đọc native output cùng lineage; không upgrade thành canonical artifact."""
    doc = _checked_manifest(manifest_path)
    try:
        req, output = doc["request"], doc["output"]
        source = PrefusedLiDARSource(
            source_input_checksum=output["checksum"],
            source_frame=req["target_frame"],
            unit=req["unit"],
            coordinate_status=doc["coordinate_status"],
            confirmed_rgb_alignment=doc["confirmed_rgb_alignment"],
            preprocessing_provenance=PreprocessingProvenance(
                ground_truth_assisted=doc["trajectory_gt_used_for_lidar_prefusion"],
                dependencies=_build_dependencies(req, doc["trajectory_gt_used_for_lidar_prefusion"]),
                details={"prefusion_manifest_checksum": doc["manifest_checksum"]},
            ),
        )
        stats = inspect_point_cloud(ply_path)
        if (
            compute_file_checksum(ply_path) != source.source_input_checksum
            or stats.point_count != output["point_count"]
        ):
            raise ValueError("prefusion output identity/count mismatch")
    except (KeyError, TypeError) as error:
        raise ValueError("incomplete prefusion manifest") from error
    return source


def _checked_manifest(path: Path) -> dict:
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or "manifest_checksum" not in doc:
        raise ValueError("invalid prefusion manifest")
    if doc["manifest_checksum"] != canonical_content_checksum(doc, "manifest_checksum"):
        raise ValueError("prefusion manifest checksum mismatch")
    if doc.get("artifact_type") != "TorwicLiDARPreparation" or doc.get("schema_version") != "1.0":
        raise ValueError("unsupported prefusion manifest")
    return doc
