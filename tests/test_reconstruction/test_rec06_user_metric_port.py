"""Port REC-06 cho PRODUCT: xem trước/xác nhận tỉ lệ từ điểm người dùng chọn (fixture REC-03/04)."""

import math
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.orchestration.artifacts import ArtifactNotFoundError
from src.services.reconstruction import UserMetricInput, check_tolerance_m, user_metric_port
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
        check_a=(0.0, 0.5, floor_z),
        check_b=(0.0, 0.75, floor_z),
        check_distance_m=1.0,  # 0,25 đơn vị × 4 = 1 m: đoạn kiểm khớp
    )
    return port, visual, data, resolver, writer


def test_preview_then_confirm_publishes_real_measurement(tmp_path: Path) -> None:
    port, visual, data, resolver, writer = _world(tmp_path)
    summary = port.preview(JOB, visual.reference, data)
    assert summary.scale_m_per_sfm_unit == pytest.approx(4.0)
    assert summary.measured_distance_m == pytest.approx(2.0)
    assert summary.camera_height_min_m == pytest.approx(4.0)  # 1 đơn vị × 4 m
    assert summary.floor_residual_m == pytest.approx(0.0, abs=1e-9)
    assert summary.check_measured_m == pytest.approx(1.0) and summary.check_passed
    assert summary.check_tolerance_m == pytest.approx(check_tolerance_m(2.0, 1.0))
    assert summary.distance_source == "user_measured"

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


def test_check_segment_outside_tolerance_blocks_confirmation(tmp_path: Path) -> None:
    port, visual, data, _, writer = _world(tmp_path)
    wrong = data.model_copy(update={"check_distance_m": 1.2})  # đo C–D lệch 20 cm
    summary = port.preview(JOB, visual.reference, wrong)
    assert not summary.check_passed and summary.check_error_m == pytest.approx(0.2)
    from src.services.reconstruction import publish_json

    decision_ref = publish_json(writer, lambda _: False, JOB, "decisions", wrong, "TestDecision")
    with pytest.raises(ValueError, match="vượt ngưỡng"):
        port.confirm(JOB, visual.reference, wrong, summary.preview_checksum, decision_ref, lambda *_: True)


def test_short_segments_and_missing_lidar_are_rejected(tmp_path: Path) -> None:
    port, visual, data, _, _ = _world(tmp_path)
    with pytest.raises(ValueError, match="0,5 m"):
        port.preview(JOB, visual.reference, data.model_copy(update={"check_distance_m": 0.3}))
    with pytest.raises(ValueError, match="quá ngắn"):
        port.preview(JOB, visual.reference, data.model_copy(update={"distance_m": 0.5, "check_distance_m": 5.0}))
    with pytest.raises(ValueError, match="không có số đo LiDAR"):
        port.preview(JOB, visual.reference, data.model_copy(update={"distance_source": "lidar_demo"}))


