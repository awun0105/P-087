"""Producer-boundary tests for bounded, lease-fenced LiDAR odometry."""

import hashlib
import io
import json
import os
import struct
import time
import zipfile
from pathlib import Path
from threading import Event, Timer

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import verify_content_checksum
from src.models.contracts.input_assembly import (
    ArchiveMemberRef,
    ClockRelation,
    RuntimeCapabilityKey,
    RuntimeCapabilityRecord,
    RuntimeQualificationStatus,
    TimestampUnit,
)
from src.models.contracts.reconstruction import EstimatedTrajectoryArtifact
from src.models.contracts.retryability import classify_retryability
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.inputs.timestamps import (
    TimestampRowFormatError,
    TimestampRowValueError,
    parse_timestamp_rows,
    timestamps_in_seconds,
)
from src.services.reconstruction.lidar.cloud_payload import load_xyz_points
from src.services.reconstruction.lidar.odometry import (
    KissIcpProcess,
    LidarOdometryCancelledError,
    LidarOdometryLeaseLostError,
    LidarOdometryProcessError,
    LidarOdometryProfile,
    LidarOdometryRuntimeSettings,
    LidarOdometryScanInput,
    LidarOdometryTimeoutError,
    LidarOdometryWorker,
    LidarOdometryWorkerRequest,
)
from src.services.reconstruction.lidar.trajectory_mapping import (
    RGBFrameTimestamp,
    map_estimated_trajectory_to_rgb_frames,
)


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _pcd(points: np.ndarray, *, encoding: str = "ascii") -> bytes:
    header = (
        "VERSION .7\n"
        "FIELDS x y z intensity\n"
        "SIZE 4 4 4 4\n"
        "TYPE F F F F\n"
        "COUNT 1 1 1 1\n"
        f"WIDTH {len(points)}\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {len(points)}\n"
        f"DATA {encoding}\n"
    ).encode("ascii")
    if encoding == "ascii":
        rows = "".join(f"{x} {y} {z} 1\n" for x, y, z in points)
        return header + rows.encode("ascii")
    return header + b"".join(struct.pack("<ffff", float(x), float(y), float(z), 1.0) for x, y, z in points)


def _publish_input(store: FilesystemArtifactStore, uri: str, payload: bytes, artifact_type: str) -> ArtifactRef:
    reference = ArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum=_sha(payload),
        data_class=ArtifactDataClass.PRODUCT_INPUT,
        producer_stage="ST-INPUT-VALIDATE",
        job_id="job-odometry",
    )
    store.publish(reference, payload)
    return reference


def _worker_request(
    store: FilesystemArtifactStore,
    points: np.ndarray,
    *,
    shifts: tuple[float, float, float] = (0.0, -0.1, -0.2),
    input_prefix: str = "input",
) -> LidarOdometryWorkerRequest:
    scans = []
    for index, shift in enumerate(shifts):
        payload = _pcd(points + np.array([shift, 0.0, 0.0]))
        reference = _publish_input(
            store,
            f"artifact://jobs/job-odometry/{input_prefix}/scans/scan-{index}.pcd",
            payload,
            "LidarScan",
        )
        scans.append({"file_id": f"scan-{index}", "reference": reference.model_dump(mode="json")})
    times = _publish_input(
        store,
        f"artifact://jobs/job-odometry/{input_prefix}/timestamps/lidar.txt",
        b"0\n100\n200\n",
        "LidarScanTimestamps",
    )
    return LidarOdometryWorkerRequest.model_validate(
        {
            "job_id": "job-odometry",
            "attempt_id": "attempt-1",
            "assembly_id": "assembly-1",
            "assembly_revision": 3,
            "assembly_checksum": "sha256:" + "1" * 64,
            "recipe_checksum": "sha256:" + "2" * 64,
            "scans": scans,
            "timestamp_file_ref": times.model_dump(mode="json"),
            "timestamp_unit": "milliseconds",
            "scan_coordinate_unit": "m",
            "sensor_frame_id": "lidar",
            "odometry_map_frame_id": "odom-map",
            "profile": {
                "min_range_m": 0,
                "max_range_m": 80,
                "voxel_size_m": 0.25,
                "min_points_per_scan": 10,
                "max_points_per_scan": 20_000,
                "max_total_points": 50_000,
                "prefilter_voxel_m": None,
                "max_num_threads": 2,
                "timestamp_gap_threshold_seconds": 0.15,
            },
        }
    )


