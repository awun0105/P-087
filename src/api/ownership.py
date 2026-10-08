"""Resource-level Guest authorization for the shared Studio workspace."""

from __future__ import annotations

from fastapi import HTTPException, status

from src.api import auth
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.projects.errors import JobNotFoundError
from src.services.orchestration.projects.models import ProjectRecord
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.uploads import UploadRecord, UploadSession


def owner_mutation_allowed(user: UserRecord | None, owner_user_id: str | None) -> bool:
    """Return the owner-policy decision used by both HTTP guards and UI hints.

    A missing user means authentication is disabled for this local deployment. Editors
    and Reviewers retain shared-workspace mutation rights; Guests require a known,
    matching owner ID.
    """
    return user is None or user.role != "guest" or owner_user_id == user.user_id


def _authorize_owner(
    user: UserRecord | None,
    owner_user_id: str | None,
    *,
    resource_type: str,
    resource_id: str,
    operation: str,
) -> None:
    """Guests may mutate only resources with a known matching creator ID.

    Editors and Reviewers retain shared-workspace access. Their cross-owner
    operations are recorded before the mutation so an audit failure cannot occur
    after a successful state change.
    """
    if user is None:
        return
    if not owner_mutation_allowed(user, owner_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Guest chỉ được {operation} resource do mình tạo",
        )
    if user.role == "guest":
        return
    if owner_user_id != user.user_id:
        auth.auth_service().audit(
            user.user_id,
            "operator.intervention",
            resource_id,
            {
                "operation": operation,
                "resource_type": resource_type,
                "owner_user_id": owner_user_id or "unknown",
            },
        )


def authorize_project_mutation(user: UserRecord | None, project: ProjectRecord, *, operation: str) -> None:
    owner_user_id = project.created_by.user_id if project.created_by is not None else None
    _authorize_owner(
        user,
        owner_user_id,
        resource_type="project",
        resource_id=project.project_id,
        operation=operation,
    )


def authorize_job_mutation(user: UserRecord | None, registry: ProjectRegistry, job_id: str, *, operation: str) -> None:
    if user is None:
        return
    try:
        owner_user_id = registry.get_job_owner_user_id(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    _authorize_owner(
        user,
        owner_user_id,
        resource_type="job",
        resource_id=job_id,
        operation=operation,
    )


def authorize_upload_mutation(user: UserRecord | None, upload: UploadRecord, *, operation: str) -> None:
    owner_user_id = upload.uploaded_by.user_id if upload.uploaded_by is not None else None
    _authorize_owner(
        user,
        owner_user_id,
        resource_type="upload",
        resource_id=upload.upload_id,
        operation=operation,
    )


def authorize_upload_session_mutation(user: UserRecord | None, session: UploadSession, *, operation: str) -> None:
    owner_user_id = session.uploaded_by.user_id if session.uploaded_by is not None else None
    _authorize_owner(
        user,
        owner_user_id,
        resource_type="upload_session",
        resource_id=session.upload_id,
        operation=operation,
    )
