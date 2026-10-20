"""Ghép một danh sách bước thật, từ đầu tới khi scene dùng được (T-059).

Chỉ ghép dữ liệu đã có: tiến trình job (`JobProgress`), mốc bước đã ghi (`r2s_step_marks`), trạng thái hàng đợi tách vật
và trạng thái hình học của scene. Không tự tính lại quy tắc của nơi khác. Job / scene cũ không có mốc vẫn có danh sách
đủ, với thời gian suy luận như trước (`timing_source="inferred"`).
"""

from collections.abc import Sequence
from datetime import datetime

from src.models.contracts.manifests import ExecutionError, JobManifest, JobStatus, StageId
from src.services.orchestration.jobs.progress import (
    JobProgress,
    StageProgress,
    anonymization_acceptance_stage,
    sanitized_frame_stage,
)
from src.services.orchestration.jobs.step_marks import StepMark
from src.services.orchestration.pipeline.models import PipelineStep, PipelineWait, StepState
from src.services.orchestration.scene.objectify_queue import ObjectifyState
from src.services.scene.geometry_state import ObjectGeometryState

_USER_STEPS = frozenset({StageId.ANONYMIZATION_REVIEW, StageId.METRIC_CANONICALIZE, StageId.OBJECT_CONFIRM})
_ACTIVE = frozenset({"queued", "running"})
_BUILD_MODES = frozenset({"geometry", "region", "membership"})


def _pipeline_mark(marks: Sequence[StepMark], step: StageId, attempt: int, *, reused: bool = True) -> StepMark | None:
    """Mốc của lượt hiện tại; bước có kết quả tái dùng (`reused`) lấy mốc của lượt gần nhất trước đó.

    Bước chưa chạy / đang chạy / lỗi ở lượt này chỉ dùng mốc của chính lượt này: mốc lượt cũ (vd. lượt lỗi trước khi
    chạy lại) không được hiện như thời gian của bước chưa bắt đầu.
    """
    candidates = [mark for mark in marks if mark.run_kind == "pipeline" and mark.step_id == step.value]
    for run in sorted({int(mark.run_id) for mark in candidates if mark.run_id.isdigit()}, reverse=True):
        if run > attempt or (run != attempt and not reused):
            continue
        found = next(mark for mark in candidates if mark.run_id == str(run))
        if found.started_at is not None or found.completed_at is not None:
            return found
    return None


def _timed(
    step: PipelineStep, mark: StepMark | None, started: datetime | None, completed: datetime | None
) -> PipelineStep:
    if mark is not None:
        return step.model_copy(
            update={"started_at": mark.started_at, "completed_at": mark.completed_at, "timing_source": "recorded"}
        )
    if started is not None or completed is not None:
        return step.model_copy(update={"started_at": started, "completed_at": completed, "timing_source": "inferred"})
    return step


def _job_step(stage: StageProgress, progress: JobProgress) -> PipelineStep:
    actor = "user" if stage.stage_id in _USER_STEPS else "system"
    state: StepState = stage.state
    if (
        actor == "system"
        and stage.stage_id == progress.current_stage
        and stage.state in {"running", "pending"}
        and (progress.status == JobStatus.QUEUED or progress.waiting_for in {"resources", "runtime"})
    ):
        state = "queued"
    return PipelineStep(step_id=stage.stage_id, actor=actor, state=state, error=stage.error, note=stage.note)


def _anonymization_step(progress: JobProgress, job: JobManifest, marks: Sequence[StepMark]) -> PipelineStep:
    accepted = anonymization_acceptance_stage(job)
    state: StepState = (
        "waiting"
        if progress.waiting_for == "anonymization_review"
        else "succeeded"
        if accepted is not None
        else "pending"
    )
    step = PipelineStep(step_id=StageId.ANONYMIZATION_REVIEW, actor="user", state=state)
    frames = sanitized_frame_stage(job)
    return _timed(
        step,
        _pipeline_mark(marks, StageId.ANONYMIZATION_REVIEW, progress.attempt, reused=state == "succeeded"),
        frames.completed_at if frames is not None else None,
        accepted.completed_at if accepted is not None else None,
    )


