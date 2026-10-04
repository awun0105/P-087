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

from src.config import Settings, get_settings
from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId
from src.services.orchestration.jobs.admission import ResourceAdmission
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import load_prepared_profile, prepared_frame_reference, require_profile
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.progress import awaiting_finalize
from src.services.orchestration.jobs.queue import fair_order, waiting_jobs
from src.services.orchestration.jobs.runner import run_finalize_job, run_prepared_job, run_video_job
from src.services.orchestration.jobs.workspace import attempt_in_use, job_attempts, job_root
from src.services.orchestration.processing import is_presets_file, load_presets
from src.services.orchestration.processing.capability import probe as probe_capability
from src.services.orchestration.processing.capability import record as record_capability
from src.services.orchestration.projects.errors import PrivacyGateBlockedError
from src.services.orchestration.projects.privacy import require_project_dispatch
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.orchestration.scene.objectify_queue import process_next, recover_interrupted

logger = logging.getLogger(__name__)


class PreparedRunner(Protocol):
    """Seam cho real CLI adapter và regression giả lập; không import REC internals."""

    def __call__(self, job_id: str, frame_set_uri: str, *, expected_checksum: str) -> JobManifest: ...


class VideoRunner(Protocol):
    """Seam cho job của video upload: prepare rồi preview trong một attempt."""

    def __call__(self, job_id: str, *, expected_checksum: str) -> JobManifest: ...


def _record_finalize_failure(registry: ProjectRegistry, job: JobManifest, cause: Exception) -> None:
    """Lỗi trước khi runner hoàn tất claim được job: ghi FAILED ở bước hình học, không lặp vô hạn."""
    error = ExecutionError(
        stage_id=StageId.RGB_GEOMETRY,
        error_code="REC_FINALIZE_DISPATCH_FAILED",
        human_message="Không bắt đầu được bước dựng hình học/bundle; kiểm cấu hình geometry và log worker rồi thử lại",
        retryable=False,
        details={"exception_type": type(cause).__name__},
    )
    try:
        current = registry.get_job(job.job_id)
        if current.job_manifest_checksum != job.job_manifest_checksum or current.status not in {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
        }:
            return  # Runner đã ghi kết quả/lỗi của chính nó, hoặc job đã đổi.
        if current.status == JobStatus.QUEUED:
            current = registry.transition_job(
                job.job_id,
                TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.RGB_GEOMETRY),
                expected_checksum=current.job_manifest_checksum,
            )
        registry.transition_job(
            job.job_id,
            TransitionRequest(target_status=JobStatus.FAILED, error=error),
            expected_checksum=current.job_manifest_checksum,
        )
    except (RuntimeStateConflictError, PrivacyGateBlockedError):
        logger.info("Không ghi đè revision mới hơn khi ghi lỗi bước hoàn tất")


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


def recover_interrupted_jobs(registry: ProjectRegistry, settings: Settings) -> int:
    """Lúc worker khởi động: đánh dấu FAILED (retryable=True) các job RUNNING bị mồ côi trên host này.

    Khi máy tắt đột ngột/hết pin, tiến trình chết và lock OS tự giải phóng (flock attempt.lock).
    Nếu job đang ở RUNNING (và không phải đang chờ người xác nhận tỉ lệ ST-METRIC-CANONICALIZE)
    nhưng attempt workspace trên máy này không còn ai sử dụng (attempt_in_use == False),
    chuyển trạng thái sang FAILED với retryable=True để người dùng bấm 'Thử lại' / tiếp tục.
    """
    if registry.persistence is None:
        return 0
    database = registry.persistence.database
    with database.transaction() as tx:
        rows = tx.execute(
            "SELECT e.job_id, e.payload FROM r2s_job_events e JOIN "
            "(SELECT job_id, MAX(version) AS version FROM r2s_job_events GROUP BY job_id) latest "
            "ON e.job_id=latest.job_id AND e.version=latest.version "
            "WHERE json_extract(e.payload, '$.status') = 'RUNNING'"
        ).fetchall()

    recovered = 0
    worker_root = settings.product_worker_root
    for job_id, _ in rows:
        try:
            job = registry.get_job(job_id)
        except Exception:  # noqa: BLE001
            continue
        if job.status != JobStatus.RUNNING:
            continue
        if awaiting_finalize(job):
            # Nếu đang ở REC-06 chờ finalize, kiểm tra xem có workspace finalize đang chạy dở hay chưa
            # Nếu chỉ đang chờ người dùng xác nhận metric (chưa có confirmation_stage) thì không coi là chết
            pass
        elif job.current_stage == StageId.METRIC_CANONICALIZE and not any(
            s.stage_id == StageId.METRIC_CANONICALIZE for s in job.stage_artifacts
        ):
            # Job đang dừng ở REC-06 chờ người dùng xác nhận metric; không phải tiến trình đang chạy dở
            continue

        root = job_root(job.job_id, worker_root)
        if root is None or not root.exists():
            continue

        attempts = job_attempts(root)
        if not attempts:
            continue

        # Kiểm tra nếu bất kỳ attempt nào còn đang chạy (active process / flock)
        if any(attempt_in_use(att) for att in attempts):
            continue

        error = ExecutionError(
            stage_id=job.current_stage,
            error_code="INTERRUPTED_SHUTDOWN",
            human_message="Tiến trình bị gián đoạn. Bấm thử lại để tiếp tục huấn luyện từ checkpoint đã lưu.",
            retryable=True,
            details={"job_id": job.job_id, "stage": job.current_stage},
        )
        try:
            registry.transition_job(
                job.job_id,
                TransitionRequest(target_status=JobStatus.FAILED, error=error),
                expected_checksum=job.job_manifest_checksum,
            )
            recovered += 1
            logger.info(
                "Auto-recovered interrupted job %s (was in %s) to FAILED (retryable=True)",
                job.job_id,
                job.current_stage,
            )
        except (RuntimeStateConflictError, Exception) as exc:  # noqa: BLE001
            logger.warning("Không thể auto-recover job %s: %s", job.job_id, exc)

    return recovered