def _fake_process_output(
    output_path: Path, profile: LidarOdometryProfile, *, corrupt: bool = False
) -> dict[str, object]:
    del profile
    poses = []
    for index in range(3):
        matrix = np.eye(4)
        matrix[0, 3] = index * 0.1
        poses.append(matrix.tolist())
    if corrupt:
        poses[1][0][0] = 2.0
    output = {
        "schema_version": "1.0",
        "provider_id": "kiss-icp-python",
        "provider_version": "1.3.0",
        "poses": poses,
        "point_counts": [40, 40, 40],
        "provider_elapsed_seconds": 0.2,
        "provider_cpu_seconds": 0.1,
        "provider_peak_rss_bytes": 32_000_000,
        "process_elapsed_seconds": 0.3,
    }
    output_path.write_text(json.dumps(output), encoding="utf-8")
    return output


def test_timestamp_parser_preserves_strict_one_column_upload_classification() -> None:
    values = parse_timestamp_rows("# LiDAR scan time\n0\n100,\n200\n")
    assert values == (0.0, 100.0, 200.0)
    assert timestamps_in_seconds(values, TimestampUnit.MILLISECONDS) == (0.0, 0.1, 0.2)
    with pytest.raises(TimestampRowFormatError):
        parse_timestamp_rows("0 1 2\n")
    with pytest.raises(TimestampRowValueError, match="finite"):
        parse_timestamp_rows("0\nNaN\n")
    with pytest.raises(TimestampRowValueError, match="strictly increasing"):
        parse_timestamp_rows("0\n0\n")


def test_worker_requires_matching_artifact_read_and_write_roots(tmp_path: Path) -> None:
    reader = ArtifactResolver(tmp_path / "read-root")
    writer = FilesystemArtifactStore(ArtifactResolver(tmp_path / "write-root"))
    with pytest.raises(ValueError, match="must share an artifact root"):
        LidarOdometryWorker(reader, writer)


@pytest.mark.parametrize("encoding", ["ascii", "binary"])
def test_load_xyz_points_decodes_bounded_pcd_payload(encoding: str, tmp_path: Path) -> None:
    expected = np.array([[1.0, 2.0, 3.0], [-1.0, 0.5, 4.0]], dtype=np.float64)
    source = tmp_path / "scan.pcd"
    source.write_bytes(_pcd(expected, encoding=encoding))
    points = load_xyz_points(source, max_points=2)
    np.testing.assert_allclose(points, expected)
    with pytest.raises(ValueError, match="budget"):
        load_xyz_points(source, max_points=1)