def _operation_marks(marks: Sequence[StepMark], prefix: str, step: str) -> list[StepMark]:
    return [
        mark
        for mark in marks
        if mark.run_kind == "scene_operation" and mark.run_id.startswith(prefix) and mark.step_id == step
    ]


def _geometry_steps(
    extract: PipelineStep, objectify: ObjectifyState | None, geometry: ObjectGeometryState, marks: Sequence[StepMark]
) -> list[PipelineStep]:
    building = objectify is not None and objectify.mode == "geometry" and objectify.status in _ACTIVE
    confirm_state: StepState = "succeeded" if geometry == "ready" or building else "waiting"
    queued = [mark.started_at for mark in _operation_marks(marks, "geometry:", "queue") if mark.started_at is not None]
    confirm = PipelineStep(step_id=StageId.OBJECT_CONFIRM, actor="user", state=confirm_state)
    if queued:
        confirm = confirm.model_copy(
            update={"started_at": extract.completed_at, "completed_at": min(queued), "timing_source": "recorded"}
        )
    elif extract.completed_at is not None:
        ended = objectify.requested_at if building and objectify is not None else None
        confirm = confirm.model_copy(
            update={"started_at": extract.completed_at, "completed_at": ended, "timing_source": "inferred"}
        )

    build_state: StepState = "pending"
    error = None
    phase = None
    if building and objectify is not None:
        build_state = "running" if objectify.status == "running" else "queued"
        phase = objectify.phase
    elif geometry == "ready":
        build_state = "succeeded"
    elif (
        objectify is not None
        and objectify.mode == "geometry"
        and objectify.status in {"failed", "cancelled"}
        and objectify.base_revision == objectify.scene_revision
    ):
        build_state = "failed"
        error = ExecutionError(
            error_code="OBJECT_GEOMETRY_BUILD_FAILED",
            stage_id=StageId.SCENE_DECOMPOSE,
            human_message=objectify.error or "Tạo mesh chưa xong.",
            retryable=bool(objectify.retryable),
        )
    build = PipelineStep(step_id=StageId.SCENE_DECOMPOSE, actor="system", state=build_state, phase=phase, error=error)
    runs = [mark for mark in _operation_marks(marks, "geometry:", "operation") if mark.outcome == "succeeded"]
    if runs:
        latest = max(runs, key=lambda mark: mark.completed_at or mark.started_at or datetime.min)
        build = build.model_copy(
            update={"started_at": latest.started_at, "completed_at": latest.completed_at, "timing_source": "recorded"}
        )
    elif building and objectify is not None:
        build = build.model_copy(update={"started_at": objectify.started_at, "timing_source": "inferred"})
    return [confirm, build]


