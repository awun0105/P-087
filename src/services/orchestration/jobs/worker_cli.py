"""Basic durable queue consumer, chạy ngoài API và chỉ xử lý prepared RGB.

QUEUED + published frame set là request bền vững; manifest CAS là claim. Không
reclaim RUNNING theo timeout vì trainer có thể vẫn còn sống trên host khác.
"""

import argparse
import logging
import signal
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from src.config import get_settings
from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import load_prepared_profile, prepared_frame_reference, require_profile
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.runner import run_prepared_job, run_video_job
from src.services.orchestration.processing import is_presets_file, load_presets
from src.services.orchestration.processing.capability import probe as probe_capability
from src.services.orchestration.processing.capability import record as record_capability
from src.services.orchestration.projects.errors import PrivacyGateBlockedError
from src.services.orchestration.projects.privacy import require_project_dispatch
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry

logger = logging.getLogger(__name__)


class PreparedRunner(Protocol):
    """Seam cho real CLI adapter và regression giả lập; không import REC internals."""

    def __call__(self, job_id: str, frame_set_uri: str, *, expected_checksum: str) -> JobManifest: ...


class VideoRunner(Protocol):
    """Seam cho job của video upload: prepare rồi preview trong một attempt."""

    def __call__(self, job_id: str, *, expected_checksum: str) -> JobManifest: ...


def _record_dispatch_failure(registry: ProjectRegistry, job: JobManifest, cause: Exception) -> None:
    """Lỗi trước claim phải hiện ở job; không đổi attempt đã bị cancel/retry."""
    try:
        claimed = registry.transition_job(
            job.job_id,
            TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.FRAME_EXTRACT),
            expected_checksum=job.job_manifest_checksum,
        )
        registry.transition_job(
            job.job_id,
            TransitionRequest(
                target_status=JobStatus.FAILED,
                error=ExecutionError(
                    stage_id=StageId.FRAME_EXTRACT,
                    error_code="PREPARED_DISPATCH_FAILED",
                    human_message="Không dispatch được prepared input; kiểm tra frame artifact, cấu hình và worker log trước khi retry",
                    retryable=False,
                    details={"exception_type": type(cause).__name__},
                ),
            ),
            expected_checksum=claimed.job_manifest_checksum,
        )
    except (RuntimeStateConflictError, PrivacyGateBlockedError):
        logger.info("Không ghi đè job hoặc privacy revision mới hơn khi ghi dispatch failure")


def dispatch_next(
    registry: ProjectRegistry,
    runner: PreparedRunner = run_prepared_job,
    video_runner: VideoRunner = run_video_job,
) -> bool:
    """Xử lý tối đa một job mỗi lượt; skip input chưa chuẩn bị/profile khác.

    Job có frame set (dataset hoặc retry sau lỗi preview) đi thẳng vào preview; job
    của video upload chưa có frame set thì chạy prepare trước.

    Một manifest hỏng được log riêng, không làm chết queue của các project khác.
    Exception rộng chỉ tại boundary của mỗi job; cause được log bằng tên type
    để không lộ local path/secret từ stderr của tool.
    """
    if registry.persistence is None or registry.execution_profile is None:
        raise ValueError("Queue consumer cần durable registry và execution profile")
    cursor = ""
    while page := registry.persistence.job_ids_after(cursor):
        for job_id in page:
            job: JobManifest | None = None
            try:
                candidate = registry.get_job(job_id)
                require_profile(candidate, registry.execution_profile)
                project = registry.get_project(candidate.project_id)
                require_project_dispatch(project)
                job = candidate
                frames = prepared_frame_reference(job)
                if frames is not None:
                    runner(job_id, frames.artifact_uri, expected_checksum=job.job_manifest_checksum)
                    return True
                if project.input_manifest_ref is None:
                    continue  # Chưa có input để chuẩn bị (ví dụ project dataset chưa publish frames).
                video_runner(job_id, expected_checksum=job.job_manifest_checksum)
                return True
            except (RuntimeStateConflictError, PrivacyGateBlockedError):
                continue  # Job không eligible hoặc runner khác đã claim; không auto retry.
            except Exception as error:
                logger.error("Prepared queue dispatch failed job=%s cause=%s", job_id, type(error).__name__)
                if job is not None:
                    _record_dispatch_failure(registry, job, error)
                    return True
        cursor = page[-1]
    return False


#: Chu kỳ đo lại cấu hình máy; nhỏ hơn TTL của số đo (15 phút) để UI luôn có số mới.
CAPABILITY_INTERVAL_SECONDS = 300


def _start_capability_heartbeat(registry: ProjectRegistry, worker_root: Path) -> Event:
    """Đo và ghi cấu hình máy ngay, rồi lặp ở luồng nền (job dài không làm số đo quá hạn).

    Trả Event để dừng luồng khi worker thoát; lỗi đo được log, không làm dừng worker.
    """
    stop = Event()
    database = registry.persistence.database if registry.persistence is not None else None

    def beat() -> None:
        while True:
            try:
                if database is not None:
                    record_capability(database, probe_capability(worker_root))
            except (OSError, ValueError, RuntimeError) as error:
                logger.warning("Không ghi được cấu hình máy worker: %s", type(error).__name__)
            if stop.wait(CAPABILITY_INTERVAL_SECONDS):
                return

    Thread(target=beat, name="capability-heartbeat", daemon=True).start()
    return stop


def main(argv: list[str] | None = None) -> int:
    """Worker cần cùng DB/store/profile với API; không tạo background thread ở HTTP."""
    parser = argparse.ArgumentParser(description="Consume durable prepared RGB jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one eligible job, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    registry = get_project_registry()
    if registry.execution_profile is None or settings.product_processing_config is None:
        logger.error("Configure PRODUCT_PROCESSING_CONFIG and PRODUCT_RUNTIME_MANIFEST before starting worker")
        return 2
    if is_presets_file(settings.product_processing_config):
        load_presets(settings.product_processing_config)
    else:
        load_prepared_profile(settings.product_processing_config, registry.execution_profile)
    heartbeat = _start_capability_heartbeat(registry, settings.product_worker_root)
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Cho runner cleanup subprocess tree trước khi service thoát."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    pause = Event()
    try:
        while True:
            handled = dispatch_next(registry)
            if args.once:
                return 0
            if not handled:
                pause.wait(settings.product_queue_poll_seconds)
    except KeyboardInterrupt:
        return 130
    finally:
        heartbeat.set()
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
