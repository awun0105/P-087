"""Basic worker runner cho RGB jobs, chạy ngoài HTTP process.

REC vẫn sở hữu thuật toán và consumer verification. Runner chỉ claim durable job,
chạy entrypoint cố định của REC qua process boundary, quan sát cancel/timeout và
commit result đã kiểm chứng. Hai đường vào:

- `run_prepared_job`: job đã có frame set publish sẵn (dataset/offline prep).
- `run_video_job`: job của video upload — chạy `prepare` (quality → privacy tự khai
  → frame set) rồi preview COLMAP/Brush trong cùng một attempt.

Runner không tự cấp privacy approval: gate nằm ở project policy và REC gate.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from src.config import Settings, get_settings
from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.input_assembly import (
    CandidateState,
    ClockRelation,
    CloudObservationState,
    DistanceUnit,
    InputAssemblySnapshot,
    InputAssetFormat,
    InputRecipe,
    InputResolutionReport,
    InputResolutionState,
    InputRole,
    RecipeGroup,
    RuntimeCapabilityKey,
    RuntimeCapabilityRecord,
    RuntimeQualificationRegistry,
    RuntimeQualificationStatus,
    StagedInputFile,
    TimestampUnit,
    TrajectoryOrigin,
    VideoRecipeCandidate,
    verify_input_assembly_checksum,
    verify_input_recipe_checksum,
    verify_input_resolution_checksum,
    verify_runtime_registry_checksum,
)
from src.models.contracts.manifests import (
    ExecutionError,
    InputManifest,
    JobManifest,
    JobStatus,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.models.contracts.preview import ReconstructionPreview
from src.models.contracts.retryability import classify_retryability
from src.services.orchestration.artifacts import (
    ArtifactResolver,
    ArtifactStoreError,
    FilesystemArtifactStore,
    lod,
    sha256_bytes,
)
from src.services.orchestration.benchmark import build_benchmark, publish_benchmark
from src.services.orchestration.inputs import InputAssemblyService
from src.services.orchestration.inputs.compatibility import INPUT_ASSEMBLY_RUNNABLE_RECIPE_GROUPS
from src.services.orchestration.inputs.loose_package import LoosePackageError, verify_package_members
from src.services.orchestration.jobs.admission import ResourceAdmission, job_drivers, touch_job_reservation
from src.services.orchestration.jobs.anonymization_review import accept_when_nothing_redacted
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import (
    ResolvedProcessing,
    prepared_frame_reference,
    require_profile,
    resolve_job_processing,
)
from src.services.orchestration.jobs.heartbeat import HeartbeatTolerance
from src.services.orchestration.jobs.lease import LEASE_TTL, lease_lost
from src.services.orchestration.jobs.log_context import configure_worker_logging, job_log_context
from src.services.orchestration.jobs.models import PreparedInputReceipt, TransitionRequest
from src.services.orchestration.jobs.profile import machine_runtime_checksum
from src.services.orchestration.jobs.progress import (
    awaiting_anonymization_review,
    awaiting_finalize,
    awaiting_pose_step,
    awaiting_scene_extract,
    metric_confirmation_stage,
)
from src.services.orchestration.jobs.step_marks import MarkWrite, record_marks
from src.services.orchestration.jobs.workspace import attempt_lease, cleanup_attempt_workspace, cleanup_finished_job
from src.services.orchestration.processing.capability import latest as latest_capability
from src.services.orchestration.processing.capability import probe as probe_capability
from src.services.orchestration.processing.config import load_job_config
from src.services.orchestration.processing.expected_duration import Estimate, deadline_seconds, expected_seconds
from src.services.orchestration.processing.gpu_budget import (
    GPU_TOOLS,
    GpuBudgetExceededError,
    running_message,
    spent_gpu_hours,
    start_message,
)
from src.services.orchestration.processing.observed import load_usages, pipeline_usages
from src.services.orchestration.processing.telemetry import (
    Outcome,
    ResourceContext,
    ResourceSampler,
    ResourceUsage,
    sampled_section,
)
from src.services.orchestration.processing.usage_recording import build_sampler, record_usage
from src.services.orchestration.projects.models import LidarPackageMember, ProjectRecord
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.reconstruction import (
    MogeSettings,
    confirmation_summary,
    load_finalize_result,
    load_geometry_profile,
    propose_metric,
    verify_prepared_preview,
)

logger = logging.getLogger(__name__)

_MAX_TOOL_RESPONSE_BYTES = 1048576
_JOB_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"


def _attempt_log_id(registry: ProjectRegistry, job_id: str) -> str:
    """Use the durable attempt sequence as the stable log correlation ID."""
    history = registry.list_job_attempts(job_id)
    return str(history[-1].attempt) if history else "-"


class PreviewCancelledError(RuntimeError):
    """Owner hoặc process khác đã kết thúc job; không được publish success muộn."""


def _stop(process: subprocess.Popen) -> None:
    """Nhả cả COLMAP/Brush/FFmpeg con; không để GPU tiếp tục chạy sau khi cancel."""
    # Leader có thể đã thoát nhưng children trong group vẫn đọc scratch/GPU.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    # Sau TERM, parent có thể thoát trước child. Dừng group còn lại trước cleanup.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


@dataclass
class _Attempt:
    """Một attempt đang chạy; `job` luôn là revision mới nhất do chính runner ghi."""

    registry: ProjectRegistry
    settings: Settings
    job: JobManifest
    workspace: Path
    #: Một công cụ của attempt này lỗi trong lúc GPU/RAM gần cạn (suy luận từ số đo).
    exhausted: bool = False


@dataclass(frozen=True)
class _AcceptedRecipeEvidence:
    assembly: InputAssemblySnapshot
    report: InputResolutionReport
    runtime_registry: RuntimeQualificationRegistry
    recipe: InputRecipe


_MARK_OUTCOMES = {StageStatus.SUCCEEDED: "succeeded", StageStatus.FAILED: "failed", StageStatus.CANCELLED: "cancelled"}


class _StageProgress:
    """Đọc dần progress file của REC (JSON lines StageArtifact) và đẩy stage RUNNING vào job."""

    def __init__(self, attempt: _Attempt, path: Path) -> None:
        self.attempt = attempt
        self.path = path
        self.offset = 0
        #: Số lượt chạy hiện tại, dùng làm run_id của mốc bước (T-056); đọc lười ở lần ghi đầu.
        self.run_id: str | None = None

    def poll(self) -> None:
        """Chỉ xử lý dòng hoàn chỉnh; dòng đang ghi dở đợi lượt sau."""
        if not self.path.is_file():
            return
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read()
        complete = chunk[: chunk.rfind(b"\n") + 1]
        self.offset += len(complete)
        for line in complete.splitlines():
            stage = StageArtifact.model_validate_json(line)
            if stage.status == StageStatus.RUNNING:
                self.attempt.job = self.attempt.registry.record_stage_progress(
                    self.attempt.job, stage.stage_id, started_at=stage.started_at
                )
            elif stage.completed_at is not None and stage.status in _MARK_OUTCOMES:
                self._mark_finished(stage)

    def _mark_finished(self, stage: StageArtifact) -> None:
        """Ghi mốc kết thúc ngay khi worker báo xong (T-056); receipt cuối lượt vẫn ghi lại cùng mốc."""
        persistence = self.attempt.registry.persistence
        if persistence is None or stage.completed_at is None:
            return
        if self.run_id is None:
            try:
                self.run_id = str(persistence.list_attempts(self.attempt.job.job_id)[-1].attempt)
            except Exception as error:  # noqa: BLE001 - mốc bước là đo đạc, không được làm hỏng lượt chạy
                logger.warning("Không đọc được lượt chạy để ghi mốc bước cause=%s", type(error).__name__)
                return
        record_marks(
            persistence.database,
            self.attempt.job.job_id,
            "pipeline",
            self.run_id,
            [MarkWrite("finish", stage.stage_id.value, stage.completed_at, _MARK_OUTCOMES[stage.status])],
        )


class ExpectedDurationError(TimeoutError):
    """Công cụ vượt hạn tự tính theo số đo của chính máy này (T-043), không phải giới hạn cố định."""

    code = "EXPECTED_DURATION_EXCEEDED"


def _expected_limit(attempt: _Attempt, name: str, fixed_timeout: float) -> tuple[float, Estimate | None]:
    """Hạn của một lượt công cụ: theo số đo khi có đủ; không thì giữ giới hạn cố định như trước."""
    registry = attempt.registry
    if registry.persistence is None:
        return fixed_timeout, None
    try:
        capability = latest_capability(registry.persistence.database)
        params = job_drivers(registry, attempt.settings, attempt.job)
        if capability is None or params is None:
            return fixed_timeout, None
        usages = load_usages(registry.persistence.database)
        if any(
            usage.job_id == attempt.job.job_id and usage.tool == name and usage.outcome == "timeout" for usage in usages
        ):
            # T-050: lượt trước của chính công cụ này đã bị cắt vì quá hạn; dùng lại cùng số đo sẽ cắt lặp lại.
            logger.info(
                "Lượt trước của %s bị cắt vì quá hạn; lượt này dùng giới hạn cố định %.0f s", name, fixed_timeout
            )
            return fixed_timeout, None
        estimate = expected_seconds(name, params, capability.gpu_name, attempt.job.runtime_manifest_checksum, usages)
    except Exception as error:  # noqa: BLE001 - ước lượng chỉ là phụ; lỗi đọc số đo không được làm hỏng lượt chạy
        logger.warning("Không tính được hạn theo số đo tool=%s cause=%s", name, type(error).__name__)
        return fixed_timeout, None
    if estimate is None:
        return fixed_timeout, None
    return deadline_seconds(estimate, fixed_timeout), estimate


def _gpu_budget_at_start(attempt: _Attempt, name: str, estimate: Estimate | None) -> tuple[float, float] | None:
    """(giờ GPU đã dùng, trần) khi job có trần và công cụ dùng GPU; chưa đủ ước thì chỉ kiểm phần đã dùng."""
    # Settings giả trong test có thể thiếu trường mới: coi như không đặt trần (cùng mẫu với api/studio/deps.py).
    cap = getattr(attempt.settings, "product_job_gpu_hours_max", None)
    if cap is None or name not in GPU_TOOLS or attempt.registry.persistence is None:
        return None
    spent = spent_gpu_hours(load_usages(attempt.registry.persistence.database), attempt.job.job_id)
    planned = estimate.seconds / 3600 if estimate is not None else 0.0
    if spent + planned > cap:
        raise GpuBudgetExceededError(start_message(spent, planned, cap, name))
    return spent, cap


def _write_expectation(path: Path, fixed_timeout: float, deadline: float, estimate: Estimate | None) -> None:
    """Ghi hạn đã dùng và ước lượng vào workspace: lượt sau đọc lại được vì sao hạn là bao nhiêu."""
    record = {
        "fixed_limit_seconds": fixed_timeout,
        "deadline_seconds": deadline,
        "estimate": asdict(estimate) if estimate is not None else None,
    }
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _expected_message(name: str, estimate: Estimate, elapsed: float) -> str:
    minutes = max(1, round(elapsed / 60))
    times = round(elapsed / estimate.seconds, 1)
    return (
        f"{name} chạy quá {minutes} phút, gấp {times} lần thời gian thường thấy trên {estimate.gpu_name} "
        "cho scene cỡ này; đã dừng."
    )


def _run_tool(
    attempt: _Attempt,
    name: str,
    command: list[str],
    timeout: float,
    progress: _StageProgress | None = None,
) -> tuple[int, dict]:
    """Chạy một REC CLI trong process group riêng, hủy khi job revision đổi (cancel)."""
    stdout_path = attempt.workspace / f"{name}.stdout.json"
    sampler = _resource_sampler(attempt, name)
    deadline_limit, estimate = _expected_limit(attempt, name, timeout)
    _write_expectation(attempt.workspace / f"{name}.expected.json", timeout, deadline_limit, estimate)
    gpu_budget = _gpu_budget_at_start(attempt, name, estimate)
    outcome: Outcome = "failed"
    exit_code: int | None = None
    try:
        with stdout_path.open("xb") as output, (attempt.workspace / f"{name}.stderr.log").open("xb") as errors:
            process = subprocess.Popen(
                command, stdout=output, stderr=errors, stdin=subprocess.DEVNULL, start_new_session=True
            )
            started = time.monotonic()
            deadline = started + deadline_limit
            tolerance = HeartbeatTolerance(LEASE_TTL)
            last_heartbeat = 0.0
            pause = Event()
            try:
                while process.poll() is None:
                    now_mono = time.monotonic()
                    try:
                        if now_mono - last_heartbeat >= 3.0:
                            if attempt.registry.persistence is not None:
                                touch_job_reservation(attempt.registry.persistence.database, attempt.job.job_id)
                            last_heartbeat = now_mono
                        if progress is not None:
                            progress.poll()  # Tự cập nhật attempt.job trước khi so revision để phát hiện cancel.
                        current = attempt.registry.get_job(attempt.job.job_id)
                        tolerance.succeeded()
                    except Exception as error:
                        if not tolerance.tolerate(error):
                            raise
                        current = None  # DB chập chờn: bỏ qua kiểm hủy ở nhịp này (T-049)
                    if current is not None and current.job_manifest_checksum != attempt.job.job_manifest_checksum:
                        raise PreviewCancelledError("Job revision đã thay đổi trong khi worker chạy")
                    if lease_lost(attempt.job.job_id):
                        raise PreviewCancelledError("Mất lease job; máy khác đã nhận việc, dừng tiến trình con")
                    if gpu_budget is not None:
                        spent_now = gpu_budget[0] + (time.monotonic() - started) / 3600
                        if spent_now > gpu_budget[1]:
                            raise GpuBudgetExceededError(running_message(spent_now, gpu_budget[1], name))
                    if time.monotonic() >= deadline:
                        if estimate is None:
                            raise TimeoutError(f"{name} worker quá thời gian cấu hình")
                        raise ExpectedDurationError(_expected_message(name, estimate, time.monotonic() - started))
                    _sample_resources(sampler, process.pid)
                    pause.wait(1)
            finally:
                _stop(process)
                exit_code = process.returncode
                _sample_resources(sampler, process.pid)
        if stdout_path.stat().st_size > _MAX_TOOL_RESPONSE_BYTES:
            raise ValueError(f"{name} worker response vượt giới hạn 1 MiB")
        lines = stdout_path.read_bytes().strip().splitlines()
        payload = json.loads(lines[-1]) if lines else None
        if not isinstance(payload, dict):
            raise RuntimeError(f"{name} worker không trả result hợp lệ")
        outcome = "completed" if exit_code == 0 else "failed"
        return exit_code, payload
    except PreviewCancelledError:
        outcome = "cancelled"
        raise
    except TimeoutError:
        outcome = "timeout"
        raise
    except KeyboardInterrupt:
        outcome = "interrupted"  # Worker nhận SIGTERM/Ctrl+C: không phải lỗi của tool.
        raise
    finally:
        usage = _finish_resources(attempt, sampler, outcome, exit_code)
        attempt.exhausted = attempt.exhausted or (usage is not None and usage.exhausted)


def _finish_resources(
    attempt: _Attempt, sampler: ResourceSampler | None, outcome: Outcome, exit_code: int | None
) -> ResourceUsage | None:
    """Ghi bản ghi đo vào workspace rồi vào DB; lỗi ghi không che kết quả/lỗi chính của tool."""
    if sampler is None:
        return None
    try:
        usage = sampler.finish(outcome, exit_code)
    except Exception as error:  # noqa: BLE001 - telemetry process boundary, preserve primary result/error
        logger.warning("Không ghi được resource telemetry cause=%s", type(error).__name__)
        return None
    _persist_usage(attempt, usage)
    return usage


def _persist_usage(attempt: _Attempt, usage: ResourceUsage) -> None:
    """Lưu bản ghi vào runtime DB khi job có persistence."""
    persistence = attempt.registry.persistence
    if persistence is None:
        return
    record_usage(persistence.database, usage)


@contextmanager
def _sampled(attempt: _Attempt, tool: str) -> Iterator[None]:
    """Đo một bước chạy ngay trong tiến trình worker (không qua `_run_tool`)."""
    sampler = _resource_sampler(attempt, tool)
    outcome: Outcome = "failed"
    try:
        with sampled_section(
            sampler,
            on_error=lambda error: logger.warning("Không lấy được resource sample cause=%s", type(error).__name__),
        ):
            yield
        outcome = "completed"
    except KeyboardInterrupt:
        outcome = "interrupted"
        raise
    finally:
        _finish_resources(attempt, sampler, outcome, None)


def _resource_sampler(attempt: _Attempt, tool: str) -> ResourceSampler | None:
    """Best effort measurement boundary; probe lỗi không chặn dispatch hoặc đổi config."""
    try:
        settings, registry = attempt.settings, attempt.registry
        shared: bool | None = None
        if registry.persistence is not None:
            shared = ResourceAdmission(registry, settings).shares_gpu()
        context = ResourceContext(
            job_id=attempt.job.job_id,
            attempt_id=attempt.workspace.name,
            tool=tool,
            config_checksum=attempt.job.config_checksum,
            runtime_manifest_checksum=machine_runtime_checksum(
                registry.execution_profile, attempt.job.runtime_manifest_checksum
            ),
            params=job_drivers(registry, settings, attempt.job),
            shared_gpu=shared,
        )
    except Exception as error:  # noqa: BLE001 - measurement boundary must not change job execution
        logger.warning("Không tạo được resource sampler cause=%s", type(error).__name__)
        return None
    return build_sampler(settings, context, attempt.workspace)


def _requeue_if_exhausted(attempt: _Attempt) -> JobManifest | None:
    """Job FAILED vì nhiều khả năng hết bộ nhớ: tự đưa về hàng đợi đúng một lần.

    Lượt chạy lại được gate cho chạy một mình trên GPU (job đã có bản ghi `exhausted`). Lượt đó
    mà vẫn hết bộ nhớ thì giữ FAILED: máy này không đủ cho cấu hình, chạy lại nữa chỉ lặp vô ích.
    Đây là hệ thống tự sửa việc xếp lịch, không qua API retry nên không tính vào hạn mức người dùng.
    """
    persistence = attempt.registry.persistence
    if not attempt.exhausted or persistence is None:
        return None
    try:
        current = attempt.registry.get_job(attempt.job.job_id)
        if current.status != JobStatus.FAILED:
            return None
        earlier = sum(
            1
            for usage in pipeline_usages(load_usages(persistence.database))
            if usage.job_id == current.job_id and usage.exhausted
        )
        if earlier > 1:
            logger.warning("Job %s hết bộ nhớ cả khi chạy một mình; giữ FAILED", current.job_id)
            return None
        logger.warning("Job %s có dấu hiệu hết bộ nhớ; tự xếp lại để chạy một mình trên GPU", current.job_id)
        return attempt.registry.transition_job(
            current.job_id,
            TransitionRequest(target_status=JobStatus.QUEUED),
            expected_checksum=current.job_manifest_checksum,
        )
    except Exception as error:  # noqa: BLE001 - tự phục hồi là best effort; job vẫn FAILED đúng như đã ghi
        logger.warning("Không tự xếp lại được job sau khi hết bộ nhớ cause=%s", type(error).__name__)
        return None


def _sample_resources(sampler: ResourceSampler | None, process_group: int) -> None:
    """Isolation boundary: sampler fail không làm tool chạy thành công trở thành lỗi."""
    if sampler is not None:
        try:
            sampler.sample(process_group)
        except Exception as error:  # noqa: BLE001 - preserve worker error/result if optional monitoring fails
            logger.warning("Không lấy được resource sample cause=%s", type(error).__name__)


def _record_runner_failure(attempt: _Attempt, error: BaseException) -> None:
    """Process boundary: ghi FAILED có redaction trên đúng revision runner đang giữ."""
    current = attempt.registry.get_job(attempt.job.job_id)
    if current.job_manifest_checksum != attempt.job.job_manifest_checksum:
        if current.status == JobStatus.CANCELLED:
            _record_benchmark(attempt)
        return
    details = {"exception_type": type(error).__name__}
    if isinstance(error, ExpectedDurationError | GpuBudgetExceededError):
        code, message = error.code, str(error)
    elif isinstance(error, KeyboardInterrupt | SystemExit):
        # Worker bị tắt (SIGTERM/Ctrl-C, deploy): gián đoạn giống mất lease, không phải lỗi của job.
        code = "INTERRUPTED_SHUTDOWN"
        message = "Worker dừng giữa chừng (tắt hoặc khởi động lại máy xử lý). Bấm Thử lại để chạy tiếp."
    else:
        code, message = "PREVIEW_RUNNER_FAILED", "Worker dừng trước checkpoint hợp lệ; kiểm log attempt và runtime"
    try:
        attempt.job = attempt.registry.transition_job(
            attempt.job.job_id,
            TransitionRequest(
                target_status=JobStatus.FAILED,
                error=ExecutionError(
                    stage_id=current.current_stage,
                    error_code=code,
                    human_message=message,
                    retryable=classify_retryability(code, details),
                    details=details,
                ),
            ),
            expected_checksum=attempt.job.job_manifest_checksum,
        )
        _record_benchmark(attempt)
    except RuntimeStateConflictError:
        logger.info("Worker failure không ghi đè revision mới hơn")


def _prepare_claimed_attempt(attempt: _Attempt) -> str:
    """Chuẩn bị workspace + log id cho job vừa claim RUNNING; lỗi ở đây được ghi FAILED thay vì để job treo (T-048)."""
    try:
        attempt.workspace.mkdir(parents=True, exist_ok=False)
        return _attempt_log_id(attempt.registry, attempt.job.job_id)
    except BaseException as error:
        _record_runner_failure(attempt, error)
        raise


def _start_attempt(
    job_id: str, expected_checksum: str | None, first_stage: StageId
) -> tuple[_Attempt, ResolvedProcessing]:
    """Kiểm profile rồi CAS claim QUEUED→RUNNING; hai runner không thể cùng thắng."""
    settings = get_settings()
    registry = get_project_registry()
    initial = registry.get_job(job_id)
    if expected_checksum is not None and initial.job_manifest_checksum != expected_checksum:
        raise RuntimeStateConflictError("Queue candidate đã thay đổi trước dispatch")
    if re.fullmatch(_JOB_ID_PATTERN, job_id) is None:
        raise ValueError("Job ID không thể dùng làm worker namespace")
    profile_path = settings.product_processing_config
    if profile_path is None or registry.execution_profile is None:
        raise ValueError("Worker cần execution profile đã cấu hình")
    require_profile(initial, registry.execution_profile)
    profile = resolve_job_processing(
        initial,
        registry.execution_profile,
        profile_path,
        registry.runtime_resolver,
        settings.product_target_frame_count,
    )
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / f"attempt-{uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=False)
    job = registry.transition_job(
        job_id,
        TransitionRequest(target_status=JobStatus.RUNNING, current_stage=first_stage),
        expected_checksum=initial.job_manifest_checksum,
    )
    # Máy GPU thuê khởi động với cache rỗng: kéo artifact các attempt trước của job về.
    registry.runtime_resolver.sync_down(job_id)
    return _Attempt(registry, settings, job, workspace), profile


def _lidar_package_ref(job: JobManifest) -> ProductArtifactRef | None:
    """`LidarPackageRecord` của job nếu bước nhận LiDAR đã chạy xong; job chỉ có video trả None."""
    stage = next(
        (item for item in job.stage_artifacts if item.stage_id == StageId.LIDAR_INGEST and item.artifact_uri),
        None,
    )
    if stage is None:
        return None
    return ProductArtifactRef(
        artifact_type=stage.artifact_type or "LidarPackageRecord",
        schema_version="1.0",
        artifact_uri=stage.artifact_uri,
        artifact_checksum=stage.artifact_checksum,
        data_class=stage.data_class,
        producer_stage=StageId.LIDAR_INGEST,
        job_id=job.job_id,
    )


def _execute_preview(attempt: _Attempt, frames: ProductArtifactRef, profile: ResolvedProcessing) -> JobManifest:
    """COLMAP → Brush → preview trên frame set đã verify, rồi commit receipt."""
    attempt.registry.runtime_resolver.require(frames)
    attempt_id = f"preview-{uuid4().hex}"
    request = {
        "schema_version": "1.0",
        "execution_scope": "prepared_rgb_preview",
        "job_id": attempt.job.job_id,
        "attempt_id": attempt_id,
        "source_input_checksum": attempt.job.input_manifest_checksum,
        "frame_set_ref": frames.model_dump(mode="json"),
        "colmap": profile.colmap,
        "brush": profile.brush,
    }
    # Job có gói LiDAR (ADR 0009): giao bản ghi gói cho REC để dựng pose bám theo quỹ đạo.
    lidar = _lidar_package_ref(attempt.job)
    if lidar is not None:
        request["lidar_package_ref"] = lidar.model_dump(mode="json")
    request_path = attempt.workspace / "preview.request.json"
    with request_path.open("x", encoding="utf-8") as stream:
        json.dump(request, stream)
    command = [
        sys.executable,
        "-m",
        "src.services.reconstruction.preview_cli",
        "--request",
        str(request_path),
        "--store-root",
        str(attempt.registry.runtime_resolver.artifact_root),
        "--workspace",
        str(attempt.workspace / "rec"),
        "--progress-file",
        str(attempt.workspace / "preview.progress.jsonl"),
        # Cùng thư mục cho mọi attempt của job: retry sau khi đứt dùng lại COLMAP + checkpoint Brush.
        "--resume-root",
        str(attempt.workspace.parent / "resume"),
    ]
    progress = _StageProgress(attempt, attempt.workspace / "preview.progress.jsonl")
    exit_code, payload = _run_tool(
        attempt, "preview", command, attempt.settings.product_preview_timeout_seconds, progress
    )
    # REC ghi mọi output vào `jobs/<job_id>/`; đẩy lên kho file trước khi commit để API đọc được.
    attempt.registry.runtime_resolver.sync_up(attempt.job.job_id)
    if exit_code not in {0, 1}:
        raise RuntimeError("Preview worker không trả result hợp lệ")
    reference = ProductArtifactRef.model_validate(payload.get("result_ref"))
    receipt = verify_prepared_preview(reference, attempt.registry.runtime_resolver.require)
    if receipt.attempt_id != attempt_id or (receipt.error is None) != (exit_code == 0):
        raise ValueError("Worker result khác attempt/exit status")
    preview_verified_at = datetime.now(UTC) if receipt.error is None else None
    # Trước khi job chuyển sang chờ xác nhận tỉ lệ: khi người dùng mở bước đó thì đề xuất đã có (hoặc
    # chắc chắn không có), UI không phải đoán "đang tính" hay "không bật".
    _propose_metric(attempt, receipt.preview_ref)
    job = attempt.registry.record_preview(attempt.job, receipt, verified_at=preview_verified_at)
    _record_benchmark(attempt)
    if receipt.error is None:
        _cleanup_attempt_workspace(attempt)
    return job


def _propose_metric(attempt: _Attempt, preview_ref: ProductArtifactRef | None) -> None:
    """Đề xuất tỉ lệ/mặt sàn tự động (ADR 0001 §2) cho preview vừa dựng; không bao giờ làm hỏng job.

    Không cấu hình runtime MoGe, không đủ dữ liệu hoặc lỗi runtime đều chỉ có nghĩa là không có đề
    xuất: người dùng xác nhận tỉ lệ bằng số đo tay như trước.
    """
    if preview_ref is None:
        return
    resolver = attempt.registry.runtime_resolver
    try:
        preview = ReconstructionPreview.model_validate_json(resolver.require(preview_ref).read_bytes())
        lidar = _lidar_package_ref(attempt.job)
        if lidar is not None:
            # Job có gói LiDAR (ADR 0009): tỉ lệ và sàn lấy từ căn chỉnh quỹ đạo, không chạy mô hình đoán độ sâu.
            from src.services.reconstruction import propose_metric_from_lidar

            propose_metric_from_lidar(
                attempt.job.job_id,
                preview.source_visual_ref,
                lidar,
                resolver.require,
                FilesystemArtifactStore(resolver),
                resolver.locate,
            )
            resolver.sync_up(attempt.job.job_id)
            logger.info("Đề xuất tỉ lệ từ LiDAR job=%s", attempt.job.job_id)
            return
        settings = MogeSettings()
        if settings.python is None or settings.model is None:
            return
        with _sampled(attempt, "metric_proposal"):
            reference = propose_metric(
                attempt.job.job_id,
                preview.source_visual_ref,
                resolver.require,
                FilesystemArtifactStore(resolver),
                resolver.locate,
                attempt.workspace / "metric_proposal",
                settings,
            )
        if reference is not None:
            resolver.sync_up(attempt.job.job_id)
        logger.info("Đề xuất tỉ lệ tự động job=%s: %s", attempt.job.job_id, "có" if reference else "không có")
    except Exception as error:  # noqa: BLE001 - bước phụ trợ: lỗi không được chặn preview đã dựng xong
        logger.warning("Không tạo được đề xuất tỉ lệ job=%s cause=%s", attempt.job.job_id, type(error).__name__)


def _cleanup_attempt_workspace(attempt: _Attempt) -> None:
    """Best effort sau verified/durable success; giữ nguyên log, resume và job state."""
    if attempt.settings.product_worker_keep_scratch:
        return
    try:
        result = cleanup_attempt_workspace(
            attempt.workspace,
            worker_root=attempt.settings.product_worker_root,
            artifact_root=attempt.registry.runtime_resolver.artifact_root,
        )
        logger.info(
            "Scratch cleanup files=%s bytes=%s errors=%s", result.files_removed, result.bytes_removed, result.errors
        )
    except (OSError, ValueError) as error:
        logger.warning("Bỏ qua scratch cleanup cause=%s", type(error).__name__)


def _cleanup_finished_job(attempt: _Attempt) -> None:
    """Job đã SUCCEEDED: bỏ scratch của các attempt cũ và resume (không còn retry nào đọc)."""
    if attempt.settings.product_worker_keep_scratch:
        return
    try:
        result = cleanup_finished_job(
            attempt.job.job_id,
            worker_root=attempt.settings.product_worker_root,
            artifact_root=attempt.registry.runtime_resolver.artifact_root,
        )
        logger.info(
            "Finished-job cleanup files=%s bytes=%s errors=%s",
            result.files_removed,
            result.bytes_removed,
            result.errors,
        )
    except (OSError, ValueError) as error:
        logger.warning("Bỏ qua finished-job cleanup cause=%s", type(error).__name__)


def _record_benchmark(attempt: _Attempt) -> None:
    """Ghi benchmark sau attempt; không bao giờ làm hỏng job vì lỗi đo đạc (process boundary)."""
    try:
        try:
            machine = probe_capability(attempt.settings.product_worker_root)
        except (OSError, ValueError) as error:
            logger.warning("Không đo được máy chạy benchmark cause=%s", type(error).__name__)
            machine = None
        benchmark = build_benchmark(
            attempt.registry,
            attempt.job.job_id,
            machine=machine,
            gpu_hourly_usd=attempt.settings.benchmark_gpu_hourly_usd,
            label=attempt.settings.benchmark_label,
        )
        publish_benchmark(attempt.registry, benchmark)
    except Exception:
        logger.exception("Không ghi được benchmark cho job %s", attempt.job.job_id)


def _pull_input(resolver: ArtifactResolver, manifest_ref: ProductArtifactRef) -> InputManifest:
    """Đưa InputManifest và input gốc vào cache cục bộ, kiểm đúng checksum trong manifest."""
    manifest = InputManifest.model_validate_json(resolver.require(manifest_ref).read_bytes())
    for item in manifest.files:
        resolver.require_uri(item.artifact_uri, item.checksum)
    if manifest.video_preparation is not None:
        # prepare_cli runs in a subprocess with a local-only resolver: the browser-prepared video's frame map must
        # be in the local cache too, or frame extraction fails with ArtifactNotFoundError on a remote worker.
        resolver.require(manifest.video_preparation.frame_map_ref)
    return manifest


def _validate_project_input_recipe(
    attempt: _Attempt,
    project: ProjectRecord,
    manifest: InputManifest,
) -> _AcceptedRecipeEvidence | None:
    """Recheck the accepted recipe, worker qualification, and bound source bytes before reconstruction resumes."""
    assembly_ref = project.input_assembly_ref
    if assembly_ref is None:
        return None
    resolution_ref = project.input_resolution_ref
    recipe_ref = project.input_recipe_ref
    runtime_ref = project.input_runtime_registry_ref
    references = (assembly_ref, resolution_ref, recipe_ref, runtime_ref)
    if any(reference is None for reference in references):
        raise ValueError("Grouped input project is missing an immutable evidence reference")
    if any(reference.job_id != project.project_id for reference in references if reference is not None):
        raise ValueError("Grouped input evidence points outside the project namespace")
    resolver = attempt.registry.runtime_resolver
    assembly = InputAssemblySnapshot.model_validate_json(resolver.require(assembly_ref).read_bytes())
    report = InputResolutionReport.model_validate_json(resolver.require(resolution_ref).read_bytes())
    recipe = InputRecipe.model_validate_json(resolver.require(recipe_ref).read_bytes())
    runtime_registry = RuntimeQualificationRegistry.model_validate_json(resolver.require(runtime_ref).read_bytes())
    verify_input_assembly_checksum(assembly)
    verify_input_resolution_checksum(report)
    verify_input_recipe_checksum(recipe)
    verify_runtime_registry_checksum(runtime_registry)
    if (
        recipe.assembly_id != assembly.assembly_id
        or recipe.assembly_revision != assembly.revision
        or recipe.assembly_checksum != assembly.assembly_checksum
        or report.assembly_id != assembly.assembly_id
        or report.assembly_revision != assembly.revision
        or report.assembly_checksum != assembly.assembly_checksum
        or report.report_checksum != recipe.resolution_checksum
        or report.runtime_registry_checksum != runtime_registry.registry_checksum
        or recipe.config_checksum != attempt.job.config_checksum
        or manifest.input_manifest_checksum != attempt.job.input_manifest_checksum
    ):
        raise ValueError("Grouped input recipe, report, runtime, and job checksums do not form one exact chain")
    if report.state != InputResolutionState.READY or report.recommended_candidate_id != recipe.candidate_id:
        raise ValueError("Accepted grouped input recipe is no longer the unique ready resolution")
    candidate = next((item for item in report.candidates if item.candidate_id == recipe.candidate_id), None)
    if (
        not isinstance(candidate, VideoRecipeCandidate)
        or candidate.state != CandidateState.READY
        or candidate.runtime.status != RuntimeQualificationStatus.QUALIFIED
        or candidate.recipe_group not in INPUT_ASSEMBLY_RUNNABLE_RECIPE_GROUPS
        or recipe.recipe_group != candidate.recipe_group
        or recipe.bindings != candidate.bindings
        or recipe.excluded_file_ids != candidate.excluded_file_ids
        or recipe.trajectory_origin != candidate.trajectory_origin
    ):
        raise ValueError("Accepted recipe has no current qualified reconstruction adapter")
    versions = {item.component_id: item for item in recipe.component_versions}
    runtime_version = versions.get(f"runtime-{candidate.runtime.runtime_id}")
    resolver_version = versions.get("input-resolver")
    if (
        runtime_version is None
        or runtime_version.version != candidate.runtime.runtime_version
        or runtime_version.config_checksum != candidate.runtime.qualification_evidence_checksum
        or resolver_version is None
        or resolver_version.version != report.resolver_version
        or resolver_version.config_checksum != runtime_registry.registry_checksum
    ):
        raise ValueError("Accepted recipe component versions do not match the qualified runtime evidence")
    bindings = {binding.role: binding.file_ids for binding in candidate.bindings}
    video_ids = bindings.get(InputRole.RGB_VIDEO, [])
    if len(video_ids) != 1:
        raise ValueError("Accepted recipe must bind exactly one RGB video")
    by_id = {item.file_id: item for item in assembly.files}
    video = by_id[video_ids[0]]
    video_manifest = [item for item in manifest.files if item.media_type in {"video/mp4", "video/quicktime"}]
    if (
        len(video_manifest) != 1
        or video.archive_member is not None
        or video.source_file.checksum != video_manifest[0].checksum
        or video.source_file.artifact_uri != video_manifest[0].artifact_uri
    ):
        raise ValueError("Accepted RGB binding does not match the worker InputManifest video")
    if candidate.recipe_group == RecipeGroup.RGB_ONLY:
        if manifest.input_configuration.registered_lidar_present or len(manifest.files) != 1:
            raise ValueError("R1 recipe must dispatch the video-only worker path")
        selected_upload_ids = {video.upload_id}
    elif candidate.recipe_group in {RecipeGroup.REGISTERED_MAP, RecipeGroup.SINGLE_STATIC_CLOUD}:
        source_role = (
            InputRole.REGISTERED_LIDAR_MAP
            if candidate.recipe_group == RecipeGroup.REGISTERED_MAP
            else InputRole.STATIC_LIDAR_CLOUD
        )
        source_ids = bindings.get(source_role, [])
        declarations = assembly.declarations
        source = by_id[source_ids[0]] if len(source_ids) == 1 else None
        expected_cloud_state = (
            CloudObservationState.REGISTERED_MAP
            if candidate.recipe_group == RecipeGroup.REGISTERED_MAP
            else CloudObservationState.SINGLE_STATIC_CLOUD
        )
        if (
            manifest.input_configuration.registered_lidar_present
            or manifest.lidar_metadata is not None
            or len(manifest.files) != 1
            or source is None
            or source.observed_format not in {InputAssetFormat.POINT_CLOUD_PCD, InputAssetFormat.POINT_CLOUD_PLY}
            or declarations.cloud_state is None
            or declarations.cloud_state.value != expected_cloud_state
            or declarations.same_scene is None
            or declarations.same_scene.value is not True
            or declarations.coordinate_unit is None
            or declarations.lidar_frame_id is None
        ):
            raise ValueError("R2/R3 recipe must bind one exact map/cloud source and a video-only worker manifest")
        selected_upload_ids = {video.upload_id, source.upload_id}
    elif candidate.recipe_group == RecipeGroup.SUPPLIED_TRAJECTORY:
        if not manifest.input_configuration.registered_lidar_present or manifest.lidar_metadata is None:
            raise ValueError("R4 recipe requires the existing LiDAR package worker stage")
        role_ids = [
            file_id
            for role in (
                InputRole.LIDAR_SCAN,
                InputRole.SENSOR_TRAJECTORY,
                InputRole.CAMERA_LIDAR_CALIBRATION,
                InputRole.RGB_FRAME_TIMES,
            )
            for file_id in bindings.get(role, [])
        ]
        if not role_ids:
            raise ValueError("R4 recipe has no LiDAR package members")
        package_upload_ids = {by_id[file_id].upload_id for file_id in role_ids}
        package_checksums = {
            by_id[file_id].archive_member.container_checksum
            for file_id in role_ids
            if by_id[file_id].archive_member is not None
        }
        lidar_files = [item for item in manifest.files if item.media_type == "application/zip"]
        lidar_provenance = (manifest.preparation_provenance or {}).get("lidar")
        synthesized = lidar_provenance.get("package_members") if isinstance(lidar_provenance, dict) else None
        if synthesized is not None:
            # Gói do server đóng từ file rời: kiểm theo danh sách thành viên + checksum nguồn đã niêm phong.
            evidence = lidar_provenance.get("evidence") if isinstance(lidar_provenance, dict) else None
            if (
                len(lidar_files) != 1
                or not isinstance(evidence, dict)
                or not isinstance(synthesized, list)
                or lidar_provenance.get("trajectory_origin") != "supplied"
                or candidate.trajectory_origin != TrajectoryOrigin.SUPPLIED
            ):
                raise ValueError("R4 recipe does not match the synthesized LiDAR package in InputManifest")
            try:
                verify_package_members(
                    [LidarPackageMember.model_validate(item) for item in synthesized],
                    staged=by_id,
                    role_bindings=bindings,
                    trajectory_member=str(evidence["trajectory_member"]),
                    calibration_member=str(evidence["calibration_member"]),
                    frame_times_member=str(evidence["frame_times_member"]),
                    scan_count=int(evidence["scan_count"]),
                )
            except (LoosePackageError, ValueError, KeyError, TypeError) as error:
                raise ValueError("R4 synthesized package does not match the accepted recipe") from error
            # Đối chiếu độc lập với danh sách thành viên trong manifest: tên thành viên thật của gói trên đĩa.
            # require_uri tải từ kho từ xa khi cần và kiểm checksum; không tìm thấy gói thì lỗi, không bỏ qua.
            import zipfile

            package_path = resolver.require_uri(lidar_files[0].artifact_uri, lidar_files[0].checksum)
            try:
                with zipfile.ZipFile(package_path) as package:
                    actual_members = set(package.namelist())
            except zipfile.BadZipFile as error:
                raise ValueError("R4 synthesized package is not a readable archive") from error
            if actual_members != {str(item["member_path"]) for item in synthesized}:
                raise ValueError("R4 synthesized package contents differ from its recorded member list")
            selected_upload_ids = {video.upload_id, *(by_id[file_id].upload_id for file_id in role_ids)}
        else:
            if (
                len(package_upload_ids) != 1
                or any(by_id[file_id].archive_member is None for file_id in role_ids)
                or len(package_checksums) != 1
                or len(lidar_files) != 1
                or next(iter(package_checksums)) != lidar_files[0].checksum
                or not isinstance(lidar_provenance, dict)
                or lidar_provenance.get("trajectory_origin") != "supplied"
                or candidate.trajectory_origin != TrajectoryOrigin.SUPPLIED
            ):
                raise ValueError("R4 recipe does not match the supplied-trajectory LiDAR package in InputManifest")
            selected_upload_ids = {video.upload_id, *package_upload_ids}
    else:
        if (
            manifest.input_configuration.registered_lidar_present
            or manifest.lidar_metadata is not None
            or len(manifest.files) != 1
            or candidate.trajectory_origin != TrajectoryOrigin.ESTIMATED
            or bindings.get(InputRole.SENSOR_TRAJECTORY)
        ):
            raise ValueError("R5/R6 must estimate a scan-native trajectory without entering the legacy LiDAR path")
        scan_ids = bindings.get(InputRole.LIDAR_SCAN, [])
        timestamp_ids = bindings.get(InputRole.LIDAR_SCAN_TIMES, [])
        if (
            len(scan_ids) < 2
            or len(timestamp_ids) != 1
            or assembly.declarations.coordinate_unit is None
            or assembly.declarations.coordinate_unit.value != DistanceUnit.METER
            or assembly.declarations.lidar_frame_id is None
            or (assembly.declarations.lidar_timestamp_unit is None and assembly.declarations.timestamp_unit is None)
        ):
            raise ValueError("R5/R6 recipe lost its metric ordered scans, sensor frame, or scan timestamps")
        if candidate.recipe_group == RecipeGroup.SENSOR_GUIDED and (
            len(bindings.get(InputRole.CAMERA_LIDAR_CALIBRATION, [])) != 1
            or len(bindings.get(InputRole.RGB_FRAME_TIMES, [])) != 1
            or (assembly.declarations.rgb_timestamp_unit is None and assembly.declarations.timestamp_unit is None)
        ):
            raise ValueError("R6 requires exact calibration and RGB frame-time bindings")
        if candidate.recipe_group == RecipeGroup.ESTIMATED_TRAJECTORY and (
            bindings.get(InputRole.CAMERA_LIDAR_CALIBRATION) or bindings.get(InputRole.RGB_FRAME_TIMES)
        ):
            raise ValueError("R5 scan-only recipe cannot bind R6 calibration or RGB frame times")
        selected_ids = [
            *scan_ids,
            *timestamp_ids,
            *bindings.get(InputRole.CAMERA_LIDAR_CALIBRATION, []),
            *bindings.get(InputRole.RGB_FRAME_TIMES, []),
        ]
        selected_files = [by_id[file_id] for file_id in selected_ids]
        if any(item.observed_format != InputAssetFormat.POINT_CLOUD_PCD for item in selected_files[: len(scan_ids)]):
            raise ValueError("R5/R6 currently support checked PCD scans only")
        if any(
            item.archive_member is not None and item.archive_member.container_checksum != item.source_file.checksum
            for item in selected_files
        ):
            raise ValueError("R5/R6 archive member no longer matches its uploaded container checksum")
        selected_upload_ids = {video.upload_id, *(by_id[file_id].upload_id for file_id in selected_ids)}

        odometry_runtime = next(
            (item for item in runtime_registry.capabilities if item.capability_key == RuntimeCapabilityKey.R5), None
        )
        if candidate.recipe_group == RecipeGroup.SENSOR_GUIDED:
            odometry_component = (
                versions.get(f"runtime-R5-{odometry_runtime.runtime_id}") if odometry_runtime is not None else None
            )
            if (
                odometry_runtime is None
                or odometry_runtime.status != RuntimeQualificationStatus.QUALIFIED
                or odometry_component is None
                or odometry_component.version != odometry_runtime.runtime_version
                or odometry_component.config_checksum != odometry_runtime.qualification_evidence_checksum
            ):
                raise ValueError("R6 requires the exact qualified R5 odometry runtime")
            if assembly.declarations.clock_relation is None or assembly.declarations.clock_relation.value not in {
                ClockRelation.SAME_CLOCK,
                ClockRelation.KNOWN_OFFSET,
            }:
                raise ValueError("R6 requires a declared RGB-to-LiDAR clock relation")
            if (
                assembly.declarations.clock_relation.value == ClockRelation.KNOWN_OFFSET
                and assembly.declarations.clock_offset_seconds is None
            ):
                raise ValueError("R6 known-offset clock relation requires the exact offset in seconds")
        if candidate.recipe_group in {RecipeGroup.ESTIMATED_TRAJECTORY, RecipeGroup.SENSOR_GUIDED}:
            from src.services.reconstruction.lidar.odometry import (
                DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION,
                lidar_odometry_profile_checksum,
            )

            profile_component = versions.get("odometry-profile")
            if (
                profile_component is None
                or profile_component.version != DEFAULT_LIDAR_ODOMETRY_PROFILE_VERSION
                or profile_component.config_checksum != lidar_odometry_profile_checksum()
            ):
                raise ValueError("Accepted R5/R6 recipe does not bind the exact odometry profile")
    service = InputAssemblyService(
        RuntimeDatabase(attempt.settings.database_url),
        str(attempt.settings.product_input_runtime_registry)
        if attempt.settings.product_input_runtime_registry is not None
        else None,
        resolver,
    )
    stored = service.get_assembly(assembly.assembly_id, assembly.revision)
    if stored.snapshot != assembly:
        raise ValueError("Published input assembly differs from the durable assembly revision")
    service.verify_upload_sources(stored, upload_ids=selected_upload_ids)
    current_resolution = service.resolve(assembly.assembly_id, assembly.revision)
    if current_resolution.report != report or current_resolution.runtime_registry != runtime_registry:
        raise ValueError("Worker runtime or input resolver version differs from the accepted recipe")
    return _AcceptedRecipeEvidence(assembly, report, runtime_registry, recipe)


def must_anonymize(job_choice: bool, settings: object, privacy_mode: str) -> bool:
    """Job tự chọn, deployment bắt buộc cho mọi job, hoặc project ở chế độ `qa_verified`.

    Worker tự quyết theo chế độ của project, không tin cấu hình job do API ghi: một job `qa_verified` thiếu cờ
    `anonymize` vẫn bị che. Settings giả trong test có thể không có trường `product_anonymize_input`.
    """
    return job_choice or bool(getattr(settings, "product_anonymize_input", False)) or privacy_mode == "qa_verified"


def _execute_prepare(attempt: _Attempt, profile: ResolvedProcessing) -> JobManifest:
    """Chuẩn bị input video qua REC CLI và ghi các stage vào JobManifest."""
    project = attempt.registry.get_project(attempt.job.project_id)
    if project.input_manifest_ref is None:
        raise ValueError("Project không có InputManifest đã publish")
    manifest = _pull_input(attempt.registry.runtime_resolver, project.input_manifest_ref)
    _validate_project_input_recipe(attempt, project, manifest)
    quality_profile = json.loads(attempt.settings.product_upload_quality_profile.read_bytes())
    request = {
        "schema_version": "1.0",
        "execution_scope": "rgb_video_prepare",
        "job_id": attempt.job.job_id,
        "input_manifest_ref": project.input_manifest_ref.model_dump(mode="json"),
        "quality_profile": quality_profile,
        "privacy_mode": "self_attested",
        "sample_fps": profile.sample_fps,
        "max_frames": profile.max_frames,
        "anonymize": must_anonymize(profile.anonymize, attempt.settings, project.privacy_mode),
    }
    request_path = attempt.workspace / "prepare.request.json"
    with request_path.open("x", encoding="utf-8") as stream:
        json.dump(request, stream)
    command = [
        sys.executable,
        "-m",
        "src.services.reconstruction.prepare_cli",
        "--request",
        str(request_path),
        "--store-root",
        str(attempt.registry.runtime_resolver.artifact_root),
    ]
    exit_code, payload = _run_tool(attempt, "prepare", command, attempt.settings.product_prepare_timeout_seconds)
    attempt.registry.runtime_resolver.sync_up(attempt.job.job_id)
    if exit_code not in {0, 1} or "result" not in payload:
        raise RuntimeError("Prepare worker không trả result hợp lệ")
    receipt = PreparedInputReceipt.model_validate(payload["result"])
    if (receipt.error is None) != (exit_code == 0):
        raise ValueError("Prepare result khác exit status")
    job = attempt.registry.record_prepared_input(attempt.job, receipt)
    attempt.job = job
    if job.status == JobStatus.FAILED:
        _record_benchmark(attempt)
    return job


def _execute_lidar_ingest(attempt: _Attempt, rgb_frame_set_ref: ProductArtifactRef) -> JobManifest:
    """`ST-LIDAR-INGEST` cho job có gói LiDAR (ADR 0009): giải gói, ghép scan nếu cần, publish đám mây + bản ghi gói.

    Job chỉ có video trả nguyên job. Bằng chứng nhận diện lấy từ InputManifest (đã lưu lúc tạo scene), không nhận
    diện lại từ tên file. Sau ingest, QA calibration chiếu các scan gốc theo pose lên RGB trước khi chạy COLMAP.
    """
    from src.services.reconstruction import LidarEvidence, LidarPackageError, LidarPackageIngest

    project = attempt.registry.get_project(attempt.job.project_id)
    resolver = attempt.registry.runtime_resolver
    manifest = InputManifest.model_validate_json(resolver.require(project.input_manifest_ref).read_bytes())  # type: ignore[arg-type]
    declared = (manifest.preparation_provenance or {}).get("lidar")
    if not manifest.input_configuration.registered_lidar_present or not isinstance(declared, dict):
        return attempt.job
    package = next(item for item in manifest.files if item.media_type == "application/zip")
    # Ghi bước đang chạy ngay từ đầu để timeline hiện "Nhận dữ liệu LiDAR" thay vì bước kế tiếp (ghép scan mất vài phút).
    attempt.job = attempt.registry.record_stage_progress(attempt.job, StageId.LIDAR_INGEST)
    started = datetime.now(UTC)
    try:
        with _sampled(attempt, "lidar_ingest"):
            result = LidarPackageIngest(FilesystemArtifactStore(resolver)).ingest(
                resolver.require_uri(package.artifact_uri, package.checksum),
                LidarEvidence.model_validate(declared["evidence"]),
                attempt.job.job_id,
                declared["trajectory_origin"],
                attempt.workspace / "lidar",
            )
    except LidarPackageError as error:
        details = {"action": "Sửa gói LiDAR theo hướng dẫn rồi tạo scene mới"}
        failure = ExecutionError(
            error_code="LIDAR_PACKAGE_INVALID",
            stage_id=StageId.LIDAR_INGEST,
            human_message=str(error),
            retryable=classify_retryability("LIDAR_PACKAGE_INVALID", details),
            details=details,
        )
        stage = StageArtifact(
            stage_id=StageId.LIDAR_INGEST,
            status=StageStatus.FAILED,
            started_at=started,
            completed_at=datetime.now(UTC),
            error=failure,
        )
        return attempt.registry.record_lidar_ingest(attempt.job, stage)
    resolver.sync_up(attempt.job.job_id)
    reference = result.reference
    stage = StageArtifact(
        stage_id=StageId.LIDAR_INGEST,
        status=StageStatus.SUCCEEDED,
        artifact_type=reference.artifact_type,
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        data_class=reference.data_class,
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    attempt.job = attempt.registry.record_lidar_ingest(attempt.job, stage)
    attempt.job = attempt.registry.record_stage_progress(attempt.job, StageId.LIDAR_CALIBRATION_QA)
    qa_started = datetime.now(UTC)
    project = attempt.registry.get_project(attempt.job.project_id)
    declarations = None
    if project.input_assembly_ref is not None:
        try:
            assembly = InputAssemblySnapshot.model_validate_json(
                resolver.require(project.input_assembly_ref).read_bytes()
            )
            declarations = assembly.declarations
        except (ArtifactStoreError, ValueError) as error:
            logger.warning(
                "LiDAR QA declarations unavailable for job %s; continuing as inconclusive cause=%s",
                attempt.job.job_id,
                type(error).__name__,
            )
    from src.models.contracts.lidar_calibration_qa import LidarCalibrationQAResult
    from src.services.reconstruction.lidar.calibration_qa_worker import run_lidar_calibration_qa

    with _sampled(attempt, "lidar_calibration_qa"):
        qa = run_lidar_calibration_qa(
            resolver=resolver,
            writer=FilesystemArtifactStore(resolver),
            job_id=attempt.job.job_id,
            package_ref=result.reference,
            package=result.record,
            input_manifest=manifest,
            rgb_frame_set_ref=rgb_frame_set_ref,
            declarations=declarations,
        )
    resolver.sync_up(attempt.job.job_id)
    qa_failed = qa.report.result == LidarCalibrationQAResult.FAIL
    qa_error = (
        ExecutionError(
            error_code="LIDAR_CALIBRATION_QA_FAILED",
            stage_id=StageId.LIDAR_CALIBRATION_QA,
            human_message="LiDAR calibration QA found structural input inconsistencies; correct the source and create a new job.",
            retryable=False,
            details={"action": "Correct calibration, units, timestamps, or source bindings and create a new job"},
        )
        if qa_failed
        else None
    )
    qa_stage = StageArtifact(
        stage_id=StageId.LIDAR_CALIBRATION_QA,
        status=StageStatus.FAILED if qa_failed else StageStatus.SUCCEEDED,
        artifact_type=qa.report_ref.artifact_type,
        artifact_uri=qa.report_ref.artifact_uri,
        artifact_checksum=qa.report_ref.artifact_checksum,
        data_class=qa.report_ref.data_class,
        started_at=qa_started,
        completed_at=datetime.now(UTC),
        error=qa_error,
    )
    return attempt.registry.record_lidar_calibration_qa(attempt.job, qa_stage)


def _staged_upload_ref(staged: StagedInputFile) -> ArtifactRef:
    """Represent the exact uploaded container without relabeling it as a job-derived artifact."""
    return ArtifactRef(
        artifact_type="InputAssemblyUpload",
        schema_version="1.0",
        artifact_uri=staged.source_file.artifact_uri,
        artifact_checksum=staged.source_file.checksum,
        data_class=staged.source_file.data_class,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=None,
        source_provenance={"upload_id": staged.upload_id, "file_id": staged.file_id},
    )


def _read_staged_member_bytes(attempt: _Attempt, staged: StagedInputFile, max_bytes: int) -> bytes:
    """Read one direct input or ZIP member while verifying both stored identities."""
    source = attempt.registry.runtime_resolver.require_uri(staged.source_file.artifact_uri, staged.source_file.checksum)
    member = staged.archive_member
    if member is None:
        if source.stat().st_size > max_bytes:
            raise ValueError("Input assembly member exceeds the configured byte limit")
        payload = source.read_bytes()
        if sha256_bytes(payload) != staged.source_file.checksum:
            raise ArtifactStoreError("Input assembly source changed after its checksum was verified")
        return payload
    if member.container_checksum != staged.source_file.checksum or member.uncompressed_size_bytes > max_bytes:
        raise ValueError("Input assembly ZIP member does not match its bounded source identity")
    try:
        with zipfile.ZipFile(source) as archive:
            matches = [info for info in archive.infolist() if info.filename == member.member_path]
            if len(matches) != 1:
                raise ValueError("Input assembly ZIP member is missing or duplicated")
            info = matches[0]
            mode = info.external_attr >> 16
            if info.is_dir() or info.flag_bits & 0x1 or stat.S_ISLNK(mode):
                raise ValueError("Input assembly ZIP member must be an unencrypted regular file")
            if info.file_size != member.uncompressed_size_bytes:
                raise ValueError("Input assembly ZIP member size differs from its staged identity")
            digest = hashlib.sha256()
            payload = bytearray()
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    payload.extend(chunk)
                    if len(payload) > max_bytes or len(payload) > member.uncompressed_size_bytes:
                        raise ValueError("Input assembly ZIP member exceeds its declared size")
                    digest.update(chunk)
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError) as error:
        raise ValueError("Input assembly ZIP member is unreadable") from error
    if len(payload) != member.uncompressed_size_bytes or "sha256:" + digest.hexdigest() != member.member_checksum:
        raise ArtifactStoreError("Input assembly ZIP member changed after its checksum was verified")
    return bytes(payload)


def _publish_staged_member(
    attempt: _Attempt,
    assembly: InputAssemblySnapshot,
    staged: StagedInputFile,
    role: InputRole,
) -> ProductArtifactRef:
    """Copy small exact R5/R6 evidence into this attempt's durable product-input namespace."""
    payload = _read_staged_member_bytes(attempt, staged, 16 * 1024 * 1024)
    source_provenance: dict[str, object] = {
        "assembly_checksum": assembly.assembly_checksum,
        "file_id": staged.file_id,
        "upload_id": staged.upload_id,
        "role": role.value,
        "source_file_checksum": staged.source_file.checksum,
    }
    if staged.archive_member is not None:
        source_provenance["source_member_checksum"] = staged.archive_member.member_checksum
        source_provenance["source_member_path"] = staged.archive_member.member_path
    reference = ProductArtifactRef(
        artifact_type="InputAssemblyMember",
        schema_version="1.0",
        artifact_uri=(
            f"artifact://jobs/{attempt.job.job_id}/attempts/{attempt.workspace.name}/lidar-odometry/input/"
            f"{hashlib.sha256(staged.file_id.encode('utf-8')).hexdigest()}.bin"
        ),
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.PRODUCT_INPUT,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=attempt.job.job_id,
        source_provenance=source_provenance,
    )
    writer = FilesystemArtifactStore(attempt.registry.runtime_resolver)
    if writer.publish(reference, payload) != reference:
        raise ArtifactStoreError("Input assembly member publication changed its identity")
    if attempt.registry.runtime_resolver.require(reference).read_bytes() != payload:
        raise ArtifactStoreError("Published input assembly member failed read-back verification")
    return reference


