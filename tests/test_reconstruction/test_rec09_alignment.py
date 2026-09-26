import hashlib
from pathlib import Path

import pytest

from src.models.contracts.artifacts import Checksum, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    AlignmentStatus,
    LiDARGeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
)
from src.services.reconstruction.alignment import (
    AlignmentRequest,
    RgbLidarAlignmentService,
    invert_transform,
    normalize_torwic_extrinsics,
)
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest
from tests.test_reconstruction.test_rec05_adapter import config
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline


def dummy_lidar_ref(writer: object, job_id: str) -> tuple[LiDARGeometryArtifact, ProductArtifactRef]:
    """Tạo mock published LiDARGeometryArtifact theo đúng contract REC-08."""
    dummy_cs = Checksum("sha256:" + "a" * 64)
    data = dict(
        artifact_type="LiDARGeometryArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec08/lidar.pcd",
        artifact_checksum=dummy_cs,
        producer_stage=StageId.LIDAR_INGEST,
        job_id=job_id,
        source_modality="registered_lidar",
        source_input_checksum=dummy_cs,
        geometry_format="pcd",
        coordinate_system=CoordinateSystem().model_dump(mode="json"),
        source_frame="os_sensor",
        preprocessing_provenance=PreprocessingProvenance(
            dependencies=[PreprocessingDependency(role="raw_pcd", origin="sensor_input", source_checksum=dummy_cs)],
            ground_truth_assisted=False,
        ).model_dump(mode="json"),
    )
    artifact = LiDARGeometryArtifact.model_validate(data)
    payload = artifact.model_dump_json(indent=2).encode() + b"\n"
    payload_cs = Checksum("sha256:" + hashlib.sha256(payload).hexdigest())
    ref = ProductArtifactRef(
        artifact_type="LiDARGeometryArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec08/lidar_geometry.json",
        artifact_checksum=payload_cs,
        data_class="derived",
        producer_stage=StageId.LIDAR_INGEST,
        job_id=job_id,
        source_provenance=artifact.preprocessing_provenance.model_dump(mode="json"),
    )
    writer.publish(ref, payload)
    return artifact, ref


def test_alignment_success(tmp_path: Path) -> None:
    """Xác nhận thành công AlignmentRecord liên kết giữa RGB Geometry và LiDAR Geometry."""
    geom_service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec09",
        ),
        tmp_path / "workspace_geom",
    )
    _, lidar_ref = dummy_lidar_ref(canonicalizer.deps.writer, "test-job-rec09")
    tf = normalize_torwic_extrinsics((0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 1.0))
    align_service = RgbLidarAlignmentService(canonicalizer.deps.writer)
    req = AlignmentRequest(
        job_id="test-job-rec09",
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_ref,
        transform_target_from_source=tf,
        status=AlignmentStatus.CONFIRMED,
        method="calibration_known_transform",
    )
    record, pub_ref = align_service.align(req)
    assert record.status == AlignmentStatus.CONFIRMED
    assert record.source_lidar_checksum == lidar_ref.artifact_checksum
    assert record.target_rgb_geometry_checksum == geom_res.geometry_ref.artifact_checksum
    assert record.transform_target_from_source.parent_frame == "world"
    assert record.transform_target_from_source.local_frame == "registered_lidar"
    assert pub_ref.producer_stage == StageId.RGB_LIDAR_ALIGN


def test_alignment_rejects_different_scene(tmp_path: Path) -> None:
    """Từ chối khi không khai báo same_scene_attestation."""
    geom_service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec09",
        ),
        tmp_path / "workspace_geom",
    )
    _, lidar_ref = dummy_lidar_ref(canonicalizer.deps.writer, "test-job-rec09")
    tf = normalize_torwic_extrinsics((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    align_service = RgbLidarAlignmentService(canonicalizer.deps.writer)
    req = AlignmentRequest(
        job_id="test-job-rec09",
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_ref,
        transform_target_from_source=tf,
        same_scene_attestation=False,
    )
    with pytest.raises(ValueError, match="same scene"):
        align_service.align(req)


def test_alignment_rejects_invalid_parent_frame(tmp_path: Path) -> None:
    """Từ chối khi parent_frame của transform không phải là canonical 'world'."""
    geom_service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec09",
        ),
        tmp_path / "workspace_geom",
    )
    _, lidar_ref = dummy_lidar_ref(canonicalizer.deps.writer, "test-job-rec09")
    bad_tf = Transform(
        parent_frame="custom_frame",
        local_frame="registered_lidar",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    align_service = RgbLidarAlignmentService(canonicalizer.deps.writer)
    req = AlignmentRequest(
        job_id="test-job-rec09",
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_ref,
        transform_target_from_source=bad_tf,
    )
    with pytest.raises(ValueError, match="must be canonical 'world'"):
        align_service.align(req)


def test_transform_inversion_roundtrip() -> None:
    """Kiểm tra tính đúng đắn của phép nghịch đảo transform."""
    tf = Transform(
        parent_frame="world",
        local_frame="registered_lidar",
        translation_xyz=(1.0, 2.0, 3.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    inv = invert_transform(tf)
    assert inv.parent_frame == "registered_lidar"
    assert inv.local_frame == "world"
    assert inv.translation_xyz == (-1.0, -2.0, -3.0)
    roundtrip = invert_transform(inv)
    assert roundtrip.parent_frame == tf.parent_frame
    assert roundtrip.local_frame == tf.local_frame
    assert roundtrip.translation_xyz == pytest.approx(tf.translation_xyz)
