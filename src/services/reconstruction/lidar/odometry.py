"""Lease-fenced producer for metric LiDAR odometry trajectories.

This module deliberately produces only a scan-native, unqualified trajectory. It
does not publish a JobManifest pointer or enable recipe R5; product integration
must commit the returned reference under the operation lease in a later sprint.
"""

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Self

import numpy as np
from pydantic import Field, FiniteFloat, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ContractModel, Identifier
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.input_assembly import DistanceUnit, TimestampUnit
from src.models.contracts.reconstruction import (
    EstimatedTrajectoryArtifact,
    EstimatedTrajectoryDiagnostics,
    EstimatedTrajectoryExecutionMetrics,
    EstimatedTrajectoryIngestBinding,
    EstimatedTrajectoryPose,
)
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.inputs.timestamps import parse_timestamp_rows, timestamps_in_seconds
from src.services.reconstruction.lidar.cloud_payload import load_xyz_points

_PINNED_PROVIDER_VERSION = "1.3.0"
_MAX_TIMESTAMP_FILE_BYTES = 16 * 1024 * 1024
_MAX_RESULT_BYTES = 128 * 1024 * 1024
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class LidarOdometryProfile(ContractModel):
    """Explicit metric and resource bounds for one KISS-ICP worker attempt."""

    min_range_m: FiniteFloat = Field(ge=0)
    max_range_m: FiniteFloat = Field(gt=0)
    voxel_size_m: FiniteFloat = Field(gt=0)
    min_points_per_scan: int = Field(default=100, ge=3)
    max_points_per_scan: int = Field(default=5_000_000, ge=3, le=20_000_000)
    max_total_points: int = Field(default=25_000_000, ge=3, le=100_000_000)
    max_num_threads: int = Field(default=4, ge=1, le=64)
    timestamp_gap_threshold_seconds: FiniteFloat = Field(default=0.5, gt=0)

    @model_validator(mode="after")
    def _validate_ranges_and_budget(self) -> Self:
        if self.min_range_m >= self.max_range_m:
            raise ValueError("LiDAR odometry range must have positive extent")
        if self.min_points_per_scan > self.max_points_per_scan:
            raise ValueError("minimum point count exceeds the per-scan point budget")
        if self.max_total_points < self.min_points_per_scan * 2:
            raise ValueError("total point budget cannot cover the minimum two-scan trajectory")
        return self


class LidarOdometryScanInput(ContractModel):
    """One exact uploaded scan identity; no filesystem path crosses this contract."""

    file_id: Identifier
    reference: ArtifactRef

    @model_validator(mode="after")
    def _require_product_input(self) -> Self:
        if self.reference.data_class != ArtifactDataClass.PRODUCT_INPUT:
            raise ValueError("odometry scan refs must be product inputs")
        return self


class LidarOdometryWorkerRequest(ContractModel):
    """Validated assembly bindings required to estimate a scan-native trajectory."""

    job_id: Identifier
    attempt_id: Identifier
    assembly_id: Identifier
    assembly_revision: int = Field(gt=0)
    assembly_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    recipe_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scans: list[LidarOdometryScanInput] = Field(min_length=2, max_length=20_000)
    timestamp_file_ref: ArtifactRef
    timestamp_unit: TimestampUnit
    scan_coordinate_unit: DistanceUnit
    sensor_frame_id: Identifier
    odometry_map_frame_id: Identifier
    profile: LidarOdometryProfile

    @model_validator(mode="after")
    def _bind_request_identities(self) -> Self:
        if not _SAFE_SEGMENT.fullmatch(self.job_id) or not _SAFE_SEGMENT.fullmatch(self.attempt_id):
            raise ValueError("job and attempt IDs must be safe artifact path segments")
        if self.sensor_frame_id == self.odometry_map_frame_id:
            raise ValueError("sensor and odometry map frame IDs must differ")
        if self.scan_coordinate_unit != DistanceUnit.METER:
            raise ValueError("LiDAR odometry requires scan coordinates declared in metres")
        if self.timestamp_file_ref.data_class != ArtifactDataClass.PRODUCT_INPUT:
            raise ValueError("timestamp file must be a product input")
        refs = [self.timestamp_file_ref, *(scan.reference for scan in self.scans)]
        if any(reference.job_id is not None and reference.job_id != self.job_id for reference in refs):
            raise ValueError("odometry input references must belong to the requested job")
        file_ids = [scan.file_id for scan in self.scans]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("odometry scan file IDs must be unique")
        return self


