"""REC-06 preflight proof: fixture success không được báo final scene CONFIRMED."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.reconstruction.rgb.canonical_poses import CanonicalPoseService
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest
from src.services.reconstruction.rgb.metric_models import DistanceAnchor
from src.services.reconstruction.rgb.metric_verification import (
    CrossArtifactVerificationReport,
    CrossArtifactVerificationRequest,
    MetricVerificationService,
)
from tests.test_reconstruction.support.rec06_fixtures import acceptance_for, publish_evidence
from tests.test_reconstruction.test_rec05_adapter import config
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline


def verification_fixture(root: Path) -> tuple[MetricVerificationService, CrossArtifactVerificationRequest]:
    """Real artifact store; transform process và measurement authority là synthetic."""
    geometry, canonicalizer, reference, metric, _ = setup_pipeline(root)
    result = geometry.execute(
        GeometryExecutionRequest(
            execution_scope="synthetic_fixture",
            confirmation_ref=reference,
            source_visual=metric.source_visual,
            config=config(),
            job_id=reference.job_id,
        ),
        root / "geometry",
    )
    sample = DistanceAnchor(
        anchor_id="independent-ac",
        source_master=metric.anchor.source_master,
        point_a=(0, 0, 3),
        point_b=(0, 0.25, 3),
        distance_m=0.5,
        measurement_ref=publish_evidence(canonicalizer.deps.writer, "independent", {"fixture_distance_m": 0.5}),
    )
    request = CrossArtifactVerificationRequest(
        confirmation_ref=reference,
        visual_ref=metric.source_visual,
        geometry_ref=result.geometry_ref,
        camera_pose_ref=CanonicalPoseService(canonicalizer).publish(reference),
        independent_sample=sample,
        tolerance_m=0.02,
    )
    return MetricVerificationService(canonicalizer), request


def test_preflight_is_not_final_metric_approval(tmp_path: Path) -> None:
    """Có canonical pose bytes vẫn còn thiếu canonical visual và measurement authority."""
    verifier, request = verification_fixture(tmp_path)
    report = verifier.verify(request)
    assert report.status == "PENDING_FINAL_VERIFICATION"
    assert report.evidence_kind == "synthetic_fixture"
    assert report.request == request
    assert report.independent_distance_error_m == pytest.approx(0)
    assert report.num_canonical_poses > 0
    assert "metric_scale" not in report.model_dump()
    with pytest.raises(ValidationError):
        CrossArtifactVerificationReport.model_validate(report.model_dump() | {"status": "CONFIRMED"})


@pytest.mark.parametrize("field", ["independent_sample", "tolerance_m"])
def test_missing_sample_or_tolerance_rejected(tmp_path: Path, field: str) -> None:
    """Không có default 5cm hay optional sample để đi qua acceptance gate."""
    _, request = verification_fixture(tmp_path)
    data = request.model_dump()
    del data[field]
    with pytest.raises(ValidationError, match=field):
        CrossArtifactVerificationRequest.model_validate(data)


@pytest.mark.parametrize("tolerance", [0, -0.1, float("nan"), float("inf"), None])
def test_invalid_tolerance_rejected(tmp_path: Path, tolerance: float | None) -> None:
    """Caller không thể vô hiệu distance check bằng NaN/Inf hoặc zero."""
    verifier, request = verification_fixture(tmp_path)
    with pytest.raises(ValidationError, match="tolerance_m"):
        verifier.verify(request.model_copy(update={"tolerance_m": tolerance}))


def test_independent_distance_exceeds_tolerance(tmp_path: Path) -> None:
    """Sai 10cm trên fixture đo độc lập phải bị từ chối ở threshold explicit 2cm."""
    verifier, request = verification_fixture(tmp_path)
    sample = request.independent_sample.model_copy(update={"distance_m": 0.6})
    with pytest.raises(ValueError, match="exceeds tolerance"):
        verifier.verify(request.model_copy(update={"independent_sample": sample}))


def test_calibration_pair_cannot_be_reused(tmp_path: Path) -> None:
    """Đổi ID/đảo A-B vẫn là calibration pair, không phải test độc lập."""
    verifier, request = verification_fixture(tmp_path)
    record = verifier.canonicalizer.load(request.confirmation_ref)
    anchor = record.preview.request.anchor
    sample = anchor.model_copy(
        update={"anchor_id": "different-id", "point_a": anchor.point_b, "point_b": anchor.point_a}
    )
    with pytest.raises(ValueError, match="cannot be reused"):
        verifier.verify(request.model_copy(update={"independent_sample": sample}))


def test_independent_measurement_payload_must_resolve(tmp_path: Path) -> None:
    """Opaque measurement ref vẫn phải có exact bytes; đây chưa là authority check."""
    verifier, request = verification_fixture(tmp_path)
    verifier.visuals.require(request.independent_sample.measurement_ref).write_bytes(b"changed")
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        verifier.verify(request)


def test_geometry_payload_cannot_be_metadata_only(tmp_path: Path) -> None:
    """Reference provenance hợp lệ không thay payload checksum verification."""
    verifier, request = verification_fixture(tmp_path)
    verifier.visuals.require(request.geometry_ref).write_bytes(b"corrupted")
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        verifier.verify(request)


def test_invalid_glb_with_matching_hash_rejected(tmp_path: Path) -> None:
    """Byte hash đúng không chứng minh payload thực sự là collision mesh hợp lệ."""
    verifier, request = verification_fixture(tmp_path)
    payload = b"not a collision GLB"
    ref = request.geometry_ref.model_copy(
        update={
            "artifact_uri": request.geometry_ref.artifact_uri.replace("collision.glb", "invalid.glb"),
            "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
    )
    verifier.canonicalizer.deps.writer.publish(ref, payload)
    with pytest.raises(ValueError):
        verifier.verify(request.model_copy(update={"geometry_ref": ref}))


@pytest.mark.parametrize(
    "field", ["applied_transform", "source_checksum", "evidence_kind", "coordinate_system", "metric_confirmation_ref"]
)
def test_full_geometry_lineage_required(tmp_path: Path, field: str) -> None:
    """Giữ scalar scale/confirmation hash đúng nhưng bỏ R/t hoặc source vẫn sai."""
    verifier, request = verification_fixture(tmp_path)
    provenance = dict(request.geometry_ref.source_provenance)
    del provenance[field]
    ref = request.geometry_ref.model_copy(update={"source_provenance": provenance})
    with pytest.raises(ValueError, match="full transform/source lineage"):
        verifier.verify(request.model_copy(update={"geometry_ref": ref}))


@pytest.mark.parametrize("field,value", [("producer_stage", "ST-VISUAL-RECON"), ("job_id", "other-job")])
def test_geometry_producer_identity(tmp_path: Path, field: str, value: str) -> None:
    """Không chỉ verify bytes khi artifact thuộc stage/job khác."""
    verifier, request = verification_fixture(tmp_path)
    ref = request.geometry_ref.model_copy(update={field: value})
    with pytest.raises(ValueError, match="type/stage mismatch|different confirmation job"):
        verifier.verify(request.model_copy(update={"geometry_ref": ref}))


def test_raw_poses_are_not_canonical_payload(tmp_path: Path) -> None:
    """Không canonicalize tạm trong memory rồi trả checksum của raw SfM poses."""
    verifier, request = verification_fixture(tmp_path)
    raw = verifier.canonicalizer.load(request.confirmation_ref).preview.source_camera_poses
    with pytest.raises(ValueError, match="not a REC-06 canonical"):
        verifier.verify(request.model_copy(update={"camera_pose_ref": raw}))


def test_poses_from_another_confirmation_rejected(tmp_path: Path) -> None:
    """Cùng source nhưng user đổi world origin phải tạo revision riêng."""
    verifier, request = verification_fixture(tmp_path)
    service = verifier.canonicalizer
    previous = service.load(request.confirmation_ref).preview.request
    frame = previous.frame.model_copy(update={"translation_m": (0, 0, 0)})
    preview = service.preview(previous.model_copy(update={"frame": frame}))
    record = service.confirm(preview, acceptance_for(service, preview))
    other = service.publish(record, request.confirmation_ref.job_id)
    poses = CanonicalPoseService(service).publish(other)
    with pytest.raises(ValueError, match="different metric confirmation"):
        verifier.verify(request.model_copy(update={"camera_pose_ref": poses}))


def test_exact_raw_visual_required(tmp_path: Path) -> None:
    """Raw master trùng nhau không cho phép thay visual ref đã được review."""
    verifier, request = verification_fixture(tmp_path)
    ref = request.visual_ref.model_copy(update={"source_provenance": {"changed": True}})
    with pytest.raises(ValueError, match="exact confirmed source"):
        verifier.verify(request.model_copy(update={"visual_ref": ref}))
