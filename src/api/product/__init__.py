"""Endpoint product (hợp đồng UI P0): project, job, artifact, scene, review.

Mỗi module con là một nhóm route, cùng kiểu với `src/api/studio/`; `deps.py` giữ dependency dùng chung. Router tổng
được `routes.py` include (không gắn ở `main.py` — `main.py` không thuộc ownership của EX-PRODUCT). Mọi handler là
`def` đồng bộ vì `FilesystemArtifactStore` là code đồng bộ; FastAPI chạy chúng trong threadpool nên không chặn event
loop.
"""

from fastapi import APIRouter

from src.api.product import artifacts, jobs, projects, review, scene

router = APIRouter(tags=["product"])
for module in (projects, jobs, artifacts, scene, review):
    router.include_router(module.router)

__all__ = ["router"]
