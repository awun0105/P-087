"""Lọc thông tin nhạy cảm của ExecutionError theo vai trò người dùng."""

from src.models.contracts.manifests import ExecutionError, JobManifest, StageArtifact
from src.services.orchestration.auth import UserRecord, has_role
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.progress import JobProgress, StageProgress


def visible_error(error: ExecutionError | None, user: UserRecord | None) -> ExecutionError | None:
    """Che log_excerpt đối với người dùng không phải reviewer khi auth được bật."""
    if error is None:
        return None
    if user is None:
        return error
    if has_role(user, "reviewer"):
        return error
    if not error.details or "log_excerpt" not in error.details:
        return error
    sanitized_details = {k: v for k, v in error.details.items() if k != "log_excerpt"}
    return error.model_copy(update={"details": sanitized_details})


def filter_stage_artifact_errors(stage: StageArtifact, user: UserRecord | None) -> StageArtifact:
    """Áp dụng visible_error lên StageArtifact."""
    if stage.error is None:
        return stage
    filtered_error = visible_error(stage.error, user)
    if filtered_error is stage.error:
        return stage
    return stage.model_copy(update={"error": filtered_error})


def filter_manifest_errors(manifest: JobManifest, user: UserRecord | None) -> JobManifest:
    """Áp dụng visible_error lên mọi stage_artifacts của JobManifest."""
    stages = [filter_stage_artifact_errors(s, user) for s in manifest.stage_artifacts]
    return manifest.model_copy(update={"stage_artifacts": stages})


def filter_stage_progress_errors(stage: StageProgress, user: UserRecord | None) -> StageProgress:
    """Áp dụng visible_error lên StageProgress."""
    if stage.error is None:
        return stage
    filtered_error = visible_error(stage.error, user)
    if filtered_error is stage.error:
        return stage
    return stage.model_copy(update={"error": filtered_error})


def filter_job_progress_errors(progress: JobProgress, user: UserRecord | None) -> JobProgress:
    """Áp dụng visible_error lên lỗi cấp job và từng stage của JobProgress."""
    job_err = visible_error(progress.error, user)
    stages = [filter_stage_progress_errors(s, user) for s in progress.stages]
    return progress.model_copy(update={"error": job_err, "stages": stages})


def filter_job_attempt_errors(attempt: JobAttemptRecord, user: UserRecord | None) -> JobAttemptRecord:
    """Áp dụng visible_error lên JobAttemptRecord."""
    if attempt.error is None:
        return attempt
    filtered_error = visible_error(attempt.error, user)
    if filtered_error is attempt.error:
        return attempt
    return attempt.model_copy(update={"error": filtered_error})
