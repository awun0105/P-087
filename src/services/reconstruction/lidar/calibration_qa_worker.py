"""Worker-side, source-bound LiDAR projection diagnostics.

This stage only scores raw per-pose scans. Registered maps do not retain the scan/time
association needed for image projection, so those inputs produce an explicit
INCONCLUSIVE report instead of synthetic frame evidence.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypeVar

import numpy as np

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.input_assembly import (
    ClockRelation,
    DistanceUnit,
    EvidenceValue,
    InputAssemblyDeclarations,
)
from src.models.contracts.lidar_calibration_qa import (
    LidarCalibrationFindingCode,
    LidarCalibrationFrameObservation,
    LidarCalibrationQAFinding,
    LidarCalibrationQAReport,
    LidarCalibrationQAResult,
    seal_lidar_calibration_qa_config,
    seal_lidar_calibration_qa_report,
)
from src.models.contracts.lidar_projection_qa import (
    seal_lidar_calibration_projection_config,
)
from src.models.contracts.manifests import InputManifest, StageId
from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError, FilesystemArtifactStore
from src.services.reconstruction.inputs.detect import LidarEvidence
from src.services.reconstruction.lidar.calibration_qa import (
    LidarCalibrationQAInput,
    evaluate_lidar_calibration_qa,
)
from src.services.reconstruction.lidar.fusion import FusionConfig, parse_trajectory, read_points
from src.services.reconstruction.lidar.package import LidarPackageRecord, parse_frame_times
from src.services.reconstruction.lidar.projection_qa import (
    LidarCalibrationProjectionFrame,
    score_lidar_calibration_projection,
)
from src.services.reconstruction.rgb.frames.frame_set import NormalizedRGBFrame, NormalizedRGBFrameSet

_MAX_SAMPLE_FRAMES = 8
_MAX_SCAN_POINTS = FusionConfig().max_scan_points
_MAX_OVERLAY_SAMPLES = 64
_T = TypeVar("_T")


@dataclass(frozen=True)
class LidarCalibrationQAWorkerResult:
    report: LidarCalibrationQAReport
    report_ref: ProductArtifactRef


def diagnostic_qa_profile():
    """Explicit diagnostic thresholds; they are not field-qualified production limits."""
    return seal_lidar_calibration_qa_config(
        profile_id="aud13-diagnostic-unqualified-v1",
        minimum_sampled_frames=3,
        minimum_matched_frames=3,
        minimum_overlapping_frames=2,
        minimum_projected_points_per_frame=30,
        minimum_overlap_fraction=0.05,
        maximum_timestamp_residual_sec=0.05,
    )


def diagnostic_projection_profile():
    """Bound compute and overlay size for a diagnostic projection run."""
    return seal_lidar_calibration_projection_config(
        profile_id="aud13-projection-diagnostic-unqualified-v1",
        edge_distance_threshold_px=4.0,
        minimum_edge_pixels=50,
        maximum_points_per_frame=5_000,
        maximum_edge_pixels_per_frame=5_000,
        maximum_overlay_samples_per_frame=_MAX_OVERLAY_SAMPLES,
        minimum_edge_orientation_bins=2,
        minimum_edge_span_fraction=0.25,
        maximum_frame_median_spread_px=8.0,
    )


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _publish(
    writer: FilesystemArtifactStore,
    job_id: str,
    package_checksum: str,
    profile_checksum: str,
    name: str,
    artifact_type: str,
    payload: bytes,
) -> ProductArtifactRef:
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=(
            f"artifact://jobs/{job_id}/lidar-calibration-qa/"
            f"{package_checksum.removeprefix('sha256:')}/{profile_checksum.removeprefix('sha256:')}/{name}"
        ),
        artifact_checksum=_digest(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_CALIBRATION_QA,
        job_id=job_id,
        source_provenance={"package_checksum": package_checksum, "profile_checksum": profile_checksum},
    )
    if writer.publish(reference, payload) != reference:
        raise ValueError("Artifact writer changed LiDAR calibration QA identity")
    return reference


def _even_sample(items: list[_T], maximum: int) -> list[_T]:
    if len(items) <= maximum:
        return items
    indices = np.linspace(0, len(items) - 1, maximum, dtype=np.int64)
    return [items[int(index)] for index in indices]


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise ValueError("RGB frame artifact is not a valid PNG")
    width, height = int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")
    if width < 2 or height < 2 or width * height > 100_000_000:
        raise ValueError("RGB frame dimensions are invalid or exceed the QA limit")
    return width, height


def _edge_pixels(path: Path, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Decode one checksum-verified PNG through the worker's configured PATH FFmpeg."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise ValueError("FFmpeg could not decode an RGB frame for calibration QA") from error
    if result.returncode != 0 or len(result.stdout) != width * height:
        raise ValueError("FFmpeg returned an invalid grayscale frame for calibration QA")
    gray = np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width).astype(np.float32)
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = (gray[:, 2:] - gray[:, :-2]) * 0.5
    gy[1:-1, :] = (gray[2:, :] - gray[:-2, :]) * 0.5
    magnitude = np.hypot(gx, gy)
    threshold = max(12.0, float(np.percentile(magnitude, 90)))
    ys, xs = np.nonzero(magnitude >= threshold)
    if len(xs) == 0:
        return np.empty((0, 2), dtype=np.float64), np.empty((0, 2), dtype=np.float64)
    lengths = magnitude[ys, xs]
    normals = np.column_stack((gx[ys, xs] / lengths, gy[ys, xs] / lengths))
    return np.column_stack((xs, ys)).astype(np.float64), normals.astype(np.float64)


def _pose_scan_members(archive: zipfile.ZipFile, evidence: LidarEvidence, pose_count: int) -> dict[int, str]:
    if evidence.cloud_member is not None:
        return {}
    names = sorted(name for name in archive.namelist() if PurePosixPath(name).suffix.lower() == ".pcd")
    if len(names) != evidence.scan_count:
        raise ValueError("LiDAR scan count changed after package ingest")
    mapping: dict[int, str] = {}
    for index, name in enumerate(names):
        pose_id = int(PurePosixPath(name).stem) if evidence.pairing == "index_in_name" else index
        if pose_id < 0 or pose_id >= pose_count or pose_id in mapping:
            raise ValueError("LiDAR scan-to-pose pairing is ambiguous")
        mapping[pose_id] = name
    if len(mapping) != pose_count:
        raise ValueError("LiDAR scan sequence does not cover every trajectory pose")
    return mapping


def _match_observations(
    frames: list[NormalizedRGBFrame],
    lidar_times: list[float],
    *,
    timestamp_unit: str | None,
    clock_relation: ClockRelation | None,
    offset_seconds: float | None,
    maximum_residual_seconds: float,
) -> list[LidarCalibrationFrameObservation]:
    can_match = (
        timestamp_unit == "seconds"
        and clock_relation in {ClockRelation.SAME_CLOCK, ClockRelation.KNOWN_OFFSET}
        and offset_seconds is not None
    )
    observations: list[LidarCalibrationFrameObservation] = []
    next_pose_id = 0
    for frame in frames:
        rgb_time = float(frame.timestamp_sec)
        pose_id: int | None = None
        lidar_time: float | None = None
        if can_match and next_pose_id < len(lidar_times):
            nearest = min(
                range(next_pose_id, len(lidar_times)),
                key=lambda index: abs(rgb_time - lidar_times[index] - float(offset_seconds)),
            )
            if abs(rgb_time - lidar_times[nearest] - float(offset_seconds)) <= maximum_residual_seconds:
                pose_id = nearest
                lidar_time = lidar_times[nearest]
                next_pose_id = nearest + 1
        observations.append(
            LidarCalibrationFrameObservation(
                rgb_frame_id=frame.frame_id,
                rgb_timestamp_sec=rgb_time,
                lidar_pose_id=pose_id,
                lidar_timestamp_sec=lidar_time,
            )
        )
    return observations


def _overlay_svg(image: bytes, width: int, height: int, samples: list[object]) -> bytes:
    encoded = base64.b64encode(image).decode("ascii")
    points = []
    for sample in samples:
        u = float(getattr(sample, "u_px"))
        v = float(getattr(sample, "v_px"))
        if not math.isfinite(u) or not math.isfinite(v):
            continue
        points.append(f'<circle cx="{u:.2f}" cy="{v:.2f}" r="3" fill="#16d9ff" stroke="#10202a" stroke-width="1" />')
    body = "".join(points)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<image width="{width}" height="{height}" href="data:image/png;base64,{encoded}" />{body}</svg>'
    ).encode()


def _extra_finding(detail: str, remediation: str) -> LidarCalibrationQAFinding:
    return LidarCalibrationQAFinding(
        code=LidarCalibrationFindingCode.PROJECTION_SCORING_PENDING,
        severity="inconclusive",
        detail=detail,
        remediation=remediation,
    )


def run_lidar_calibration_qa(
    *,
    resolver: ArtifactResolver,
    writer: FilesystemArtifactStore,
    job_id: str,
    package_ref: ProductArtifactRef,
    package: LidarPackageRecord,
    input_manifest: InputManifest,
    rgb_frame_set_ref: ProductArtifactRef | None,
    declarations: InputAssemblyDeclarations | None,
) -> LidarCalibrationQAWorkerResult:
    """Persist a diagnostic QA report and overlay artifacts without qualifying collision use."""
    declarations = declarations or InputAssemblyDeclarations()
    profile = diagnostic_qa_profile()
    projection_profile = diagnostic_projection_profile()
    provenance = input_manifest.preparation_provenance or {}
    lidar_source = provenance.get("lidar")
    try:
        evidence = LidarEvidence.model_validate(lidar_source["evidence"]) if isinstance(lidar_source, dict) else None
    except (KeyError, TypeError, ValueError):
        evidence = None

    coordinate_unit = declarations.coordinate_unit
    timestamp_unit = declarations.timestamp_unit.value.value if declarations.timestamp_unit else None
    clock_relation = declarations.clock_relation.value if declarations.clock_relation else None
    supplied_offset = declarations.clock_offset_seconds.value if declarations.clock_offset_seconds else None
    effective_offset = (
        0.0 if clock_relation == ClockRelation.SAME_CLOCK and supplied_offset is None else supplied_offset
    )

    intrinsics_ref: ProductArtifactRef | None = None
    camera = package.camera
    if camera is not None:
        camera_payload = (
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source_calibration_ref": package.calibration_ref.model_dump(mode="json")
                    if package.calibration_ref
                    else None,
                    "camera": camera.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        intrinsics_ref = _publish(
            writer,
            job_id,
            package_ref.artifact_checksum,
            profile.config_checksum,
            "camera-intrinsics.json",
            "CameraIntrinsics",
            camera_payload,
        )

    frame_set: NormalizedRGBFrameSet | None = None
    extra_findings: list[LidarCalibrationQAFinding] = []
    if rgb_frame_set_ref is not None:
        try:
            frame_set = NormalizedRGBFrameSet.model_validate_json(resolver.require(rgb_frame_set_ref).read_bytes())
            if frame_set.input_manifest_checksum != input_manifest.input_manifest_checksum:
                raise ValueError("RGB frame-set belongs to a different input manifest")
        except (ArtifactStoreError, OSError, ValueError) as error:
            extra_findings.append(
                _extra_finding(
                    f"The checksum-bound RGB frame set could not be verified ({type(error).__name__}).",
                    "Restore or re-upload the exact RGB input and create a new immutable scene job.",
                )
            )
            frame_set = None

    sampled_rgb = _even_sample(frame_set.frames, _MAX_SAMPLE_FRAMES) if frame_set else []
    poses = []
    lidar_times: list[float] = []
    scan_members: dict[int, str] = {}
    package_path: Path | None = None
    if evidence is not None and package.kind == "lidar_scan_sequence" and evidence.cloud_member is None:
        try:
            poses = parse_trajectory(resolver.require(package.trajectory_ref).read_text(encoding="utf-8"))
            timing_text = resolver.require(package.frame_times_ref).read_text(encoding="utf-8")
            lidar_times = parse_frame_times(timing_text, package.pose_count)
            if len(poses) != package.pose_count or any(
                not math.isclose(time, pose.timestamp, rel_tol=0.0, abs_tol=1e-6)
                for time, pose in zip(lidar_times, poses, strict=True)
            ):
                raise ValueError("Frame-time inventory differs from the timestamped trajectory")
            package_input = next(item for item in input_manifest.files if item.media_type == "application/zip")
            package_path = resolver.require_uri(package_input.artifact_uri, package_input.checksum)
            with zipfile.ZipFile(package_path) as archive:
                scan_members = _pose_scan_members(
                    archive,
                    evidence,
                    package.pose_count,
                )
        except (ArtifactStoreError, OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as error:
            extra_findings.append(
                _extra_finding(
                    f"Per-pose scan sources were unavailable or inconsistent ({type(error).__name__}).",
                    "Use a complete raw scan sequence with a matching TUM trajectory and timestamp inventory.",
                )
            )
            poses, lidar_times, scan_members, package_path = [], [], {}, None
    elif package.kind == "registered_lidar" or (evidence is not None and evidence.cloud_member is not None):
        extra_findings.append(
            _extra_finding(
                "This input contains a registered map, not timestamped per-pose scans; projection QA cannot recover scan timing from the fused cloud.",
                "Provide the original raw scan sequence and its trajectory to inspect per-frame calibration overlays.",
            )
        )
    elif evidence is None:
        extra_findings.append(
            _extra_finding(
                "The original LiDAR evidence declaration is unavailable to the QA worker.",
                "Create a new input assembly that binds the LiDAR archive and its detected evidence.",
            )
        )

    observations = _match_observations(
        sampled_rgb,
        lidar_times,
        timestamp_unit=timestamp_unit,
        clock_relation=clock_relation,
        offset_seconds=effective_offset,
        maximum_residual_seconds=profile.maximum_timestamp_residual_sec,
    )
    qa_input = LidarCalibrationQAInput(
        package_ref=package_ref,
        package=package,
        rgb_frame_set_ref=rgb_frame_set_ref if frame_set is not None else None,
        camera=camera,
        intrinsics_ref=intrinsics_ref,
        coordinate_unit=coordinate_unit,
        timestamp_unit=timestamp_unit,
        clock_relation=declarations.clock_relation,
        clock_offset_seconds=declarations.clock_offset_seconds
        or (
            EvidenceValue(value=0.0, provenance="declared", method="same_clock_declaration")
            if clock_relation == ClockRelation.SAME_CLOCK
            else None
        ),
        observations=observations,
    )

    projection_frames: list[LidarCalibrationProjectionFrame] = []
    image_bytes_by_frame: dict[int, tuple[bytes, int, int]] = {}
    can_project = (
        frame_set is not None
        and evidence is not None
        and package.kind == "lidar_scan_sequence"
        and bool(scan_members)
        and bool(poses)
        and timestamp_unit == "seconds"
        and clock_relation in {ClockRelation.SAME_CLOCK, ClockRelation.KNOWN_OFFSET}
        and effective_offset is not None
        and coordinate_unit is not None
        and coordinate_unit.value == DistanceUnit.METER
        and camera is not None
        and camera.distortion_status == "declared"
        and intrinsics_ref is not None
        and package.calibration_ref is not None
    )
    if can_project:
        try:
            frame_lookup = {frame.frame_id: frame for frame in sampled_rgb}
            image_metadata: dict[int, tuple[Path, bytes, int, int]] = {}
            for rgb in sampled_rgb:
                path = resolver.require(rgb.image)
                image = path.read_bytes()
                width, height = _png_dimensions(image)
                image_metadata[rgb.frame_id] = (path, image, width, height)
            prepared_video = frame_set.video_preparation
            pixel_basis = "prepared_rgb" if prepared_video is not None else "source_video"
            if prepared_video is None and any(
                width != camera.width or height != camera.height for _, _, width, height in image_metadata.values()
            ):
                raise ValueError("RGB dimensions differ from calibration and have no verified pixel transform")
            selected = [row for row in observations if row.lidar_pose_id is not None]
            if package_path is None:
                raise ValueError("Original LiDAR package is unavailable")
            with zipfile.ZipFile(package_path) as archive:
                for observation in selected:
                    rgb = frame_lookup[observation.rgb_frame_id]
                    scan_name = scan_members[int(observation.lidar_pose_id)]
                    scan_payload = archive.read(scan_name)
                    points = read_points(io.BytesIO(scan_payload), _MAX_SCAN_POINTS)
                    ranges = np.linalg.norm(points, axis=1)
                    keep = (
                        np.isfinite(points).all(axis=1)
                        & np.isfinite(ranges)
                        & (ranges >= FusionConfig().min_range_m)
                        & (ranges <= FusionConfig().max_range_m)
                    )
                    points = points[keep]
                    path, image, width, height = image_metadata[rgb.frame_id]
                    edges, normals = _edge_pixels(path, width, height)
                    projection_frames.append(
                        LidarCalibrationProjectionFrame(
                            frame_id=rgb.frame_id,
                            lidar_pose_id=int(observation.lidar_pose_id),
                            rgb_timestamp_sec=observation.rgb_timestamp_sec,
                            lidar_timestamp_sec=float(observation.lidar_timestamp_sec),
                            rgb_frame_checksum=rgb.image.artifact_checksum,
                            lidar_scan_checksum=_digest(scan_payload),
                            pixel_basis=pixel_basis,
                            image_width=width,
                            image_height=height,
                            edge_pixels_xy=edges,
                            edge_normals_xy=normals,
                            lidar_points_sensor_m=points,
                        )
                    )
                    image_bytes_by_frame[rgb.frame_id] = (image, width, height)
        except (
            ArtifactStoreError,
            OSError,
            ValueError,
            KeyError,
            subprocess.SubprocessError,
            zipfile.BadZipFile,
        ) as error:
            projection_frames = []
            image_bytes_by_frame = {}
            extra_findings.append(
                _extra_finding(
                    f"Projection diagnostics could not be built from verified source bytes ({type(error).__name__}).",
                    "Check the RGB frame artifacts and the raw LiDAR scan-to-pose mapping, then create a new job if source bytes need replacement.",
                )
            )

    camera_pixel_basis = "source_video"
    rgb_frame_pixel_basis = (
        "prepared_rgb" if frame_set is not None and frame_set.video_preparation is not None else "source_video"
    )
    projection = score_lidar_calibration_projection(
        qa_input,
        profile,
        projection_profile,
        projection_frames,
        camera_pixel_basis=camera_pixel_basis,
        rgb_frame_pixel_basis=rgb_frame_pixel_basis,
        video_preparation_verification=frame_set.video_preparation if frame_set else None,
    )

    overlay_refs: list[ProductArtifactRef] = []
    overlay_by_frame: dict[int, ProductArtifactRef] = {}
    for frame in projection.frames:
        image_row = image_bytes_by_frame.get(frame.frame_id)
        if not image_row or not frame.overlay_samples:
            continue
        image, width, height = image_row
        overlay = _overlay_svg(image, width, height, frame.overlay_samples)
        reference = _publish(
            writer,
            job_id,
            package_ref.artifact_checksum,
            profile.config_checksum,
            f"overlay-{frame.frame_id:06d}.svg",
            "LidarCalibrationQAOverlay",
            overlay,
        )
        overlay_refs.append(reference)
        overlay_by_frame[frame.frame_id] = reference

    projection_payload = projection.model_dump_json(indent=2).encode("utf-8") + b"\n"
    diagnostic_projection_ref = _publish(
        writer,
        job_id,
        package_ref.artifact_checksum,
        profile.config_checksum,
        "projection-evidence.json",
        "LidarCalibrationProjectionEvidence",
        projection_payload,
    )

    metrics = {frame.frame_id: frame for frame in projection.frames}
    measured_observations = [
        LidarCalibrationFrameObservation(
            rgb_frame_id=row.rgb_frame_id,
            rgb_timestamp_sec=row.rgb_timestamp_sec,
            lidar_pose_id=row.lidar_pose_id,
            lidar_timestamp_sec=row.lidar_timestamp_sec,
            projected_point_count=metrics[row.rgb_frame_id].visible_projected_point_count
            if row.rgb_frame_id in metrics
            else 0,
            overlap_point_count=metrics[row.rgb_frame_id].overlap_point_count if row.rgb_frame_id in metrics else 0,
            overlay_ref=overlay_by_frame.get(row.rgb_frame_id),
        )
        for row in observations
    ]
    qa_input = qa_input.model_copy(update={"observations": measured_observations})
    base_report = evaluate_lidar_calibration_qa(qa_input, profile)
    findings = [
        finding
        for finding in base_report.findings
        if finding.code != LidarCalibrationFindingCode.PROJECTION_SCORING_PENDING
    ]
    findings.extend(extra_findings)
    findings.append(
        LidarCalibrationQAFinding(
            code=LidarCalibrationFindingCode.PRODUCTION_QUALIFICATION_PENDING,
            severity="inconclusive",
            detail="Projection metrics are diagnostic only; production thresholds and a held-out real capture have not been qualified.",
            remediation="Review the overlay, provide corrected calibration/timing as a new immutable job when needed, and qualify thresholds on a separate held-out real sequence before collision use.",
        )
    )
    report_payload = {
        field: getattr(base_report, field)
        for field in LidarCalibrationQAReport.model_fields
        if field != "report_checksum"
    }
    report_payload.update(
        {
            "result": (
                LidarCalibrationQAResult.FAIL
                if base_report.result == LidarCalibrationQAResult.FAIL
                else LidarCalibrationQAResult.INCONCLUSIVE
            ),
            "findings": findings,
            "overlay_refs": overlay_refs,
            "diagnostic_projection_ref": diagnostic_projection_ref,
            "projection_evidence_ref": None,
        }
    )
    report = seal_lidar_calibration_qa_report(**report_payload)
    report_ref = _publish(
        writer,
        job_id,
        package_ref.artifact_checksum,
        profile.config_checksum,
        "report.json",
        "LidarCalibrationQAReport",
        report.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    return LidarCalibrationQAWorkerResult(report=report, report_ref=report_ref)