class LidarOdometryRuntimeSettings(BaseSettings):
    """Isolated provider interpreter and process limits injected by deployment."""

    python: Path = Path("/opt/real2sim/lidar_runtime/bin/python")
    work_root: Path = Path("/tmp/real2sim-lidar-odometry")
    timeout_seconds: float = Field(default=3600, gt=0, allow_inf_nan=False)
    provider_version: str = _PINNED_PROVIDER_VERSION
    model_config = SettingsConfigDict(env_prefix="REC17_LIDAR_ODOMETRY_", extra="forbid")


class LidarOdometryError(RuntimeError):
    """Structured failure at the isolated odometry worker boundary."""

    error_code = "LIDAR_ODOMETRY_FAILED"
    retryable = False


class LidarOdometryRuntimeUnavailableError(LidarOdometryError):
    """Pinned isolated interpreter is not available in this worker image."""

    error_code = "LIDAR_ODOMETRY_RUNTIME_UNAVAILABLE"
    retryable = True


class LidarOdometryRuntimeIncompatibleError(LidarOdometryError):
    """Installed provider identity differs from the pinned adapter contract."""

    error_code = "LIDAR_ODOMETRY_RUNTIME_INCOMPATIBLE"


class LidarOdometryTimeoutError(LidarOdometryError):
    """Provider process exceeded the per-attempt deadline."""

    error_code = "LIDAR_ODOMETRY_TIMEOUT"
    retryable = True


class LidarOdometryOutOfMemoryError(LidarOdometryError):
    """Provider was terminated by the OS for exceeding its memory envelope."""

    error_code = "LIDAR_ODOMETRY_OUT_OF_MEMORY"
    retryable = True


class LidarOdometryCancelledError(LidarOdometryError):
    """The admitted operation was cancelled and its child process was reaped."""

    error_code = "LIDAR_ODOMETRY_CANCELLED"


class LidarOdometryLeaseLostError(LidarOdometryError):
    """A stale operation lease may not publish or return an ingest binding."""

    error_code = "LIDAR_ODOMETRY_LEASE_LOST"


class LidarOdometryProcessError(LidarOdometryError):
    """Provider exited unsuccessfully or returned an invalid result."""

    error_code = "LIDAR_ODOMETRY_PROCESS_FAILED"


class LidarOdometryResult(ContractModel):
    """Verified local producer output; caller still owns durable manifest commit."""

    trajectory: EstimatedTrajectoryArtifact
    artifact_ref: ArtifactRef
    ingest_binding: EstimatedTrajectoryIngestBinding


