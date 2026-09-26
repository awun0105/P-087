"""Tests cho REC-08 Registered LiDAR Ingest và xuất bản LiDARGeometryArtifact."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import Checksum, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    DependencyOrigin,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
)
from src.services.reconstruction.lidar import (
    LiDARIngestRequest,
    LiDARIngestService,
    build_request_from_rec07_manifest,
    compute_file_checksum,
    inspect_point_cloud_header,
)


class MemoryArtifactWriter:
    """Mock storage phục vụ test publication."""

    def __init__(self) -> None:
        self.published: dict[str, bytes] = {}
        self.refs: dict[str, ProductArtifactRef] = {}

    def publish(self, reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        self.published[reference.artifact_uri] = payload
        self.refs[reference.artifact_uri] = reference
        return reference


def _create_test_ply(path: Path, point_count: int = 10) -> Checksum:
    header = f"ply\nformat ascii 1.0\nelement vertex {point_count}\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
    body = "\n".join(f"{i}.0 {i}.0 {i}.0" for i in range(point_count)) + "\n"
    path.write_text(header + body)
    return compute_file_checksum(path)


def test_inspect_point_cloud_header(tmp_path: Path) -> None:
    """Header inspector đọc đúng số điểm từ PLY và PCD."""
    ply_path = tmp_path / "cloud.ply"
    _create_test_ply(ply_path, 42)
    assert inspect_point_cloud_header(ply_path) == 42

    pcd_path = tmp_path / "cloud.pcd"
    pcd_path.write_text("# .PCD v0.7\nVERSION 0.7\nPOINTS 99\nDATA ascii\n")
    assert inspect_point_cloud_header(pcd_path) == 99

    bad_path = tmp_path / "bad.txt"
    bad_path.write_text("random content without header")
    with pytest.raises(ValueError, match="unsupported point cloud format"):
        inspect_point_cloud_header(bad_path)


def test_lidar_ingest_request_validation(tmp_path: Path) -> None:
    """Kiểm tra các chốt chặn: checksum sai, thiếu file, số điểm vượt ngưỡng, đơn vị sai."""
    ply_path = tmp_path / "cloud.ply"
    chk = _create_test_ply(ply_path, 10)

    prov = PreprocessingProvenance(
        ground_truth_assisted=False,
        dependencies=[PreprocessingDependency(role="scan", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=chk)],
    )

    req = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=ply_path,
        source_input_checksum=chk,
        preprocessing_provenance=prov,
    )
    assert req.validate_payload() == 10

    # 1. Checksum mismatch
    bad_chk = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=ply_path,
        source_input_checksum="sha256:" + "0" * 64,
        preprocessing_provenance=prov,
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        bad_chk.validate_payload()

    # 2. File không tồn tại
    missing_file = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=tmp_path / "nonexistent.ply",
        source_input_checksum=chk,
        preprocessing_provenance=prov,
    )
    with pytest.raises(ValueError, match="LiDAR file missing"):
        missing_file.validate_payload()

    # 3. Đơn vị không phải mét
    with pytest.raises(ValidationError):
        LiDARIngestRequest(
            job_id="job-01",
            lidar_file=ply_path,
            source_input_checksum=chk,
            coordinate_system=CoordinateSystem(unit="millimeter"),  # type: ignore[arg-type]
            preprocessing_provenance=prov,
        )

    # 4. Số điểm dưới min_points
    too_few = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=ply_path,
        source_input_checksum=chk,
        min_points=100,
        preprocessing_provenance=prov,
    )
    with pytest.raises(ValueError, match="too few points"):
        too_few.validate_payload()


def test_lidar_ingest_service_success(tmp_path: Path) -> None:
    """Service xuất bản đúng LiDARGeometryArtifact và manifest."""
    ply_path = tmp_path / "cloud.ply"
    chk = _create_test_ply(ply_path, 25)

    prov = PreprocessingProvenance(
        ground_truth_assisted=True,
        dependencies=[
            PreprocessingDependency(role="trajectory", origin=DependencyOrigin.GROUND_TRUTH, source_checksum=chk)
        ],
    )

    request = LiDARIngestRequest(
        job_id="job-rec08-demo",
        lidar_file=ply_path,
        source_input_checksum=chk,
        preprocessing_provenance=prov,
    )

    writer = MemoryArtifactWriter()
    service = LiDARIngestService(writer)

    artifact, manifest_ref = service.ingest(request)

    assert isinstance(artifact, LiDARGeometryArtifact)
    assert artifact.producer_stage == StageId.LIDAR_INGEST
    assert artifact.job_id == "job-rec08-demo"
    assert artifact.source_modality == "registered_lidar"
    assert artifact.source_input_checksum == chk
    assert artifact.preprocessing_provenance.ground_truth_assisted is True

    # Kiểm tra payload đã publish
    payload_uri = "artifact://jobs/job-rec08-demo/rec08/lidar.ply"
    manifest_uri = "artifact://jobs/job-rec08-demo/rec08/lidar_geometry.json"

    assert payload_uri in writer.published
    assert manifest_uri in writer.published

    published_manifest = json.loads(writer.published[manifest_uri].decode("utf-8"))
    assert published_manifest["artifact_type"] == "LiDARGeometryArtifact"
    assert published_manifest["job_id"] == "job-rec08-demo"


def test_ingest_real_rec07_output() -> None:
    """Kiểm thử ingest file registered_lidar.ply thật sinh ra từ REC-07 smoke."""
    smoke_dir = Path("data/torwic_slam/derived/aisle_cw/rec07_smoke_sub100_104")
    manifest_file = smoke_dir / "preparation_manifest.json"
    ply_file = smoke_dir / "registered_lidar.ply"

    if not manifest_file.is_file() or not ply_file.is_file():
        pytest.skip("Chưa có output smoke REC-07 trên đĩa")

    request = build_request_from_rec07_manifest(manifest_file, ply_file, "job-aisle-cw-01")

    writer = MemoryArtifactWriter()
    service = LiDARIngestService(writer)

    artifact, manifest_ref = service.ingest(request)

    assert artifact.artifact_type == "LiDARGeometryArtifact"
    assert artifact.job_id == "job-aisle-cw-01"
    assert artifact.geometry_format == "ply"
    assert artifact.coordinate_system.unit == "meter"
    assert artifact.preprocessing_provenance.ground_truth_assisted is True
    assert artifact.artifact_uri == "artifact://jobs/job-aisle-cw-01/rec08/lidar.ply"
