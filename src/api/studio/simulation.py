"""Gói mô phỏng cho Isaac (EX-SIM SIM-02…05 nối vào Studio): tạo, xem trạng thái, tải về."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from src.api.studio import deps
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.projects import JobNotFoundError
from src.services.orchestration.review.simulation_package import (
    SimulationPackage,
    build_simulation_package,
    current_package,
)
from src.services.orchestration.scene import SceneError
from src.services.orchestration.scene.errors import SceneNotAvailableError

router = APIRouter()


def _guard(job_id: str) -> None:
    try:
        deps.registry().get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/jobs/{job_id}/simulation-package", response_model=SimulationPackage | None)
def get_simulation_package(job_id: str) -> SimulationPackage | None:
    """Gói của revision SceneIR hiện tại; null nếu chưa tạo (hoặc scene đã sửa sau lần tạo)."""
    _guard(job_id)
    try:
        return current_package(deps.registry(), job_id)
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/jobs/{job_id}/simulation-package", response_model=SimulationPackage)
def create_simulation_package(job_id: str) -> SimulationPackage:
    """Khoét môi trường, gắn collider, preflight; PASS thì đóng gói. FAIL trả báo cáo, không đổi scene."""
    _guard(job_id)
    try:
        return build_simulation_package(deps.registry(), job_id)
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (ArtifactStoreError, SceneError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get("/jobs/{job_id}/simulation-package/download", response_class=FileResponse)
def download_simulation_package(job_id: str) -> FileResponse:
    """File zip của gói hiện tại (scene.usda + layer môi trường + manifest + preflight)."""
    _guard(job_id)
    package = current_package(deps.registry(), job_id)
    if package is None or package.package_ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chưa có gói mô phỏng cho revision hiện tại")
    path = deps.registry().runtime_resolver.require(package.package_ref)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{job_id}-{package.scene_revision}-simulation.zip",
    )
