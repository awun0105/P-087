"""Benchmark loại `pipeline_runtime`: thời gian/chi phí xử lý mỗi job và attempt.

Mục lục mọi loại benchmark: `eval/protocols/BENCHMARKS.md`; giao thức loại này:
`eval/protocols/pipeline_runtime.md`. Chỉ dùng dữ liệu product nhìn thấy được qua
contract và resource journal; không đọc manifest nội bộ của EX-REC.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import JobManifest, JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactStoreError, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.progress import JobProgress, job_progress
from src.services.orchestration.processing import JobProcessingConfig, MachineCapability, job_config_reference
from src.services.orchestration.processing.observed import load_usages
from src.services.orchestration.projects.registry import ProjectRegistry

BENCHMARK_SCHEMA_VERSION: Literal["1.1"] = "1.1"
#: Mã loại benchmark; dùng làm tên thư mục kết quả `eval/results/<kind>/`.
BENCHMARK_KIND: Literal["pipeline_runtime"] = "pipeline_runtime"
TERMINAL_STATUSES = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class StageTiming(BaseModel):
    """Thời gian wall đo được của một stage, không phải GPU busy time."""

    model_config = ConfigDict(extra="forbid")

    stage_id: str
    state: str
    seconds: float | None = Field(default=None, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scope: Literal["attempt", "reused", "unknown"] = "unknown"
    waiting_seconds: float | None = Field(default=None, ge=0)


class ToolTiming(BaseModel):
    """Thời lượng process đo bởi ResourceUsage; gồm xử lý và I/O của process."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float = Field(ge=0)
    outcome: Literal["completed", "failed", "cancelled", "timeout", "interrupted"]


class TimingCoverage(BaseModel):
    """Số stage worker của attempt có và chưa có đủ hai mốc thời gian."""

    model_config = ConfigDict(extra="forbid")

    worker_stage_count: int = Field(ge=0)
    measured_worker_stage_count: int = Field(ge=0)
    missing_worker_stage_ids: list[str]


