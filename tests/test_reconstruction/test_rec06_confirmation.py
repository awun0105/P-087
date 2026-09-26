"""Authority/lineage/immutable publication tests bằng fixture, không fake real scale."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError, ArtifactChecksumError
from src.services.reconstruction.rgb.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.metric_models import MetricConfirmation, MetricRequest, independent_distance_error
from tests.test_reconstruction.rec06_fixtures import acceptance_for, metric_fixture


@pytest.fixture
def context(tmp_path: Path) -> tuple:
    """Mỗi test có immutable store riêng, không sửa artifacts của workspace người dùng."""
    service, request = metric_fixture(tmp_path)
    preview = service.preview(request)
    return service, request, preview, acceptance_for(service, preview)


def test_preview_confirm_publish_resolve_and_plan(context: tuple) -> None:
    """Đi qua actual source resolvers/store; fixture receipt không là real confirmation."""
    service, request, preview, acceptance = context
    assert preview.status == "UNCONFIRMED" and preview.transform.scale_m_per_sfm_unit == 2
    record = service.confirm(preview, acceptance)
    ref = service.publish(record, "rec06-fixture")
    assert service.load(ref) == record
    assert record.scope == "anchor_and_frame_only"
    plan = service.conversion_plan(ref, request.anchor.source_master)
    assert plan.confirmation_checksum == record.record_checksum
    assert plan.output_meters_per_unit == 1 and plan.payload_converted is False
    assert plan.transform.apply_point((1, 2, 3)) == pytest.approx((6, 22, 36))
    assert plan.evidence_kind == "synthetic_fixture"
    with pytest.raises(ValueError, match="synthetic confirmation"):
        service.require_real(ref)
    with pytest.raises(ArtifactAlreadyExistsError):
        service.publish(record, "rec06-fixture")


@pytest.mark.parametrize("failure", ["absent", "no_verifier", "denied", "stale", "kind", "decision_tampered"])
def test_explicit_acceptance_gate(context: tuple, failure: str) -> None:
    """Checksum/CONFIRMED field không tự thay authority verification."""
    service, _, preview, acceptance = context
    if failure == "absent":
        acceptance = None
    elif failure == "no_verifier":
        service = MetricCanonicalizer(replace(service.deps, verify_acceptance=None))
    elif failure == "denied":
        service = MetricCanonicalizer(replace(service.deps, verify_acceptance=lambda p, a: False))
    elif failure == "stale":
        acceptance = acceptance.model_copy(update={"preview_checksum": "sha256:" + "f" * 64})
    elif failure == "kind":
        acceptance = acceptance.model_copy(update={"evidence_kind": "real_measurement"})
    else:
        service.deps.visuals.require(acceptance.decision_ref).write_bytes(b"changed decision")
    with pytest.raises((ValueError, ArtifactChecksumError)):
        service.confirm(preview, acceptance)


@pytest.mark.parametrize("member", ["master", "measurement", "visual", "poses"])
def test_source_change_invalidates_confirmation(context: tuple, member: str) -> None:
    """Review gắn exact source bytes, không chỉ artifact path hoặc task ID."""
    service, request, preview, acceptance = context
    refs = dict(
        master=request.anchor.source_master,
        measurement=request.anchor.measurement_ref,
        visual=request.source_visual,
        poses=preview.source_camera_poses,
    )
    service.deps.visuals.require(refs[member]).write_bytes(b"modified after preview")
    with pytest.raises((ValueError, ArtifactChecksumError)):
        service.confirm(preview, acceptance)


def test_changed_preview_requires_new_acceptance(context: tuple) -> None:
    """Hai valid previews khác scale không dùng chung review decision."""
    service, request, preview, acceptance = context
    data = request.model_dump()
    data["anchor"]["distance_m"] = 2
    revised = service.preview(MetricRequest.model_validate(data))
    assert revised.checksum() != preview.checksum()
    with pytest.raises(ValueError, match="stale"):
        service.confirm(revised, acceptance)
    new_record = service.confirm(revised, acceptance_for(service, revised))
    old_ref = service.publish(service.confirm(preview, acceptance), "rec06-fixture")
    new_ref = service.publish(new_record, "rec06-fixture")
    assert old_ref.artifact_uri != new_ref.artifact_uri
    assert service.load(old_ref).preview.transform.scale_m_per_sfm_unit == 2
    assert service.load(new_ref).preview.transform.scale_m_per_sfm_unit == 4


@pytest.mark.parametrize("failure", ["different_source", "missing_frame", "eval_only", "nan", "coincident"])
def test_preview_input_rejections(context: tuple, failure: str) -> None:
    """Không suy frame mặc định hoặc dùng evaluation-only evidence trong product input."""
    service, request, _, _ = context
    data = request.model_dump()
    if failure == "different_source":
        data["anchor"]["source_master"] = request.source_visual.model_dump()
    elif failure == "missing_frame":
        del data["frame"]
    elif failure == "eval_only":
        data["anchor"]["measurement_ref"]["data_class"] = "evaluation_only"
    elif failure == "nan":
        data["anchor"]["distance_m"] = float("nan")
    else:
        data["anchor"]["point_b"] = data["anchor"]["point_a"]
    with pytest.raises(ValueError):
        service.preview(MetricRequest.model_validate(data))


def test_persisted_record_still_requires_authority(context: tuple) -> None:
    """Load không tin status/chữ ký checksum như quyền xác nhận của Editor."""
    service, _, preview, acceptance = context
    reference = service.publish(service.confirm(preview, acceptance), "rec06-fixture")
    unconfigured = MetricCanonicalizer(replace(service.deps, verify_acceptance=None))
    with pytest.raises(ValueError, match="verifier"):
        unconfigured.load(reference)
    denied = MetricCanonicalizer(replace(service.deps, verify_acceptance=lambda p, a: False))
    with pytest.raises(ValueError, match="not authorized"):
        denied.load(reference)


@pytest.mark.parametrize("failure", ["checksum", "scale", "acceptance"])
def test_record_tampering_rejected(context: tuple, failure: str) -> None:
    """Rehash outer record không làm mismatched transform/acceptance trở nên hợp lệ."""
    service, _, preview, acceptance = context
    payload = service.confirm(preview, acceptance).model_dump(mode="json")
    if failure == "checksum":
        payload["record_checksum"] = "sha256:" + "f" * 64
    elif failure == "scale":
        payload["preview"]["transform"]["scale_m_per_sfm_unit"] = 10
    else:
        payload["acceptance"]["preview_checksum"] = "sha256:" + "f" * 64
    if failure != "checksum":
        payload["record_checksum"] = canonical_content_checksum(payload, "record_checksum")
    with pytest.raises(ValueError):
        MetricConfirmation.model_validate(payload)


def test_conversion_provenance_rejects_second_scaling(context: tuple) -> None:
    """Raw source identity và applied record marker đều phải được kiểm."""
    service, request, preview, acceptance = context
    record = service.confirm(preview, acceptance)
    reference = service.publish(record, "rec06-fixture")
    for applied in (record.record_checksum, "sha256:" + "f" * 64):
        with pytest.raises(ValueError, match="double scaling"):
            service.conversion_plan(reference, request.anchor.source_master, applied)
    with pytest.raises(ValueError, match="raw source"):
        service.conversion_plan(reference, reference)
    assert service.conversion_plan(reference, preview.source_camera_poses).input_ref == preview.source_camera_poses


def test_independent_distance_not_calibration_anchor(context: tuple) -> None:
    """Khoảng cách khác tính tay; không encode ngưỡng acceptance chưa khóa."""
    service, request, preview, acceptance = context
    record = service.confirm(preview, acceptance)
    sample = request.anchor.model_copy(
        update={"anchor_id": "independent", "point_a": (0, 0, 0), "point_b": (0, 0.25, 0), "distance_m": 0.51}
    )
    assert independent_distance_error(record, sample) == pytest.approx(0.01)
    with pytest.raises(ValueError, match="calibration anchor"):
        independent_distance_error(record, request.anchor)
    reversed_anchor = request.anchor.model_copy(
        update={"anchor_id": "renamed", "point_a": request.anchor.point_b, "point_b": request.anchor.point_a}
    )
    with pytest.raises(ValueError, match="calibration anchor"):
        independent_distance_error(record, reversed_anchor)
