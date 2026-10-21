"""Basic durable queue consumer, chạy ngoài API và chỉ xử lý prepared RGB.

QUEUED + published frame set là request bền vững; manifest CAS là claim. Không
reclaim RUNNING theo timeout vì trainer có thể vẫn còn sống trên host khác.
"""

import argparse
import json
import logging
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from src.config import Settings, get_settings
from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId
from src.models.contracts.retryability import classify_retryability
from src.services.orchestration.artifacts.lod import idle_lod_builder
from src.services.orchestration.gpu.state import supports
from src.services.orchestration.gpu.worker import ManagedWorker
from src.services.orchestration.jobs.admission import ResourceAdmission
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.dispatch import load_prepared_profile, prepared_frame_reference, require_profile
from src.services.orchestration.jobs.lease import LEASE_TTL, expired_job_ids, has_lease, leased, release_expired
from src.services.orchestration.jobs.log_context import configure_worker_logging, job_log_context
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.progress import (
    awaiting_anonymization_review,
    awaiting_finalize,
    awaiting_pose_step,
    awaiting_scene_extract,
)
from src.services.orchestration.jobs.registration_worker import RegistrationOperationWorker
from src.services.orchestration.jobs.runner import (
    run_geometry_step,
    run_prepare_step,
    run_prepared_job,
    run_reviewed_preview_job,
    run_scene_step,
    run_view_lod_step,
)
from src.services.orchestration.jobs.steps import (
    DEFAULT_LANES,
    StepId,
    StepKind,
    claim_step,
    finish_claim,
    release_claim,
    resync,
    step_candidates,
    step_cpu_slots,
)
from src.services.orchestration.jobs.worker_runtimes import has_live_runtime, publisher
from src.services.orchestration.jobs.workspace import attempt_in_use, job_attempts, job_root
from src.services.orchestration.processing import is_presets_file, load_presets
from src.services.orchestration.processing.capability import probe as probe_capability
from src.services.orchestration.processing.capability import record as record_capability
from src.services.orchestration.processing.capability import worker_identity
from src.services.orchestration.projects.errors import PrivacyGateBlockedError
from src.services.orchestration.projects.privacy import require_project_dispatch
from src.services.orchestration.projects.registry import ProjectRegistry, get_project_registry
from src.services.orchestration.review.validation_worker import IsaacValidationWorker
from src.services.orchestration.samples.session_worker import process_demo_session
from src.services.orchestration.scene.objectify_queue import process_next, recover_interrupted
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads.scene_imports import ImportService

logger = logging.getLogger(__name__)

#: Thời gian nghỉ tối đa (giây) khi một hàng đợi lỗi liên tiếp.
_MAX_BACKOFF_SECONDS = 60


@dataclass
class QueueGuard:
    """Đếm lỗi liên tiếp theo hàng đợi; một hàng đợi lỗi không được làm thoát vòng lặp worker."""

    failures: dict[str, int] = field(default_factory=dict)

    def run(self, name: str, step: Callable[[], bool]) -> bool:
        """Chạy một lượt của hàng đợi; lỗi thường được ghi log và coi như không có việc."""
        try:
            handled = step()
        except Exception:
            count = self.failures.get(name, 0) + 1
            self.failures[name] = count
            logger.exception("Hàng đợi %s lỗi lần %d liên tiếp", name, count)
            return False
        self.failures.pop(name, None)
        return handled

    def backoff_seconds(self) -> float:
        """0 khi không hàng đợi nào đang lỗi; ngược lại 1, 2, 4… giây, tối đa 60."""
        if not self.failures:
            return 0
        return min(2 ** (max(self.failures.values()) - 1), _MAX_BACKOFF_SECONDS)


