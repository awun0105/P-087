"""Artifact của job: danh sách được phép thấy, bytes theo allow-list, preview 3DGS, bản ghi Rerun."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError

from src.api import schemas
from src.api.product import deps
from src.models.contracts.artifacts import ArtifactRef, Checksum
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import ArtifactNotFoundError, ArtifactStoreError
from src.services.orchestration.jobs.display_glb import display_space_glb
from src.services.orchestration.projects import JobNotFoundError

router = APIRouter()


@router.get("/jobs/{job_id}/artifacts", response_model=schemas.ArtifactListResponse)
def list_job_artifacts(job_id: str) -> schemas.ArtifactListResponse:
    """Artifact product được phép thấy.

    Ref lấy từ `data_class` có type trong JobManifest, không phải từ việc liệt kê
    thư mục — nên `ground_truth`/`evaluation_only` không thể lọt ra ngoài.
    """
    try:
        visible, excluded = deps.registry().list_job_artifacts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.ArtifactListResponse(job_id=job_id, artifacts=visible, excluded_artifact_count=excluded)


@router.get("/jobs/{job_id}/preview", response_model=ReconstructionPreview)
def get_job_preview(job_id: str) -> ReconstructionPreview:
    """Không cần SceneIR; chỉ trả preview trong journal của đúng job."""
    try:
        return deps.registry().get_preview(job_id)
    except (JobNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ArtifactStoreError, ValueError) as error:
        raise HTTPException(status_code=409, detail="Preview identity/schema/checksum không hợp lệ") from error


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
    deps.job_or_404(job_id)
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
        registry = deps.registry()
        # Có kho file: trình duyệt tải thẳng từ R2 bằng link có hạn (ADR 0003), API không
        # cõng file lớn qua băng thông tính phí. Quyền đọc vẫn kiểm theo allow-list ở trên.
        link = registry.presigned_artifact_url(job_id, reference, deps.settings().artifact_presign_seconds)
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


@router.get("/jobs/{job_id}/walk-collision/{filename}")
def get_walk_collision(
    job_id: str,
    filename: str,
    artifact_uri: str = Query(..., min_length=1),
    artifact_checksum: Checksum = Query(...),
) -> Response:
    """Lưới va chạm của job đã xoay sang không gian hiển thị, cho chế độ đi bộ của viewer.

    Quyền đọc như `artifacts/content`: URI/checksum phải nằm trong allow-list của job. Bytes
    trả về là bản dẫn xuất tính tại chỗ từ artifact đã verify checksum; artifact gốc không đổi.
    Luôn đi qua API (không redirect sang kho file) vì kho chỉ giữ bản canonical.
    """
    if filename != artifact_uri.rsplit("/", 1)[-1] or not filename.lower().endswith(".glb"):
        raise HTTPException(status_code=404, detail="artifact filename does not match its reference")
    deps.job_or_404(job_id)
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
        payload = display_space_glb(deps.registry().resolve_artifact(job_id, reference).read_bytes())
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Không dùng được lưới va chạm: {error}"
        ) from error
    return Response(
        payload,
        media_type="model/gltf-binary",
        # Nội dung gắn với checksum trong URL nên trình duyệt được giữ lại.
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


def _training_recording(job_id: str) -> Path:
    """File bản ghi Rerun của job; tên lấy từ job đã tra được, không từ tham số đường dẫn."""
    job = deps.job_or_404(job_id)
    return deps.settings().product_rerun_recording_dir / f"{job.job_id}.rrd"


@router.get(
    "/jobs/{job_id}/training-recording",
    response_model=schemas.TrainingRecordingResponse,
    responses={404: {"model": schemas.ApiErrorResponse}},
)
def get_training_recording(job_id: str) -> schemas.TrainingRecordingResponse:
    """Job có bản ghi Rerun của quá trình train 3DGS không (chế độ xem tuỳ chọn, ngoài pipeline)."""
    path = _training_recording(job_id)
    available = path.is_file()
    return schemas.TrainingRecordingResponse(available=available, size_bytes=path.stat().st_size if available else None)


@router.get("/jobs/{job_id}/training-recording.rrd", responses={404: {"model": schemas.ApiErrorResponse}})
def download_training_recording(job_id: str) -> FileResponse:
    """Bản ghi Rerun (.rrd) cho viewer Rerun nhúng trong Studio."""
    path = _training_recording(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="job chưa có bản ghi quá trình train")
    return FileResponse(path, media_type="application/octet-stream")
