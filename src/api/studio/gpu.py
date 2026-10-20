"""Managed GPU capacity for people waiting on a job (read-only, one DB read, no provider call)."""

from fastapi import APIRouter
from pydantic import ValidationError

from src.api.studio import deps
from src.services.orchestration.gpu.config import GpuSettings
from src.services.orchestration.gpu.status import DEFAULT_STARTUP_SECONDS, GpuCapacity, gpu_capacity

router = APIRouter()


def deployment_id() -> str:
    """The controller's deployment; empty when RunPod autoprovisioning is not configured here."""
    try:
        return GpuSettings().deployment_id
    except ValidationError:
        return ""


@router.get("/gpu/status", response_model=GpuCapacity)
def get_gpu_status() -> GpuCapacity:
    """Whether a GPU is off, starting (with since + typical cold start) or ready; clients count down locally."""
    registry = deps.registry()
    if registry.persistence is None:
        return GpuCapacity(state="unmanaged", expected_startup_seconds=DEFAULT_STARTUP_SECONDS)
    return gpu_capacity(registry.persistence.database, deployment_id())
