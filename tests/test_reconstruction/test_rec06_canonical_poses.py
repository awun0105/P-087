"""Canonical pose publication dùng fixture authority, không xác nhận metric scene thật."""

import hashlib
import json
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.reconstruction.rgb.canonical.canonical_poses import CanonicalCameraPoseArtifact, CanonicalPoseService
from src.services.reconstruction.rgb.canonical.metric_math import canonical_camera_pose
from tests.test_reconstruction.support.rec06_fixtures import acceptance_for, metric_fixture


def pose_service(root: Path) -> tuple:
    """Published raw sources và confirmation đã được fixture verifier kiểm."""
    canonicalizer, request = metric_fixture(root)
    preview = canonicalizer.preview(request)
    record = canonicalizer.confirm(preview, acceptance_for(canonicalizer, preview))
    reference = canonicalizer.publish(record, "rec06-fixture")
    return CanonicalPoseService(canonicalizer), reference, record


def test_publish_and_reload_full_similarity(tmp_path: Path) -> None:
    """Consumer đọc bytes canonical, giữ nguyên intrinsics và bytes raw SfM."""
    service, confirmation_ref, record = pose_service(tmp_path)
    source = record.preview.source_camera_poses
    resolver = service.canonicalizer.deps.visuals
    original = resolver.require(source).read_bytes()
    raw = resolver.poses.load(source)
    reference = service.publish(confirmation_ref)
    artifact = service.load(reference)
    assert artifact.poses == [canonical_camera_pose(p, record.preview.transform) for p in raw.poses]
    x, y, z = raw.poses[0].translation
    assert artifact.poses[0].translation == pytest.approx((10 - 2 * y, 20 + 2 * x, 30 + 2 * z))
    assert artifact.cameras == raw.cameras
    assert artifact.input_frame_ids == raw.input_frame_ids
    assert artifact.unregistered_frame_ids == raw.unregistered_frame_ids
    assert artifact.coordinate_system.world_frame == "world"
    assert artifact.evidence_kind == "synthetic_fixture"
    assert reference.producer_stage == "ST-METRIC-CANONICALIZE"
    assert artifact.artifact_checksum.removeprefix("sha256:") in reference.artifact_uri
    assert resolver.require(source).read_bytes() == original


def test_reject_raw_pose_as_canonical(tmp_path: Path) -> None:
    """Raw poses có checksum đúng vẫn không là artifact canonical."""
    service, _, record = pose_service(tmp_path)
    with pytest.raises(ValueError, match="not a REC-06"):
        service.load(record.preview.source_camera_poses)


@pytest.mark.parametrize("job_id", [None, "another-job"])
def test_confirmation_job_identity_is_required(tmp_path: Path, job_id: str | None) -> None:
    """Không tạo derivative namespace từ confirmation ref thiếu/sai job binding."""
    service, reference, _ = pose_service(tmp_path)
    forged = reference.model_copy(update={"job_id": job_id})
    with pytest.raises(ValueError, match="confirmation job identity"):
        service.build(forged)


def test_reject_corrupted_published_bytes(tmp_path: Path) -> None:
    """Không tin resolver chỉ trả path hay metadata không đổi."""
    service, confirmation_ref, _ = pose_service(tmp_path)
    reference = service.publish(confirmation_ref)
    service.canonicalizer.deps.visuals.require(reference).write_bytes(b"corrupted")
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        service.load(reference)


def test_reject_changed_reference_provenance(tmp_path: Path) -> None:
    """Đổi evidence kind ngoài payload không nâng fixture thành real measurement."""
    service, confirmation_ref, _ = pose_service(tmp_path)
    reference = service.publish(confirmation_ref)
    bad = reference.model_copy(update={"source_provenance": {"evidence_kind": "real_measurement"}})
    with pytest.raises(ValueError, match="identity/provenance mismatch"):
        service.load(bad)


@pytest.mark.parametrize("change", ["translation", "intrinsics", "inventory", "transform", "evidence"])
def test_reject_rehashed_semantically_wrong_payload(tmp_path: Path, change: str) -> None:
    """Checksum tự nhất quán không đủ: compare lại exact raw lineage và phép biến đổi."""
    service, confirmation_ref, _ = pose_service(tmp_path)
    artifact = service.build(confirmation_ref)
    data = artifact.model_dump(mode="json")
    if change == "translation":
        data["poses"][0]["translation"][0] += 1
    elif change == "intrinsics":
        data["cameras"][0]["parameters"][0] += 1
    elif change == "inventory":
        data["unregistered_frame_ids"] = [999]
    elif change == "transform":
        data["transform"]["translation_m"][0] += 1
    else:
        data["evidence_kind"] = "real_measurement"
    _publish_forgery(service, data)


def _publish_forgery(service: CanonicalPoseService, data: dict) -> None:
    """Fixture attacker tự ký hash mới nhưng không đổi confirmed source."""
    from src.services.reconstruction.rgb.canonical.canonical_poses import _reference

    data["artifact_checksum"] = canonical_content_checksum(data, "artifact_checksum")
    artifact = CanonicalCameraPoseArtifact.model_validate(data)
    payload = (json.dumps(data) + "\n").encode()
    reference = _reference(artifact, payload)
    assert reference.artifact_checksum == "sha256:" + hashlib.sha256(payload).hexdigest()
    service.canonicalizer.deps.writer.publish(reference, payload)
    with pytest.raises(ValueError, match="differs from confirmed source transform"):
        service.load(reference)