def _publish_accepted_input_evidence(
    attempt: _Attempt,
    source: ProductArtifactRef | None,
    filename: str,
) -> ProductArtifactRef:
    """Copy one immutable project input record into the consuming job's namespace."""
    if source is None:
        raise ValueError("Estimated odometry requires every accepted input evidence reference")
    payload = attempt.registry.runtime_resolver.require(source).read_bytes()
    reference = ProductArtifactRef(
        artifact_type=source.artifact_type,
        schema_version=source.schema_version,
        artifact_uri=(
            f"artifact://jobs/{attempt.job.job_id}/attempts/{attempt.workspace.name}/lidar-odometry/input/{filename}"
        ),
        artifact_checksum=sha256_bytes(payload),
        data_class=source.data_class,
        producer_stage=source.producer_stage,
        job_id=attempt.job.job_id,
        source_provenance={
            "accepted_project_ref_uri": source.artifact_uri,
            "accepted_project_ref_checksum": source.artifact_checksum,
        },
    )
    writer = FilesystemArtifactStore(attempt.registry.runtime_resolver)
    if writer.publish(reference, payload) != reference:
        raise ArtifactStoreError("Accepted input evidence copy changed its identity")
    if attempt.registry.runtime_resolver.require(reference).read_bytes() != payload:
        raise ArtifactStoreError("Accepted input evidence copy failed read-back verification")
    return reference