def _lidar_support(  # noqa: ANN001
    tmp_path: Path, visual, writer, points_world: list, poses_checksum: str | None = None
) -> ProductArtifactRef:
    """Bản ghi hỗ trợ tổng hợp: căn chỉnh scale 4 (khớp scene fixture) + point cloud ở đúng các điểm."""
    import hashlib
    import json
    import struct

    from src.models.contracts.coordinates import CoordinateSystem, Transform
    from src.models.contracts.reconstruction import DependencyOrigin, PreprocessingDependency, PreprocessingProvenance
    from src.services.reconstruction.alignment.similarity import fit_similarity
    from src.services.reconstruction.lidar import LiDARIngestRequest, LiDARIngestService
    from src.services.reconstruction.rgb.canonical.lidar_assist import DemoLidarSupport, support_uri

    body = struct.pack(f"<{3 * len(points_world)}f", *[value for point in points_world for value in point])
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {len(points_world)}\n"
    header += "property float x\nproperty float y\nproperty float z\nend_header\n"
    ply = tmp_path / "lidar.ply"
    ply.write_bytes(header.encode() + body)
    checksum = "sha256:" + hashlib.sha256(ply.read_bytes()).hexdigest()
    request = LiDARIngestRequest(
        job_id=JOB,
        lidar_file=ply,
        source_input_checksum=checksum,
        coordinate_system=CoordinateSystem(),
        source_frame="torwic_map",
        declared_transform_to_canonical=Transform(
            parent_frame="world",
            local_frame="torwic_map",
            translation_xyz=(0.0, 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        preprocessing_provenance=PreprocessingProvenance(
            ground_truth_assisted=False,
            dependencies=[
                PreprocessingDependency(role="scan", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=checksum)
            ],
        ),
    )
    lidar = LiDARIngestService(writer).ingest_with_metadata(request)
    source = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    fit = fit_similarity(source, [tuple(4 * v for v in point) for point in source])  # SfM × 4 = world
    poses = poses_checksum or visual.artifact.source_camera_poses.artifact_checksum
    alignment = {
        "artifact_type": "SfmWorldTrajectoryAlignment",
        "target_frame": "world",
        "fit": fit.model_dump(mode="json"),
        "inputs": {"camera_poses_checksum": poses},
    }

    def publish(uri: str, payload: bytes, kind: str) -> ProductArtifactRef:
        ref = ProductArtifactRef(
            artifact_type=kind,
            schema_version="1.0",
            artifact_uri=uri,
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class="derived",
            producer_stage="ST-RGB-LIDAR-ALIGN",
            job_id=JOB,
        )
        writer.publish(ref, payload)
        return ref

    alignment_ref = publish(
        f"artifact://jobs/{JOB}/rec09/trajectory/a.json", json.dumps(alignment).encode(), "SfmWorldTrajectoryAlignment"
    )
    support = DemoLidarSupport(
        job_id=JOB,
        camera_poses_checksum=poses,
        alignment_ref=alignment_ref,
        lidar_geometry_ref=lidar.geometry_ref,
        lidar_metadata_ref=lidar.metadata_ref,
    )
    return publish(support_uri(JOB), support.model_dump_json().encode(), "DemoLidarSupport")


def test_dataset_distances_come_from_lidar_and_are_rechecked(tmp_path: Path) -> None:
    port, visual, data, _, writer = _world(tmp_path)
    world = [tuple(4 * v for v in point) for point in (data.point_a, data.point_b, data.check_a, data.check_b)]
    support = _lidar_support(tmp_path, visual, writer, world)
    measured = port.lidar_measurements(
        JOB, visual.reference, support, (data.point_a, data.point_b), (data.check_a, data.check_b)
    )
    assert measured.anchor.distance_m == pytest.approx(2.0, abs=1e-5)
    assert measured.check.distance_m == pytest.approx(1.0, abs=1e-5)
    assert measured.anchor.point_sources == ("lidar_surface", "lidar_surface")
    lidar_input = data.model_copy(
        update={
            "distance_source": "lidar_demo",
            "distance_m": measured.anchor.distance_m,
            "check_distance_m": measured.check.distance_m,
        }
    )
    summary = port.preview(JOB, visual.reference, lidar_input, support)
    assert summary.distance_source == "lidar_demo" and summary.check_passed
    tampered = lidar_input.model_copy(update={"distance_m": 2.5})
    with pytest.raises(ValueError, match="không khớp"):
        port.preview(JOB, visual.reference, tampered, support)


def test_lidar_support_must_bind_pose_file_checksum_not_inner_checksum(tmp_path: Path) -> None:
    """Hồi quy 2026-09-30: gắn self-checksum bên trong JSON pose thì không bao giờ khớp ref."""
    port, visual, data, _, writer = _world(tmp_path)
    inner = port.poses.load(visual.artifact.source_camera_poses).artifact_checksum
    assert inner != visual.artifact.source_camera_poses.artifact_checksum
    world = [tuple(4 * v for v in point) for point in (data.point_a, data.point_b, data.check_a, data.check_b)]
    support = _lidar_support(tmp_path, visual, writer, world, poses_checksum=inner)
    with pytest.raises(ValueError, match="camera pose khác"):
        port.lidar_measurements(
            JOB, visual.reference, support, (data.point_a, data.point_b), (data.check_a, data.check_b)
        )


def test_points_without_lidar_coverage_fall_back_to_alignment(tmp_path: Path) -> None:
    """Point cloud chỉ phủ một đoạn: không chặn người dùng, dùng vị trí theo căn chỉnh và ghi nguồn."""
    port, visual, data, _, writer = _world(tmp_path)
    world = [tuple(4 * v for v in point) for point in (data.point_a, data.check_a, data.check_b)]  # thiếu B
    support = _lidar_support(tmp_path, visual, writer, world)
    far_b = (data.point_b[0], data.point_b[1], data.point_b[2] + 0.5)  # 2 m trên sàn, xa mọi điểm LiDAR
    measured = port.lidar_measurements(
        JOB, visual.reference, support, (data.point_a, far_b), (data.check_a, data.check_b)
    )
    assert measured.anchor.point_sources == ("lidar_surface", "trajectory_alignment")
    assert measured.anchor.snap_offsets_m[1] > 0.2
    assert measured.anchor.distance_m == pytest.approx(math.dist((0, 0, 0), (2.0, 0, 2.0)), abs=1e-4)
