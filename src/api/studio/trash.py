"""Thùng rác scene của Studio: gỡ, liệt kê, khôi phục, xoá hẳn.

Gỡ và khôi phục: Editor. Xoá hẳn không hoàn tác được (xoá cả object trên kho file) nên chỉ Reviewer.
Logic nằm ở `orchestration/projects/deletion.py`; route chỉ đổi lỗi nghiệp vụ thành mã HTTP.
"""

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.api import schemas
from src.api.auth import require_contributor, require_reviewer
from src.api.studio import deps
from src.services.orchestration.auth.models import UserRecord
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.projects.deletion import (
    DeletionContext,
    DeletionRecord,
    DeletionRefusedError,
    DeletionRequest,
    GuestOwnershipError,
    SummaryLine,
    apply_deletion,
    context_from_settings,
    guest_owns_deletion_plan,
    list_trash,
    purge_deletion,
    purge_expired,
    restore_deletion,
)

router = APIRouter()
_ERRORS = {404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}}


class TrashCapabilities(BaseModel):
    """Caller-specific restore/purge hints; mutation endpoints still enforce policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_restore: bool
    can_purge: bool


class TrashEntry(BaseModel):
    """Một mục trong thùng rác: một scene (hoặc scene nhập) cùng upload chỉ nó dùng."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    title: str
    deleted_at: datetime
    #: Thời điểm mục tự bị xoá hẳn; None khi deployment tắt tự xoá.
    expires_at: datetime | None
    deleted_by: str | None
    size_bytes: int
    items: list[SummaryLine]
    capabilities: TrashCapabilities


class TrashListResponse(BaseModel):
    """Thùng rác, mới gỡ nhất trước."""

    model_config = ConfigDict(extra="forbid")

    entries: list[TrashEntry]


class TrashSelection(BaseModel):
    """Các mục được chọn để khôi phục hoặc xoá hẳn."""

    model_config = ConfigDict(extra="forbid")

    entry_ids: list[str] = Field(min_length=1, max_length=200)


class TrashFailure(BaseModel):
    """Mục không xử lý được và lý do hiển thị cho người dùng."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    reason: str


class TrashActionResponse(BaseModel):
    """Kết quả theo từng mục: mục lỗi không chặn các mục còn lại."""

    model_config = ConfigDict(extra="forbid")

    done: list[str]
    failed: list[TrashFailure]


def _context() -> DeletionContext:
    return context_from_settings(deps.settings())


def _entry(context: DeletionContext, record: DeletionRecord, user: UserRecord | None) -> TrashEntry:
    primary = next((line for line in record.plan.summary if line.kind != "upload"), record.plan.summary[0])
    return TrashEntry(
        entry_id=record.entry_id,
        title=primary.name,
        deleted_at=record.created_at,
        expires_at=context.expires_at(record),
        deleted_by=record.deleted_by,
        size_bytes=record.plan.size_bytes,
        items=record.plan.summary,
        capabilities=TrashCapabilities(
            can_restore=(user is None or user.role != "guest" or guest_owns_deletion_plan(record.plan, user.user_id)),
            can_purge=user is None or user.role == "reviewer",
        ),
    )


def _move_to_trash(request: DeletionRequest, user: UserRecord | None) -> TrashEntry:
    context = _context()
    try:
        result = _entry(
            context,
            apply_deletion(
                context,
                request,
                user.user_id if user else None,
                guest_owner_user_id=user.user_id if user is not None and user.role == "guest" else None,
            ),
            user,
        )
        purge_expired(context)
        return result
    except GuestOwnershipError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except DeletionRefusedError as error:
        missing = all("không tìm thấy" in reason for reason in error.reasons)
        code = status.HTTP_404_NOT_FOUND if missing else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail="; ".join(error.reasons)) from error
    except RuntimeStateConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.delete("/scenes/{project_id}", response_model=TrashEntry, responses=_ERRORS)
def delete_scene(project_id: str, user: UserRecord | None = Depends(require_contributor)) -> TrashEntry:
    """Chuyển scene vào thùng rác; scene đang được worker xử lý hoặc đã phát hành thì từ chối (409)."""
    return _move_to_trash(DeletionRequest(project_ids=[project_id]), user)


@router.delete("/imports/{import_id}", response_model=TrashEntry, responses=_ERRORS)
def delete_import(import_id: str, user: UserRecord | None = Depends(require_contributor)) -> TrashEntry:
    """Chuyển scene nhập vào thùng rác."""
    return _move_to_trash(DeletionRequest(import_ids=[import_id]), user)


@router.get("/trash", response_model=TrashListResponse)
def get_trash(user: UserRecord | None = Depends(require_contributor)) -> TrashListResponse:
    """Các mục đang nằm trong thùng rác; mục quá hạn bị xoá hẳn trước khi trả danh sách."""
    context = _context()
    purge_expired(context)
    return TrashListResponse(entries=[_entry(context, record, user) for record in list_trash(context.database)])


def _each(
    selection: TrashSelection, action: Callable[[DeletionContext, str, str | None], object], user: UserRecord | None
) -> TrashActionResponse:
    context = _context()
    done: list[str] = []
    failed: list[TrashFailure] = []
    for entry_id in dict.fromkeys(selection.entry_ids):
        try:
            action(context, entry_id, user.user_id if user else None)
            done.append(entry_id)
        except (DeletionRefusedError, GuestOwnershipError, RuntimeStateConflictError) as error:
            failed.append(TrashFailure(entry_id=entry_id, reason=str(error)))
    return TrashActionResponse(done=done, failed=failed)


@router.post("/trash/restore", response_model=TrashActionResponse)
def restore_trash(
    selection: TrashSelection, user: UserRecord | None = Depends(require_contributor)
) -> TrashActionResponse:
    """Khôi phục các mục đã chọn về đúng trạng thái lúc gỡ."""

    def restore_one(context: DeletionContext, entry_id: str, actor: str | None) -> DeletionRecord:
        return restore_deletion(
            context,
            entry_id,
            actor,
            guest_owner_user_id=user.user_id if user is not None and user.role == "guest" else None,
        )

    return _each(selection, restore_one, user)


@router.post("/trash/purge", response_model=TrashActionResponse)
def purge_trash(selection: TrashSelection, user: UserRecord | None = Depends(require_reviewer)) -> TrashActionResponse:
    """Xoá hẳn các mục đã chọn, kể cả file trên kho file; không khôi phục được."""
    return _each(selection, purge_deletion, user)
