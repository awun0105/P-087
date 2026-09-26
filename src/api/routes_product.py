"""Endpoint product: project, job và artifact (mock-first).

Router này được `routes.py` include vào, không gắn ở `main.py` — `main.py` không
thuộc ownership của EX-PRODUCT. Mọi handler ở đây là `def` đồng bộ vì
`FilesystemArtifactStore` là code đồng bộ; FastAPI sẽ chạy chúng trong threadpool
nên không chặn event loop.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import ValidationError

from src.api import schemas
from src.models.contracts.artifacts import ArtifactRef, Checksum
from src.models.contracts.manifests import JobManifest, JobStatus
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.jobs import (
    InvalidTransitionError,
    JobLifecycleError,
    JobNotResolvableError,
    TransitionRequest,
)
from src.services.orchestration.projects import (
    JobCreateInput,
    JobNotFoundError,
    PrivacyGateBlockedError,
    ProjectCreateInput,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectRegistry,
    get_project_registry,
)
from src.services.orchestration.scene import (
    SceneEditCommand,
    SceneError,
    SceneRevisionConflictError,
)

router = APIRouter(tags=["product"])


def _registry() -> ProjectRegistry:
    """Registry dùng chung; fixture chỉ được nạp một lần."""
    return get_project_registry()


def _project_or_404(project_id: str) -> ProjectRecord:
    try:
        return _registry().get_project(project_id)
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/projects", response_model=schemas.ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(request: ProjectCreateInput) -> schemas.ProjectResponse:
    """Tạo project và ghi nhận source-rights attestation.

    Input mới luôn vào ở mức sàng lọc sơ bộ: chưa có `ST-PRIVACY-GATE` thật chạy,
    nên project chưa được phép dispatch job.
    """
    return schemas.project_response(_registry().create_project(request))


@router.get("/projects", response_model=schemas.ProjectListResponse)
def list_projects() -> schemas.ProjectListResponse:
    """Danh sách project kèm privacy state."""
    return schemas.ProjectListResponse(
        projects=[schemas.project_response(record) for record in _registry().list_projects()]
    )


@router.get("/projects/{project_id}", response_model=schemas.ProjectResponse)
def get_project(project_id: str) -> schemas.ProjectResponse:
    """Chi tiết một project."""
    return schemas.project_response(_project_or_404(project_id))


@router.get("/projects/{project_id}/privacy", response_model=schemas.PrivacyStateResponse)
def get_project_privacy(project_id: str) -> schemas.PrivacyStateResponse:
    """Privacy state riêng cho PRODUCT-02/PRODUCT-05."""
    return schemas.privacy_state(_project_or_404(project_id).privacy_report)


@router.post(
    "/projects/{project_id}/jobs",
    response_model=JobManifest,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": schemas.ApiErrorResponse}},
)
def create_job(project_id: str, request: schemas.JobCreateRequest) -> JobManifest:
    """Tạo job cho một project. Bị chặn nếu privacy gate chưa cho input đi qua.

    `project_id` lấy từ path; body không được ghi đè project.
    """
    registry = _registry()
    try:
        return registry.create_job(JobCreateInput(project_id=project_id, scene_revision=request.scene_revision))
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PrivacyGateBlockedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/projects/{project_id}/jobs", response_model=schemas.JobListResponse)
def list_jobs(project_id: str) -> schemas.JobListResponse:
    """Job của một project."""
    try:
        jobs = _registry().list_jobs(project_id)
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.JobListResponse(project_id=project_id, jobs=jobs)


@router.get("/jobs/{job_id}", response_model=JobManifest)
def get_job(job_id: str) -> JobManifest:
    """JobManifest đầy đủ: status, stage và artifact đã publish."""
    try:
        return _registry().get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/jobs/{job_id}/artifacts", response_model=schemas.ArtifactListResponse)
def list_job_artifacts(job_id: str) -> schemas.ArtifactListResponse:
    """Artifact product được phép thấy.

    Ref lấy từ `data_class` có type trong JobManifest, không phải từ việc liệt kê
    thư mục — nên `ground_truth`/`evaluation_only` không thể lọt ra ngoài.
    """
    try:
        visible, excluded = _registry().list_job_artifacts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.ArtifactListResponse(job_id=job_id, artifacts=visible, excluded_artifact_count=excluded)


@router.post(
    "/jobs/{job_id}/transitions",
    response_model=JobManifest,
    responses={409: {"model": schemas.ApiErrorResponse}, 422: {"model": schemas.ApiErrorResponse}},
)
def transition_job(job_id: str, request: TransitionRequest) -> JobManifest:
    """Chuyển trạng thái job theo bảng chuyển hợp lệ (PRODUCT-02).

    Đây là affordance **mock-worker**: trong P0 chưa có worker thật nên client
    đóng vai người báo tiến độ. Worker thật (PRODUCT-08) sẽ gọi cùng đường này.
    """
    try:
        return _registry().transition_job(job_id, request)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidTransitionError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except JobNotResolvableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/jobs/{job_id}/retry", response_model=JobManifest)
def retry_job(job_id: str) -> JobManifest:
    """Chạy lại một job FAILED. Attempt mới được nối thêm, không ghi đè attempt cũ."""
    try:
        return _registry().transition_job(job_id, TransitionRequest(target_status=JobStatus.QUEUED))
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except JobLifecycleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get("/jobs/{job_id}/attempts", response_model=schemas.JobAttemptListResponse)
def list_job_attempts(job_id: str) -> schemas.JobAttemptListResponse:
    """Lịch sử attempt của job, cũ nhất trước."""
    try:
        attempts = _registry().list_job_attempts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.JobAttemptListResponse(job_id=job_id, attempts=attempts)


# ── PRODUCT-06: scene revision cho viewer ────────────────────────────────────


def _job_or_404(job_id: str) -> JobManifest:
    try:
        return _registry().get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/jobs/{job_id}/scene", response_model=schemas.SceneResponse)
def get_job_scene(job_id: str) -> schemas.SceneResponse:
    """SceneIR hiện tại của job, kèm ref và trạng thái visual.

    `visual.brush_compatibility_proof` đi kèm payload vì fixture hiện chỉ có
    visual tổng hợp — thiếu cờ này thì viewer rất dễ bị đọc thành AC-11.
    """
    _job_or_404(job_id)
    editor = _registry().scene
    return schemas.scene_response(editor.current(job_id), editor.visual_binding())


@router.post(
    "/jobs/{job_id}/scene/edits",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}},
)
def edit_job_scene(job_id: str, command: SceneEditCommand) -> schemas.SceneEditResponse:
    """Áp transform edit và persist thành revision mới (PRODUCT-06).

    `expected_scene_revision` là khoá optimistic: client sửa trên revision đã cũ
    sẽ bị 409 chứ không ghi đè thay đổi của người khác.

    `ArtifactStoreError` map sang 409 theo đúng precedent của `/validation` và
    `/review`: nó nổi lên khi bytes của một revision đã niêm phong không còn khớp
    ref, tức là xung đột bất biến artifact — không phải lỗi command của client.
    """
    _job_or_404(job_id)
    try:
        return schemas.scene_edit_response(_registry().scene.apply(job_id, command))
    except SceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get("/jobs/{job_id}/validation", response_model=schemas.ValidationStateResponse)
def get_job_validation(job_id: str) -> schemas.ValidationStateResponse:
    """Báo cáo validation của job, kèm cờ nói rõ Isaac đã chạy thật hay chưa."""
    _job_or_404(job_id)
    try:
        return schemas.validation_state(job_id, _registry().get_validation_report(job_id))
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/jobs/{job_id}/review", response_model=schemas.ReviewStateResponse)
def get_job_review(job_id: str) -> schemas.ReviewStateResponse:
    """Trạng thái review của job. Approval ở đây là bản synthetic của fixture."""
    _job_or_404(job_id)
    try:
        return schemas.review_state(job_id, _registry().get_approval_record(job_id))
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/jobs/{job_id}/artifacts/content")
def get_artifact_content(
    job_id: str,
    artifact_uri: str = Query(..., min_length=1),
    artifact_checksum: Checksum = Query(...),
) -> Response:
    """Trả bytes của một artifact **đã nằm trong allow-list của job**.

    URI không được tự do: registry đối chiếu với danh sách product-visible của
    chính job rồi mới resolve và verify checksum byte. Nhờ vậy
    `evaluation_only/`/`ground_truth` cùng thư mục không gọi tới được, và không
    có tham số đường dẫn nào đi qua API.
    """
    _job_or_404(job_id)
    try:
        reference = ArtifactRef(
            artifact_type="ArtifactContent",
            schema_version="1.0",
            artifact_uri=artifact_uri,
            artifact_checksum=artifact_checksum,
            data_class="derived",
            producer_stage="ST-EDIT",
            job_id=job_id,
        )
        payload = _registry().read_artifact_bytes(job_id, reference)
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(content=payload, media_type="application/octet-stream")


# ── PRODUCT-07: object actions (fake stub) ───────────────────────────────────


@router.post(
    "/jobs/{job_id}/scene/objects/{object_id}/{action}",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def object_action(
    job_id: str,
    object_id: str,
    action: str,
    request: schemas.ObjectActionRequest,
) -> schemas.SceneEditResponse:
    """Fake stub cho các object action: confirm/ignore/hide/delete/rename.

    Thực tế sẽ gọi SCENE Core operations (SCENE-05/08). Hiện tại trả về revision
    mới bằng cách áp một transform edit rỗng để tạo revision mới — client thấy
    UI cập nhật. Object id không tồn tại → 422.
    """
    _job_or_404(job_id)
    editor = _registry().scene
    current = editor.current(job_id)
    if current.scene.scene_revision != request.expected_scene_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scene đã đổi: client đang giữ {request.expected_scene_revision}, revision hiện tại là {current.scene.scene_revision}",
        )
    if object_id not in {obj.id for obj in current.scene.objects}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"object {object_id} không tồn tại trong revision",
        )
    if action not in {"confirm", "ignore", "hide", "delete", "rename"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action {action} không được hỗ trợ",
        )
    try:
        # Tạo revision mới bằng edit rỗng để client thấy revision bump.
        return schemas.scene_edit_response(
            editor.apply(job_id, SceneEditCommand(expected_scene_revision=request.expected_scene_revision, edits=[]))
        )
    except SceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/scene/objects",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def add_object(
    job_id: str,
    request: schemas.AddObjectRequest,
) -> schemas.SceneEditResponse:
    """Fake stub cho add obstacle (PRODUCT-07A).

    Khi SCENE-08A implement, endpoint này sẽ delegate xuống domain add-object.
    Hiện tại tạo revision mới bằng edit rỗng để client thấy revision bump.
    """
    _job_or_404(job_id)
    editor = _registry().scene
    current = editor.current(job_id)
    if current.scene.scene_revision != request.expected_scene_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scene đã đổi: client đang giữ {request.expected_scene_revision}, revision hiện tại là {current.scene.scene_revision}",
        )
    try:
        return schemas.scene_edit_response(
            editor.apply(job_id, SceneEditCommand(expected_scene_revision=request.expected_scene_revision, edits=[]))
        )
    except SceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


# ── PRODUCT-10/11: review & release (fake stub) ──────────────────────────────


@router.post(
    "/jobs/{job_id}/review/{action}",
    response_model=schemas.ReviewStateResponse,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def review_action(
    job_id: str,
    action: str,
    request: schemas.ReviewActionRequest,
) -> schemas.ReviewStateResponse:
    """Fake stub cho submit/approve/reject review.

    Khi PRODUCT-10 backend implement, endpoint này sẽ delegate xuống review
    lifecycle service. Hiện tại trả về state fixture với decision tương ứng.
    """
    _job_or_404(job_id)
    if action not in {"submit", "approve", "reject"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action review {action} không được hỗ trợ",
        )
    if action == "reject" and not request.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="lý do từ chối không được để trống",
        )
    try:
        approval = _registry().get_approval_record(job_id)
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    decision = "APPROVE" if action in {"submit", "approve"} else "REJECT"
    approval = approval.model_copy(
        update={
            "decision": decision,
            "reason": request.reason,
            "reviewer_id": request.reviewer_id,
            "decided_at": datetime.now(UTC).isoformat(),
        }
    )
    return schemas.review_state(job_id, approval)


@router.post(
    "/jobs/{job_id}/release",
    response_model=schemas.ReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def release_candidate(
    job_id: str,
    request: schemas.ReleaseRequest,
) -> schemas.ReleaseResponse:
    """Fake stub seal exact candidate → ReleaseManifest (PRODUCT-11).

    Khi PRODUCT-11 backend implement, endpoint này sẽ verify approval record,
    candidate checksum và validation report checksum rồi tạo ReleaseManifest.
    """
    _job_or_404(job_id)
    try:
        approval = _registry().get_approval_record(job_id)
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    if approval.decision != "APPROVE":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="chỉ được release khi review đã APPROVE",
        )
    if request.approval_record_checksum != approval.record_checksum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="approval record checksum không khớp",
        )
    if request.candidate_checksum != approval.candidate_checksum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="candidate checksum không khớp approval record",
        )
    if request.validation_report_checksum != approval.validation_report_checksum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="validation report checksum không khớp approval record",
        )

    return schemas.ReleaseResponse(
        release_id=f"rel-{job_id}",
        release_checksum=f"sha256:{'0' * 64}",
        released_at=datetime.now(UTC).isoformat(),
    )