class PipelineRuntimeBenchmark(BaseModel):
    """Một snapshot bất biến theo job + attempt + partial/terminal phase."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = BENCHMARK_SCHEMA_VERSION
    benchmark_kind: Literal["pipeline_runtime"] = BENCHMARK_KIND
    job_id: str
    project_id: str
    attempt: int
    label: str | None = None
    recorded_at: datetime
    status: str
    snapshot_phase: Literal["partial", "terminal"] | None = None
    stages: list[StageTiming]
    #: v1.1 ghi trọn vòng đời từ JobManifest.started_at tới completed_at; partial là null.
    total_seconds: float | None = Field(default=None, ge=0)
    attempt_started_at: datetime | None = None
    attempt_completed_at: datetime | None = None
    attempt_wall_seconds: float | None = Field(default=None, ge=0)
    queue_seconds: float | None = Field(default=None, ge=0)
    user_wait_seconds: float | None = Field(default=None, ge=0)
    critical_path_seconds: float | None = Field(default=None, ge=0)
    worker_process_seconds: float | None = Field(default=None, ge=0)
    worker_wall_seconds: float | None = Field(default=None, ge=0)
    worker_measurement_count: int = Field(default=0, ge=0)
    tool_timings: list[ToolTiming] = Field(default_factory=list)
    timing_coverage: TimingCoverage | None = None
    timing_issues: list[str] = Field(default_factory=list)
    first_preview_ready_at: datetime | None = None
    first_preview_time_source: Literal["verified", "unknown"] = "unknown"
    time_to_first_preview_seconds: float | None = Field(default=None, ge=0)
    actual_frame_count: int | None = Field(default=None, ge=2)
    input_manifest_checksum: str | None = None
    runtime_manifest_checksum: str | None = None
    processing: dict[str, int | float | str] | None = None
    config_checksum: str
    machine: MachineCapability | None = None
    gpu_power_limit_watts: float | None = Field(default=None, ge=0)
    input_size_bytes: int | None = None
    sog_size_bytes: int | None = None
    #: Chỉ đo được khi có provider allocation record; ResourceUsage chưa phải allocation ledger.
    gpu_allocated_seconds: float | None = Field(default=None, ge=0)
    gpu_hourly_usd: float | None = Field(default=None, ge=0)
    estimated_gpu_cost_usd: float | None = Field(default=None, ge=0)
    #: Chưa được phân tách bởi các nguồn timing hiện có; null có nghĩa là unknown.
    active_compute_seconds: float | None = Field(default=None, ge=0)
    io_seconds: float | None = Field(default=None, ge=0)
    publication_seconds: float | None = Field(default=None, ge=0)


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (end - start).total_seconds()
    return value if value >= 0 else None


def _interval_union_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float | None:
    """Wall occupied by recorded process intervals, counting overlap once."""
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return None
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += (current_end - current_start).total_seconds()
            current_start, current_end = start, end
    return total + (current_end - current_start).total_seconds()


def _critical_path(stages: list[StageTiming], *, terminal: bool) -> tuple[float | None, list[str]]:
    """Measure first-to-last worker stage span, excluding user-wait overlap, only with complete intervals."""
    if not terminal:
        return None, []
    worker_stages = [
        stage
        for stage in stages
        if stage.stage_id != StageId.METRIC_CANONICALIZE.value
        and stage.scope == "attempt"
        and stage.state not in {"pending", "waiting"}
    ]
    if not worker_stages:
        return None, []
    if any(stage.seconds is None for stage in worker_stages):
        return None, ["incomplete_worker_stage_intervals"]

    executed = [stage for stage in stages if stage.scope == "attempt" and stage.state not in {"pending", "waiting"}]
    previous_end: datetime | None = None
    for stage in executed:
        if stage.started_at is None or stage.completed_at is None:
            return None, ["incomplete_worker_stage_intervals"]
        if stage.stage_id == StageId.METRIC_CANONICALIZE.value and stage.waiting_seconds is None:
            return None, ["incomplete_user_wait_interval"]
        if previous_end is not None and stage.started_at < previous_end:
            return None, ["overlapping_serial_stage_intervals"]
        previous_end = stage.completed_at

    first_start = worker_stages[0].started_at
    last_end = worker_stages[-1].completed_at
    span = _seconds(first_start, last_end)
    if span is None:
        return None, ["incomplete_worker_stage_intervals"]
    waiting_overlap = sum(
        max(
            0.0,
            (min(stage.completed_at, last_end) - max(stage.started_at, first_start)).total_seconds(),
        )
        for stage in executed
        if stage.stage_id == StageId.METRIC_CANONICALIZE.value
        and stage.started_at is not None
        and stage.completed_at is not None
    )
    return max(0.0, span - waiting_overlap), []


def _stage_scope(
    stage_id: StageId,
    started_at: datetime | None,
    completed_at: datetime | None,
    attempt_started_at: datetime | None,
    current_attempt_stage_ids: set[StageId],
) -> Literal["attempt", "reused", "unknown"]:
    if stage_id in current_attempt_stage_ids:
        return "attempt"
    timestamps = [value for value in (started_at, completed_at) if value is not None]
    if attempt_started_at is not None and timestamps:
        if all(value < attempt_started_at for value in timestamps):
            return "reused"
        if any(value >= attempt_started_at for value in timestamps):
            return "attempt"
    return "unknown"


def _tool_timings(
    registry: ProjectRegistry,
    job_id: str,
    config_checksum: str,
    runtime_manifest_checksum: str,
    attempt_started_at: datetime | None,
    attempt_completed_at: datetime | None,
    observed_at: datetime,
) -> list[ToolTiming]:
    if registry.persistence is None or attempt_started_at is None:
        return []
    usages = load_usages(registry.persistence.database)
    cutoff = attempt_completed_at or observed_at
    return [
        ToolTiming(
            tool=usage.tool,
            started_at=usage.started_at,
            completed_at=usage.completed_at,
            duration_seconds=usage.duration_seconds,
            outcome=usage.outcome,
        )
        for usage in usages
        if usage.job_id == job_id
        and usage.config_checksum == config_checksum
        and usage.runtime_manifest_checksum == runtime_manifest_checksum
        and usage.started_at >= attempt_started_at
        and usage.completed_at <= cutoff
    ]


def _user_wait_seconds(
    progress: JobProgress,
    attempts: Sequence[JobAttemptRecord],
    observed_at: datetime,
    job: JobManifest,
) -> float | None:
    starts = [
        event.stage_started_at or event.recorded_at
        for event in attempts
        if event.current_stage == StageId.METRIC_CANONICALIZE and event.status == JobStatus.RUNNING
    ]
    starts.extend(
        stage.started_at
        for stage in progress.stages
        if stage.stage_id == StageId.METRIC_CANONICALIZE and stage.started_at is not None
    )
    if not starts:
        return None
    start = min(starts)
    confirmations = [
        stage.completed_at
        for stage in job.stage_artifacts
        if stage.stage_id == StageId.METRIC_CANONICALIZE
        and stage.status == "SUCCEEDED"
        and stage.completed_at is not None
    ]
    end = min(confirmations) if confirmations else None
    if end is None and progress.waiting_for == "metric_confirmation":
        end = observed_at
    elif end is None and job.completed_at is not None:
        end = job.completed_at
    return _seconds(start, end)


def build_benchmark(
    registry: ProjectRegistry,
    job_id: str,
    *,
    machine: MachineCapability | None = None,
    gpu_hourly_usd: float | None = None,
    label: str | None = None,
    observed_at: datetime | None = None,
) -> PipelineRuntimeBenchmark:
    """Dựng snapshot từ journal, contract artifact và resource telemetry (không ghi gì)."""
    observed_at = observed_at or datetime.now(UTC)
    job = registry.get_job(job_id)
    attempts = registry.list_job_attempts(job_id)
    preview_ready = True
    try:
        preview = registry.get_preview(job_id)
    except (ArtifactStoreError, ValueError):
        preview, preview_ready = None, False
    progress = job_progress(job, attempts, preview_ready)
    attempt_events = [event for event in attempts if event.attempt == progress.attempt]
    attempt_started_at = next(
        (event.recorded_at for event in attempt_events if event.status == JobStatus.RUNNING), None
    )
    terminal_event = next((event for event in reversed(attempt_events) if event.status in TERMINAL_STATUSES), None)
    is_terminal = job.status in TERMINAL_STATUSES and job.completed_at is not None
    attempt_completed_at = terminal_event.recorded_at if terminal_event else job.completed_at if is_terminal else None
    current_attempt_stage_ids = {event.current_stage for event in attempt_events if event.status == JobStatus.RUNNING}

    stages: list[StageTiming] = []
    for stage in progress.stages:
        started_at, completed_at = stage.started_at, stage.completed_at
        # Legacy records end visual timing after metric proposal; use Brush's published visual stage
        # artifact as the closest direct observation when no product-verified preview timestamp exists.
        has_verified_preview_time = any(event.preview_verified_at is not None for event in attempt_events)
        if stage.stage_id == StageId.VISUAL_RECON and not has_verified_preview_time and attempt_started_at is not None:
            visual_outputs = [
                item.completed_at
                for item in job.stage_artifacts
                if item.stage_id == StageId.VISUAL_RECON
                and item.artifact_type == "BrushVisualArtifact"
                and item.completed_at is not None
                and item.completed_at >= attempt_started_at
            ]
            if visual_outputs:
                completed_at = max(visual_outputs)
        scope = _stage_scope(stage.stage_id, started_at, completed_at, attempt_started_at, current_attempt_stage_ids)
        duration = (
            _seconds(started_at, completed_at)
            if scope == "attempt" and stage.stage_id != StageId.METRIC_CANONICALIZE
            else None
        )
        wait_end = completed_at
        if stage.stage_id == StageId.METRIC_CANONICALIZE and stage.state == "waiting":
            wait_end = observed_at
        wait_duration = (
            _seconds(started_at, wait_end)
            if scope == "attempt" and stage.stage_id == StageId.METRIC_CANONICALIZE
            else None
        )
        stages.append(
            StageTiming(
                stage_id=stage.stage_id.value,
                state=stage.state,
                seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
                scope=scope,
                waiting_seconds=wait_duration,
            )
        )

    active_worker_stages = [
        stage
        for stage in stages
        if stage.stage_id != StageId.METRIC_CANONICALIZE.value
        and stage.scope == "attempt"
        and stage.state not in {"pending", "waiting"}
    ]
    missing = [stage.stage_id for stage in active_worker_stages if stage.seconds is None]
    critical_path, critical_issues = _critical_path(stages, terminal=is_terminal)
    first_preview_ready_at = min(
        (event.preview_verified_at for event in attempts if event.preview_verified_at is not None), default=None
    )
    tool_timings = _tool_timings(
        registry,
        job_id,
        job.config_checksum,
        job.runtime_manifest_checksum,
        attempt_started_at,
        attempt_completed_at if is_terminal else None,
        observed_at,
    )
    tool_intervals = [(timing.started_at, timing.completed_at) for timing in tool_timings]
    worker_process_seconds = sum((timing.duration_seconds for timing in tool_timings), 0.0) if tool_timings else None
    worker_wall_seconds = _interval_union_seconds(tool_intervals)

    processing = None
    try:
        config_path = registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
        processing = JobProcessingConfig.model_validate_json(config_path.read_bytes()).params
    except ArtifactStoreError:
        processing = None  # Job legacy trước khi có file cấu hình chung.

    project = registry.get_project(job.project_id)
    sog_size = None
    if preview is not None:
        try:
            sog_size = registry.runtime_resolver.require(preview.delivery_ref).stat().st_size
        except ArtifactStoreError:
            sog_size = None

    queue_at = next((event.recorded_at for event in attempt_events if event.status == JobStatus.QUEUED), None)
    first_run_at = attempt_started_at
    queue_seconds = _seconds(queue_at, first_run_at)
    user_wait = _user_wait_seconds(progress, attempts, observed_at, job)
    job_elapsed = _seconds(job.started_at, job.completed_at) if is_terminal else None
    attempt_wall = _seconds(attempt_started_at, attempt_completed_at) if is_terminal else None
    frame_count = next(
        (event.actual_frame_count for event in reversed(attempts) if event.actual_frame_count is not None), None
    )
    preview_latency = _seconds(job.started_at, first_preview_ready_at)
    timing_issues = [*critical_issues]
    if not tool_timings:
        timing_issues.append("worker_resource_telemetry_unavailable")
    if any(stage.stage_id == StageId.VISUAL_RECON.value for stage in stages) and first_preview_ready_at is None:
        timing_issues.append("preview_verified_timestamp_unavailable")

    return PipelineRuntimeBenchmark(
        schema_version=BENCHMARK_SCHEMA_VERSION,
        job_id=job.job_id,
        project_id=job.project_id,
        attempt=progress.attempt,
        label=label,
        recorded_at=observed_at,
        status=job.status.value,
        snapshot_phase="terminal" if is_terminal else "partial",
        stages=stages,
        total_seconds=job_elapsed,
        attempt_started_at=attempt_started_at,
        attempt_completed_at=attempt_completed_at,
        attempt_wall_seconds=attempt_wall,
        queue_seconds=queue_seconds,
        user_wait_seconds=user_wait,
        critical_path_seconds=critical_path,
        worker_process_seconds=worker_process_seconds,
        worker_wall_seconds=worker_wall_seconds,
        worker_measurement_count=len(tool_timings),
        tool_timings=tool_timings,
        timing_coverage=TimingCoverage(
            worker_stage_count=len(active_worker_stages),
            measured_worker_stage_count=len(active_worker_stages) - len(missing),
            missing_worker_stage_ids=missing,
        ),
        timing_issues=timing_issues,
        first_preview_ready_at=first_preview_ready_at,
        first_preview_time_source="verified" if first_preview_ready_at is not None else "unknown",
        time_to_first_preview_seconds=preview_latency,
        actual_frame_count=frame_count,
        input_manifest_checksum=job.input_manifest_checksum,
        runtime_manifest_checksum=job.runtime_manifest_checksum,
        processing=processing,
        config_checksum=job.config_checksum,
        machine=machine,
        input_size_bytes=project.input_video.size_bytes if project.input_video else None,
        sog_size_bytes=sog_size,
        gpu_allocated_seconds=None,
        gpu_hourly_usd=gpu_hourly_usd,
        estimated_gpu_cost_usd=None,
        active_compute_seconds=None,
        io_seconds=None,
        publication_seconds=None,
    )


def publish_benchmark(registry: ProjectRegistry, benchmark: PipelineRuntimeBenchmark) -> ProductArtifactRef:
    """Publish partial and terminal snapshots at separate immutable paths."""
    payload = benchmark.model_dump_json(indent=2).encode("utf-8") + b"\n"
    phase = benchmark.snapshot_phase or (
        "terminal" if benchmark.status in {status.value for status in TERMINAL_STATUSES} else "partial"
    )
    reference = ProductArtifactRef(
        artifact_type="PipelineRuntimeBenchmark",
        schema_version=benchmark.schema_version,
        artifact_uri=(
            f"artifact://jobs/{benchmark.job_id}/benchmark/{BENCHMARK_KIND}/attempt-{benchmark.attempt}-{phase}.json"
        ),
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="benchmark",
        job_id=benchmark.job_id,
    )
    FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)
    return reference
