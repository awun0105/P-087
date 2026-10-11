"""Worker integration for source-bound LiDAR projection and inspectable overlays."""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

import numpy as np

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.input_assembly import (
    ClockRelation,
    DistanceUnit,
    EvidenceProvenance,
    EvidenceValue,
    InputAssemblyDeclarations,
    TimestampUnit,
)
from src.models.contracts.lidar_calibration_qa import LidarCalibrationQAResult
from src.models.contracts.lidar_projection_qa import LidarCalibrationProjectionEvidence
from src.models.contracts.manifests import InputConfiguration, InputFile, InputManifest, LidarMetadata, StageId
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore, sha256_bytes
from src.services.reconstruction.inputs.detect import LidarEvidence
from src.services.reconstruction.lidar.calibration_qa_worker import run_lidar_calibration_qa
from src.services.reconstruction.lidar.fusion import FusionStats
from src.services.reconstruction.lidar.package import (
    CAMERA_FRAME,
    SENSOR_FRAME,
    CameraCalibration,
    LidarPackageRecord,
    Transform,
)
from src.services.reconstruction.rgb.frames.frame_set import NormalizedRGBFrame, NormalizedRGBFrameSet

JOB_ID = "job-lidar-qa-worker"
ZERO_CHECKSUM = "sha256:" + "0" * 64


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes((24, 28, 34)) * width
    pixels = row * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def _publish(
    store: FilesystemArtifactStore,
    name: str,
    artifact_type: str,
    payload: bytes,
    *,
    producer_stage: StageId,
    data_class: ArtifactDataClass = ArtifactDataClass.DERIVED,
) -> ProductArtifactRef:
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB_ID}/test-inputs/{name}",
        artifact_checksum=sha256_bytes(payload),
        data_class=data_class,
        producer_stage=producer_stage,
        job_id=JOB_ID,
    )
    store.publish(reference, payload)
    return reference


def _pcd(points: np.ndarray) -> bytes:
    rows = "\n".join(" ".join(f"{value:.8f}" for value in point) for point in points)
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\n"
        "TYPE F F F\nCOUNT 1 1 1\n"
        f"WIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA ascii\n"
    )
    return (header + rows + "\n").encode()


def _camera_rig() -> tuple[CameraCalibration, np.ndarray, np.ndarray, np.ndarray]:
    camera = CameraCalibration(
        width=320,
        height=240,
        fx=200,
        fy=200,
        cx=160,
        cy=120,
        distortion=(0.0, 0.0, 0.0, 0.0),
        distortion_status="declared",
    )
    pixels: list[tuple[int, int]] = []
    normals: list[tuple[float, float]] = []
    for u in range(28, 293, 5):
        pixels.extend(((u, 55), (u, 185)))
        normals.extend(((0.0, 1.0), (0.0, 1.0)))
    for v in range(28, 213, 5):
        pixels.extend(((65, v), (255, v)))
        normals.extend(((1.0, 0.0), (1.0, 0.0)))
    edge_pixels = np.asarray(pixels, dtype=np.float64)
    edge_normals = np.asarray(normals, dtype=np.float64)
    depth = 4.0
    points = np.column_stack(
        (
            (edge_pixels[:, 0] - camera.cx) * depth / camera.fx,
            (edge_pixels[:, 1] - camera.cy) * depth / camera.fy,
            np.full(len(edge_pixels), depth),
        )
    )
    return camera, points, edge_pixels, edge_normals


def _frame_set(
    store: FilesystemArtifactStore,
    input_manifest_checksum: str,
    image: bytes,
) -> ProductArtifactRef:
    frame_timestamps = ["0.0", "0.1", "0.2"]
    frame_images = [
        _publish(store, f"rgb-{index}.png", "RGBFrameImage", image, producer_stage=StageId.FRAME_EXTRACT)
        for index in range(len(frame_timestamps))
    ]
    frames = [
        NormalizedRGBFrame(
            frame_id=index,
            timestamp_sec=timestamp,
            image=reference,
            source_checksum=reference.artifact_checksum,
        )
        for index, (timestamp, reference) in enumerate(zip(frame_timestamps, frame_images, strict=True))
    ]
    timestamp_inventory_checksum = (
        "sha256:"
        + hashlib.sha256(
            json.dumps({str(frame.frame_id): frame.timestamp_sec for frame in frames}, sort_keys=True).encode()
        ).hexdigest()
    )
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "input_manifest_checksum": input_manifest_checksum,
        "quality_report_checksum": ZERO_CHECKSUM,
        "privacy_report_checksum": ZERO_CHECKSUM,
        "selection_checksum": ZERO_CHECKSUM,
        "timestamp_inventory_checksum": timestamp_inventory_checksum,
        "extraction_config_checksum": ZERO_CHECKSUM,
        "ffmpeg_version": "synthetic-test-fixture",
        "frames": [frame.model_dump(mode="json") for frame in frames],
        "frame_set_checksum": ZERO_CHECKSUM,
    }
    payload["frame_set_checksum"] = canonical_content_checksum(payload, "frame_set_checksum")
    frame_set = NormalizedRGBFrameSet.model_validate(payload)
    frame_set_ref = _publish(
        store,
        "rgb-frame-set.json",
        "NormalizedRGBFrameSet",
        frame_set.model_dump_json().encode(),
        producer_stage=StageId.FRAME_EXTRACT,
    )
    return frame_set_ref