def compose_steps(
    progress: JobProgress,
    job: JobManifest,
    marks: Sequence[StepMark],
    objectify: ObjectifyState | None,
    geometry: ObjectGeometryState | None,
) -> list[PipelineStep]:
    """Danh sách bước theo thứ tự thật; hàm thuần."""
    steps: list[PipelineStep] = []
    for stage in progress.stages:
        step = _timed(
            _job_step(stage, progress),
            _pipeline_mark(marks, stage.stage_id, progress.attempt, reused=stage.state in {"succeeded", "skipped"}),
            stage.started_at,
            stage.completed_at,
        )
        if stage.stage_id == StageId.METRIC_CANONICALIZE:
            step = step.model_copy(update={"actor": "user"})
        steps.append(step)
        if stage.stage_id == StageId.FRAME_EXTRACT and sanitized_frame_stage(job) is not None:
            steps.append(_anonymization_step(progress, job, marks))

    extract_index = next((index for index, step in enumerate(steps) if step.step_id == StageId.OBJECT_EXTRACT), None)
    if extract_index is None or objectify is None:
        return _with_view_lod(steps, marks, progress.attempt)
    extract = steps[extract_index]
    if objectify.status in _ACTIVE and objectify.mode in {"objectify", "boxes"}:
        extract = extract.model_copy(
            update={"state": "running" if objectify.status == "running" else "queued", "phase": objectify.phase}
        )
    elif objectify.awaiting_choice:
        extract = extract.model_copy(
            update={
                "state": "failed",
                "error": ExecutionError(
                    error_code="OBJECTIFY_AWAITING_CHOICE",
                    stage_id=StageId.OBJECT_EXTRACT,
                    human_message="Tách theo vật chưa thành công sau các lần thử. Chạy lại tách theo vật hoặc dùng hộp ứng viên.",
                    retryable=bool(objectify.retryable),
                ),
            }
        )
    steps[extract_index] = extract
    if geometry is not None and steps[extract_index].state == "succeeded":
        steps.extend(_geometry_steps(extract, objectify, geometry, marks))
    return _with_view_lod(steps, marks, progress.attempt)


def _with_view_lod(steps: list[PipelineStep], marks: Sequence[StepMark], attempt: int) -> list[PipelineStep]:
    """T-070: bước tạo bộ LOD của lượt hiện tại, ngay sau Tách vật; lỗi hiện là bỏ qua (scene vẫn xem bằng SOG gốc)."""
    mark = next(
        (
            item
            for item in marks
            if item.run_kind == "pipeline" and item.step_id == StageId.VIEW_LOD.value and item.run_id == str(attempt)
        ),
        None,
    )
    if mark is None or mark.started_at is None:
        return steps
    state: StepState = (
        "running" if mark.completed_at is None else "succeeded" if mark.outcome == "succeeded" else "skipped"
    )
    step = PipelineStep(
        step_id=StageId.VIEW_LOD,
        actor="system",
        state=state,
        started_at=mark.started_at,
        completed_at=mark.completed_at,
        timing_source="recorded",
        note="Không tạo được; scene mở bằng bản gốc." if state == "skipped" else None,
    )
    after = next((index for index, item in enumerate(steps) if item.step_id == StageId.OBJECT_EXTRACT), None)
    index = len(steps) if after is None else after + 1
    return [*steps[:index], step, *steps[index:]]


def current_step(steps: Sequence[PipelineStep]) -> StageId | None:
    """Bước đầu tiên đang cần chú ý (đang chạy, chờ máy, chờ người hoặc lỗi).

    Bước tạo bộ LOD chạy sau khi scene đã xem được nên chỉ là bước hiện tại khi không còn bước nào khác cần chú ý.
    """
    attention = {"running", "queued", "waiting", "failed"}
    found = next((step.step_id for step in steps if step.state in attention and step.step_id != StageId.VIEW_LOD), None)
    if found is not None:
        return found
    return next((step.step_id for step in steps if step.state in attention), None)


def is_usable(job_status: JobStatus, geometry: ObjectGeometryState | None, awaiting_choice: bool) -> bool:
    """Scene dùng được: job xong, hình học theo vật sẵn sàng (hoặc scene cũ không có bước này), không chờ chọn."""
    return job_status == JobStatus.SUCCEEDED and geometry in {None, "ready"} and not awaiting_choice


def scene_operation_wait(objectify: ObjectifyState | None, geometry: ObjectGeometryState | None) -> PipelineWait | None:
    """Dựng lại vùng / membership trên scene đã dùng được: bước Tạo mesh giữ `succeeded`, việc nền hiện ở `wait`."""
    if objectify is None or objectify.status not in _ACTIVE or objectify.mode not in _BUILD_MODES:
        return None
    if geometry != "ready":
        return None
    return PipelineWait(
        kind="scene_operation", step_id=StageId.SCENE_DECOMPOSE, since=objectify.started_at or objectify.requested_at
    )
