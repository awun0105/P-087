"""Unit và integration tests cho REC-09 RGB-LiDAR Alignment."""

import hashlib
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    AlignmentStatus,
    PreprocessingProvenance,
)
from src.services.reconstruction.alignment import (
    AlignmentRequest,
    RgbLidarAlignmentService,
    invert_transform,
    load_torwic_cam_to_lidar_transform,
    load_torwic_lidar_to_camera_transform,
    normalize_torwic_extrinsics,
    parse_torwic_calibrations,
)
from src.services.reconstruction.lidar import LiDARIngestRequest, LiDARIngestService
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest
from tests.test_reconstruction.rec09_fixtures import reviewed_fixture
from tests.test_reconstruction.test_rec05_adapter import config
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline


def create_real_lidar_ref(writer: object, job_id: str, tmp_path: Path) -> ProductArtifactRef:
    """Tạo published LiDARGeometryArtifact thông qua LiDARIngestService chuẩn của REC-08."""
    ply_path = tmp_path / f"lidar_input_{job_id}.ply"
    ply_bytes = (
        b"ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\n"
        b"property float y\nproperty float z\nend_header\n0.0 0.0 0.0\n1.0 1.0 1.0\n"
    )
    ply_path.write_bytes(ply_bytes)
    cs = "sha256:" + hashlib.sha256(ply_bytes).hexdigest()
    prov = PreprocessingProvenance(ground_truth_assisted=False, dependencies=[])
    req = LiDARIngestRequest(
        job_id=job_id,
        lidar_file=ply_path,
        source_input_checksum=cs,
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=prov,
    )
    service = LiDARIngestService(writer)
    _, pub_ref = service.ingest(req)
    return pub_ref


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
    lidar_ref = create_real_lidar_ref(canonicalizer.deps.writer, "test-job-rec09", tmp_path)
    tf = normalize_torwic_extrinsics((0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 1.0), ("world", "registered_lidar"))
    align_service = RgbLidarAlignmentService(canonicalizer.deps.writer)
    req = AlignmentRequest(
        job_id="test-job-rec09",
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_ref,
        transform_target_from_source=tf,
        status=AlignmentStatus.CONFIRMED,
        method="calibration_known_transform",
    )
    align_service, req = reviewed_fixture(canonicalizer.deps.writer, req)
    record, pub_ref = align_service.align(req)
    assert align_service.load(pub_ref) == record
    assert record.status == AlignmentStatus.CONFIRMED
    assert record.source_lidar_checksum == lidar_ref.artifact_checksum
    assert record.target_rgb_geometry_checksum == geom_res.geometry_ref.artifact_checksum
    assert record.transform_target_from_source.parent_frame == "world"
    assert record.transform_target_from_source.local_frame == "registered_lidar"
    assert pub_ref.producer_stage == StageId.RGB_LIDAR_ALIGN


def test_alignment_with_real_torwic_calibrations(tmp_path: Path) -> None:
    """Sensor calibration thật không chứng minh alignment với fixture hoặc world map."""
    calib_file = Path("data/torwic_slam/raw/global/calibrations.txt")
    if not calib_file.is_file():
        pytest.skip("calibrations.txt không khả dụng trong môi trường kiểm thử")
    raw_vals = parse_torwic_calibrations(calib_file)
    assert raw_vals["T_cam1_os.px"] == pytest.approx(0.12944592)
    forward = load_torwic_cam_to_lidar_transform(calib_file)
    assert (forward.parent_frame, forward.local_frame) == ("os_sensor", "azure_left_camera")
    tf = load_torwic_lidar_to_camera_transform(calib_file)
    assert (tf.parent_frame, tf.local_frame) == ("azure_left_camera", "os_sensor")
    # Kiểm tra vector t và quaternion q sau khi nghịch đảo T_os_from_cam thành T_cam_from_os
    assert tf.translation_xyz == pytest.approx((-0.0206607, -0.1053642, -0.1414717), abs=1e-5)
    assert tf.rotation_quaternion_xyzw == pytest.approx((0.6116725, -0.39292797, 0.3567415, 0.58668551), abs=1e-5)

    # Roundtrip nghịch đảo lại phải trả về đúng giá trị thô ban đầu
    inv_tf = invert_transform(tf)
    assert inv_tf.translation_xyz == pytest.approx((0.12944592, 0.04299934, -0.1137434), abs=1e-5)


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
    lidar_ref = create_real_lidar_ref(canonicalizer.deps.writer, "test-job-rec09", tmp_path)
    tf = normalize_torwic_extrinsics((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), ("world", "registered_lidar"))
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


def test_alignment_rejects_mismatched_job_id(tmp_path: Path) -> None:
    """Từ chối khi artifact thuộc về một job_id khác."""
    geom_service, canonicalizer, conf_ref, metric_req, _ = setup_pipeline(tmp_path)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="job-A",
        ),
        tmp_path / "workspace_job_a",
    )
    lidar_ref = create_real_lidar_ref(canonicalizer.deps.writer, "job-A", tmp_path)
    tf = normalize_torwic_extrinsics((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), ("world", "registered_lidar"))
    align_service = RgbLidarAlignmentService(canonicalizer.deps.writer)
    req = AlignmentRequest(
        job_id="job-B",
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_ref,
        transform_target_from_source=tf,
    )
    with pytest.raises(ValueError, match="job_id does not match"):
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
    lidar_ref = create_real_lidar_ref(canonicalizer.deps.writer, "test-job-rec09", tmp_path)
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