def test_raw_scan_worker_persists_diagnostic_projection_and_svg_overlays(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import src.services.reconstruction.lidar.calibration_qa_worker as worker

    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    camera, points, edge_pixels, edge_normals = _camera_rig()
    image = _png(camera.width, camera.height)

    times_text = "0.0\n0.1\n0.2\n"
    trajectory_text = "".join(f"{time} 0 0 0 0 0 0 1\n" for time in (0.0, 0.1, 0.2))
    calibration_text = "synthetic declared calibration\n"
    scan_payloads = [_pcd(points) for _ in range(3)]
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        for index, scan in enumerate(scan_payloads):
            archive.writestr(f"{index:06d}.pcd", scan)
        archive.writestr("trajectory.tum", trajectory_text)
        archive.writestr("frame_times.txt", times_text)
        archive.writestr("calibration.txt", calibration_text)
    package_bytes = archive_buffer.getvalue()

    input_manifest_checksum = sha256_bytes(b"exact input manifest")
    package = LidarPackageRecord(
        job_id=JOB_ID,
        kind="lidar_scan_sequence",
        trajectory_origin="supplied",
        pose_count=3,
        trajectory_ref=_publish(
            store, "trajectory.tum", "LidarTrajectory", trajectory_text.encode(), producer_stage=StageId.LIDAR_INGEST
        ),
        frame_times_ref=_publish(
            store, "frame-times.txt", "LidarFrameTimes", times_text.encode(), producer_stage=StageId.LIDAR_INGEST
        ),
        calibration_ref=_publish(
            store,
            "calibration.txt",
            "LidarCalibrationSource",
            calibration_text.encode(),
            producer_stage=StageId.LIDAR_INGEST,
        ),
        sensor_from_camera=Transform(
            parent_frame=SENSOR_FRAME,
            local_frame=CAMERA_FRAME,
            translation_xyz=(0.0, 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        camera=camera,
        lidar_geometry_ref=_publish(
            store, "fused.ply", "LiDARGeometryArtifact", b"fused", producer_stage=StageId.LIDAR_INGEST
        ),
        lidar_metadata_ref=_publish(
            store, "metadata.json", "LiDARGeometryMetadata", b"metadata", producer_stage=StageId.LIDAR_INGEST
        ),
        point_count=len(points),
        floor_z_m=0.0,
        floor_support_points=600,
        fusion=FusionStats(
            scan_count=3,
            input_points=len(points) * 3,
            removed_points=0,
            point_count=len(points),
            bounds_min=tuple(float(value) for value in points.min(axis=0)),
            bounds_max=tuple(float(value) for value in points.max(axis=0)),
        ),
        record_checksum=ZERO_CHECKSUM,
    )
    package_ref = _publish(
        store,
        "lidar-package.json",
        "LidarPackageRecord",
        package.model_dump_json().encode(),
        producer_stage=StageId.LIDAR_INGEST,
    )
    zip_ref = _publish(
        store,
        "source-lidar.zip",
        "LidarPackageUpload",
        package_bytes,
        producer_stage=StageId.INPUT_VALIDATE,
        data_class=ArtifactDataClass.PRODUCT_INPUT,
    )
    evidence = LidarEvidence(
        geometry_format="pcd",
        scan_count=3,
        pose_count=3,
        trajectory_member="trajectory.tum",
        calibration_member="calibration.txt",
        calibration_format="torwic_txt",
        frame_times_member="frame_times.txt",
        pairing="index_in_name",
    )
    input_manifest = InputManifest(
        schema_version="1.0",
        source_type="upload",
        received_at="2026-10-08T00:00:00Z",
        files=[
            InputFile(
                original_name="lidar.zip",
                media_type="application/zip",
                size_bytes=len(package_bytes),
                checksum=zip_ref.artifact_checksum,
                artifact_uri=zip_ref.artifact_uri,
                data_class=ArtifactDataClass.PRODUCT_INPUT,
            )
        ],
        input_configuration=InputConfiguration(
            rgb_present=True, registered_lidar_present=True, declared_same_scene=True
        ),
        lidar_metadata=LidarMetadata(unit="m", coordinate_frame="lidar", registration_status="registered"),
        source_rights_attestation={"rights_to_use_confirmed": True},
        preparation_provenance={"lidar": {"evidence": evidence.model_dump(mode="json")}},
        input_manifest_checksum=input_manifest_checksum,
    )
    frame_set_ref = _frame_set(store, input_manifest_checksum, image)
    monkeypatch.setattr(worker, "_edge_pixels", lambda _path, _width, _height: (edge_pixels, edge_normals))

    result = run_lidar_calibration_qa(
        resolver=resolver,
        writer=store,
        job_id=JOB_ID,
        package_ref=package_ref,
        package=package,
        input_manifest=input_manifest,
        rgb_frame_set_ref=frame_set_ref,
        declarations=InputAssemblyDeclarations(
            coordinate_unit=EvidenceValue(value=DistanceUnit.METER, provenance=EvidenceProvenance.DECLARED),
            timestamp_unit=EvidenceValue(value=TimestampUnit.SECONDS, provenance=EvidenceProvenance.DECLARED),
            clock_relation=EvidenceValue(value=ClockRelation.SAME_CLOCK, provenance=EvidenceProvenance.DECLARED),
        ),
    )

    assert result.report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert result.report.matched_frame_count == 3
    assert result.report.diagnostic_projection_ref is not None
    assert result.report.projection_evidence_ref is None
    projection = LidarCalibrationProjectionEvidence.model_validate_json(
        resolver.require(result.report.diagnostic_projection_ref).read_bytes()
    )
    assert result.report.projected_point_count > 0, [finding.model_dump() for finding in result.report.findings]
    assert result.report.overlay_refs
    assert projection.qualification_status == "diagnostic_only"
    assert len(projection.frames) == 3
    assert all(resolver.require(reference).read_bytes().startswith(b"<svg") for reference in result.report.overlay_refs)