def test_worker_publishes_byte_verified_scan_native_unqualified_trajectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    generator = np.random.default_rng(41)
    base = generator.uniform([-3, -3, 1], [3, 3, 5], size=(40, 3))
    request = _worker_request(store, base)
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def fake_run(
        manifest: Path, output: Path, log: Path, profile: LidarOdometryProfile, **_: object
    ) -> dict[str, object]:
        del manifest, log
        return _fake_process_output(output, profile)

    monkeypatch.setattr(worker.process, "run", fake_run)
    result = worker.run(request)

    assert [pose.timestamp_seconds for pose in result.trajectory.poses] == [0.0, 0.1, 0.2]
    assert [pose.source_scan_file_id for pose in result.trajectory.poses] == ["scan-0", "scan-1", "scan-2"]
    assert result.trajectory.runtime_qualification_status == "wired_unqualified"
    assert result.trajectory.diagnostics.timestamp_gap_count == 0
    assert result.ingest_binding.source_scan_file_ids == ["scan-0", "scan-1", "scan-2"]
    assert result.ingest_binding.world_frame_status == "pending_world_from_map_confirmation"
    assert result.trajectory.diagnostics.execution_metrics is not None
    verify_content_checksum(result.trajectory, "artifact_checksum")
    stored = resolver.require(result.artifact_ref).read_bytes()
    assert _sha(stored) == result.artifact_ref.artifact_checksum
    assert result.artifact_ref.artifact_checksum != result.trajectory.artifact_checksum
    with pytest.raises(FileExistsError):
        worker.run(request)


def test_worker_binds_zip_scan_member_checksum_and_exact_qualified_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.random.default_rng(8).uniform(1, 4, size=(40, 3)))
    first_scan = request.scans[0]
    source_bytes = resolver.require(first_scan.reference).read_bytes()
    archive_stream = io.BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("scans/000000.pcd", source_bytes)
    archive_bytes = archive_stream.getvalue()
    container_ref = _publish_input(
        store,
        "artifact://jobs/job-odometry/input/lidar.zip",
        archive_bytes,
        "LidarScanArchive",
    )
    archived_scan = LidarOdometryScanInput(
        file_id=first_scan.file_id,
        reference=container_ref,
        archive_member=ArchiveMemberRef(
            container_checksum=container_ref.artifact_checksum,
            member_path="scans/000000.pcd",
            member_checksum=_sha(source_bytes),
            uncompressed_size_bytes=len(source_bytes),
        ),
    )
    runtime = RuntimeCapabilityRecord(
        capability_key=RuntimeCapabilityKey.R5,
        status=RuntimeQualificationStatus.QUALIFIED,
        runtime_id="kiss-icp-python",
        runtime_version="1.3.0",
        qualification_evidence_checksum=_sha(b"qualified held-out runtime envelope"),
    )
    request = request.model_copy(
        update={"scans": [archived_scan, *request.scans[1:]], "runtime_qualification": runtime}
    )
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def fake_run(
        manifest: Path, output: Path, log: Path, profile: LidarOdometryProfile, **_: object
    ) -> dict[str, object]:
        del manifest, log
        return _fake_process_output(output, profile)

    monkeypatch.setattr(worker.process, "run", fake_run)
    result = worker.run(request)

    assert result.trajectory.runtime_qualification_status == "qualified"
    assert result.trajectory.schema_version == "1.1"
    assert result.trajectory.runtime_qualification_evidence_checksum == runtime.qualification_evidence_checksum
    assert result.trajectory.poses[0].source_scan_checksum == _sha(source_bytes)
    assert result.ingest_binding.source_scan_checksums[0] == _sha(source_bytes)


