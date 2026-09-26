"""Tests cho REC-08 Registered LiDAR Ingest với FilesystemArtifactStore thật."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import Checksum
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    DependencyOrigin,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
)
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.lidar import (
    LiDARIngestRequest,
    LiDARIngestService,
    build_request_from_rec07_manifest,
    compute_file_checksum,
    inspect_point_cloud,
    inspect_point_cloud_header,
    inspect_rec07_preparation,
)


def _create_test_ply(path: Path, point_count: int = 10) -> Checksum:
    header = f"ply\nformat ascii 1.0\nelement vertex {point_count}\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
    body = "\n".join(f"{i}.0 {i}.0 {i}.0" for i in range(point_count)) + "\n"
    path.write_text(header + body)
    return compute_file_checksum(path)


def test_inspect_point_cloud_valid_and_nonfinite(tmp_path: Path) -> None:
    """Header inspector và content validator phát hiện đúng số điểm và loại bỏ NaN/Inf."""
    ply_path = tmp_path / "cloud.ply"
    _create_test_ply(ply_path, 42)
    stats = inspect_point_cloud(ply_path)
    assert stats.point_count == 42
    assert stats.geometry_format == "ply"
    assert inspect_point_cloud_header(ply_path) == 42

    pcd_path = tmp_path / "cloud.pcd"
    pcd_path.write_text(
        "# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 99\nHEIGHT 1\nPOINTS 99\nDATA ascii\n"
        + "1.0 1.0 1.0\n" * 99
    )
    assert inspect_point_cloud(pcd_path).point_count == 99

    nan_path = tmp_path / "nan.ply"
    nan_path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\nnan 0.0 0.0\n"
    )
    with pytest.raises(ValueError, match="non-finite points"):
        inspect_point_cloud(nan_path)

    bad_path = tmp_path / "bad.txt"
    bad_path.write_text("random content without header")
    with pytest.raises(ValueError, match="unsupported point cloud format"):
        inspect_point_cloud(bad_path)


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
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=prov,
    )
    assert req.validate_payload().point_count == 10

    # 1. Checksum mismatch
    bad_chk = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=ply_path,
        source_input_checksum="sha256:" + "0" * 64,
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=prov,
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        bad_chk.validate_payload()

    # 2. File không tồn tại
    missing_file = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=tmp_path / "nonexistent.ply",
        source_input_checksum=chk,
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
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
            source_frame="registered_lidar",
            preprocessing_provenance=prov,
        )

    # 4. Số điểm dưới min_points
    too_few = LiDARIngestRequest(
        job_id="job-01",
        lidar_file=ply_path,
        source_input_checksum=chk,
        min_points=100,
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=prov,
    )
    with pytest.raises(ValueError, match="too few points"):
        too_few.validate_payload()


def test_lidar_ingest_service_filesystem_store_success(tmp_path: Path) -> None:
    """Service xuất bản đúng LiDARGeometryArtifact vào FilesystemArtifactStore thật với checksum chuẩn."""
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
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=prov,
    )
    resolver = ArtifactResolver(tmp_path / "store")
    writer = FilesystemArtifactStore(resolver)
    service = LiDARIngestService(writer)

    result = service.ingest_with_metadata(request)
    artifact, geom_ref = result.artifact, result.geometry_ref

    assert isinstance(artifact, LiDARGeometryArtifact)
    assert artifact.producer_stage == StageId.LIDAR_INGEST
    assert artifact.job_id == "job-rec08-demo"
    assert artifact.source_modality == "registered_lidar"
    assert artifact.source_input_checksum == chk

    # geom_ref trỏ tới file PLY với artifact_type chuẩn
    assert geom_ref.artifact_type == "LiDARGeometryArtifact"
    assert geom_ref.artifact_uri.startswith("artifact://jobs/job-rec08-demo/rec08/")
    assert geom_ref.artifact_checksum == chk
    assert resolver.require(geom_ref).is_file()

    # PreprocessingProvenance deserialize thành công từ provenance của reference
    parsed_prov = PreprocessingProvenance.model_validate(geom_ref.source_provenance)
    assert parsed_prov.ground_truth_assisted is True

    # Manifest metadata cũng được xuất bản và kiểm tra checksum byte thành công
    meta_path = resolver.require(result.metadata_ref)
    assert meta_path.is_file()
    meta_doc = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_doc["artifact_type"] == "LiDARGeometryArtifact"


def test_ingest_real_rec07_output(tmp_path: Path) -> None:
    """Kiểm thử ingest file registered_lidar.ply thật sinh ra từ REC-07 smoke với store thật."""
    smoke_dir = Path("data/torwic_slam/derived/aisle_cw/rec07_smoke_sub100_104")
    manifest_file = smoke_dir / "preparation_manifest.json"
    ply_file = smoke_dir / "registered_lidar.ply"
    if not manifest_file.is_file() or not ply_file.is_file():
        pytest.skip("Chưa có output smoke REC-07 trên đĩa")

    prepared = inspect_rec07_preparation(manifest_file, ply_file)
    assert prepared.coordinate_status == "UNVERIFIED"
    assert prepared.preprocessing_provenance.ground_truth_assisted is True
    assert prepared.preprocessing_provenance.dependencies[0].role == "pose"
    manifest = json.loads(manifest_file.read_text())
    assert prepared.source_frame == manifest["request"]["target_frame"]
    with pytest.raises(ValueError, match="UNVERIFIED"):
        build_request_from_rec07_manifest(manifest_file, ply_file, "job-aisle-cw-01")
