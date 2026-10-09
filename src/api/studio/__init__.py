"""Endpoint Studio MVP: upload video → scene 3DGS, thông số xử lý và video mẫu.

Mỗi module con là một nhóm route; `deps.py` giữ dependency dùng chung (settings,
registry, upload service, file thông số chung) để test chỉ cần patch một chỗ.
"""

from fastapi import APIRouter, Depends

from src.api.auth import require_contributor
from src.api.studio import (
    anonymization,
    assemblies,
    demo,
    evaluation,
    imports,
    metric,
    processing,
    review,
    samples,
    scenes,
    simulation,
    trash,
    uploads,
)

router = APIRouter(tags=["studio"])
# Protected Studio routes require an authenticated contributor; each mutation must
# additionally check resource ownership. Reviewer-only handlers keep their own gate.
for module in (
    uploads,
    assemblies,
    scenes,
    metric,
    imports,
    simulation,
    review,
    trash,
    evaluation,
    demo,
    anonymization,
):
    router.include_router(module.router, dependencies=[Depends(require_contributor)])
for module in (samples, processing):
    router.include_router(module.router)

__all__ = ["router"]