def _preview_start_stage(registry: ProjectRegistry, job: JobManifest) -> StageId:
    """Claim the sensor-odometry stage before camera preview only for accepted R5/R6 recipes."""
    project = registry.get_project(job.project_id)
    recipe_ref = project.input_recipe_ref
    if recipe_ref is None:
        return StageId.CAMERA_POSE
    recipe = InputRecipe.model_validate_json(registry.runtime_resolver.require(recipe_ref).read_bytes())
    verify_input_recipe_checksum(recipe)
    if recipe.recipe_group not in {RecipeGroup.ESTIMATED_TRAJECTORY, RecipeGroup.SENSOR_GUIDED}:
        return StageId.CAMERA_POSE
    completed = next(
        (
            item
            for item in reversed(job.stage_artifacts)
            if item.stage_id == StageId.LIDAR_ODOMETRY and item.status == StageStatus.SUCCEEDED
        ),
        None,
    )
    return StageId.CAMERA_POSE if completed is not None else StageId.LIDAR_ODOMETRY


def _execute_lidar_odometry(attempt: _Attempt) -> JobManifest:
    """Run accepted R5/R6 scan odometry and persist source evidence before RGB preview."""
    from src.models.contracts.reconstruction import (
        EstimatedTrajectoryConsumerEvidence,
        EstimatedTrajectoryMapEvidence,
        EstimatedTrajectoryMapStats,
        EstimatedTrajectoryProductEvidence,
    )
    from src.services.reconstruction.lidar.odometry import (
        LidarOdometryRuntimeSettings,
        LidarOdometryScanInput,
        LidarOdometryWorker,
        LidarOdometryWorkerRequest,
        default_lidar_odometry_profile,
    )

    project = attempt.registry.get_project(attempt.job.project_id)
    if project.input_manifest_ref is None:
        return attempt.job
    manifest = _pull_input(attempt.registry.runtime_resolver, project.input_manifest_ref)
    accepted = _validate_project_input_recipe(attempt, project, manifest)
    if accepted is None or accepted.recipe.recipe_group not in {
        RecipeGroup.ESTIMATED_TRAJECTORY,
        RecipeGroup.SENSOR_GUIDED,
    }:
        return attempt.job
    recipe = accepted.recipe
    group = recipe.recipe_group
    bindings = {binding.role: binding.file_ids for binding in recipe.bindings}
    by_id = {item.file_id: item for item in accepted.assembly.files}
    previous = next(
        (
            item
            for item in reversed(attempt.job.stage_artifacts)
            if item.stage_id == StageId.LIDAR_ODOMETRY and item.status == StageStatus.SUCCEEDED
        ),
        None,
    )
    if previous is not None:
        if previous.artifact_uri is None or previous.artifact_checksum is None or previous.artifact_type is None:
            raise ValueError("Previously completed odometry stage is missing its immutable evidence reference")
        previous_ref = ProductArtifactRef(
            artifact_type=previous.artifact_type,
            schema_version="1.0",
            artifact_uri=previous.artifact_uri,
            artifact_checksum=previous.artifact_checksum,
            data_class=previous.data_class,
            producer_stage=previous.stage_id,
            job_id=attempt.job.job_id,
        )
        previous_payload = attempt.registry.runtime_resolver.require(previous_ref).read_bytes()
        previous_document = json.loads(previous_payload)
        if previous_document.get("artifact_type") == "EstimatedTrajectoryProductEvidence":
            previous_evidence = EstimatedTrajectoryProductEvidence.model_validate_json(
                previous_payload
            ).consumer_evidence
        else:
            previous_evidence = EstimatedTrajectoryConsumerEvidence.model_validate_json(previous_payload)
        accepted_refs = (
            project.input_assembly_ref,
            project.input_resolution_ref,
            project.input_runtime_registry_ref,
            project.input_recipe_ref,
        )
        if any(reference is None for reference in accepted_refs):
            raise ValueError("Previously completed odometry stage lost its accepted input evidence chain")
        if (
            any(
                evidence_ref.artifact_checksum != source_ref.artifact_checksum
                or evidence_ref.artifact_type != source_ref.artifact_type
                for evidence_ref, source_ref in zip(
                    (
                        previous_evidence.assembly_ref,
                        previous_evidence.resolution_ref,
                        previous_evidence.runtime_registry_ref,
                        previous_evidence.recipe_ref,
                    ),
                    accepted_refs,
                    strict=True,
                )
                if source_ref is not None
            )
            or previous_evidence.ingest_binding.recipe_checksum != recipe.recipe_checksum
        ):
            raise ValueError("Previously completed odometry evidence belongs to a different accepted input recipe")
        return attempt.registry.record_stage_progress(attempt.job, StageId.CAMERA_POSE)

    if attempt.job.current_stage != StageId.LIDAR_ODOMETRY:
        attempt.job = attempt.registry.record_stage_progress(attempt.job, StageId.LIDAR_ODOMETRY)
    odometry_runtime = next(
        (item for item in accepted.runtime_registry.capabilities if item.capability_key == RuntimeCapabilityKey.R5),
        None,
    )
    if odometry_runtime is None or odometry_runtime.status != RuntimeQualificationStatus.QUALIFIED:
        raise ValueError("R5 odometry worker is not qualified for this accepted recipe")
    sensor_runtime: RuntimeCapabilityRecord | None = None
    if group == RecipeGroup.SENSOR_GUIDED:
        sensor_runtime = next(
            (item for item in accepted.runtime_registry.capabilities if item.capability_key == RuntimeCapabilityKey.R6),
            None,
        )
        if sensor_runtime is None or sensor_runtime.status != RuntimeQualificationStatus.QUALIFIED:
            raise ValueError("R6 sensor-guided worker is not qualified for this accepted recipe")

    scan_time_file = by_id[bindings[InputRole.LIDAR_SCAN_TIMES][0]]
    timestamp_ref = _publish_staged_member(attempt, accepted.assembly, scan_time_file, InputRole.LIDAR_SCAN_TIMES)
    timestamp_unit = (
        accepted.assembly.declarations.lidar_timestamp_unit or accepted.assembly.declarations.timestamp_unit
    )
    sensor_frame = accepted.assembly.declarations.lidar_frame_id
    if timestamp_unit is None or sensor_frame is None:
        raise ValueError("Accepted odometry recipe lost the required scan clock or sensor-frame declaration")
    scan_inputs = [
        LidarOdometryScanInput(
            file_id=file_id,
            reference=_staged_upload_ref(by_id[file_id]),
            archive_member=by_id[file_id].archive_member,
        )
        for file_id in bindings[InputRole.LIDAR_SCAN]
    ]
    calibration_ref = None
    rgb_frame_times_ref = None
    if group == RecipeGroup.SENSOR_GUIDED:
        calibration_ref = _publish_staged_member(
            attempt,
            accepted.assembly,
            by_id[bindings[InputRole.CAMERA_LIDAR_CALIBRATION][0]],
            InputRole.CAMERA_LIDAR_CALIBRATION,
        )
        rgb_frame_times_ref = _publish_staged_member(
            attempt,
            accepted.assembly,
            by_id[bindings[InputRole.RGB_FRAME_TIMES][0]],
            InputRole.RGB_FRAME_TIMES,
        )

    profile = default_lidar_odometry_profile()
    started_at = datetime.now(UTC)
    request = LidarOdometryWorkerRequest(
        job_id=attempt.job.job_id,
        attempt_id=attempt.workspace.name,
        assembly_id=accepted.assembly.assembly_id,
        assembly_revision=accepted.assembly.revision,
        assembly_checksum=accepted.assembly.assembly_checksum,
        recipe_checksum=recipe.recipe_checksum,
        scans=scan_inputs,
        timestamp_file_ref=timestamp_ref,
        timestamp_unit=TimestampUnit(timestamp_unit.value),
        scan_coordinate_unit=DistanceUnit.METER,
        sensor_frame_id=sensor_frame.value,
        odometry_map_frame_id=f"{attempt.job.job_id}-lidar-map",
        profile=profile,
        runtime_qualification=odometry_runtime,
    )
    resolver = attempt.registry.runtime_resolver

    def lease_is_current() -> bool:
        current = attempt.registry.get_job(attempt.job.job_id)
        return (
            current.status == JobStatus.RUNNING
            and current.current_stage == StageId.LIDAR_ODOMETRY
            and current.job_manifest_checksum == attempt.job.job_manifest_checksum
        )

    writer = FilesystemArtifactStore(resolver)
    worker = LidarOdometryWorker(resolver, writer, LidarOdometryRuntimeSettings())
    with _sampled(attempt, "lidar_odometry"):
        result = worker.run(request, lease_is_current=lease_is_current)
    job_accepted_refs = (
        _publish_accepted_input_evidence(attempt, project.input_assembly_ref, "input_assembly.json"),
        _publish_accepted_input_evidence(attempt, project.input_resolution_ref, "input_resolution.json"),
        _publish_accepted_input_evidence(attempt, project.input_runtime_registry_ref, "input_runtime_registry.json"),
        _publish_accepted_input_evidence(attempt, project.input_recipe_ref, "input_recipe.json"),
    )
    evidence = EstimatedTrajectoryConsumerEvidence(
        job_id=attempt.job.job_id,
        recipe_group=group.value,
        assembly_ref=job_accepted_refs[0],
        resolution_ref=job_accepted_refs[1],
        runtime_registry_ref=job_accepted_refs[2],
        recipe_ref=job_accepted_refs[3],
        trajectory_ref=result.artifact_ref,
        ingest_binding=result.ingest_binding,
        lidar_scan_times_ref=timestamp_ref,
        camera_lidar_calibration_ref=calibration_ref,
        rgb_frame_times_ref=rgb_frame_times_ref,
        odometry_runtime_id=odometry_runtime.runtime_id,
        odometry_runtime_version=odometry_runtime.runtime_version,
        odometry_profile_checksum=result.trajectory.config_checksum,
        runtime_qualification_status=odometry_runtime.status.value,
        runtime_qualification_evidence_checksum=odometry_runtime.qualification_evidence_checksum,
        sensor_guided_runtime_id=sensor_runtime.runtime_id if sensor_runtime is not None else None,
        sensor_guided_runtime_version=sensor_runtime.runtime_version if sensor_runtime is not None else None,
        sensor_guided_runtime_evidence_checksum=(
            sensor_runtime.qualification_evidence_checksum if sensor_runtime is not None else None
        ),
    )
    map_evidence = EstimatedTrajectoryMapEvidence(
        job_id=attempt.job.job_id,
        trajectory_ref=result.artifact_ref,
        ingest_binding=result.ingest_binding,
        map_cloud_ref=result.map_cloud_ref,
        map_frame_id=result.ingest_binding.odometry_map_frame_id,
        map_status="ready" if result.map_cloud_ref is not None else "blocked",
        point_count=result.map_fusion_stats.point_count if result.map_fusion_stats is not None else None,
        fusion_profile_checksum=result.map_fusion_profile_checksum,
        fusion_stats=(
            EstimatedTrajectoryMapStats.model_validate(result.map_fusion_stats.model_dump(mode="python"))
            if result.map_fusion_stats is not None
            else None
        ),
        diagnostic_code=result.map_diagnostic_code,
    )
    product_evidence = EstimatedTrajectoryProductEvidence(
        job_id=attempt.job.job_id,
        consumer_evidence=evidence,
        map_evidence=map_evidence,
    )
    payload = product_evidence.model_dump_json(indent=2).encode("utf-8") + b"\n"
    evidence_ref = ProductArtifactRef(
        artifact_type=product_evidence.artifact_type,
        schema_version=product_evidence.schema_version,
        artifact_uri=(
            f"artifact://jobs/{attempt.job.job_id}/attempts/{attempt.workspace.name}/lidar-odometry/product-evidence.json"
        ),
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.LIDAR_ODOMETRY,
        job_id=attempt.job.job_id,
        source_provenance={
            "assembly_checksum": accepted.assembly.assembly_checksum,
            "recipe_checksum": recipe.recipe_checksum,
            "trajectory_ref_checksum": result.artifact_ref.artifact_checksum,
            "world_frame_status": evidence.world_frame_status,
            "floor_status": evidence.floor_status,
            "alignment_status": evidence.alignment_status,
            "map_status": map_evidence.map_status,
            "map_cloud_checksum": map_evidence.map_cloud_ref.artifact_checksum
            if map_evidence.map_cloud_ref is not None
            else None,
        },
    )
    if writer.publish(evidence_ref, payload) != evidence_ref:
        raise ArtifactStoreError("Odometry consumer evidence publication changed its identity")
    stored = EstimatedTrajectoryProductEvidence.model_validate_json(resolver.require(evidence_ref).read_bytes())
    if stored.model_dump(mode="json") != product_evidence.model_dump(mode="json"):
        raise ArtifactStoreError("Odometry product evidence failed read-back verification")
    resolver.sync_up(attempt.job.job_id)
    stage = StageArtifact(
        stage_id=StageId.LIDAR_ODOMETRY,
        status=StageStatus.SUCCEEDED,
        artifact_type=evidence_ref.artifact_type,
        artifact_uri=evidence_ref.artifact_uri,
        artifact_checksum=evidence_ref.artifact_checksum,
        data_class=evidence_ref.data_class,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    return attempt.registry.record_lidar_odometry(attempt.job, stage)


def run_prepared_job(job_id: str, frame_set_uri: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Chỉ dispatch frame ref đã publish/allow-list và profile đúng JobManifest."""
    initial = get_project_registry().get_job(job_id)
    frames = prepared_frame_reference(initial)
    if frames is None or frames.artifact_uri != frame_set_uri:
        raise ValueError("Frame set không phải output thành công duy nhất trong JobManifest")
    attempt, profile = _start_attempt(job_id, expected_checksum, StageId.CAMERA_POSE)
    with job_log_context(attempt.job.job_id, _attempt_log_id(attempt.registry, attempt.job.job_id)):
        try:
            with attempt_lease(attempt.workspace):
                project = attempt.registry.get_project(attempt.job.project_id)
                if project.input_recipe_ref is not None:
                    if project.input_manifest_ref is None:
                        raise ValueError("Grouped input project has no InputManifest")
                    manifest = _pull_input(attempt.registry.runtime_resolver, project.input_manifest_ref)
                    _validate_project_input_recipe(attempt, project, manifest)
                    attempt.job = _execute_lidar_odometry(attempt)
                    if attempt.job.status != JobStatus.RUNNING:
                        return attempt.job
                job = _execute_preview(attempt, frames, profile)
            return _requeue_if_exhausted(attempt) or job
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def run_video_job(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Upload video → frame set → preview trong một attempt; dừng ngay ở stage lỗi."""
    attempt, profile = _start_attempt(job_id, expected_checksum, StageId.INPUT_VALIDATE)
    with job_log_context(attempt.job.job_id, _attempt_log_id(attempt.registry, attempt.job.job_id)):
        try:
            with attempt_lease(attempt.workspace):
                attempt.job = _execute_prepare(attempt, profile)
                if attempt.job.status != JobStatus.RUNNING:
                    _record_benchmark(attempt)  # job dừng ở bước chuẩn bị (vd video lỗi) vẫn có số đo
                    return attempt.job
                frames = prepared_frame_reference(attempt.job)
                if frames is None:
                    raise ValueError("Prepare thành công nhưng thiếu frame set")
                if awaiting_anonymization_review(attempt.job):
                    # Không frame nào bị che thì không có gì để người dùng xem: ghi nhận tự động và chạy tiếp.
                    accepted = accept_when_nothing_redacted(attempt.registry, attempt.job.job_id)
                    if accepted is None:
                        # Có frame đã che: dừng ở đây, giữ RUNNING ở bước tách frame. Chỉ khi người dùng xem và
                        # chấp nhận bản đã che thì `run_reviewed_preview_job` mới dựng 3D (owner chốt 2026-10-09).
                        _record_benchmark(attempt)
                        return attempt.job
                    attempt.job = accepted
                attempt.job = _execute_lidar_ingest(attempt, frames)
                if attempt.job.status != JobStatus.RUNNING:
                    _record_benchmark(attempt)  # LiDAR ingest hoặc structural QA lỗi: dừng trước COLMAP/Brush
                    return attempt.job
                attempt.job = _execute_lidar_odometry(attempt)
                if attempt.job.status != JobStatus.RUNNING:
                    _record_benchmark(attempt)
                    return attempt.job
                job = _execute_preview(attempt, frames, profile)
            return _requeue_if_exhausted(attempt) or job
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def run_prepare_step(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Bước `prepare` (CPU) của hàng đợi theo bước (T-073): kiểm video → che (nếu bật) → tách frame, rồi dừng.

    Job giữ RUNNING ở bước tách frame, không worker nào giữ: bước dựng camera do worker có GPU nhận sau (hoặc sau khi
    người dùng duyệt bản đã che). Không frame nào bị che thì ghi chấp nhận tự động ngay, như đường một mạch.
    """
    attempt, profile = _start_attempt(job_id, expected_checksum, StageId.INPUT_VALIDATE)
    with job_log_context(attempt.job.job_id, _attempt_log_id(attempt.registry, attempt.job.job_id)):
        try:
            with attempt_lease(attempt.workspace):
                attempt.job = _execute_prepare(attempt, profile)
                if attempt.job.status != JobStatus.RUNNING:
                    return attempt.job  # `_execute_prepare` đã ghi benchmark cho job dừng ở bước chuẩn bị
                if prepared_frame_reference(attempt.job) is None:
                    raise ValueError("Prepare thành công nhưng thiếu frame set")
                if awaiting_anonymization_review(attempt.job):
                    accepted = accept_when_nothing_redacted(attempt.registry, attempt.job.job_id, claim_stage=None)
                    if accepted is None:
                        _record_benchmark(attempt)  # dừng chờ người dùng duyệt bản đã che
                    else:
                        attempt.job = accepted
                # `prepare` ghi thẳng vào kho artifact; workspace chỉ có log và hạn của tool, giữ lại như mọi attempt.
            return _requeue_if_exhausted(attempt) or attempt.job
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def run_reviewed_preview_job(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Bước `pose_visual` của job đã chuẩn bị xong (T-073): LiDAR ingest/odometry (nếu có) → preview, trên cùng job.

    Job dừng ở bước tách frame sau bước `prepare` (và sau khi người dùng chấp nhận bản đã che, nếu có frame bị che).
    Claim bằng CAS chuyển stage FRAME_EXTRACT → CAMERA_POSE nên hai worker không cùng chạy.
    """
    settings = get_settings()
    registry = get_project_registry()
    job = registry.get_job(job_id)
    if expected_checksum is not None and job.job_manifest_checksum != expected_checksum:
        raise RuntimeStateConflictError("Queue candidate đã thay đổi trước dispatch")
    if re.fullmatch(_JOB_ID_PATTERN, job_id) is None:
        raise ValueError("Job ID không thể dùng làm worker namespace")
    if not awaiting_pose_step(job):
        raise RuntimeStateConflictError("Job không chờ bước dựng camera + 3DGS")
    profile_path = settings.product_processing_config
    execution = registry.execution_profile
    if profile_path is None or execution is None:
        raise ValueError("Worker cần execution profile đã cấu hình")
    if not execution.accepts_runtime(job.runtime_manifest_checksum) or job.seed != execution.seed:
        raise RuntimeStateConflictError("Job cần worker có execution profile tương ứng")
    profile = resolve_job_processing(
        job, execution, profile_path, registry.runtime_resolver, settings.product_target_frame_count
    )
    registry.runtime_resolver.sync_down(job_id)
    frames = prepared_frame_reference(job)
    if frames is None:
        raise ValueError("Job đã chấp nhận bản đã che nhưng thiếu frame set")
    job = registry.record_stage_progress(job, _preview_start_stage(registry, job))
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / f"attempt-{uuid4().hex}"
    attempt = _Attempt(registry, settings, job, workspace)
    log_id = _prepare_claimed_attempt(attempt)
    with job_log_context(job_id, log_id):
        try:
            with attempt_lease(workspace):
                attempt.job = _execute_lidar_ingest(attempt, frames)
                if attempt.job.status != JobStatus.RUNNING:
                    _record_benchmark(attempt)
                    return attempt.job
                attempt.job = _execute_lidar_odometry(attempt)
                if attempt.job.status != JobStatus.RUNNING:
                    _record_benchmark(attempt)
                    return attempt.job
                job = _execute_preview(attempt, frames, profile)
            return _requeue_if_exhausted(attempt) or job
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def _authorized_decision(attempt_registry: ProjectRegistry, job: JobManifest) -> tuple[ProductArtifactRef, str]:
    """PRODUCT xác minh quyết định người dùng trước khi giao REC chạy tiếp (authority của PRODUCT)."""
    from src.services.orchestration.jobs.metric import MetricDecision

    stage = metric_confirmation_stage(job)
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None:
        raise ValueError("Job chưa có xác nhận tỉ lệ mét")
    resolver = attempt_registry.runtime_resolver
    resolver.require_uri(stage.artifact_uri, stage.artifact_checksum)
    summary = confirmation_summary(stage.artifact_uri, stage.artifact_checksum, job.job_id, resolver.require)
    decision = MetricDecision.model_validate_json(resolver.require(summary.decision_ref).read_bytes())
    if decision.job_id != job.job_id or decision.preview_checksum != summary.preview_checksum:
        raise ValueError("Quyết định xác nhận không khớp job/preview")
    if get_settings().auth_required and decision.decided_by is None:
        raise ValueError("Quyết định xác nhận thiếu người xác nhận")
    return summary.reference, summary.decision_ref.artifact_checksum


def _extract_scene_stage(
    attempt: _Attempt, workspace: Path, bundle_ref: ProductArtifactRef | None
) -> list[StageArtifact]:
    """Tách vật thể (ADR 0006) sau bundle; lỗi không làm hỏng job (tái dựng đã xong).

    Bundle chưa nằm trong JobManifest ở thời điểm này (ghi cùng `record_finalize`), nên đọc
    thẳng từ ref trong kết quả REC đã qua consumer `load_finalize_result`.
    """
    from src.models.contracts.reconstruction import ReconstructionBundle
    from src.services.orchestration.scene.extraction import extract_scene

    if bundle_ref is None:
        return []
    try:
        attempt.job = attempt.registry.record_stage_progress(attempt.job, StageId.OBJECT_EXTRACT)
        bundle = ReconstructionBundle.model_validate_json(
            attempt.registry.runtime_resolver.require(bundle_ref).read_bytes()
        )
        with _sampled(attempt, "scene_extract"):
            stage = extract_scene(attempt.registry, attempt.job, bundle, attempt.settings, workspace / "scene")
        attempt.registry.runtime_resolver.sync_up(attempt.job.job_id)
        return [stage]
    except RuntimeStateConflictError:
        raise
    except Exception:  # noqa: BLE001 - process boundary: ghi log, job vẫn hoàn tất phần tái dựng
        logger.exception("Tách vật thể thất bại job=%s", attempt.job.job_id)
        return []


def _build_view_lods(attempt: _Attempt) -> None:
    """Bước T-070 (sau khi job xong): bộ LOD cho các SOG lớn của job; lỗi chỉ ghi mốc, không làm hỏng job."""
    cli = lod.lod_cli()
    persistence = attempt.registry.persistence
    if cli is None or persistence is None:
        return  # máy không có GPU / runtime: bộ dựng chạy ngầm trên worker GPU sẽ bù
    job_id = attempt.job.job_id
    try:
        run_id = str(persistence.list_attempts(job_id)[-1].attempt)
    except Exception as error:  # noqa: BLE001 - mốc bước là đo đạc, không được làm hỏng job đã xong
        logger.warning("Không đọc được lượt chạy cho bước LOD cause=%s", type(error).__name__)
        return
    step = StageId.VIEW_LOD.value

    def mark(write: MarkWrite) -> None:
        try:
            record_marks(persistence.database, job_id, "pipeline", run_id, [write])
        except Exception as error:  # noqa: BLE001 - mốc bước là đo đạc; job đã xong không được bị đánh lỗi
            logger.warning("Không ghi được mốc bước LOD cause=%s", type(error).__name__)

    mark(MarkWrite("start", step, datetime.now(UTC)))
    outcome = "cancelled"
    try:
        built = lod.build_job_view_lods(
            attempt.registry.runtime_resolver,
            job_id,
            attempt.registry.viewable_sogs(job_id),
            cli,
            Path(attempt.settings.product_worker_root) / "lod",
        )
        outcome = "succeeded"
        logger.info("Bước LOD job=%s đã tạo %d bộ", job_id, built)
    except Exception as error:  # noqa: BLE001 - scene vẫn xem bằng SOG gốc; bộ dựng ngầm thử lại sau
        outcome = "failed"
        logger.warning("Không tạo được bộ LOD job=%s cause=%s", job_id, type(error).__name__)
    finally:
        # Worker bị dừng giữa chừng (KeyboardInterrupt/SystemExit) vẫn đóng mốc, rồi lỗi đi tiếp như cũ.
        mark(MarkWrite("finish", step, datetime.now(UTC), outcome))


def _claim_finalize(
    job_id: str, expected_checksum: str | None
) -> tuple[_Attempt, ProductArtifactRef, str, object, str]:
    """Kiểm job chờ bước hình học rồi CAS claim stage METRIC/QUEUED → RGB_GEOMETRY; trả attempt + đầu vào REC."""
    settings = get_settings()
    registry = get_project_registry()
    job = registry.get_job(job_id)
    if expected_checksum is not None and job.job_manifest_checksum != expected_checksum:
        raise RuntimeStateConflictError("Queue candidate đã thay đổi trước dispatch")
    if re.fullmatch(_JOB_ID_PATTERN, job_id) is None:
        raise ValueError("Job ID không thể dùng làm worker namespace")
    if not awaiting_finalize(job):
        raise RuntimeStateConflictError("Job không chờ bước hoàn tất")
    confirmation, decision_checksum = _authorized_decision(registry, job)
    registry.runtime_resolver.sync_down(job_id)
    processing = load_job_config(job_id, job.config_checksum, registry.runtime_resolver)
    profile = load_geometry_profile(
        settings.product_geometry_config, overrides=dict(processing.geometry) if processing else None
    )
    if settings.product_geometry_gpu_index is not None:
        profile = profile.model_copy(update={"gpu_index": settings.product_geometry_gpu_index})
    if job.status == JobStatus.QUEUED:
        # Retry sau lỗi bước hoàn tất: attempt mới bắt đầu thẳng ở hình học (CAS claim).
        job = registry.transition_job(
            job_id,
            TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.RGB_GEOMETRY),
            expected_checksum=job.job_manifest_checksum,
        )
    else:
        job = registry.record_stage_progress(job, StageId.RGB_GEOMETRY)
    attempt_id = f"finalize-{uuid4().hex}"
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / attempt_id
    return _Attempt(registry, settings, job, workspace), confirmation, decision_checksum, profile, attempt_id


def _run_finalize_tool(
    attempt: _Attempt, confirmation: ProductArtifactRef, decision_checksum: str, profile: object, attempt_id: str
) -> tuple[ProductArtifactRef, object]:
    """REC-06 canonical → REC-05 geometry → REC-10 bundle qua `finalize_cli`; trả ref + kết quả đã qua consumer REC."""
    registry, settings, job_id, workspace = attempt.registry, attempt.settings, attempt.job.job_id, attempt.workspace
    request = {
        "schema_version": "1.0",
        "execution_scope": "product_finalize",
        "job_id": job_id,
        "attempt_id": attempt_id,
        "confirmation_ref": confirmation.model_dump(mode="json"),
        "authorized_decision_checksum": decision_checksum,
        "geometry": profile.model_dump(mode="json"),  # type: ignore[attr-defined]
    }
    # Job có gói LiDAR (ADR 0009): bước hoàn tất gắn đám mây LiDAR vào bundle bằng căn chỉnh đã xác nhận.
    lidar = _lidar_package_ref(registry.get_job(job_id))
    if lidar is not None:
        request["lidar_package_ref"] = lidar.model_dump(mode="json")
    request_path = workspace / "finalize.request.json"
    with request_path.open("x", encoding="utf-8") as stream:
        json.dump(request, stream)
    command = [
        sys.executable,
        "-m",
        "src.services.reconstruction.finalize_cli",
        "--request",
        str(request_path),
        "--store-root",
        str(registry.runtime_resolver.artifact_root),
        "--workspace",
        str(workspace / "rec"),
        "--progress-file",
        str(workspace / "finalize.progress.jsonl"),
    ]
    exit_code, payload = _run_tool(attempt, "finalize", command, settings.product_finalize_timeout_seconds)
    registry.runtime_resolver.sync_up(job_id)
    if exit_code not in {0, 1}:
        raise RuntimeError("Finalize worker không trả result hợp lệ")
    reference = ProductArtifactRef.model_validate(payload.get("result_ref"))
    result = load_finalize_result(reference, registry.runtime_resolver.require)
    if result.attempt_id != attempt_id or (result.error is None) != (exit_code == 0):
        raise ValueError("Finalize result khác attempt/exit status")
    return reference, result


def run_finalize_job(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Đường một mạch sau xác nhận tỉ lệ: REC-06 canonical → REC-05 geometry → REC-10 bundle → tách vật; job kết thúc.

    Hàng đợi theo bước (T-073) không gọi hàm này mà chạy `run_geometry_step` rồi `run_scene_step`; hàm giữ lại cho
    chạy tay và test. Claim bằng CAS chuyển stage METRIC → RGB_GEOMETRY nên hai worker không cùng chạy.
    """
    attempt, confirmation, decision_checksum, profile, attempt_id = _claim_finalize(job_id, expected_checksum)
    registry, workspace = attempt.registry, attempt.workspace
    log_id = _prepare_claimed_attempt(attempt)
    with job_log_context(job_id, log_id):
        try:
            with attempt_lease(workspace):
                reference, result = _run_finalize_tool(attempt, confirmation, decision_checksum, profile, attempt_id)
                extra: list[StageArtifact] = []
                if result.error is None:  # type: ignore[attr-defined]
                    extra = _extract_scene_stage(attempt, workspace, result.bundle_ref)  # type: ignore[attr-defined]
                completed = registry.record_finalize(attempt.job, result, reference, extra)  # type: ignore[arg-type]
                _record_benchmark(attempt)
                # Scene consumer đã chạy xong trước durable commit; lỗi extraction vẫn giữ scratch để debug.
                if result.error is None and extra:  # type: ignore[attr-defined]
                    _cleanup_attempt_workspace(attempt)
                if completed.status == JobStatus.SUCCEEDED:
                    # T-070: scene đã xem được; tạo bộ LOD trong cùng lượt (vẫn giữ lease nên máy GPU không bị tắt).
                    _build_view_lods(attempt)
                    _cleanup_finished_job(attempt)
            return _requeue_if_exhausted(attempt) or completed
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def run_geometry_step(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Bước `canonical_geometry` (T-073): REC-06 canonical → REC-05 geometry → REC-10 bundle, rồi dừng.

    Thành công: job RUNNING ở `ST-RGB-GEOMETRY` kèm bundle, chờ worker có GPU nhận bước tách vật. Lỗi: FAILED như cũ.
    Bước này chỉ dùng CPU, trừ khi máy đặt `product_geometry_gpu_index` (bộ dò lúc nhận ghi bước là GPU).
    """
    attempt, confirmation, decision_checksum, profile, attempt_id = _claim_finalize(job_id, expected_checksum)
    registry = attempt.registry
    log_id = _prepare_claimed_attempt(attempt)
    with job_log_context(job_id, log_id):
        try:
            with attempt_lease(attempt.workspace):
                reference, result = _run_finalize_tool(attempt, confirmation, decision_checksum, profile, attempt_id)
                if result.error is None:  # type: ignore[attr-defined]
                    completed = registry.record_geometry(attempt.job, result, reference)  # type: ignore[arg-type]
                    attempt.job = completed
                    _cleanup_attempt_workspace(attempt)
                else:
                    completed = registry.record_finalize(attempt.job, result, reference, [])  # type: ignore[arg-type]
                    attempt.job = completed
                    _record_benchmark(attempt)
            return _requeue_if_exhausted(attempt) or completed
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def _bundle_ref(job: JobManifest) -> ProductArtifactRef:
    """Ref của bundle bước hình học đã ghi vào job (đọc lại qua checksum, không tin đường dẫn khác)."""
    stage = next(
        (
            item
            for item in reversed(job.stage_artifacts)
            if item.artifact_type == "ReconstructionBundle"
            and item.status == StageStatus.SUCCEEDED
            and item.artifact_uri
            and item.artifact_checksum
        ),
        None,
    )
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None:
        raise ValueError("Job chưa có bundle để tách vật")
    return ProductArtifactRef(
        artifact_type="ReconstructionBundle",
        schema_version="1.0",
        artifact_uri=stage.artifact_uri,
        artifact_checksum=stage.artifact_checksum,
        data_class=stage.data_class,
        producer_stage=stage.stage_id,
        job_id=job.job_id,
    )


def run_scene_step(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Bước `scene_extract` (GPU, T-073): tách vật từ bundle đã ghi rồi kết thúc job; lỗi tách vật không làm hỏng job.

    Claim bằng CAS: RUNNING `ST-RGB-GEOMETRY` → `ST-OBJECT-EXTRACT` (hoặc QUEUED → RUNNING khi retry).
    """
    settings = get_settings()
    registry = get_project_registry()
    job = registry.get_job(job_id)
    if expected_checksum is not None and job.job_manifest_checksum != expected_checksum:
        raise RuntimeStateConflictError("Queue candidate đã thay đổi trước dispatch")
    if re.fullmatch(_JOB_ID_PATTERN, job_id) is None:
        raise ValueError("Job ID không thể dùng làm worker namespace")
    if not awaiting_scene_extract(job):
        raise RuntimeStateConflictError("Job không chờ bước tách vật")
    registry.runtime_resolver.sync_down(job_id)
    bundle_ref = _bundle_ref(job)
    if job.status == JobStatus.QUEUED:
        job = registry.transition_job(
            job_id,
            TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.OBJECT_EXTRACT),
            expected_checksum=job.job_manifest_checksum,
        )
    else:
        job = registry.record_stage_progress(job, StageId.OBJECT_EXTRACT)
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / f"scene-{uuid4().hex}"
    attempt = _Attempt(registry, settings, job, workspace)
    log_id = _prepare_claimed_attempt(attempt)
    with job_log_context(job_id, log_id):
        try:
            with attempt_lease(workspace):
                extra = _extract_scene_stage(attempt, workspace, bundle_ref)
                completed = registry.record_scene_extract(attempt.job, extra)
                attempt.job = completed
                _record_benchmark(attempt)
                if extra:
                    _cleanup_attempt_workspace(attempt)  # lỗi tách vật giữ scratch để debug
                if completed.status == JobStatus.SUCCEEDED:
                    if registry.persistence is not None:
                        from src.services.orchestration.jobs.steps import enqueue_view_lod

                        try:
                            enqueue_view_lod(registry.persistence.database, completed)
                        except Exception as error:  # noqa: BLE001 - bộ dựng LOD lúc rảnh vẫn bù cho job này
                            logger.warning("Không xếp được bước LOD cause=%s", type(error).__name__)
                    _cleanup_finished_job(attempt)
            return _requeue_if_exhausted(attempt) or completed
        except BaseException as error:
            _record_runner_failure(attempt, error)
            _requeue_if_exhausted(attempt)
            raise


def run_view_lod_step(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Bước `view_lod` (GPU, ưu tiên thấp, T-073): bộ LOD cho các SOG lớn của job đã xong; lỗi không làm hỏng job."""
    settings = get_settings()
    registry = get_project_registry()
    job = registry.get_job(job_id)
    if job.status != JobStatus.SUCCEEDED:
        raise RuntimeStateConflictError("Bộ LOD chỉ dựng cho job đã xong")
    registry.runtime_resolver.sync_down(job_id)
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / f"lod-{uuid4().hex}"
    _build_view_lods(_Attempt(registry, settings, job, workspace))
    return job


def main(argv: list[str] | None = None) -> int:
    """Operator CLI dùng cùng DB/artifact Settings với API, không sửa paths của artifact."""
    parser = argparse.ArgumentParser(description="Run a queued, privacy-approved prepared RGB preview job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--frame-set-uri", required=True)
    args = parser.parse_args(argv)
    configure_worker_logging()
    previous_handler = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Để finally của runner dừng cả process group khi service nhận SIGTERM."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        job = run_prepared_job(args.job_id, args.frame_set_uri)
        print(json.dumps({"job_id": job.job_id, "status": job.status, "current_stage": job.current_stage}))
        return 1 if job.status == JobStatus.FAILED else 0
    except Exception as error:
        logger.error("Preview runner failed cause=%s", type(error).__name__)
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
