"""Port REC-06 cho PRODUCT: xem trước/xác nhận tỉ lệ từ điểm người dùng chọn (fixture REC-03/04)."""

from pathlib import Path

import pytest

from src.services.orchestration.artifacts import ArtifactNotFoundError
from src.services.reconstruction import UserMetricInput, user_metric_port
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer, MetricDependencies
from tests.test_reconstruction.test_rec04_brush import adapter

JOB = "job-metric-01"


def _world(root: Path):  # noqa: ANN202
    brush, request = adapter(root)
    visual = brush.execute(request)
    resolver = brush.deps.resolver
    writer = brush.deps.publisher.writer
    store_root = root / "store"
    frames = resolver.poses.frames  # fixture để frame set ở store riêng; runtime thật dùng chung một store

    def resolve(reference):  # noqa: ANN001, ANN202
        try:
            return resolver.resolve(reference)
        except ArtifactNotFoundError:
            return frames._resolve(reference)

    port = user_metric_port(resolve, writer, lambda uri: (store_root / uri.removeprefix("artifact://")).is_file())
    cameras = [pose.translation for pose in resolver.poses.load(visual.artifact.source_camera_poses).poses]
    floor_z = min(point[2] for point in cameras) - 1.0  # sàn thấp hơn mọi camera 1 đơn vị SfM
    data = UserMetricInput(
        floor_points=((0.0, 0.0, floor_z), (1.0, 0.0, floor_z), (0.0, 1.0, floor_z)),
        point_a=(0.0, 0.0, floor_z),
        point_b=(0.5, 0.0, floor_z),
        distance_m=2.0,  # 0,5 đơn vị SfM = 2 m → scale 4
    )
    return port, visual, data, resolver, writer


def test_preview_then_confirm_publishes_real_measurement(tmp_path: Path) -> None:
    port, visual, data, resolver, writer = _world(tmp_path)
    summary = port.preview(JOB, visual.reference, data)
    assert summary.scale_m_per_sfm_unit == pytest.approx(4.0)
    assert summary.measured_distance_m == pytest.approx(2.0)
    assert summary.camera_height_min_m == pytest.approx(4.0)  # 1 đơn vị × 4 m
    assert summary.floor_residual_m == pytest.approx(0.0, abs=1e-9)

    decisions: list[tuple[str, str]] = []

    def verify(preview_checksum: str, decision_ref: object) -> bool:
        decisions.append((preview_checksum, decision_ref.artifact_uri))  # type: ignore[attr-defined]
        return True

    evidence = port.preview(JOB, visual.reference, data)  # idempotent: cùng bản khai
    assert evidence.preview_checksum == summary.preview_checksum
    from src.services.reconstruction import publish_json

    decision_ref = publish_json(writer, lambda _: False, JOB, "decisions", data, "TestDecision")
    reference = port.confirm(JOB, visual.reference, data, summary.preview_checksum, decision_ref, verify)
    assert reference.artifact_type == "RGBMetricConfirmation" and reference.job_id == JOB
    assert decisions and decisions[0][0] == summary.preview_checksum

    loader = MetricCanonicalizer(MetricDependencies(resolver, writer, lambda preview, acceptance: True))
    record = loader.require_real(reference)  # consumer thật nhận: evidence_kind = real_measurement
    assert record.status == "CONFIRMED"
    assert record.preview.transform.apply_point(data.point_b) == pytest.approx((2.0, 0.0, 0.0))


def test_confirm_refuses_stale_preview_and_unauthorized_decision(tmp_path: Path) -> None:
    port, visual, data, _, writer = _world(tmp_path)
    summary = port.preview(JOB, visual.reference, data)
    from src.services.reconstruction import publish_json

    decision_ref = publish_json(writer, lambda _: False, JOB, "decisions", data, "TestDecision")
    changed = data.model_copy(update={"distance_m": 2.5})
    with pytest.raises(ValueError, match="đã đổi"):
        port.confirm(JOB, visual.reference, changed, summary.preview_checksum, decision_ref, lambda *_: True)
    with pytest.raises(ValueError, match="not authorized"):
        port.confirm(JOB, visual.reference, data, summary.preview_checksum, decision_ref, lambda *_: False)


def test_degenerate_floor_is_rejected(tmp_path: Path) -> None:
    port, visual, data, _, _ = _world(tmp_path)
    line = data.model_copy(update={"floor_points": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))})
    with pytest.raises(ValueError, match="thẳng hàng"):
        port.preview(JOB, visual.reference, line)
