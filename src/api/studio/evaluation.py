"""Bảng đánh giá của một scene và bản xuất báo cáo (STUDIO_UX_SPEC D-16).

Số liệu tính lại mỗi lần đọc từ artifact bất biến của job; route không lưu gì.
"""

import logging
import sqlite3

try:
    import psycopg
except ImportError:
    _DATABASE_READ_ERRORS: tuple[type[Exception], ...] = (OSError, RuntimeError, ValueError, sqlite3.Error)
else:
    _DATABASE_READ_ERRORS = (OSError, RuntimeError, ValueError, sqlite3.Error, psycopg.Error)

from fastapi import APIRouter, HTTPException, Response, status

from src.api import schemas
from src.api.studio import deps
from src.services.orchestration.evaluation import JobEvaluation, evaluate_job, evaluation_markdown
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.observed import load_usages
from src.services.orchestration.projects import JobNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter()
_ERRORS = {404: {"model": schemas.ApiErrorResponse}}


def _evaluation(job_id: str) -> JobEvaluation:
    try:
        settings = deps.settings()
        reference = getattr(settings, "product_evaluation_reference", None)
        usages = None
        db_url = getattr(settings, "database_url", None)
        if db_url:
            try:
                usages = load_usages(RuntimeDatabase(db_url))
            except _DATABASE_READ_ERRORS as error:
                logger.warning("Không đọc được bản ghi tài nguyên của job %s (%s)", job_id, type(error).__name__)
        return evaluate_job(
            deps.registry(),
            job_id,
            settings.product_geometry_config,
            reference_config=reference,
            usages=usages,
        )
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/jobs/{job_id}/evaluation", response_model=JobEvaluation, responses=_ERRORS)
def get_evaluation(job_id: str) -> JobEvaluation:
    """Chỉ số tự kiểm theo từng bước của job; bước chưa chạy có trạng thái `pending`."""
    return _evaluation(job_id)


@router.get("/jobs/{job_id}/evaluation/report.md", responses=_ERRORS)
def download_evaluation_report(job_id: str) -> Response:
    """Báo cáo Markdown của bảng đánh giá, tải về để đưa vào tài liệu."""
    evaluation = _evaluation(job_id)
    return Response(
        content=evaluation_markdown(evaluation),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="evaluation-{evaluation.job_id}.md"'},
    )