def _diagnostic_trajectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, with_world_frame: bool = True
) -> EstimatedTrajectoryArtifact:
    resolver = ArtifactResolver(tmp_path / "mapping-artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.random.default_rng(17).uniform(1, 5, size=(40, 3)))
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "mapping-attempts",
        ),
    )

    def fake_run(
        manifest: Path, output: Path, log: Path, profile: LidarOdometryProfile, **_: object
    ) -> dict[str, object]:
        del manifest, log
        return _fake_process_output(output, profile)

    monkeypatch.setattr(worker.process, "run", fake_run)
    trajectory = worker.run(request).trajectory
    if not with_world_frame:
        return trajectory
    values = trajectory.model_dump(mode="python")
    values["world_from_map"] = Transform(
        parent_frame="world",
        local_frame="odom-map",
        translation_xyz=(10.0, 20.0, 1.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    return type(trajectory).model_validate(values)


def test_estimated_camera_mapping_interpolates_with_confirmed_frames_and_time_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = _diagnostic_trajectory(tmp_path, monkeypatch)
    sensor_from_camera = Transform(
        parent_frame="lidar",
        local_frame="camera",
        translation_xyz=(0.0, 1.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )

    result = map_estimated_trajectory_to_rgb_frames(
        trajectory,
        (RGBFrameTimestamp(4, 12, 0.2),),
        sensor_from_camera,
        clock_relation=ClockRelation.KNOWN_OFFSET,
        clock_offset_seconds=0.05,
        maximum_interpolation_gap_seconds=0.15,
    )

    assert result.status == "diagnostic_only"
    assert not result.complete_for_consumer
    assert result.reason_codes == ("ODOMETRY_RUNTIME_NOT_QUALIFIED",)
    pose = result.poses[0]
    assert (pose.output_frame_id, pose.source_frame_id) == (4, 12)
    assert (pose.left_scan_index, pose.right_scan_index) == (1, 2)
    assert pose.interpolation_fraction == pytest.approx(0.5)
    assert pose.lidar_timestamp_seconds == pytest.approx(0.15)
    assert pose.world_from_camera.translation_xyz == pytest.approx((10.15, 21.0, 1.0))


def test_estimated_camera_mapping_slerps_orientation_between_scan_poses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = _diagnostic_trajectory(tmp_path, monkeypatch)
    values = trajectory.model_dump(mode="python")
    values["poses"][2]["map_from_sensor"]["rotation_quaternion_xyzw"] = (
        0.0,
        0.0,
        0.7071067811865475,
        0.7071067811865476,
    )
    rotated_trajectory = EstimatedTrajectoryArtifact.model_validate(values)
    calibration = Transform(
        parent_frame="lidar",
        local_frame="camera",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )

    result = map_estimated_trajectory_to_rgb_frames(
        rotated_trajectory,
        (RGBFrameTimestamp(0, 0, 0.15),),
        calibration,
        clock_relation=ClockRelation.SAME_CLOCK,
        clock_offset_seconds=None,
        maximum_interpolation_gap_seconds=0.15,
    )

    assert not result.complete_for_consumer
    assert result.reason_codes == ("ODOMETRY_RUNTIME_NOT_QUALIFIED",)
    assert result.poses[0].world_from_camera.rotation_quaternion_xyzw == pytest.approx(
        (0.0, 0.0, 0.3826834323650898, 0.9238795325112867)
    )


def test_estimated_camera_mapping_blocks_unknown_clock_and_unconfirmed_world_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = (RGBFrameTimestamp(0, 0, 0.05),)
    calibration = Transform(
        parent_frame="lidar",
        local_frame="camera",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    trajectory = _diagnostic_trajectory(tmp_path / "clock", monkeypatch)
    unknown_clock = map_estimated_trajectory_to_rgb_frames(
        trajectory,
        frames,
        calibration,
        clock_relation=ClockRelation.UNKNOWN,
        clock_offset_seconds=None,
        maximum_interpolation_gap_seconds=0.2,
    )
    assert not unknown_clock.complete_for_consumer
    assert unknown_clock.poses == ()
    assert unknown_clock.reason_codes == ("CLOCK_RELATION_REQUIRED", "ODOMETRY_RUNTIME_NOT_QUALIFIED")

    missing_calibration_and_clock = map_estimated_trajectory_to_rgb_frames(
        trajectory,
        frames,
        None,
        clock_relation=ClockRelation.UNKNOWN,
        clock_offset_seconds=None,
        maximum_interpolation_gap_seconds=0.2,
    )
    assert missing_calibration_and_clock.reason_codes == (
        "CAMERA_LIDAR_CALIBRATION_REQUIRED",
        "CLOCK_RELATION_REQUIRED",
        "ODOMETRY_RUNTIME_NOT_QUALIFIED",
    )
    with pytest.raises(ValueError, match="same-clock declaration"):
        map_estimated_trajectory_to_rgb_frames(
            trajectory,
            frames,
            calibration,
            clock_relation=ClockRelation.SAME_CLOCK,
            clock_offset_seconds=0.01,
            maximum_interpolation_gap_seconds=0.2,
        )

    local_trajectory = _diagnostic_trajectory(tmp_path / "world", monkeypatch, with_world_frame=False)
    unconfirmed_world = map_estimated_trajectory_to_rgb_frames(
        local_trajectory,
        frames,
        calibration,
        clock_relation=ClockRelation.SAME_CLOCK,
        clock_offset_seconds=None,
        maximum_interpolation_gap_seconds=0.2,
    )
    assert not unconfirmed_world.complete_for_consumer
    assert unconfirmed_world.reason_codes == (
        "ODOMETRY_RUNTIME_NOT_QUALIFIED",
        "WORLD_FROM_MAP_CONFIRMATION_REQUIRED",
    )
    assert len(unconfirmed_world.poses) == 1
    assert unconfirmed_world.poses[0].map_from_camera.local_frame == "camera"
    assert unconfirmed_world.poses[0].map_from_camera.translation_xyz == pytest.approx((0.05, 0.0, 0.0))
    assert unconfirmed_world.poses[0].world_from_camera is None

    bad_world_frame = trajectory.model_copy(
        update={
            "world_from_map": Transform(
                parent_frame="world",
                local_frame="other-map",
                translation_xyz=(10.0, 20.0, 1.0),
                rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
        }
    )
    with pytest.raises(ValueError, match="does not match the estimated odometry frame"):
        map_estimated_trajectory_to_rgb_frames(
            bad_world_frame,
            frames,
            calibration,
            clock_relation=ClockRelation.SAME_CLOCK,
            clock_offset_seconds=None,
            maximum_interpolation_gap_seconds=0.2,
        )


def test_estimated_camera_mapping_never_extrapolates_or_crosses_large_scan_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = _diagnostic_trajectory(tmp_path, monkeypatch)
    calibration = Transform(
        parent_frame="lidar",
        local_frame="camera",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )

    result = map_estimated_trajectory_to_rgb_frames(
        trajectory,
        (
            RGBFrameTimestamp(0, 0, -0.01),
            RGBFrameTimestamp(1, 1, 0.05),
            RGBFrameTimestamp(2, 2, 0.21),
        ),
        calibration,
        clock_relation=ClockRelation.SAME_CLOCK,
        clock_offset_seconds=None,
        maximum_interpolation_gap_seconds=0.05,
    )

    assert not result.complete_for_consumer
    assert [pose.output_frame_id for pose in result.poses] == []
    assert [item.reason_code for item in result.unmapped_frames] == [
        "RGB_TIMESTAMP_OUTSIDE_LIDAR_TRAJECTORY",
        "LIDAR_TIMESTAMP_GAP_EXCEEDS_LIMIT",
        "RGB_TIMESTAMP_OUTSIDE_LIDAR_TRAJECTORY",
    ]


def test_worker_reports_timestamp_gaps_after_unit_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.ones((40, 3)))
    timestamp_ref = _publish_input(
        store,
        "artifact://jobs/job-odometry/input/timestamps/lidar-gap.txt",
        b"0\n100\n400\n",
        "LidarScanTimestamps",
    )
    request = request.model_copy(update={"attempt_id": "attempt-gaps", "timestamp_file_ref": timestamp_ref})
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def fake_run(
        manifest: Path, output: Path, log: Path, profile: LidarOdometryProfile, **_: object
    ) -> dict[str, object]:
        del manifest, log
        return _fake_process_output(output, profile)

    monkeypatch.setattr(worker.process, "run", fake_run)
    result = worker.run(request)

    assert [pose.timestamp_seconds for pose in result.trajectory.poses] == [0.0, 0.1, 0.4]
    assert result.trajectory.diagnostics.timestamp_gap_count == 1
    assert result.trajectory.diagnostics.maximum_timestamp_gap_seconds == pytest.approx(0.3)


def test_worker_rejects_stale_lease_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.ones((40, 3)))
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def fake_run(
        manifest: Path, output: Path, log: Path, profile: LidarOdometryProfile, **_: object
    ) -> dict[str, object]:
        del manifest, log
        return _fake_process_output(output, profile)

    monkeypatch.setattr(worker.process, "run", fake_run)
    calls = 0

    def lease_is_current() -> bool:
        nonlocal calls
        calls += 1
        return calls < 5

    with pytest.raises(LidarOdometryLeaseLostError):
        worker.run(request, lease_is_current=lease_is_current)
    assert not resolver.resolve(
        "artifact://jobs/job-odometry/attempts/attempt-1/lidar-odometry/trajectory.json"
    ).exists()


def test_worker_rejects_corrupt_provider_se3_without_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.ones((40, 3)))
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def corrupt_run(
        manifest: Path, output: Path, log: Path, profile: LidarOdometryProfile, **_: object
    ) -> dict[str, object]:
        del manifest, log
        return _fake_process_output(output, profile, corrupt=True)

    monkeypatch.setattr(worker.process, "run", corrupt_run)
    with pytest.raises(LidarOdometryProcessError, match=r"proper SE\(3\)"):
        worker.run(request)
    assert not resolver.resolve(
        "artifact://jobs/job-odometry/attempts/attempt-1/lidar-odometry/trajectory.json"
    ).exists()


def test_worker_rejects_timestamp_count_mismatch_before_running_provider(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.ones((40, 3)))
    timestamp_ref = _publish_input(
        store,
        "artifact://jobs/job-odometry/input/timestamps/wrong-count.txt",
        b"0\n100\n",
        "LidarScanTimestamps",
    )
    request = request.model_copy(update={"timestamp_file_ref": timestamp_ref, "attempt_id": "attempt-2"})
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )
    with pytest.raises(ValueError, match="row counts differ"):
        worker.run(request)


def test_worker_request_requires_metric_scan_coordinates(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    payload = _worker_request(store, np.ones((40, 3))).model_dump(mode="json")
    payload["scan_coordinate_unit"] = "mm"
    with pytest.raises(ValidationError, match="requires scan coordinates declared in metres"):
        LidarOdometryWorkerRequest.model_validate(payload)


def test_worker_rejects_sparse_scan_before_starting_provider(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.ones((5, 3)))
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def unexpected_run(*_: object, **__: object) -> dict[str, object]:
        pytest.fail("sparse input must be rejected before KISS-ICP starts")

    worker.process.run = unexpected_run  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="too few points"):
        worker.run(request)


def test_the_point_budget_counts_points_after_the_per_scan_prefilter(tmp_path: Path) -> None:
    """900 điểm/scan cách nhau 3 cm: chỉ còn ~100 sau ô 0,1 m, nên ba scan lọt trần 700 điểm; không lọc thì vượt."""
    grid = np.array([[0.015 + x * 0.03, 0.015 + y * 0.03, 1.0] for x in range(30) for y in range(30)])

    class _Reached(Exception):
        pass

    def attempt(prefilter: float | None, name: str) -> None:
        resolver = ArtifactResolver(tmp_path / name / "artifacts")
        store = FilesystemArtifactStore(resolver)
        request = _worker_request(store, grid)
        profile = LidarOdometryProfile(
            min_range_m=0,
            max_range_m=80,
            voxel_size_m=0.25,
            min_points_per_scan=10,
            max_points_per_scan=2_000,
            max_total_points=700,
            prefilter_voxel_m=prefilter,
        )
        worker = LidarOdometryWorker(
            resolver,
            store,
            LidarOdometryRuntimeSettings(python=Path("/tmp/none/bin/python"), work_root=tmp_path / name / "attempts"),
        )

        def reached(*_: object, **__: object) -> dict[str, object]:
            raise _Reached

        worker.process.run = reached  # type: ignore[method-assign]
        worker.run(request.model_copy(update={"profile": profile}))

    with pytest.raises(ValueError, match="total point budget"):
        attempt(None, "unfiltered")
    with pytest.raises(_Reached):
        attempt(0.1, "filtered")  # qua được bước đếm điểm và tới được provider


def test_worker_enforces_total_point_budget_before_starting_provider(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    request = _worker_request(store, np.ones((40, 3)))
    profile = LidarOdometryProfile(
        min_range_m=0,
        max_range_m=80,
        voxel_size_m=0.25,
        min_points_per_scan=10,
        max_points_per_scan=100,
        max_total_points=100,
        prefilter_voxel_m=None,
    )
    request = request.model_copy(update={"attempt_id": "attempt-budget", "profile": profile})
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=Path("/tmp/r2s-lidar-runtime/bin/python"),
            work_root=tmp_path / "attempts",
        ),
    )

    def unexpected_run(*_: object, **__: object) -> dict[str, object]:
        pytest.fail("total point budget must be enforced before KISS-ICP starts")

    worker.process.run = unexpected_run  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="total point budget"):
        worker.run(request)


