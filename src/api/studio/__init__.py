"""Endpoint Studio MVP: upload video → scene 3DGS, thông số xử lý và video mẫu.

Mỗi module con là một nhóm route; `deps.py` giữ dependency dùng chung (settings,
registry, upload service, file thông số chung) để test chỉ cần patch một chỗ.
"""

from fastapi import APIRouter, Depends

from src.api.auth import require_editor
from src.api.studio import imports, metric, processing, samples, scenes, simulation, uploads

router = APIRouter(tags=["studio"])
# Upload và scene tốn GPU/lưu trữ → cần Editor khi bật đăng nhập (ADR 0003 §3).
# Video mẫu và bảng thông số không có tác dụng phụ → khách dùng được.
for module in (uploads, scenes, metric, imports, simulation):
    router.include_router(module.router, dependencies=[Depends(require_editor)])
for module in (samples, processing):
    router.include_router(module.router)

__all__ = ["router"]
