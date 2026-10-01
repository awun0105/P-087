"""Endpoint product: project, job và artifact (mock-first).

Router này được `routes.py` include vào, không gắn ở `main.py` — `main.py` không
thuộc ownership của EX-PRODUCT. Mọi handler ở đây là `def` đồng bộ vì
`FilesystemArtifactStore` là code đồng bộ; FastAPI sẽ chạy chúng trong threadpool
nên không chặn event loop.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError

from src.api import schemas
from src.api.auth import enforce_gpu_quota, record_gpu_run, require_editor, require_reviewer
from src.config import get_settings
from src.models.contracts.artifacts import ArtifactRef, Checksum
from src.models.contracts.manifests import JobManifest, JobStatus
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration import scene_objectify_queue
from src.services.orchestration.artifacts import ArtifactNotFoundError, ArtifactStoreError
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.jobs import (
    InvalidTransitionError,
    JobLifecycleError,
    JobNotResolvableError,
    TransitionRequest,
)
from src.services.orchestration.jobs.database import RuntimeStateConflictError
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
    SceneEditor,
    SceneEditResult,
    SceneError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.catalog import load_catalog, suggest_classes
from src.services.orchestration.scene.errors import SceneNotAvailableError
from src.services.orchestration.scene.objects import (
    OBJECT_ACTIONS,
    add_box_object,
    add_catalog_object,
    apply_object_action,
    restore_revision,
)
from src.services.orchestration.scene_objectify_queue import ObjectifyRequestError, ObjectifyState

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
    return schemas.privacy_state(_project_or_404(project_id))


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
    except (PrivacyGateBlockedError, RuntimeStateConflictError) as error:
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

    Runtime HTTP chỉ nhận cancel; progress do worker ghi qua durable registry.
    Constructor registry không DB là test seam cũ, không phải runtime API mode.
    """
    try:
        registry = _registry()
        if registry.persistence is not None and (
            request.target_status != JobStatus.CANCELLED
            or request.current_stage is not None
            or request.error is not None
        ):
            raise HTTPException(
                status_code=409, detail="Runtime progress do worker sở hữu; dùng cancel/retry, không tự báo SUCCESS"
            )
        return registry.transition_job(job_id, request)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidTransitionError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except (JobNotResolvableError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/jobs/{job_id}/retry", response_model=JobManifest)
def retry_job(job_id: str, user: UserRecord | None = Depends(require_editor)) -> JobManifest:
    """Chạy lại một job FAILED. Attempt mới được nối thêm, không ghi đè attempt cũ.

    Mỗi lần thử lại là một lần xử lý GPU nên tính vào hạn mức của Editor.
    """
    enforce_gpu_quota(user)
    try:
        job = _registry().transition_job(job_id, TransitionRequest(target_status=JobStatus.QUEUED))
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except JobLifecycleError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except (RuntimeStateConflictError, PrivacyGateBlockedError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_gpu_run(user, job_id, {"kind": "job.retry"})
    return job


@router.get("/jobs/{job_id}/attempts", response_model=schemas.JobAttemptListResponse)
def list_job_attempts(job_id: str) -> schemas.JobAttemptListResponse:
    """Lịch sử attempt của job, cũ nhất trước."""
    try:
        attempts = _registry().list_job_attempts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.JobAttemptListResponse(job_id=job_id, attempts=attempts)


# ── PRODUCT-06: scene revision cho viewer ────────────────────────────────────


@router.get("/jobs/{job_id}/preview", response_model=ReconstructionPreview)
def get_job_preview(job_id: str) -> ReconstructionPreview:
    """Không cần SceneIR; chỉ trả preview trong journal của đúng job."""
    try:
        return _registry().get_preview(job_id)
    except (JobNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ArtifactStoreError, ValueError) as error:
        raise HTTPException(status_code=409, detail="Preview identity/schema/checksum không hợp lệ") from error


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
    try:
        return schemas.scene_response(editor.current(job_id), editor.visual_binding(job_id))
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ArtifactStoreError, SceneError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
        registry = _registry()
        # Có kho file: trình duyệt tải thẳng từ R2 bằng link có hạn (ADR 0003), API không
        # cõng file lớn qua băng thông tính phí. Quyền đọc vẫn kiểm theo allow-list ở trên.
        link = registry.presigned_artifact_url(job_id, reference, get_settings().artifact_presign_seconds)
        if link is not None:
            return RedirectResponse(link, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        path = registry.resolve_artifact(job_id, reference)
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    # FileResponse stream/range: không copy toàn bộ SOG/video lớn vào RAM của API.
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/jobs/{job_id}/artifacts/content/{filename}")
def get_named_artifact_content(
    job_id: str,
    filename: str,
    artifact_uri: str = Query(..., min_length=1),
    artifact_checksum: Checksum = Query(...),
) -> Response:
    """Tên file dùng chọn parser; quyền đọc vẫn bind URI/checksum canonical."""
    if filename != artifact_uri.rsplit("/", 1)[-1]:
        raise HTTPException(status_code=404, detail="artifact filename does not match its reference")
    return get_artifact_content(job_id, artifact_uri, artifact_checksum)


# ── PRODUCT-07: object actions ───────────────────────────────────────────────


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
    """confirm/ignore ứng viên, hide/delete/rename vật thể — lệnh domain EX-SCENE, revision mới."""
    _job_or_404(job_id)
    if action not in OBJECT_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action {action} không được hỗ trợ",
        )
    return _scene_mutation(
        lambda editor: apply_object_action(
            editor,
            job_id,
            object_id,
            action,  # type: ignore[arg-type] - đã kiểm trong OBJECT_ACTIONS
            request.expected_scene_revision,
            active=request.active,
            name=request.name,
            semantic_class=request.semantic_class,
            mass_kg=request.mass_kg,
            asset_family=request.asset_family,
        )
    )


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
    """Thêm vật cản hộp do người dùng đặt (PRODUCT-07A); `position_xyz` là tâm hộp (mét, world)."""
    _job_or_404(job_id)
    if request.collider_type != "AABB" or request.origin != "user_added":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="chỉ hỗ trợ vật cản hộp (AABB) do người dùng thêm",
        )
    return _scene_mutation(
        lambda editor: add_box_object(
            editor,
            job_id,
            request.expected_scene_revision,
            request.name,
            request.dimensions_xyz_m,
            request.position_xyz,
        )
    )


@router.get("/scene/catalog", response_model=schemas.SceneCatalogResponse)
def get_scene_catalog() -> schemas.SceneCatalogResponse:
    """Danh mục nhãn + asset Isaac đặt được (ADR 0007); giá trị vật lý là mặc định tham khảo."""
    catalog = load_catalog()
    return schemas.SceneCatalogResponse(
        classes=catalog.classes(),
        entries=[
            schemas.CatalogEntryResponse(
                family=entry.family,
                semantic_class=entry.semantic_class,
                size_xyz_m=entry.size_xyz_m,
                dynamic=bool(entry.physics.get("dynamic", True)),
                default_mass_kg=entry.physics.get("mass_kg"),
            )
            for entry in catalog.placeable()
        ],
        physics_note=catalog.physics_note,
    )


@router.get(
    "/jobs/{job_id}/scene/objectify",
    response_model=ObjectifyState,
    responses={404: {"model": schemas.ApiErrorResponse}},
)
def get_objectify_state(job_id: str) -> ObjectifyState:
    """Scene đang là scene theo vật hay đường hộp, và yêu cầu chạy lại gần nhất đang ở đâu."""
    _job_or_404(job_id)
    try:
        return scene_objectify_queue.state(_registry(), get_settings(), job_id)
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/scene/objectify",
    response_model=ObjectifyState,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}},
)
def request_objectify(
    job_id: str, request: schemas.ObjectifyRequest, user: UserRecord | None = Depends(require_editor)
) -> ObjectifyState:
    """Xếp hàng chạy lại tách theo vật (hoặc dùng hộp ứng viên); worker thực hiện, ghi revision SceneIR kế tiếp.

    Tập vật mới là ứng viên mới: xác nhận/nhãn của revision hiện tại không mang sang (vẫn hoàn tác được).
    Đây là một lần xử lý GPU nên tính vào hạn mức của Editor.
    """
    _job_or_404(job_id)
    enforce_gpu_quota(user)
    try:
        result = scene_objectify_queue.request(
            _registry(), get_settings(), job_id, request.expected_scene_revision, request.mode
        )
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ObjectifyRequestError, SceneRevisionConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    record_gpu_run(user, job_id, {"kind": f"scene.{request.mode}"})
    return result