@pytest.mark.parametrize(
    ("lease_state", "cancelled", "timeout", "error"),
    [
        (True, True, 10.0, LidarOdometryCancelledError),
        (False, False, 10.0, LidarOdometryLeaseLostError),
        (True, False, 0.05, LidarOdometryTimeoutError),
    ],
)
def test_process_group_is_reaped_on_cancel_timeout_or_stale_lease(
    tmp_path: Path, lease_state: bool, cancelled: bool, timeout: float, error: type[Exception]
) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    fake_python.chmod(0o755)
    settings = LidarOdometryRuntimeSettings(
        python=fake_python,
        work_root=tmp_path / "attempts",
        timeout_seconds=timeout,
    )
    cancel_event = Event()
    timer = Timer(0.1, cancel_event.set)
    if cancelled:
        timer.start()
    process = KissIcpProcess(settings)
    started = time.monotonic()
    try:
        with pytest.raises(error):
            process.run(
                tmp_path / "manifest.json",
                tmp_path / "output.json",
                tmp_path / "provider.log",
                LidarOdometryProfile(
                    min_range_m=0,
                    max_range_m=80,
                    voxel_size_m=0.25,
                    min_points_per_scan=3,
                    max_points_per_scan=100,
                ),
                cancel_event=cancel_event,
                lease_is_current=lambda: lease_state,
            )
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5


