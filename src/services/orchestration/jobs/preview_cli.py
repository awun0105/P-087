"""Basic worker runner cho prepared RGB jobs, chạy ngoài HTTP process.

REC vẫn sở hữu thuật toán và consumer verification. Runner chỉ claim durable job,
chạy entrypoint cố định, quan sát cancel/timeout và commit result đã kiểm chứng.
Không nhận raw video hoặc tự cấp privacy approval.
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
from pathlib import Path
from threading import Event
from uuid import uuid4

from src.config import get_settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import load_prepared_profile, prepared_frame_reference, require_profile
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.reconstruction import verify_prepared_preview

logger = logging.getLogger(__name__)


class PreviewCancelledError(RuntimeError):
    """Owner hoặc process khác đã kết thúc job; không được publish success muộn."""


def _stop(process: subprocess.Popen) -> None:
    """Nhả cả COLMAP/Brush con; không để GPU tiếp tục train sau khi cancel."""
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


def _run(command: list[str], workspace: Path, registry: ProjectRegistry, job: JobManifest, timeout: float) -> int:
    with (workspace / "stdout.json").open("xb") as output, (workspace / "stderr.log").open("xb") as errors:
        process = subprocess.Popen(
            command, stdout=output, stderr=errors, stdin=subprocess.DEVNULL, start_new_session=True
        )
        deadline = time.monotonic() + timeout
        pause = Event()
        try:
            while process.poll() is None:
                current = registry.get_job(job.job_id)
                if current.job_manifest_checksum != job.job_manifest_checksum:
                    raise PreviewCancelledError("Job revision đã thay đổi trong khi worker chạy")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Preview worker quá thời gian cấu hình")
                pause.wait(1)
            return process.returncode
        finally:
            _stop(process)


def run_prepared_job(job_id: str, frame_set_uri: str, *, expected_checksum: str | None = None) -> JobManifest:
    """Chỉ dispatch frame ref đã publish/allow-list và profile đúng JobManifest."""
    settings = get_settings()
    registry = get_project_registry()
    initial = registry.get_job(job_id)
    if expected_checksum is not None and initial.job_manifest_checksum != expected_checksum:
        raise RuntimeStateConflictError("Queue candidate đã thay đổi trước dispatch")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", job_id) is None:
        raise ValueError("Job ID không thể dùng làm worker namespace")
    profile_path = settings.product_processing_config
    if profile_path is None or registry.execution_profile is None:
        raise ValueError("Worker cần execution profile đã cấu hình")
    require_profile(initial, registry.execution_profile)
    profile = load_prepared_profile(profile_path, registry.execution_profile)
    frames = prepared_frame_reference(initial)
    if frames is None or frames.artifact_uri != frame_set_uri:
        raise ValueError("Frame set không phải output thành công duy nhất trong JobManifest")
    # Không fallback fixture và không resolve graph preview cũ của attempt trước.
    registry.runtime_resolver.require(frames)
    attempt_id = f"preview-{uuid4().hex}"
    workspace = settings.product_worker_root.expanduser().resolve() / job_id / attempt_id
    workspace.mkdir(parents=True, exist_ok=False)
    request = {
        "schema_version": "1.0",
        "execution_scope": "prepared_rgb_preview",
        "job_id": job_id,
        "attempt_id": attempt_id,
        "source_input_checksum": initial.input_manifest_checksum,
        "frame_set_ref": frames.model_dump(mode="json"),
        **profile,
    }
    request_path = workspace / "request.json"
    with request_path.open("x", encoding="utf-8") as stream:
        json.dump(request, stream)
    # CAS claim: hai runner không thể cùng chuyển QUEUED→RUNNING thành công.
    job = registry.transition_job(
        job_id,
        TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.CAMERA_POSE),
        expected_checksum=initial.job_manifest_checksum,
    )
    try:
        command = [
            sys.executable,
            "-m",
            "src.services.reconstruction.preview_cli",
            "--request",
            str(request_path),
            "--store-root",
            str(registry.runtime_resolver.artifact_root),
            "--workspace",
            str(workspace / "rec"),
        ]
        exit_code = _run(command, workspace, registry, job, settings.product_preview_timeout_seconds)
        output_path = workspace / "stdout.json"
        if output_path.stat().st_size > 1048576:
            raise ValueError("Preview worker response vượt giới hạn 1 MiB")
        payload = json.loads(output_path.read_bytes())
        if not isinstance(payload, dict) or exit_code not in {0, 1}:
            raise RuntimeError("Preview worker không trả result hợp lệ")
        reference = ProductArtifactRef.model_validate(payload.get("result_ref"))
        receipt = verify_prepared_preview(reference, registry.runtime_resolver.require)
        if receipt.attempt_id != attempt_id or (receipt.error is None) != (exit_code == 0):
            raise ValueError("Worker result khác attempt/exit status")
        return registry.record_preview(job, receipt)
    except BaseException as error:
        # Process boundary: luôn ghi failure có redaction, không swallow interrupt.
        current = registry.get_job(job_id)
        if current.job_manifest_checksum == job.job_manifest_checksum:
            try:
                registry.transition_job(
                    job_id,
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
                    expected_checksum=job.job_manifest_checksum,
                )
            except RuntimeStateConflictError:
                logger.info("Worker failure không ghi đè revision mới hơn")
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
