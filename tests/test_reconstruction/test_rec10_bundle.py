"""Unit và integration tests cho REC-10 Publish ReconstructionBundle, kiểm chứng trực tiếp với EX-SCENE consumer."""

import hashlib
from pathlib import Path

import pytest

from src.models.contracts.artifacts import Checksum, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.manifests import InputConfiguration, StageId
from src.models.contracts.reconstruction import (
    AlignmentStatus,
    DependencyOrigin,
    PreprocessingDependency,
    PreprocessingProvenance,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.reconstruction.alignment import (
    AlignmentRequest,
    RgbLidarAlignmentService,
    normalize_torwic_extrinsics,
)
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.lidar import LiDARIngestRequest, LiDARIngestService
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest
from src.services.scene.bundle_consumer import load_reconstruction_bundle
from tests.test_reconstruction.rec09_fixtures import reviewed_fixture
from tests.test_reconstruction.rec10_fixtures import reviewed_bundle_fixture
from tests.test_reconstruction.test_rec05_adapter import config
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline


def dummy_rgb_frame(writer: object, job_id: str) -> ProductArtifactRef:
    """Tạo frame artifact để bundle consumer có thể resolve file thật."""
    payload = b"dummy frame image data"
    ref = ProductArtifactRef(
        artifact_type="RGBFrame",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec02/frames/frame_0000.png",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class="derived",
        producer_stage=StageId.FRAME_EXTRACT,
        job_id=job_id,
    )
    writer.publish(ref, payload)
    return ref


def create_lidar_artifact_via_rec08(writer: object, job_id: str, tmp_path: Path) -> ProductArtifactRef:
    """Tạo LiDAR geometry artifact thật thông qua LiDARIngestService của REC-08."""
    ply_path = tmp_path / "lidar_input.ply"
    ply_bytes = (
        b"ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\n"
        b"property float y\nproperty float z\nend_header\n0.0 0.0 0.0\n1.0 1.0 1.0\n"
    )
    ply_path.write_bytes(ply_bytes)
    cs = "sha256:" + hashlib.sha256(ply_bytes).hexdigest()
    prov = PreprocessingProvenance(
        ground_truth_assisted=False,
        dependencies=[PreprocessingDependency(role="scan", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=cs)],
    )
    req = LiDARIngestRequest(
        job_id=job_id,
        lidar_file=ply_path,
        source_input_checksum=cs,
        coordinate_system=CoordinateSystem(),
        source_frame="registered_lidar",
        preprocessing_provenance=prov,
    )
    service = LiDARIngestService(writer)
    _, geom_ref = service.ingest(req)
    return geom_ref


def test_publish_rgb_only_bundle_and_consume_by_scene(tmp_path: Path) -> None:
    """Tạo và xuất bản RGB-only bundle, thẩm định deserialize trực tiếp từ EX-SCENE consumer."""
    job_id = "test-job-rec10-rgb"
    geom_service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    # Cần re-publish artifacts dưới job_id này để khớp job boundary của SCENE consumer
    frame_ref = dummy_rgb_frame(canonicalizer.deps.writer, job_id)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id=job_id,
        ),
        tmp_path / "workspace_geom_rgb",
    )
    # Pose ref dưới job_id
    poses_path = canonicalizer.deps.visuals.require(record.preview.source_camera_poses)
    pose_ref = ProductArtifactRef(
        artifact_type="CameraPoseArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec03/camera_poses.json",
        artifact_checksum=record.preview.source_camera_poses.artifact_checksum,
        data_class="derived",
        producer_stage=StageId.CAMERA_POSE,
        job_id=job_id,
    )
    canonicalizer.deps.writer.publish(pose_ref, poses_path.read_bytes())
    # Visual ref dưới job_id
    visual_path = canonicalizer.deps.visuals.require(metric_req.source_visual)
    visual_ref = ProductArtifactRef(
        artifact_type="VisualArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec04/visual.json",
        artifact_checksum=metric_req.source_visual.artifact_checksum,
        data_class="derived",
        producer_stage=StageId.VISUAL_RECON,
        job_id=job_id,
        source_provenance=metric_req.source_visual.source_provenance,
    )
    canonicalizer.deps.writer.publish(visual_ref, visual_path.read_bytes())
    bundle_req = BundleBuildRequest(
        job_id=job_id,
        source_input_checksum=Checksum("sha256:" + "1" * 64),
        input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
        rgb_frame_refs=[frame_ref],
        camera_pose_refs=[pose_ref],
        visual_artifact_ref=visual_ref,
        rgb_geometry_ref=geom_res.geometry_ref,
    )
    deps, bundle_req = reviewed_bundle_fixture(canonicalizer.deps.writer, bundle_req)
    bundle_service = ReconstructionBundleService(canonicalizer.deps.writer, deps)
    bundle, bundle_ref = bundle_service.build_and_publish(bundle_req)
    assert bundle.provenance["evidence_kind"] == "synthetic_fixture"
    assert bundle.artifact_type == "ReconstructionBundle"
    assert bundle.producer_stage == StageId.METRIC_CANONICALIZE
    # EX-SCENE consumer direct validation:
    resolver = ArtifactResolver(tmp_path / "store")
    view = load_reconstruction_bundle(bundle_ref, resolver)
    assert view.canonical_geometry.is_file()
    assert len(view.rgb_frames) == 1
    assert len(view.camera_poses) == 1
    assert view.lidar_geometry is None


