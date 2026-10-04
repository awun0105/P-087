"""Bảng đánh giá của một scene và bản xuất báo cáo (STUDIO_UX_SPEC D-16).

Số liệu tính lại mỗi lần đọc từ artifact bất biến của job; route không lưu gì.
"""

from fastapi import APIRouter, HTTPException, Response, status

from src.api import schemas
from src.api.studio import deps
from src.services.orchestration.evaluation import JobEvaluation, evaluate_job, evaluation_markdown
from src.services.orchestration.projects import JobNotFoundError

router = APIRouter()
_ERRORS = {404: {"model": schemas.ApiErrorResponse}}


def _evaluation(job_id: str) -> JobEvaluation:
    try:
        return evaluate_job(deps.registry(), job_id, deps.settings().product_geometry_config)
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
