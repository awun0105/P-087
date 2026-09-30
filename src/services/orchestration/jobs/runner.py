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
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from uuid import uuid4

from src.config import Settings, get_settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import (
    ExecutionError,
    InputManifest,
    JobManifest,
    JobStatus,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.benchmark import build_benchmark, publish_benchmark
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import (
    ResolvedProcessing,
    prepared_frame_reference,
    require_profile,
    resolve_job_processing,
)
from src.services.orchestration.jobs.models import PreparedInputReceipt, TransitionRequest
from src.services.orchestration.jobs.progress import awaiting_finalize, metric_confirmation_stage
from src.services.orchestration.processing.capability import latest as latest_capability
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.reconstruction import (
    confirmation_summary,
    load_finalize_result,
    load_geometry_profile,
    verify_prepared_preview,
)

logger = logging.getLogger(__name__)

_MAX_TOOL_RESPONSE_BYTES = 1048576
_JOB_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"


class PreviewCancelledError(RuntimeError):
    """Owner hoặc process khác đã kết thúc job; không được publish success muộn."""


def _stop(process: subprocess.Popen) -> None:
    """Nhả cả COLMAP/Brush/FFmpeg con; không để GPU tiếp tục chạy sau khi cancel."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Process vừa thoát giữa timeout và kill; vẫn reap phía dưới.
        process.wait()


@dataclass
class _Attempt:
    """Một attempt đang chạy; `job` luôn là revision mới nhất do chính runner ghi."""

    registry: ProjectRegistry
    settings: Settings
    job: JobManifest
    workspace: Path


class _StageProgress:
    """Đọc dần progress file của REC (JSON lines StageArtifact) và đẩy stage RUNNING vào job."""

    def __init__(self, attempt: _Attempt, path: Path) -> None:
        self.attempt = attempt
        self.path = path
        self.offset = 0

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
            if stage.status == StageStatus.RUNNING and stage.stage_id != self.attempt.job.current_stage:
                self.attempt.job = self.attempt.registry.record_stage_progress(self.attempt.job, stage.stage_id)


def _run_tool(
    attempt: _Attempt,
    name: str,
    command: list[str],
    timeout: float,
    progress: _StageProgress | None = None,
) -> tuple[int, dict]:
    """Chạy một REC CLI trong process group riêng, hủy khi job revision đổi (cancel)."""
    stdout_path = attempt.workspace / f"{name}.stdout.json"
    with stdout_path.open("xb") as output, (attempt.workspace / f"{name}.stderr.log").open("xb") as errors:
        process = subprocess.Popen(
            command, stdout=output, stderr=errors, stdin=subprocess.DEVNULL, start_new_session=True
        )
        deadline = time.monotonic() + timeout
        pause = Event()
        try:
            while process.poll() is None:
                if progress is not None:
                    progress.poll()  # Tự cập nhật attempt.job trước khi so revision để phát hiện cancel.
                current = attempt.registry.get_job(attempt.job.job_id)
                if current.job_manifest_checksum != attempt.job.job_manifest_checksum:
                    raise PreviewCancelledError("Job revision đã thay đổi trong khi worker chạy")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{name} worker quá thời gian cấu hình")
                pause.wait(1)
            exit_code = process.returncode
        finally:
            _stop(process)
    if stdout_path.stat().st_size > _MAX_TOOL_RESPONSE_BYTES:
        raise ValueError(f"{name} worker response vượt giới hạn 1 MiB")
    lines = stdout_path.read_bytes().strip().splitlines()
    payload = json.loads(lines[-1]) if lines else None
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} worker không trả result hợp lệ")
    return exit_code, payload


def _record_runner_failure(attempt: _Attempt, error: BaseException) -> None:
    """Process boundary: ghi FAILED có redaction trên đúng revision runner đang giữ."""
    current = attempt.registry.get_job(attempt.job.job_id)
    if current.job_manifest_checksum != attempt.job.job_manifest_checksum:
        return
    try:
        attempt.registry.transition_job(
            attempt.job.job_id,
            TransitionRequest(
                target_status=JobStatus.FAILED,
                error=ExecutionError(
                    stage_id=current.current_stage,
                    error_code="PREVIEW_RUNNER_FAILED",
                    human_message="Worker dừng trước checkpoint hợp lệ; kiểm log attempt và runtime trước khi retry",
                    retryable=False,
                    details={"exception_type": type(error).__name__},
                ),
            ),
            expected_checksum=attempt.job.job_manifest_checksum,
        )
    except RuntimeStateConflictError:
        logger.info("Worker failure không ghi đè revision mới hơn")


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
    job = attempt.registry.record_preview(attempt.job, receipt)
    _record_benchmark(attempt)
    return job


def _record_benchmark(attempt: _Attempt) -> None:
    """Ghi benchmark sau attempt; không bao giờ làm hỏng job vì lỗi đo đạc (process boundary)."""
    try:
        machine = latest_capability(RuntimeDatabase(attempt.settings.database_url))
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


def _pull_input(resolver: ArtifactResolver, manifest_ref: ProductArtifactRef) -> None:
    """Đưa InputManifest và video gốc vào cache cục bộ, kiểm đúng checksum trong manifest."""
    manifest = InputManifest.model_validate_json(resolver.require(manifest_ref).read_bytes())
    for item in manifest.files:
        resolver.require_uri(item.artifact_uri, item.checksum)


def _execute_prepare(attempt: _Attempt, profile: ResolvedProcessing) -> JobManifest:
    """Chuẩn bị input video qua REC CLI và ghi các stage vào JobManifest."""
    project = attempt.registry.get_project(attempt.job.project_id)
    if project.input_manifest_ref is None:
        raise ValueError("Project không có InputManifest đã publish")
    _pull_input(attempt.registry.runtime_resolver, project.input_manifest_ref)
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
    return attempt.registry.record_prepared_input(attempt.job, receipt)


def run_prepared_job(job_id: str, frame_set_uri: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Chỉ dispatch frame ref đã publish/allow-list và profile đúng JobManifest."""
    initial = get_project_registry().get_job(job_id)
    frames = prepared_frame_reference(initial)
    if frames is None or frames.artifact_uri != frame_set_uri:
        raise ValueError("Frame set không phải output thành công duy nhất trong JobManifest")
    attempt, profile = _start_attempt(job_id, expected_checksum, StageId.CAMERA_POSE)
    try:
        return _execute_preview(attempt, frames, profile)
    except BaseException as error:
        _record_runner_failure(attempt, error)
        raise


def run_video_job(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Upload video → frame set → preview trong một attempt; dừng ngay ở stage lỗi."""
    attempt, profile = _start_attempt(job_id, expected_checksum, StageId.INPUT_VALIDATE)
    try:
        attempt.job = _execute_prepare(attempt, profile)
        if attempt.job.status != JobStatus.RUNNING:
            _record_benchmark(attempt)  # job dừng ở bước chuẩn bị (vd video lỗi) vẫn có số đo
            return attempt.job
        frames = prepared_frame_reference(attempt.job)
        if frames is None:
            raise ValueError("Prepare thành công nhưng thiếu frame set")
        return _execute_preview(attempt, frames, profile)
    except BaseException as error:
        _record_runner_failure(attempt, error)
        raise


def _authorized_decision(attempt_registry: ProjectRegistry, job: JobManifest) -> tuple[ProductArtifactRef, str]:
    """PRODUCT xác minh quyết định người dùng trước khi giao REC chạy tiếp (authority của PRODUCT)."""
    from src.services.orchestration.metric import MetricDecision

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
    from src.services.orchestration.scene_extraction import extract_scene

    if bundle_ref is None:
        return []
    try:
        attempt.job = attempt.registry.record_stage_progress(attempt.job, StageId.OBJECT_EXTRACT)
        bundle = ReconstructionBundle.model_validate_json(
            attempt.registry.runtime_resolver.require(bundle_ref).read_bytes()
        )
        stage = extract_scene(attempt.registry, attempt.job, bundle, attempt.settings, workspace / "scene")
        attempt.registry.runtime_resolver.sync_up(attempt.job.job_id)
        return [stage]
    except RuntimeStateConflictError:
        raise
    except Exception:  # noqa: BLE001 - process boundary: ghi log, job vẫn hoàn tất phần tái dựng
        logger.exception("Tách vật thể thất bại job=%s", attempt.job.job_id)
        return []


def run_finalize_job(job_id: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Sau xác nhận tỉ lệ: REC-06 canonical → REC-05 geometry → REC-10 bundle; job kết thúc.

    Claim bằng CAS chuyển stage METRIC → RGB_GEOMETRY nên hai worker không cùng chạy.
    """
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
    profile = load_geometry_profile(settings.product_geometry_config)
    if settings.product_geometry_gpu_index is not None:
        profile = profile.model_copy(update={"gpu_index": settings.product_geometry_gpu_index})
    registry.runtime_resolver.sync_down(job_id)
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
    workspace.mkdir(parents=True, exist_ok=False)
    attempt = _Attempt(registry, settings, job, workspace)
    try:
        request = {
            "schema_version": "1.0",
            "execution_scope": "product_finalize",
            "job_id": job_id,
            "attempt_id": attempt_id,
            "confirmation_ref": confirmation.model_dump(mode="json"),
            "authorized_decision_checksum": decision_checksum,
            "geometry": profile.model_dump(mode="json"),
        }
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
        extra: list[StageArtifact] = []
        if result.error is None:
            extra = _extract_scene_stage(attempt, workspace, result.bundle_ref)
        return registry.record_finalize(attempt.job, result, reference, extra)
    except BaseException as error:
        _record_runner_failure(attempt, error)
        raise


def main(argv: list[str] | None = None) -> int:
    """Operator CLI dùng cùng DB/artifact Settings với API, không sửa paths của artifact."""
    parser = argparse.ArgumentParser(description="Run a queued, privacy-approved prepared RGB preview job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--frame-set-uri", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
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