@router.get(
    "/jobs/{job_id}/scene/objects/{object_id}/label-suggestions",
    response_model=schemas.LabelSuggestionResponse,
    responses={404: {"model": schemas.ApiErrorResponse}},
)
def get_label_suggestions(job_id: str, object_id: str) -> schemas.LabelSuggestionResponse:
    """Gợi ý nhãn theo kích thước hộp bao của vật; chỉ để sắp danh sách chọn, không tự gán."""
    _job_or_404(job_id)
    try:
        scene = _registry().scene.current(job_id).scene
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    target = next((item for item in scene.objects if item.id == object_id), None)
    dimensions = target and (
        target.primitive_dimensions_xyz_m or (target.collider.dimensions_xyz_m if target.collider else None)
    )
    if target is None or dimensions is None:
        raise HTTPException(status_code=404, detail="vật không tồn tại hoặc không có kích thước")
    return schemas.LabelSuggestionResponse(
        object_id=object_id,
        suggestions=suggest_classes(dimensions),
        basis="kích thước hộp bao so với danh mục asset",
    )


@router.post(
    "/jobs/{job_id}/scene/catalog-objects",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def add_catalog_scene_object(job_id: str, request: schemas.AddCatalogObjectRequest) -> schemas.SceneEditResponse:
    """Thêm một vật từ danh mục asset Isaac: nhãn + vật lý mặc định, revision mới."""
    _job_or_404(job_id)
    return _scene_mutation(
        lambda editor: add_catalog_object(
            editor, job_id, request.expected_scene_revision, request.family, request.position_xyz, request.name
        )
    )


@router.post(
    "/jobs/{job_id}/scene/restore",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def restore_scene_revision(job_id: str, request: schemas.RestoreRevisionRequest) -> schemas.SceneEditResponse:
    """Hoàn tác: nội dung revision cũ thành revision kế tiếp; lịch sử không bị xoá."""
    _job_or_404(job_id)
    return _scene_mutation(
        lambda editor: restore_revision(editor, job_id, request.expected_scene_revision, request.target_revision)
    )


def _scene_mutation(mutate: Callable[[SceneEditor], SceneEditResult]) -> schemas.SceneEditResponse:
    """Map lỗi thao tác scene giống `/scene/edits`: revision cũ/bất biến artifact → 409, lệnh sai → 422."""
    try:
        return schemas.scene_edit_response(mutate(_registry().scene))
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ArtifactStoreError as error:
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
    dependencies=[Depends(require_reviewer)],
)
def review_action(
    job_id: str,
    action: str,
    request: schemas.ReviewActionRequest,
) -> schemas.ReviewStateResponse:
    """Không dùng fixture approval làm authorization hoặc kết quả submit thật."""
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
    raise HTTPException(
        status_code=501, detail="Review authorization/persistence chưa triển khai; không tạo approval giả"
    )


@router.post(
    "/jobs/{job_id}/release",
    response_model=schemas.ReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
    dependencies=[Depends(require_reviewer)],
)
def release_candidate(
    job_id: str,
    request: schemas.ReleaseRequest,
) -> schemas.ReleaseResponse:
    """Fail closed tới khi có producer ReleaseManifest và authorization thật."""
    _job_or_404(job_id)
    raise HTTPException(
        status_code=501, detail="Release sealing chưa triển khai; không phát hành manifest/checksum giả"
    )