class Periodic:
    """`due(now)` đúng ở lần đầu và sau mỗi `interval` giây (đồng hồ đơn điệu); dùng cho việc quét đắt trong vòng poll."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._next: float | None = None

    def due(self, now: float) -> bool:
        if self._next is not None and now < self._next:
            return False
        self._next = now + self.interval
        return True


def poll_queues(guard: QueueGuard, steps: list[tuple[str, Callable[[], bool]]]) -> bool:
    """Chạy lần lượt các hàng đợi tới khi một hàng có việc; hàng lỗi không chặn các hàng sau."""
    return any(guard.run(name, step) for name, step in steps)


class PreparedRunner(Protocol):
    """Seam cho real CLI adapter và regression giả lập; không import REC internals."""

    def __call__(self, job_id: str, frame_set_uri: str, *, expected_checksum: str) -> JobManifest: ...


class VideoRunner(Protocol):
    """Seam cho một bước chạy trên job đã có (prepare, dựng camera sau prepare, hình học, tách vật, LOD)."""

    def __call__(self, job_id: str, *, expected_checksum: str) -> JobManifest: ...


def _record_finalize_failure(
    registry: ProjectRegistry, job: JobManifest, cause: Exception, stage: StageId = StageId.RGB_GEOMETRY
) -> None:
    """Lỗi trước khi runner hoàn tất claim được job: ghi FAILED ở bước hình học/tách vật, không lặp vô hạn."""
    details = {"exception_type": type(cause).__name__}
    error = ExecutionError(
        stage_id=stage,
        error_code="REC_FINALIZE_DISPATCH_FAILED",
        human_message="Không bắt đầu được bước dựng hình học/bundle; kiểm cấu hình geometry và log worker rồi thử lại",
        retryable=classify_retryability("REC_FINALIZE_DISPATCH_FAILED", details),
        details=details,
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
                TransitionRequest(target_status=JobStatus.RUNNING, current_stage=stage),
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
    details = {"exception_type": type(cause).__name__}
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
                    retryable=classify_retryability("PREPARED_DISPATCH_FAILED", details),
                    details=details,
                ),
            ),
            expected_checksum=claimed.job_manifest_checksum,
        )
    except (RuntimeStateConflictError, PrivacyGateBlockedError):
        logger.info("Không ghi đè job hoặc privacy revision mới hơn khi ghi dispatch failure")


def latest_running_job_ids(tx) -> list[str]:
    """Job whose newest event is RUNNING, on SQLite and PostgreSQL alike.

    The status is read in Python: `json_extract` is SQLite-only and made every worker exit at startup on the
    production PostgreSQL database. The scan reads one payload per job (newest event only).
    """
    rows = tx.execute(
        "SELECT e.job_id, e.payload FROM r2s_job_events e JOIN "
        "(SELECT job_id, MAX(version) AS version FROM r2s_job_events GROUP BY job_id) latest "
        "ON e.job_id=latest.job_id AND e.version=latest.version"
    ).fetchall()
    running = []
    for job_id, payload in rows:
        try:
            status = json.loads(payload).get("status") if isinstance(payload, str) else (payload or {}).get("status")
        except ValueError:
            continue
        if status == "RUNNING":
            running.append(str(job_id))
    return running


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
        rows = [(job_id, None) for job_id in latest_running_job_ids(tx)]

    recovered = 0
    worker_root = settings.product_worker_root
    for job_id, _ in rows:
        try:
            job = registry.get_job(job_id)
        except Exception:  # noqa: BLE001
            continue
        if job.status != JobStatus.RUNNING:
            continue
        if intentionally_unleased(job):
            # Job dừng có chủ ý giữa hai bước (chờ người dùng, hoặc chờ worker nhận bước sau): không phải tiến trình chết.
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

        details = {"job_id": job.job_id, "stage": job.current_stage}
        error = ExecutionError(
            stage_id=job.current_stage,
            error_code="INTERRUPTED_SHUTDOWN",
            human_message="Tiến trình bị gián đoạn. Bấm thử lại để tiếp tục huấn luyện từ checkpoint đã lưu.",
            retryable=classify_retryability("INTERRUPTED_SHUTDOWN", details),
            details=details,
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
    video_runner: VideoRunner = run_prepare_step,
    finalize_runner: VideoRunner = run_geometry_step,
    admission: ResourceAdmission | None = None,
    reviewed_runner: VideoRunner = run_reviewed_preview_job,
    scene_runner: VideoRunner = run_scene_step,
    lod_runner: VideoRunner = run_view_lod_step,
    lanes: tuple[StepKind, ...] = DEFAULT_LANES,
) -> bool:
    """Chạy tối đa một **bước** mỗi lượt (T-073); skip input chưa chuẩn bị/profile khác.

    Mỗi bước được xét tài nguyên riêng (`admit_step`) và giữ chỗ chỉ trong lúc bước chạy, nên bước CPU của job này
    không chiếm GPU khi bước GPU của job khác đang chờ. Các runner là seam cho test: `video_runner` = bước chuẩn bị,
    `runner`/`reviewed_runner` = bước dựng camera (job đã có frame set / vừa chuẩn bị xong), `finalize_runner` = bước
    hình học, `scene_runner` = bước tách vật, `lod_runner` = bộ LOD.

    Một manifest hỏng được log riêng, không làm chết queue của các project khác.
    Exception rộng chỉ tại boundary của mỗi job; cause được log bằng tên type
    để không lộ local path/secret từ stderr của tool.
    """
    if registry.persistence is None or registry.execution_profile is None:
        raise ValueError("Queue consumer cần durable registry và execution profile")
    try:
        return _dispatch(
            registry,
            runner,
            video_runner,
            finalize_runner,
            admission,
            reviewed_runner,
            scene_runner=scene_runner,
            lod_runner=lod_runner,
            lanes=lanes,
        )
    finally:
        # Giữ chỗ chỉ sống trong lúc worker chạy bước; kể cả khi runner ném lỗi hoặc worker bị ngắt.
        if admission is not None:
            admission.release()


def _admitted(admission: ResourceAdmission | None, job: JobManifest, step: StepId, kind: StepKind) -> bool:
    if admission is None:
        return True
    return admission.admit_step(job, step, gpu_required=kind == "gpu", cpu_slots=step_cpu_slots(step, kind))


def _dispatch(
    registry: ProjectRegistry,
    runner: PreparedRunner,
    video_runner: VideoRunner,
    finalize_runner: VideoRunner,
    admission: ResourceAdmission | None,
    reviewed_runner: VideoRunner = run_reviewed_preview_job,
    *,
    scene_runner: VideoRunner = run_scene_step,
    lod_runner: VideoRunner = run_view_lod_step,
    lanes: tuple[StepKind, ...] = DEFAULT_LANES,
) -> bool:
    """Một lượt quét hàng đợi bước của `dispatch_next`."""
    if registry.persistence is None or registry.execution_profile is None:
        raise ValueError("Queue consumer cần durable registry và execution profile")
    profile = registry.execution_profile
    for candidate in step_candidates(registry, lanes):
        job_id, step, kind = candidate.job.job_id, candidate.step, candidate.kind
        job: JobManifest | None = None
        attempt_context_id = "-"
        try:
            history = registry.list_job_attempts(job_id)
            attempt_context_id = str(history[-1].attempt) if history else "-"
            with job_log_context(job_id, attempt_context_id):
                current = candidate.job
                if step == "view_lod":
                    if idle_lod_cli() is None:
                        continue  # máy không tạo được bộ LOD: để worker có GPU nhận
                    if not _admitted(admission, current, step, kind):
                        continue
                    if not _run_step(registry, current, step, kind, lambda: lod_runner(job_id, expected_checksum=None)):
                        continue
                    return True
                if step in {"canonical_geometry", "scene_extract"}:
                    # Người dùng đã xác nhận tỉ lệ: chạy tiếp REC-05/REC-10 hoặc tách vật trên cùng job; vẫn qua cổng
                    # privacy của project và chờ máy đúng runtime (T-040 Q4).
                    require_project_dispatch(registry.get_project(current.project_id))
                    if not _runtime_matches(profile, current):
                        continue
                    if not _admitted(admission, current, step, kind):
                        continue
                    step_runner = finalize_runner if step == "canonical_geometry" else scene_runner
                    try:
                        if not _run_step(
                            registry,
                            current,
                            step,
                            kind,
                            lambda: step_runner(job_id, expected_checksum=current.job_manifest_checksum),
                        ):
                            continue
                    except RuntimeStateConflictError:
                        raise
                    except Exception as error:
                        logger.error("%s dispatch failed job=%s cause=%s", step, job_id, type(error).__name__)
                        _record_finalize_failure(
                            registry,
                            current,
                            error,
                            StageId.RGB_GEOMETRY if step == "canonical_geometry" else StageId.OBJECT_EXTRACT,
                        )
                    return True
                if step == "pose_visual" and awaiting_pose_step(current):
                    # Bước chuẩn bị đã xong (và bản đã che đã được chấp nhận nếu có): dựng preview trên cùng job.
                    require_project_dispatch(registry.get_project(current.project_id))
                    if not _admitted(admission, current, step, kind):
                        continue
                    if not _run_step(
                        registry,
                        current,
                        step,
                        kind,
                        lambda: reviewed_runner(job_id, expected_checksum=current.job_manifest_checksum),
                    ):
                        continue
                    return True
                if _rebind_orphaned_job(registry, current, profile):
                    return True  # Lượt sau dispatch job này trên runtime mới.
                require_profile(current, profile)
                project = registry.get_project(current.project_id)
                require_project_dispatch(project)
                job = current
                if step == "pose_visual":
                    frames = prepared_frame_reference(job)
                    if frames is None:
                        continue
                    if not _admitted(admission, job, step, kind):
                        continue
                    if not _run_step(
                        registry,
                        job,
                        step,
                        kind,
                        lambda: runner(job_id, frames.artifact_uri, expected_checksum=current.job_manifest_checksum),
                    ):
                        continue
                    return True
                if project.input_manifest_ref is None:
                    continue  # Chưa có input để chuẩn bị (ví dụ project dataset chưa publish frames).
                if not _admitted(admission, job, step, kind):
                    continue
                if not _run_step(
                    registry,
                    job,
                    step,
                    kind,
                    lambda: video_runner(job_id, expected_checksum=current.job_manifest_checksum),
                ):
                    continue
                return True
        except (RuntimeStateConflictError, PrivacyGateBlockedError):
            continue  # Job không eligible hoặc runner khác đã claim; không auto retry.
        except Exception as error:
            with job_log_context(job_id, attempt_context_id):
                logger.error("Prepared queue dispatch failed job=%s cause=%s", job_id, type(error).__name__)
                if job is not None:
                    _record_dispatch_failure(registry, job, error)
                    return True
    return False


def idle_lod_cli() -> Path | None:
    """CLI tạo bộ LOD của máy này (None khi không có GPU / runtime); tách ra để test thay được."""
    from src.services.orchestration.artifacts import lod

    return lod.lod_cli()


def _run_step(
    registry: ProjectRegistry, job: JobManifest, step: StepId, kind: StepKind, call: Callable[[], object]
) -> bool:
    """Nhận bước (CAS `ready → claimed`), rồi chạy trong lease của job; False khi worker khác đã nhận bước/job."""
    assert registry.persistence is not None
    database = registry.persistence.database
    claim = claim_step(
        database,
        job,
        step,
        worker_identity()[0],
        load_job=registry.persistence.job_from_pointer,
        kind=kind,
    )
    if claim is None:
        return False
    ran = False
    failed = False
    try:
        ran = _leased_call(registry, job.job_id, call)
        return ran
    except BaseException:
        failed = True
        raise
    finally:
        try:
            if step == "view_lod":
                if ran or failed:
                    finish_claim(database, claim, "failed" if failed else "done")
                else:
                    release_claim(database, claim)
            else:
                release_claim(database, claim)  # bước không chạy được (vd mất lease): trả về ready nếu còn của mình
                resync(database, job.job_id, registry.persistence.job_from_pointer)
        except Exception as error:  # noqa: BLE001 - dòng bước tự hết hạn claim; không che kết quả/lỗi của bước
            logger.warning("Không cập nhật được bảng bước job=%s cause=%s", job.job_id, type(error).__name__)


def _leased_call(registry: ProjectRegistry, job_id: str, call: Callable[[], object]) -> bool:
    """Chạy một runner trong lease của job (T-040 Q2); False khi worker khác đang giữ job."""
    if registry.persistence is None:
        raise ValueError("Lease cần durable registry")
    with leased(registry.persistence.database, job_id, worker_identity()[0]) as held:
        if held is None:
            return False
        call()
    return True


def intentionally_unleased(job: JobManifest) -> bool:
    """Job RUNNING mà không worker nào giữ lease **có chủ ý**: chờ người, hoặc dừng giữa hai bước chờ worker nhận bước
    kế (T-073: sau bước chuẩn bị, sau xác nhận tỉ lệ, sau bước hình học)."""
    if (
        awaiting_anonymization_review(job)
        or awaiting_pose_step(job)
        or awaiting_finalize(job)
        or awaiting_scene_extract(job)
    ):
        return True
    return job.current_stage == StageId.METRIC_CANONICALIZE and not any(
        stage.stage_id == StageId.METRIC_CANONICALIZE for stage in job.stage_artifacts
    )


def recover_unwatched_running_jobs(registry: ProjectRegistry, *, now: datetime | None = None) -> int:
    """T-048: job RUNNING không lease, không chờ có chủ ý, quá một TTL lease → FAILED cho chạy lại.

    Mọi lượt chạy runner giữ lease trước khi ghi RUNNING, nên trường hợp này chỉ xảy ra khi runner chết
    trong khe không ghi được lỗi (hoặc job chạy trước khi có lease). Máy nào cũng xử lý được.
    """
    if registry.persistence is None:
        return 0
    database = registry.persistence.database
    current = now or datetime.now(UTC)
    with database.transaction() as tx:
        rows = [(job_id,) for job_id in latest_running_job_ids(tx)]
    recovered = 0
    for (job_id,) in rows:
        try:
            job = registry.get_job(job_id)
            if job.status != JobStatus.RUNNING or intentionally_unleased(job) or has_lease(database, job_id):
                continue
            attempts = registry.list_job_attempts(job_id)
            if not attempts or current - attempts[-1].recorded_at < LEASE_TTL:
                continue
            details = {"job_id": job_id, "stage": job.current_stage, "reason": "no_lease"}
            error = ExecutionError(
                stage_id=job.current_stage,
                error_code="INTERRUPTED_SHUTDOWN",
                human_message="Không còn máy xử lý nào chạy bước này. Bấm Thử lại để chạy tiếp.",
                retryable=classify_retryability("INTERRUPTED_SHUTDOWN", details),
                details=details,
            )
            registry.transition_job(
                job_id,
                TransitionRequest(target_status=JobStatus.FAILED, error=error),
                expected_checksum=job.job_manifest_checksum,
            )
            recovered += 1
            logger.info("Job %s RUNNING không có lease, đưa về FAILED (retryable=True)", job_id)
        except RuntimeStateConflictError:
            continue  # Máy khác đã xử lý trước (CAS).
        except Exception as error:  # noqa: BLE001 - một job lỗi không được chặn các job khác
            logger.warning("Không xử lý được job không lease %s: %s", job_id, type(error).__name__)
    return recovered


def recover_expired_leases(registry: ProjectRegistry, *, now: datetime | None = None) -> int:
    """T-040 Q2: job RUNNING mà worker giữ lease đã mất → FAILED retryable. Máy nào cũng làm được, không cần workspace."""
    if registry.persistence is None:
        return 0
    database = registry.persistence.database
    recovered = 0
    for job_id in expired_job_ids(database, now=now):
        try:
            job = registry.get_job(job_id)
            if job.status == JobStatus.RUNNING:
                details = {"job_id": job_id, "stage": job.current_stage}
                error = ExecutionError(
                    stage_id=job.current_stage,
                    error_code="INTERRUPTED_SHUTDOWN",
                    human_message="Worker chạy job đã mất (quá thời gian gia hạn). Bấm thử lại để chạy tiếp.",
                    retryable=classify_retryability("INTERRUPTED_SHUTDOWN", details),
                    details=details,
                )
                registry.transition_job(
                    job_id,
                    TransitionRequest(target_status=JobStatus.FAILED, error=error),
                    expected_checksum=job.job_manifest_checksum,
                )
                recovered += 1
                logger.info("Job %s: lease hết hạn, đưa về FAILED (retryable=True)", job_id)
            release_expired(database, job_id, now=now)
        except RuntimeStateConflictError:
            continue  # Máy khác đã xử lý trước (CAS); lượt sau đọc lại.
        except Exception as error:  # noqa: BLE001 - một job lỗi không được chặn các job hết hạn khác
            logger.warning("Không xử lý được lease hết hạn job %s: %s", job_id, type(error).__name__)
    return recovered


def _runtime_matches(profile: ExecutionProfile, job: JobManifest) -> bool:
    return profile.accepts_runtime(job.runtime_manifest_checksum) and job.seed == profile.seed


def _rebind_orphaned_job(registry: ProjectRegistry, job: JobManifest, profile: ExecutionProfile) -> bool:
    """T-040 Q1: job QUEUED chưa có stage mà runtime của nó không còn worker sống, còn máy này sống và chạy được.

    Job đã có stage không bao giờ được gắn lại ở đây; người dùng xử lý theo `waiting_for="runtime"`.
    """
    if job.status != JobStatus.QUEUED or job.stage_artifacts or job.seed != profile.seed:
        return False
    if profile.accepts_runtime(job.runtime_manifest_checksum):
        return False
    if registry.persistence is None or has_live_runtime(registry.persistence.database, job.runtime_manifest_checksum):
        return False
    try:
        registry.rebind_job_runtime(job, profile.job_runtime_checksum, reason="no_live_worker")
    except RuntimeStateConflictError:
        return False  # Máy khác đã gắn lại trước (CAS); lượt sau đọc revision mới.
    logger.info("Job %s được gắn lại sang runtime của worker đang sống", job.job_id)
    return True


#: Chu kỳ đo lại cấu hình máy; nhỏ hơn TTL của số đo (15 phút) để UI luôn có số mới.
CAPABILITY_INTERVAL_SECONDS = 300
#: Chu kỳ làm mới giữ chỗ của job đang chạy; UI coi job mất tín hiệu sau vài nhịp này (isJobStale).
HEARTBEAT_INTERVAL_SECONDS = 30


def _start_capability_heartbeat(
    registry: ProjectRegistry,
    worker_root: Path,
    admission: ResourceAdmission | None = None,
    publish_runtime: Callable[[RuntimeDatabase], None] | None = None,
) -> Event:
    """Đo và ghi cấu hình máy ngay, rồi lặp ở luồng nền (job dài không làm số đo quá hạn).

    Lượt đo lúc pipeline không dùng máy được ghi làm mốc "máy rảnh" (preset Maximum tính theo
    mốc này); lúc bận thì giữ mốc rảnh gần nhất. Giữ chỗ của job đang chạy được làm mới theo nhịp dày hơn.
    Trả Event để dừng luồng khi worker thoát; lỗi đo được log, không làm dừng worker.
    """
    stop = Event()
    database = registry.persistence.database if registry.persistence is not None else None

    def beat() -> None:
        previous = None
        next_probe = 0.0
        while True:
            # Đo máy nặng hơn nên giữ nhịp 5 phút; giữ chỗ chỉ ghi một dòng nên làm mới dày để UI không báo nhầm.
            if time.monotonic() >= next_probe:
                next_probe = time.monotonic() + CAPABILITY_INTERVAL_SECONDS
                try:
                    if database is not None:
                        idle = admission.machine_idle() if admission is not None else False
                        previous = probe_capability(worker_root, idle=idle, previous=previous)
                        record_capability(database, previous)
                        if publish_runtime is not None:
                            publish_runtime(database)
                        from src.services.orchestration.uploads.temporary import TemporaryUploadService

                        TemporaryUploadService(database, registry.runtime_resolver).purge_expired()
                except Exception as error:  # noqa: BLE001 - luồng nền: lỗi đo/DB không được làm chết heartbeat
                    logger.warning("Không ghi được cấu hình máy worker: %s", type(error).__name__)
            try:
                if database is not None and admission is not None:
                    admission.touch()
            except Exception as error:  # noqa: BLE001 - luồng nền: lỗi DB không được làm chết heartbeat
                logger.warning("Không làm mới được giữ chỗ của job: %s", type(error).__name__)
            if stop.wait(HEARTBEAT_INTERVAL_SECONDS):
                return

    Thread(target=beat, name="capability-heartbeat", daemon=True).start()
    return stop


def parse_lanes(value: str) -> tuple[StepKind, ...] | None:
    """`gpu,cpu` → ("gpu", "cpu"); giá trị lạ, rỗng hoặc lặp trả None."""
    lanes = tuple(item.strip() for item in value.split(",") if item.strip())
    if not lanes or len(set(lanes)) != len(lanes) or any(item not in {"gpu", "cpu"} for item in lanes):
        return None
    return lanes  # type: ignore[return-value]


def _start_reservation_heartbeat(admission: ResourceAdmission) -> Event:
    """Chỉ làm mới giữ chỗ của bước đang chạy (worker làn CPU)."""
    stop = Event()

    def beat() -> None:
        while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                admission.touch()
            except Exception as error:  # noqa: BLE001 - luồng nền: lỗi DB không được làm chết heartbeat
                logger.warning("Không làm mới được giữ chỗ của bước: %s", type(error).__name__)

    Thread(target=beat, name="reservation-heartbeat", daemon=True).start()
    return stop


def main(argv: list[str] | None = None) -> int:
    """Worker cần cùng DB/store/profile với API; không tạo background thread ở HTTP."""
    parser = argparse.ArgumentParser(description="Consume durable prepared RGB jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one eligible job, then exit")
    parser.add_argument("--demo-operation", choices=["pipeline", "registration", "validation", "scene"])
    parser.add_argument("--demo-parent-pid", type=int)
    parser.add_argument(
        "--lanes",
        default=os.environ.get("R2S_WORKER_LANES", ",".join(DEFAULT_LANES)),
        help="Loại bước pipeline worker nhận, theo thứ tự ưu tiên (gpu,cpu | cpu); worker chỉ có `cpu` chỉ nhận bước "
        "CPU của pipeline (T-073)",
    )
    args = parser.parse_args(argv)
    lanes = parse_lanes(args.lanes)
    if lanes is None:
        parser.error("--lanes chỉ nhận gpu và/hoặc cpu, ví dụ gpu,cpu")
    cpu_only = lanes == ("cpu",)
    configure_worker_logging()
    settings = get_settings()
    if args.demo_operation and not settings.product_demo_session_worker:
        parser.error("--demo-operation is restricted to disposable demo workers")
    registry = get_project_registry()
    if registry.execution_profile is None or settings.product_processing_config is None:
        logger.error("Configure PRODUCT_PROCESSING_CONFIG and PRODUCT_RUNTIME_MANIFEST before starting worker")
        return 2
    if is_presets_file(settings.product_processing_config):
        load_presets(settings.product_processing_config)
    else:
        load_prepared_profile(settings.product_processing_config, registry.execution_profile)
    admission = ResourceAdmission(registry, settings)
    import_service = ImportService(
        RuntimeDatabase(settings.database_url),
        runtime_resolver(settings),
        settings.product_worker_root.expanduser().resolve() / "imports",
        max_uncompressed_bytes=settings.product_upload_max_bytes * 2,
    )
    registration_worker = RegistrationOperationWorker(registry, settings, admission)
    validation_worker = IsaacValidationWorker(registry, settings, admission)
    if admission.discard_leftover_reservation():
        logger.warning("Đã xoá giữ chỗ tài nguyên còn sót của lần chạy trước worker=%s", admission.worker_id)
    publish_runtime = (
        publisher(settings.product_processing_config, settings.product_runtime_manifest, registry.execution_profile)
        if settings.product_runtime_manifest is not None
        else None
    )
    # Worker chỉ làn CPU không đo/công bố cấu hình máy (worker GPU cùng máy đã làm), chỉ làm mới giữ chỗ của bước.
    heartbeat = (
        _start_reservation_heartbeat(admission)
        if cpu_only
        else _start_capability_heartbeat(registry, settings.product_worker_root, admission, publish_runtime)
    )
    managed = ManagedWorker(settings, registry.execution_profile)
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Cho runner cleanup subprocess tree trước khi service thoát."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    pause = Event()
    try:
        if args.demo_operation:
            import ctypes

            # Linux PR_SET_PDEATHSIG: a killed dispatcher must not orphan a GPU demo worker.
            if args.demo_parent_pid != os.getppid():
                return 130
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(1, signal.SIGTERM) != 0:
                raise OSError(ctypes.get_errno(), "Cannot bind demo worker to its dispatcher")
            if args.demo_parent_pid != os.getppid():
                return 130
        recover_interrupted_jobs(registry, settings)
        recover_expired_leases(registry)
        recover_unwatched_running_jobs(registry)
        recover_interrupted(settings)
        import_service.recover_legacy_packaging()
        guard = QueueGuard()
        # Quét job RUNNING không lease đọc cả nhật ký sự kiện; trường hợp này cần ≥ một TTL lease mới xuất hiện,
        # nên quét mỗi nửa TTL là đủ (lần khởi động đã quét ở trên).
        lod_builder = None if cpu_only else idle_lod_builder(registry, settings.product_worker_root)
        lod_sweep = Periodic(60.0)
        unwatched_sweep = Periodic(LEASE_TTL.total_seconds() / 2)
        unwatched_sweep.due(time.monotonic())
        while True:
            guard.run("recover_leases", lambda: bool(recover_expired_leases(registry)))
            if unwatched_sweep.due(time.monotonic()):
                guard.run("recover_unwatched", lambda: bool(recover_unwatched_running_jobs(registry)))
            # Job trong hàng đợi đi trước; rảnh mới nhận yêu cầu chạy lại tách theo vật (cùng dùng GPU).
            # Mỗi hàng đợi đi qua `guard`: một hàng lỗi (DB chập chờn, bản ghi hỏng) không làm worker thoát.
            handled = False
            with managed.operation() as allowed:
                if allowed:
                    if cpu_only:
                        handled = guard.run(
                            "pipeline-cpu",
                            lambda: supports("pipeline") and dispatch_next(registry, admission=admission, lanes=lanes),
                        )
                    elif args.demo_operation:
                        handled = guard.run(
                            args.demo_operation,
                            {
                                "pipeline": lambda: dispatch_next(registry, admission=admission, lanes=lanes),
                                "registration": registration_worker.process_next,
                                "validation": validation_worker.process_next,
                                "scene": lambda: process_next(registry, settings),
                            }[args.demo_operation],
                        )
                    else:
                        handled = poll_queues(
                            guard,
                            [
                                (
                                    "pipeline",
                                    lambda: (
                                        supports("pipeline")
                                        and dispatch_next(registry, admission=admission, lanes=lanes)
                                    ),
                                ),
                                (
                                    "registration",
                                    lambda: supports("registration") and registration_worker.process_next(),
                                ),
                                ("validation", lambda: supports("validation") and validation_worker.process_next()),
                                ("scene", lambda: supports("scene") and process_next(registry, settings)),
                                (
                                    "import",
                                    lambda: supports("import") and import_service.process_next(admission=admission),
                                ),
                                ("demo", lambda: process_demo_session(settings, registry, admission)),
                            ],
                        )
                        # T-070: rảnh thì tạo bộ LOD cho một SOG lớn còn thiếu (chỉ worker có GPU).
                        if not handled and lod_builder is not None and lod_sweep.due(time.monotonic()):
                            handled = guard.run("lod", lod_builder.tick)
            if not handled:
                admission.release()
            if args.once:
                return 0
            if not handled:
                pause.wait(max(settings.product_queue_poll_seconds, guard.backoff_seconds()))
    except KeyboardInterrupt:
        return 130
    finally:
        heartbeat.set()
        managed.close()
        admission.release()
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
