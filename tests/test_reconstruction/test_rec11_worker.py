"""Unit và integration tests cho REC-11 Reconstruction Worker CLI và Entrypoint."""

from pathlib import Path

from src.models.contracts.artifacts import Checksum
from src.models.contracts.manifests import InputConfiguration, JobStatus, StageId, StageStatus
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.reconstruction.bundle import BundleBuildRequest
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest
from src.services.reconstruction.worker import ReconstructionWorker, WorkerConfig, create_cli_parser, main
from tests.test_reconstruction.test_rec05_adapter import config
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline
from tests.test_reconstruction.test_rec10_bundle import dummy_rgb_frame


def test_worker_run_success(tmp_path: Path) -> None:
    """Worker chạy thành công, hoàn thành stage và ghi nhận StageArtifact SUCCEEDED."""
    job_id = "test-job-rec11-success"
    geom_service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    frame_ref = dummy_rgb_frame(canonicalizer.deps.writer, job_id)
    geom_res = geom_service.execute(
        GeometryExecutionRequest(
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id=job_id,
        ),
        tmp_path / "workspace_geom_worker",
    )
    bundle_req = BundleBuildRequest(
        job_id=job_id,
        source_input_checksum=Checksum("sha256:" + "0" * 64),
        input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
        rgb_frame_refs=[frame_ref],
        camera_pose_refs=[record.preview.source_camera_poses],
        visual_artifact_ref=metric_req.source_visual,
        rgb_geometry_ref=geom_res.geometry_ref,
    )
    worker_cfg = WorkerConfig(
        job_id=job_id,
        store_root=tmp_path / "store",
        workspace_dir=tmp_path / "workspace_worker",
        bundle_request=bundle_req,
    )
    resolver = ArtifactResolver(tmp_path / "store")
    worker = ReconstructionWorker(worker_cfg, canonicalizer.deps.writer, resolver)
    result = worker.run()
    assert result.status == JobStatus.SUCCEEDED
    assert result.current_stage == StageId.METRIC_CANONICALIZE
    assert result.bundle_ref is not None
    assert len(result.stage_artifacts) == 1
    artifact_record = result.stage_artifacts[0]
    assert artifact_record.stage_id == StageId.METRIC_CANONICALIZE
    assert artifact_record.status == StageStatus.SUCCEEDED
    assert artifact_record.artifact_checksum == result.bundle_ref.artifact_checksum


def test_worker_run_failure_captures_error(tmp_path: Path) -> None:
    """Worker xử lý lỗi an toàn khi stage thất bại, ghi nhận ExecutionError có cấu trúc."""
    job_id = "test-job-rec11-fail"
    _, canonicalizer, _, metric_req, _ = setup_pipeline(tmp_path)
    bundle_req = BundleBuildRequest(
        job_id=job_id,
        source_input_checksum=Checksum("sha256:" + "0" * 64),
        input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
        rgb_frame_refs=[],
        camera_pose_refs=[],
        visual_artifact_ref=None,
        rgb_geometry_ref=None,
        canonical_geometry_ref=metric_req.source_visual,
    )
    worker_cfg = WorkerConfig(
        job_id=job_id,
        store_root=tmp_path / "store",
        workspace_dir=tmp_path / "workspace_worker",
        bundle_request=bundle_req,
    )
    resolver = ArtifactResolver(tmp_path / "store")
    worker = ReconstructionWorker(worker_cfg, canonicalizer.deps.writer, resolver)
    result = worker.run()
    assert result.status == JobStatus.FAILED
    assert result.bundle_ref is None
    assert result.error is not None
    assert result.error.stage_id == StageId.METRIC_CANONICALIZE
    assert result.error.error_code == "RECONSTRUCTION_FAILED"
    assert len(result.stage_artifacts) == 1
    assert result.stage_artifacts[0].status == StageStatus.FAILED


def test_worker_cli_parser_and_main(tmp_path: Path) -> None:
    """Kiểm tra parser CLI và entrypoint main với tham số hợp lệ."""
    parser = create_cli_parser()
    args = parser.parse_args(
        ["--job-id", "job-123", "--store-root", str(tmp_path / "store"), "--workspace", str(tmp_path / "ws")]
    )
    assert args.job_id == "job-123"
    assert args.store_root == tmp_path / "store"
    exit_code = main(
        ["--job-id", "job-123", "--store-root", str(tmp_path / "store"), "--workspace", str(tmp_path / "ws")]
    )
    assert exit_code == 0