def test_odometry_timeout_and_missing_runtime_are_the_only_retryable_worker_errors() -> None:
    assert classify_retryability("LIDAR_ODOMETRY_TIMEOUT") is True
    assert classify_retryability("LIDAR_ODOMETRY_RUNTIME_UNAVAILABLE") is True
    assert classify_retryability("LIDAR_ODOMETRY_OUT_OF_MEMORY") is True
    assert classify_retryability("LIDAR_ODOMETRY_RUNTIME_INCOMPATIBLE") is False
    assert classify_retryability("LIDAR_ODOMETRY_PROCESS_FAILED") is False
    assert classify_retryability("LIDAR_ODOMETRY_LEASE_LOST") is False


@pytest.mark.skipif(
    not os.environ.get("REC17_LIDAR_ODOMETRY_PYTHON"),
    reason="set REC17_LIDAR_ODOMETRY_PYTHON to run the isolated KISS-ICP known-motion check",
)
def test_isolated_kiss_icp_recovers_known_scan_translation_and_publishes(tmp_path: Path) -> None:
    python = Path(os.environ["REC17_LIDAR_ODOMETRY_PYTHON"])
    if not python.is_file():
        pytest.skip("configured KISS-ICP runtime is not installed")
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    generator = np.random.default_rng(1947)
    points = generator.uniform([-4, -3, 1], [4, 3, 6], size=(12_000, 3))
    request = _worker_request(store, points)
    worker = LidarOdometryWorker(
        resolver,
        store,
        LidarOdometryRuntimeSettings(
            python=python,
            work_root=tmp_path / "attempts",
            timeout_seconds=120,
        ),
    )
    result = worker.run(request)

    translations = np.asarray([pose.map_from_sensor.translation_xyz for pose in result.trajectory.poses])
    np.testing.assert_allclose(np.diff(translations[:, 0]), 0.1, atol=0.04)
    assert result.trajectory.provider_version == "1.3.0"
    assert result.trajectory.runtime_qualification_status == "wired_unqualified"
    assert result.trajectory.diagnostics.execution_metrics is not None
    assert result.trajectory.diagnostics.execution_metrics.provider_peak_rss_bytes > 0
    assert result.ingest_binding.source_scan_file_ids == ["scan-0", "scan-1", "scan-2"]
    assert _sha(resolver.require(result.artifact_ref).read_bytes()) == result.artifact_ref.artifact_checksum

    static_request = _worker_request(store, points, shifts=(0.0, 0.0, 0.0), input_prefix="static-input")
    static_request = static_request.model_copy(update={"attempt_id": "attempt-static"})
    static_result = worker.run(static_request)
    assert static_result.trajectory.runtime_qualification_status == "wired_unqualified"
    assert static_result.trajectory.diagnostics.converged_scan_count is None
    assert static_result.trajectory.diagnostics.degenerate_scan_count is None
    assert static_result.trajectory.world_from_map is None


