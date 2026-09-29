"""Endpoint Studio MVP: upload video → scene 3DGS, thông số xử lý và video mẫu.

Mỗi module con là một nhóm route; `deps.py` giữ dependency dùng chung (settings,
registry, upload service, file thông số chung) để test chỉ cần patch một chỗ.
"""

from fastapi import APIRouter

from src.api.studio import processing, samples, scenes, uploads

router = APIRouter(tags=["studio"])
for module in (uploads, scenes, samples, processing):
    router.include_router(module.router)

__all__ = ["router"]