def test_publish_mixed_rgb_lidar_bundle_and_consume_by_scene(tmp_path: Path) -> None:
    """Tạo và xuất bản Mixed RGB+LiDAR bundle có confirmed alignment, thẩm định trực tiếp qua EX-SCENE consumer."""
    job_id = "test-job-rec10-mixed"
    geom_service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    frame_ref = dummy_rgb_frame(canonicalizer.deps.writer, job_id)
    lidar_pcd_ref = create_lidar_artifact_via_rec08(canonicalizer.deps.writer, job_id, tmp_path)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id=job_id,
        ),
        tmp_path / "workspace_geom_mixed",
    )
    poses_path = canonicalizer.deps.visuals.require(record.preview.source_camera_poses)
    pose_ref = ProductArtifactRef(
        artifact_type="CameraPoseArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec03/camera_poses.json",
        artifact_checksum=record.preview.source_camera_poses.artifact_checksum,
        data_class="derived",
        producer_stage=StageId.CAMERA_POSE,
        job_id=job_id,
    )
    canonicalizer.deps.writer.publish(pose_ref, poses_path.read_bytes())
    visual_path = canonicalizer.deps.visuals.require(metric_req.source_visual)
    visual_ref = ProductArtifactRef(
        artifact_type="VisualArtifact",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec04/visual.json",
        artifact_checksum=metric_req.source_visual.artifact_checksum,
        data_class="derived",
        producer_stage=StageId.VISUAL_RECON,
        job_id=job_id,
        source_provenance=metric_req.source_visual.source_provenance,
    )
    canonicalizer.deps.writer.publish(visual_ref, visual_path.read_bytes())
    tf = normalize_torwic_extrinsics((0.1, 0.2, 0.3), (0.0, 0.0, 0.0, 1.0), ("world", "registered_lidar"))
    align_service = RgbLidarAlignmentService(canonicalizer.deps.writer)
    align_req = AlignmentRequest(
        job_id=job_id,
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_pcd_ref,
        transform_target_from_source=tf,
        status=AlignmentStatus.CONFIRMED,
        method="calibration_known_transform",
    )
    align_service, align_req = reviewed_fixture(canonicalizer.deps.writer, align_req)
    alignment_record, _ = align_service.align(align_req)
    bundle_req = BundleBuildRequest(
        job_id=job_id,
        source_input_checksum=Checksum("sha256:" + "2" * 64),
        input_configuration=InputConfiguration(
            rgb_present=True, registered_lidar_present=True, declared_same_scene=True
        ),
        rgb_frame_refs=[frame_ref],
        camera_pose_refs=[pose_ref],
        visual_artifact_ref=visual_ref,
        rgb_geometry_ref=geom_res.geometry_ref,
        lidar_geometry_ref=lidar_pcd_ref,
        alignment_record=alignment_record,
    )
    deps, bundle_req = reviewed_bundle_fixture(canonicalizer.deps.writer, bundle_req, align_service.load)
    bundle_service = ReconstructionBundleService(canonicalizer.deps.writer, deps)
    bundle, bundle_ref = bundle_service.build_and_publish(bundle_req)
    assert bundle.provenance["evidence_kind"] == "synthetic_fixture"
    assert bundle.alignment_record is not None
    assert bundle.alignment_record.status == AlignmentStatus.CONFIRMED
    # EX-SCENE consumer validation:
    resolver = ArtifactResolver(tmp_path / "store")

    view = load_reconstruction_bundle(bundle_ref, resolver)
    assert view.canonical_geometry.is_file()
    assert view.lidar_geometry is not None and view.lidar_geometry.is_file()


def test_mixed_bundle_missing_alignment_rejected() -> None:
    """Bắt buộc fail closed khi cấu hình mixed RGB+LiDAR nhưng thiếu confirmed alignment."""
    dummy_cs = Checksum("sha256:" + "3" * 64)
    dummy_ref = ProductArtifactRef(
        artifact_type="Dummy",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-01/dummy",
        artifact_checksum=dummy_cs,
        data_class="derived",
        producer_stage=StageId.INPUT_VALIDATE,
        job_id="job-01",
    )
    with pytest.raises(ValueError, match="mixed RGB/LiDAR bundle requires confirmed alignment"):
        BundleBuildRequest(
            job_id="job-01",
            source_input_checksum=dummy_cs,
            input_configuration=InputConfiguration(
                rgb_present=True, registered_lidar_present=True, declared_same_scene=True
            ),
            rgb_frame_refs=[dummy_ref],
            camera_pose_refs=[dummy_ref],
            visual_artifact_ref=dummy_ref,
            rgb_geometry_ref=dummy_ref,
            lidar_geometry_ref=dummy_ref,
            alignment_record=None,
        )
