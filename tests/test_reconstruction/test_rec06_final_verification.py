"""Unit và integration tests cho REC-06 Cross-Artifact Metric Verification."""

from pathlib import Path

import pytest

from src.models.contracts.coordinates import MetricScaleStatus
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest
from src.services.reconstruction.rgb.metric_models import DistanceAnchor
from src.services.reconstruction.rgb.metric_verification import (
    CrossArtifactVerificationRequest,
    MetricVerificationService,
)
from tests.test_reconstruction.test_rec05_adapter import config
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline


def test_cross_artifact_verification_success(tmp_path: Path) -> None:
    """Xác nhận chéo visual, geometry và poses thành công với cùng metric scale."""
    service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    geom_res = service.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec06",
        ),
        tmp_path / "workspace_geom",
    )
    verifier = MetricVerificationService(
        canonicalizer=canonicalizer,
        visuals=canonicalizer.deps.visuals,
        poses=canonicalizer.deps.visuals.poses,
    )
    req = CrossArtifactVerificationRequest(
        confirmation_ref=conf_ref,
        visual_ref=metric_req.source_visual,
        geometry_ref=geom_res.geometry_ref,
        camera_pose_ref=record.preview.source_camera_poses,
    )
    report = verifier.verify(req)
    assert report.status == "CONFIRMED"
    assert report.metric_scale.status == MetricScaleStatus.CONFIRMED
    assert report.metric_scale.meters_per_unit == 1.0
    assert report.confirmation_checksum == record.record_checksum
    assert report.rgb_geometry_checksum == geom_res.geometry_ref.artifact_checksum
    assert report.num_canonical_poses > 0


def test_cross_artifact_verification_with_independent_sample(tmp_path: Path) -> None:
    """Xác nhận khoảng cách mẫu độc lập nằm trong ngưỡng dung sai cho phép."""
    service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    geom_res = service.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec06",
        ),
        tmp_path / "workspace_geom",
    )
    verifier = MetricVerificationService(
        canonicalizer=canonicalizer,
        visuals=canonicalizer.deps.visuals,
        poses=canonicalizer.deps.visuals.poses,
    )
    # Anchor mẫu là: A(0,0,3), B(0.5,0,3), distance=1.0 (scale=2.0)
    # Mẫu độc lập: A(0,0,3), C(0,0.25,3), khoảng cách thật là 0.25 * 2.0 = 0.50m
    sample = DistanceAnchor(
        anchor_id="independent-sample-01",
        source_master=metric_req.anchor.source_master,
        point_a=(0, 0, 3),
        point_b=(0, 0.25, 3),
        distance_m=0.50,
        measurement_ref=metric_req.anchor.measurement_ref,
    )
    req = CrossArtifactVerificationRequest(
        confirmation_ref=conf_ref,
        visual_ref=metric_req.source_visual,
        geometry_ref=geom_res.geometry_ref,
        camera_pose_ref=record.preview.source_camera_poses,
        independent_sample=sample,
        tolerance_m=0.02,
    )
    report = verifier.verify(req)
    assert report.independent_distance_error_m == pytest.approx(0.0, abs=1e-5)


def test_cross_artifact_verification_rejects_exceeded_tolerance(tmp_path: Path) -> None:
    """Từ chối khi sai số khoảng cách độc lập vượt quá ngưỡng cho phép."""
    service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    geom_res = service.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec06",
        ),
        tmp_path / "workspace_geom",
    )
    verifier = MetricVerificationService(
        canonicalizer=canonicalizer,
        visuals=canonicalizer.deps.visuals,
        poses=canonicalizer.deps.visuals.poses,
    )
    # Đo được là 0.50m, nhưng mẫu ghi là 0.60m -> sai số 0.10m > tolerance 0.02m
    sample = DistanceAnchor(
        anchor_id="independent-sample-02",
        source_master=metric_req.anchor.source_master,
        point_a=(0, 0, 3),
        point_b=(0, 0.25, 3),
        distance_m=0.60,
        measurement_ref=metric_req.anchor.measurement_ref,
    )
    req = CrossArtifactVerificationRequest(
        confirmation_ref=conf_ref,
        visual_ref=metric_req.source_visual,
        geometry_ref=geom_res.geometry_ref,
        camera_pose_ref=record.preview.source_camera_poses,
        independent_sample=sample,
        tolerance_m=0.02,
    )
    with pytest.raises(ValueError, match="exceeds tolerance"):
        verifier.verify(req)


def test_cross_artifact_verification_rejects_unmatched_geometry(tmp_path: Path) -> None:
    """Từ chối khi geometry artifact mang provenance không khớp confirmation record."""
    service, canonicalizer, conf_ref, metric_req, record = setup_pipeline(tmp_path)
    geom_res = service.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=conf_ref,
            source_visual=metric_req.source_visual,
            config=config(),
            job_id="test-job-rec06",
        ),
        tmp_path / "workspace_geom",
    )
    verifier = MetricVerificationService(
        canonicalizer=canonicalizer,
        visuals=canonicalizer.deps.visuals,
        poses=canonicalizer.deps.visuals.poses,
    )
    bad_geom = geom_res.geometry_ref.model_copy(
        update={"source_provenance": {"applied_confirmation_checksum": "sha256:" + "0" * 64}}
    )
    req = CrossArtifactVerificationRequest(
        confirmation_ref=conf_ref,
        visual_ref=metric_req.source_visual,
        geometry_ref=bad_geom,
        camera_pose_ref=record.preview.source_camera_poses,
    )
    with pytest.raises(ValueError, match="not produced with this confirmed metric record"):
        verifier.verify(req)
