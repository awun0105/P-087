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
from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import load_prepared_profile, prepared_frame_reference, require_profile
from src.services.orchestration.jobs.models import PreparedInputReceipt, TransitionRequest
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.reconstruction import verify_prepared_preview

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


def _run_tool(attempt: _Attempt, name: str, command: list[str], timeout: float) -> tuple[int, dict]:
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


def _start_attempt(job_id: str, expected_checksum: str | None, first_stage: StageId) -> tuple[_Attempt, dict]:
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
    profile = load_prepared_profile(profile_path, registry.execution_profile)
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / f"attempt-{uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=False)
    job = registry.transition_job(
        job_id,
        TransitionRequest(target_status=JobStatus.RUNNING, current_stage=first_stage),
        expected_checksum=initial.job_manifest_checksum,
    )
    return _Attempt(registry, settings, job, workspace), profile


def _execute_preview(attempt: _Attempt, frames: ProductArtifactRef, profile: dict) -> JobManifest:
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
        **profile,
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
    ]
    exit_code, payload = _run_tool(attempt, "preview", command, attempt.settings.product_preview_timeout_seconds)
    if exit_code not in {0, 1}:
        raise RuntimeError("Preview worker không trả result hợp lệ")
    reference = ProductArtifactRef.model_validate(payload.get("result_ref"))
    receipt = verify_prepared_preview(reference, attempt.registry.runtime_resolver.require)
    if receipt.attempt_id != attempt_id or (receipt.error is None) != (exit_code == 0):
        raise ValueError("Worker result khác attempt/exit status")
    return attempt.registry.record_preview(attempt.job, receipt)


def _execute_prepare(attempt: _Attempt) -> JobManifest:
    """Chuẩn bị input video qua REC CLI và ghi các stage vào JobManifest."""
    project = attempt.registry.get_project(attempt.job.project_id)
    if project.input_manifest_ref is None:
        raise ValueError("Project không có InputManifest đã publish")
    quality_profile = json.loads(attempt.settings.product_upload_quality_profile.read_bytes())
    request = {
        "schema_version": "1.0",
        "execution_scope": "rgb_video_prepare",
        "job_id": attempt.job.job_id,
        "input_manifest_ref": project.input_manifest_ref.model_dump(mode="json"),
        "quality_profile": quality_profile,
        "privacy_mode": "self_attested",
        "target_frame_count": attempt.settings.product_target_frame_count,
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
        attempt.job = _execute_prepare(attempt)
        if attempt.job.status != JobStatus.RUNNING:
            return attempt.job
        frames = prepared_frame_reference(attempt.job)
        if frames is None:
            raise ValueError("Prepare thành công nhưng thiếu frame set")
        return _execute_preview(attempt, frames, profile)
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