def dispatch_next(
    registry: ProjectRegistry,
    runner: PreparedRunner = run_prepared_job,
    video_runner: VideoRunner = run_video_job,
    finalize_runner: VideoRunner = run_finalize_job,
    admission: ResourceAdmission | None = None,
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
    try:
        return _dispatch(registry, runner, video_runner, finalize_runner, admission)
    finally:
        # Giữ chỗ chỉ sống trong lúc worker chạy job; kể cả khi runner ném lỗi hoặc worker bị ngắt.
        if admission is not None:
            admission.release()


def _dispatch(
    registry: ProjectRegistry,
    runner: PreparedRunner,
    video_runner: VideoRunner,
    finalize_runner: VideoRunner,
    admission: ResourceAdmission | None,
) -> bool:
    """Một lượt quét hàng đợi của `dispatch_next`."""
    if registry.persistence is None:
        raise ValueError("Queue consumer cần durable registry")
    # Thứ tự xoay vòng theo người yêu cầu (jobs/queue.py): cũng là thứ tự UI báo cho người dùng.
    for job_id in [item.job_id for item in fair_order(waiting_jobs(registry))]:
        job: JobManifest | None = None
        try:
            candidate = registry.get_job(job_id)
            if awaiting_finalize(candidate):
                # Người dùng đã xác nhận tỉ lệ (job RUNNING, hoặc QUEUED khi retry): chạy
                # tiếp REC-05/REC-10 trên cùng job; vẫn qua cổng privacy của project.
                require_project_dispatch(registry.get_project(candidate.project_id))
                if admission is not None and not admission(candidate, "finalize"):
                    continue
                try:
                    finalize_runner(job_id, expected_checksum=candidate.job_manifest_checksum)
                except RuntimeStateConflictError:
                    raise
                except Exception as error:
                    logger.error("Finalize dispatch failed job=%s cause=%s", job_id, type(error).__name__)
                    _record_finalize_failure(registry, candidate, error)
                return True
            require_profile(candidate, registry.execution_profile)
            project = registry.get_project(candidate.project_id)
            require_project_dispatch(project)
            job = candidate
            frames = prepared_frame_reference(job)
            if frames is not None:
                if admission is not None and not admission(job):
                    continue
                runner(job_id, frames.artifact_uri, expected_checksum=job.job_manifest_checksum)
                return True
            if project.input_manifest_ref is None:
                continue  # Chưa có input để chuẩn bị (ví dụ project dataset chưa publish frames).
            if admission is not None and not admission(job):
                continue
            video_runner(job_id, expected_checksum=job.job_manifest_checksum)
            return True
        except (RuntimeStateConflictError, PrivacyGateBlockedError):
            continue  # Job không eligible hoặc runner khác đã claim; không auto retry.
        except Exception as error:
            logger.error("Prepared queue dispatch failed job=%s cause=%s", job_id, type(error).__name__)
            if job is not None:
                _record_dispatch_failure(registry, job, error)
                return True
    return False


#: Chu kỳ đo lại cấu hình máy; nhỏ hơn TTL của số đo (15 phút) để UI luôn có số mới.
CAPABILITY_INTERVAL_SECONDS = 300


def _start_capability_heartbeat(
    registry: ProjectRegistry, worker_root: Path, admission: ResourceAdmission | None = None
) -> Event:
    """Đo và ghi cấu hình máy ngay, rồi lặp ở luồng nền (job dài không làm số đo quá hạn).

    Lượt đo lúc pipeline không dùng máy được ghi làm mốc "máy rảnh" (preset Maximum tính theo
    mốc này); lúc bận thì giữ mốc rảnh gần nhất. Cùng nhịp đó làm mới giữ chỗ của job đang chạy.
    Trả Event để dừng luồng khi worker thoát; lỗi đo được log, không làm dừng worker.
    """
    stop = Event()
    database = registry.persistence.database if registry.persistence is not None else None

    def beat() -> None:
        previous = None
        while True:
            try:
                if database is not None:
                    idle = admission.machine_idle() if admission is not None else False
                    previous = probe_capability(worker_root, idle=idle, previous=previous)
                    record_capability(database, previous)
                    if admission is not None:
                        admission.touch()
            except Exception as error:  # noqa: BLE001 - luồng nền: lỗi đo/DB không được làm chết heartbeat
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
    admission = ResourceAdmission(registry, settings)
    heartbeat = _start_capability_heartbeat(registry, settings.product_worker_root, admission)
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Cho runner cleanup subprocess tree trước khi service thoát."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    pause = Event()
    try:
        recover_interrupted_jobs(registry, settings)
        recover_interrupted(settings)
        while True:
            # Job trong hàng đợi đi trước; rảnh mới nhận yêu cầu chạy lại tách theo vật (cùng dùng GPU).
            handled = dispatch_next(registry, admission=admission) or process_next(registry, settings)
            if args.once:
                return 0
            if not handled:
                pause.wait(settings.product_queue_poll_seconds)
    except KeyboardInterrupt:
        return 130
    finally:
        heartbeat.set()
        admission.release()
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