def test_default_profile_pins_the_benchmarked_values_and_its_version() -> None:
    """Đổi giá trị mặc định phải đổi version hồ sơ, vì recipe đã chấp nhận mang checksum của hồ sơ."""
    from src.services.reconstruction.lidar.odometry import (
        DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION,
        default_lidar_odometry_profile,
        lidar_odometry_profile_checksum,
    )

    profile = default_lidar_odometry_profile()
    assert (profile.voxel_size_m, profile.prefilter_voxel_m, profile.max_total_points) == (0.5, 0.1, 50_000_000)
    assert DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION == "rec17-default-v3"
    assert lidar_odometry_profile_checksum().startswith("sha256:")


def test_grid_downsample_keeps_one_stable_point_per_cell() -> None:
    from src.services.reconstruction.lidar.odometry import _grid_downsample

    points = np.array([[0.01, 0.01, 0.0], [0.02, 0.03, 0.0], [0.51, 0.0, 0.0], [0.52, 0.01, 0.0], [5.0, 5.0, 5.0]])
    kept = _grid_downsample(points, 0.1)
    assert len(kept) == 3
    assert np.array_equal(kept, points[[0, 2, 4]])  # điểm đầu mỗi ô, giữ thứ tự gốc
    assert np.array_equal(_grid_downsample(points, 0.1), kept)  # xác định
    assert _grid_downsample(np.empty((0, 3)), 0.1).shape == (0, 3)


def test_prefilter_is_a_worker_only_field_and_never_reaches_the_isolated_runner() -> None:
    from src.services.reconstruction.lidar import odometry

    payload = odometry.default_lidar_odometry_profile().model_dump(
        mode="json", exclude=odometry._WORKER_ONLY_PROFILE_FIELDS
    )
    assert "prefilter_voxel_m" not in payload
    assert set(payload) == {
        "min_range_m",
        "max_range_m",
        "voxel_size_m",
        "min_points_per_scan",
        "max_points_per_scan",
        "max_total_points",
        "max_num_threads",
        "timestamp_gap_threshold_seconds",
    }  # đúng tập khoá mà scripts/gpu/lidar_odometry_runner.py kiểm chặt