class KissIcpProcess:
    """Run the pinned KISS-ICP API in a cancellable process group."""

    def __init__(self, settings: LidarOdometryRuntimeSettings) -> None:
        self.settings = settings

    def run(
        self,
        manifest_path: Path,
        output_path: Path,
        log_path: Path,
        profile: LidarOdometryProfile,
        *,
        cancel_event: Event | None,
        lease_is_current: Callable[[], bool],
    ) -> dict[str, object]:
        """Run one isolated attempt, checking cancellation and lease while it runs."""
        # Preserve the venv's `bin/python` entrypoint symlink: resolving it can
        # make Python ignore that environment's site-packages directory.
        python = self.settings.python.expanduser().absolute()
        if not python.is_file() or not os.access(python, os.X_OK):
            raise LidarOdometryRuntimeUnavailableError("Pinned LiDAR odometry Python runtime is unavailable")
        repository_root = Path(__file__).resolve().parents[4]
        runner = repository_root / "scripts/gpu/lidar_odometry_runner.py"
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(repository_root),
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": str(profile.max_num_threads),
            "OPENBLAS_NUM_THREADS": str(profile.max_num_threads),
            "MKL_NUM_THREADS": str(profile.max_num_threads),
        }
        start = time.monotonic()
        try:
            with log_path.open("xb") as log:
                process = subprocess.Popen(
                    [str(python), str(runner), "--manifest", str(manifest_path), "--output", str(output_path)],
                    cwd=repository_root,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=environment,
                )
                deadline = start + self.settings.timeout_seconds
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self._kill_and_reap(process)
                        raise LidarOdometryCancelledError("LiDAR odometry was cancelled")
                    if not lease_is_current():
                        self._kill_and_reap(process)
                        raise LidarOdometryLeaseLostError("LiDAR odometry operation lease is no longer current")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._kill_and_reap(process)
                        raise LidarOdometryTimeoutError("LiDAR odometry exceeded its configured timeout")
                    try:
                        return_code = process.wait(timeout=min(0.2, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
        except LidarOdometryError:
            raise
        except OSError as error:
            raise LidarOdometryRuntimeUnavailableError("Could not start the pinned LiDAR odometry runtime") from error
        if return_code != 0:
            if return_code in {-signal.SIGKILL, 128 + signal.SIGKILL}:
                raise LidarOdometryOutOfMemoryError("KISS-ICP was killed by the OS, likely after exhausting memory")
            raise LidarOdometryProcessError(f"KISS-ICP exited with code {return_code}; inspect the attempt log")
        try:
            output_size = output_path.stat().st_size
        except OSError as error:
            raise LidarOdometryProcessError("KISS-ICP exited without writing its result file") from error
        if output_size > _MAX_RESULT_BYTES:
            raise LidarOdometryProcessError("KISS-ICP result exceeded the output size limit")
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LidarOdometryProcessError("KISS-ICP returned an unreadable result") from error
        if not isinstance(output, dict):
            raise LidarOdometryProcessError("KISS-ICP result must be a JSON object")
        output["process_elapsed_seconds"] = time.monotonic() - start
        return output

    @staticmethod
    def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait()


class LidarOdometryWorker:
    """Decode exact scan inputs, estimate poses, then publish verified immutable bytes."""

    def __init__(
        self,
        resolver: ArtifactResolver,
        writer: FilesystemArtifactStore,
        settings: LidarOdometryRuntimeSettings | None = None,
    ) -> None:
        if resolver.artifact_root != writer.resolver.artifact_root:
            raise ValueError("odometry artifact resolver and writer must share an artifact root")
        self.resolver = resolver
        self.writer = writer
        self.settings = settings or LidarOdometryRuntimeSettings()
        self.process = KissIcpProcess(self.settings)

    def run(
        self,
        request: LidarOdometryWorkerRequest,
        *,
        cancel_event: Event | None = None,
        lease_is_current: Callable[[], bool] = lambda: True,
    ) -> LidarOdometryResult:
        """Produce one attempt-scoped trajectory; never commit a job manifest pointer."""
        self._require_current_lease(lease_is_current)
        attempt_dir = self.settings.work_root / request.job_id / request.attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=False)
        try:
            timestamps = self._load_timestamps(request)
            scan_point_counts: list[int] = []
            scan_paths: list[Path] = []
            total_points = 0
            for index, scan in enumerate(request.scans):
                self._require_running(cancel_event, lease_is_current)
                source = self.resolver.require(scan.reference)
                points = load_xyz_points(source, request.profile.max_points_per_scan)
                ranges = np.linalg.norm(points, axis=1)
                points = points[(ranges >= request.profile.min_range_m) & (ranges <= request.profile.max_range_m)]
                if len(points) < request.profile.min_points_per_scan:
                    raise ValueError(f"scan {scan.file_id} has too few points within the configured metric range")
                total_points += len(points)
                if total_points > request.profile.max_total_points:
                    raise ValueError("LiDAR scan sequence exceeds its total point budget")
                staged_scan = attempt_dir / f"scan-{index:06d}.npy"
                np.save(staged_scan, points, allow_pickle=False)
                scan_paths.append(staged_scan)
                scan_point_counts.append(len(points))

            profile_payload = request.profile.model_dump(mode="json")
            manifest_path = attempt_dir / "provider-input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "expected_provider_version": self.settings.provider_version,
                        "profile": profile_payload,
                        "scans": [
                            {"path": str(path), "timestamp_seconds": timestamp}
                            for path, timestamp in zip(scan_paths, timestamps, strict=True)
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            output_path = attempt_dir / "provider-output.json"
            log_path = attempt_dir / "provider.log"
            raw_result = self.process.run(
                manifest_path,
                output_path,
                log_path,
                request.profile,
                cancel_event=cancel_event,
                lease_is_current=lease_is_current,
            )
            self._require_running(cancel_event, lease_is_current)
            trajectory = self._build_trajectory(request, timestamps, scan_point_counts, raw_result)
            artifact_bytes = trajectory.model_dump_json(indent=2).encode("utf-8") + b"\n"
            reference = ArtifactRef(
                artifact_type="EstimatedTrajectoryArtifact",
                schema_version="1.0",
                artifact_uri=(
                    f"artifact://jobs/{request.job_id}/attempts/{request.attempt_id}/lidar-odometry/trajectory.json"
                ),
                artifact_checksum=_sha256(artifact_bytes),
                data_class=ArtifactDataClass.DERIVED,
                producer_stage="ST-LIDAR-ODOMETRY",
                job_id=request.job_id,
                source_provenance={
                    "assembly_checksum": request.assembly_checksum,
                    "recipe_checksum": request.recipe_checksum,
                    "timestamp_file_checksum": request.timestamp_file_ref.artifact_checksum,
                    "trajectory_origin": "estimated",
                    "runtime_qualification_status": "wired_unqualified",
                },
            )
            self._require_running(cancel_event, lease_is_current)
            if self.writer.publish(reference, artifact_bytes) != reference:
                raise LidarOdometryProcessError("Artifact writer changed the odometry artifact identity")
            stored_path = self.resolver.require(reference)
            stored = EstimatedTrajectoryArtifact.model_validate_json(stored_path.read_bytes())
            verify_content_checksum(stored, "artifact_checksum")
            if stored != trajectory:
                raise LidarOdometryProcessError("Published odometry artifact changed during read-back verification")
            self._require_running(cancel_event, lease_is_current)
            binding = EstimatedTrajectoryIngestBinding(
                trajectory_ref=reference,
                timestamp_file_ref=request.timestamp_file_ref,
                assembly_checksum=request.assembly_checksum,
                recipe_checksum=request.recipe_checksum,
                source_scan_file_ids=[scan.file_id for scan in request.scans],
                source_scan_checksums=[scan.reference.artifact_checksum for scan in request.scans],
                sensor_frame_id=request.sensor_frame_id,
                odometry_map_frame_id=request.odometry_map_frame_id,
            )
            if any(
                pose.source_scan_file_id != file_id or pose.source_scan_checksum != checksum
                for pose, file_id, checksum in zip(
                    stored.poses,
                    binding.source_scan_file_ids,
                    binding.source_scan_checksums,
                    strict=True,
                )
            ):
                raise LidarOdometryProcessError("Verified ingest binding differs from the published scan sequence")
            return LidarOdometryResult(trajectory=stored, artifact_ref=reference, ingest_binding=binding)
        except (LidarOdometryError, ValueError, OSError):
            # Keep attempt-local inputs and logs for explicit failure diagnosis/recovery.
            raise

    def _load_timestamps(self, request: LidarOdometryWorkerRequest) -> tuple[float, ...]:
        path = self.resolver.require(request.timestamp_file_ref)
        if path.stat().st_size > _MAX_TIMESTAMP_FILE_BYTES:
            raise ValueError("timestamp inventory exceeds the configured size limit")
        try:
            values = parse_timestamp_rows(path.read_text(encoding="utf-8"))
            seconds = timestamps_in_seconds(values, request.timestamp_unit)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError(f"invalid LiDAR scan timestamp inventory: {error}") from error
        if len(seconds) != len(request.scans):
            raise ValueError("LiDAR scan and timestamp row counts differ")
        return seconds

    def _build_trajectory(
        self,
        request: LidarOdometryWorkerRequest,
        timestamps: tuple[float, ...],
        scan_point_counts: list[int],
        output: dict[str, object],
    ) -> EstimatedTrajectoryArtifact:
        required = {
            "schema_version",
            "provider_id",
            "provider_version",
            "poses",
            "point_counts",
            "provider_elapsed_seconds",
            "provider_cpu_seconds",
            "provider_peak_rss_bytes",
            "process_elapsed_seconds",
        }
        if set(output) != required:
            raise LidarOdometryProcessError("KISS-ICP result fields do not match the pinned adapter protocol")
        if output["schema_version"] != "1.0" or output["provider_id"] != "kiss-icp-python":
            raise LidarOdometryProcessError("KISS-ICP result protocol or provider identity mismatch")
        if output["provider_version"] != self.settings.provider_version:
            raise LidarOdometryRuntimeIncompatibleError("KISS-ICP provider version differs from the pinned runtime")
        if output["point_counts"] != scan_point_counts:
            raise LidarOdometryProcessError("KISS-ICP point inventory differs from the validated scan inputs")
        matrices = output["poses"]
        if not isinstance(matrices, list) or len(matrices) != len(request.scans):
            raise LidarOdometryProcessError("KISS-ICP did not return exactly one pose per selected scan")
        poses = [
            EstimatedTrajectoryPose(
                scan_index=index,
                source_scan_file_id=scan.file_id,
                source_scan_checksum=scan.reference.artifact_checksum,
                timestamp_seconds=timestamps[index],
                map_from_sensor=Transform(
                    parent_frame=request.odometry_map_frame_id,
                    local_frame=request.sensor_frame_id,
                    translation_xyz=tuple(translation),
                    rotation_quaternion_xyzw=tuple(quaternion),
                ),
            )
            for index, (scan, matrix) in enumerate(zip(request.scans, matrices, strict=True))
            for translation, quaternion in [_matrix_transform(matrix)]
        ]
        gaps = [right - left for left, right in zip(timestamps, timestamps[1:])]
        gap_count = sum(gap > request.profile.timestamp_gap_threshold_seconds for gap in gaps)
        execution = EstimatedTrajectoryExecutionMetrics(
            process_elapsed_seconds=_finite_nonnegative(output["process_elapsed_seconds"], "process elapsed time"),
            provider_elapsed_seconds=_finite_nonnegative(output["provider_elapsed_seconds"], "provider elapsed time"),
            provider_cpu_seconds=_finite_nonnegative(output["provider_cpu_seconds"], "provider CPU time"),
            provider_peak_rss_bytes=_positive_integer(output["provider_peak_rss_bytes"], "provider peak RSS"),
            scan_point_counts=scan_point_counts,
        )
        diagnostics = EstimatedTrajectoryDiagnostics(
            scan_count=len(request.scans),
            valid_pose_count=len(poses),
            coverage_ratio=1.0,
            timestamp_gap_threshold_seconds=request.profile.timestamp_gap_threshold_seconds,
            timestamp_gap_count=gap_count,
            maximum_timestamp_gap_seconds=max(gaps),
            execution_metrics=execution,
        )
        lockfile = Path(__file__).resolve().parents[4] / "requirements-lidar-odometry.lock.txt"
        if not lockfile.is_file():
            raise LidarOdometryRuntimeUnavailableError("Pinned LiDAR odometry lockfile is missing")
        payload = {
            "artifact_type": "EstimatedTrajectoryArtifact",
            "schema_version": "1.0",
            "artifact_uri": (
                f"artifact://jobs/{request.job_id}/attempts/{request.attempt_id}/lidar-odometry/trajectory.json"
            ),
            # The contract checksum is a logical-content identity; ArtifactRef below binds exact JSON bytes.
            "artifact_checksum": "sha256:" + "0" * 64,
            "job_id": request.job_id,
            "assembly_id": request.assembly_id,
            "assembly_revision": request.assembly_revision,
            "assembly_checksum": request.assembly_checksum,
            "recipe_checksum": request.recipe_checksum,
            "provider_id": output["provider_id"],
            "provider_version": output["provider_version"],
            "adapter_protocol_version": "1",
            "runtime_qualification_checksum": _sha256(lockfile.read_bytes()),
            "config_checksum": _canonical_checksum(request.profile.model_dump(mode="json")),
            "timestamp_file_checksum": request.timestamp_file_ref.artifact_checksum,
            "coordinate_unit": "meter",
            "sensor_frame_id": request.sensor_frame_id,
            "odometry_map_frame_id": request.odometry_map_frame_id,
            "world_from_map": None,
            "trajectory_origin": "estimated",
            "runtime_qualification_status": "wired_unqualified",
            "poses": [pose.model_dump(mode="json") for pose in poses],
            "diagnostics": diagnostics.model_dump(mode="json"),
        }
        provisional = EstimatedTrajectoryArtifact.model_validate(payload)
        payload["artifact_checksum"] = canonical_content_checksum(provisional, "artifact_checksum")
        trajectory = EstimatedTrajectoryArtifact.model_validate(payload)
        verify_content_checksum(trajectory, "artifact_checksum")
        return trajectory

    @staticmethod
    def _require_current_lease(lease_is_current: Callable[[], bool]) -> None:
        if not lease_is_current():
            raise LidarOdometryLeaseLostError("LiDAR odometry operation lease is no longer current")

    def _require_running(self, cancel_event: Event | None, lease_is_current: Callable[[], bool]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise LidarOdometryCancelledError("LiDAR odometry was cancelled")
        self._require_current_lease(lease_is_current)


def _matrix_transform(value: object) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """Validate a provider SE(3) matrix and convert its rotation to normalized xyzw."""
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise LidarOdometryProcessError("KISS-ICP pose is not a numeric matrix") from error
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise LidarOdometryProcessError("KISS-ICP pose must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-6):
        raise LidarOdometryProcessError("KISS-ICP pose has an invalid homogeneous row")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, rel_tol=1e-3, abs_tol=1e-3
    ):
        raise LidarOdometryProcessError("KISS-ICP pose rotation is not a proper SE(3) rotation")
    quaternion = _rotation_matrix_to_quaternion(rotation)
    translation = tuple(float(value) for value in matrix[:3, 3])
    return translation, quaternion


def _rotation_matrix_to_quaternion(rotation: np.ndarray) -> tuple[float, float, float, float]:
    """Convert a proper 3x3 rotation into normalized xyzw quaternion form."""
    trace = float(np.trace(rotation))
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2.0
        values = (
            (rotation[2, 1] - rotation[1, 2]) / scale,
            (rotation[0, 2] - rotation[2, 0]) / scale,
            (rotation[1, 0] - rotation[0, 1]) / scale,
            0.25 * scale,
        )
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        values = (
            0.25 * scale,
            (rotation[0, 1] + rotation[1, 0]) / scale,
            (rotation[0, 2] + rotation[2, 0]) / scale,
            (rotation[2, 1] - rotation[1, 2]) / scale,
        )
    elif rotation[1, 1] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        values = (
            (rotation[0, 1] + rotation[1, 0]) / scale,
            0.25 * scale,
            (rotation[1, 2] + rotation[2, 1]) / scale,
            (rotation[0, 2] - rotation[2, 0]) / scale,
        )
    else:
        scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        values = (
            (rotation[0, 2] + rotation[2, 0]) / scale,
            (rotation[1, 2] + rotation[2, 1]) / scale,
            0.25 * scale,
            (rotation[1, 0] - rotation[0, 1]) / scale,
        )
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0 or not math.isfinite(norm):
        raise LidarOdometryProcessError("KISS-ICP rotation could not be converted to a quaternion")
    return tuple(value / norm for value in values)


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise LidarOdometryProcessError(f"KISS-ICP {label} must be finite and nonnegative")
    return float(value)


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LidarOdometryProcessError(f"KISS-ICP {label} must be a positive integer")
    return value


def _canonical_checksum(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return _sha256(data)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
