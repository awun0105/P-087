"""Project và job của project (PRODUCT-01/02): tạo, liệt kê, privacy state."""

from fastapi import APIRouter, Depends, HTTPException, status

from src.api import schemas
from src.api.auth import enforce_gpu_quota, record_gpu_run, require_contributor, require_editor
from src.api.ownership import authorize_project_mutation
from src.api.product import deps
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.auth import UserRecord, actor_of
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects import (
    JobCreateInput,
    PrivacyGateBlockedError,
    ProjectCreateInput,
    ProjectNotFoundError,
)

router = APIRouter()


@router.post("/projects", response_model=schemas.ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateInput, user: UserRecord | None = Depends(require_contributor)
) -> schemas.ProjectResponse:
    """Tạo project và ghi nhận source-rights attestation.

    Input mới luôn vào ở mức sàng lọc sơ bộ: chưa có `ST-PRIVACY-GATE` thật chạy,
    nên project chưa được phép dispatch job.
    """
    return schemas.project_response(deps.registry().create_project(request, created_by=actor_of(user)))


@router.get("/projects", response_model=schemas.ProjectListResponse)
def list_projects() -> schemas.ProjectListResponse:
    """Danh sách project kèm privacy state."""
    return schemas.ProjectListResponse(
        projects=[schemas.project_response(record) for record in deps.registry().list_projects()]
    )


@router.get("/projects/{project_id}", response_model=schemas.ProjectResponse)
def get_project(project_id: str) -> schemas.ProjectResponse:
    """Chi tiết một project."""
    return schemas.project_response(deps.project_or_404(project_id))


@router.get("/projects/{project_id}/privacy", response_model=schemas.PrivacyStateResponse)
def get_project_privacy(project_id: str) -> schemas.PrivacyStateResponse:
    """Privacy state riêng cho PRODUCT-02/PRODUCT-05."""
    return schemas.privacy_state(deps.project_or_404(project_id))


@router.post(
    "/projects/{project_id}/jobs",
    response_model=JobManifest,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": schemas.ApiErrorResponse}},
)
def create_job(
    project_id: str,
    request: schemas.JobCreateRequest,
    user: UserRecord | None = Depends(require_editor),
) -> JobManifest:
    """Tạo job cho một project. Bị chặn nếu privacy gate chưa cho input đi qua.

    `project_id` lấy từ path; body không được ghi đè project.
    """
    enforce_gpu_quota(user)
    registry = deps.registry()
    try:
        project = registry.get_project(project_id)
        authorize_project_mutation(user, project, operation="tạo job trong")
        job = registry.create_job(
            JobCreateInput(project_id=project_id, scene_revision=request.scene_revision),
            requested_by=actor_of(user),
            owner_user_id=user.user_id if user is not None else None,
        )
        record_gpu_run(user, job.job_id, {"kind": "job.create", "project_id": project_id})
        return job
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (PrivacyGateBlockedError, RuntimeStateConflictError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/projects/{project_id}/jobs", response_model=schemas.JobListResponse)
def list_jobs(project_id: str) -> schemas.JobListResponse:
    """Job của một project."""
    try:
        jobs = deps.registry().list_jobs(project_id)
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.JobListResponse(project_id=project_id, jobs=jobs)
