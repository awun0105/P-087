"""Điểm vào duy nhất của API: gắn router product, studio và auth."""

from fastapi import APIRouter, Depends

from src.api.auth import require_contributor
from src.api.auth import router as auth_router
from src.api.demo_sessions import router as demo_session_router
from src.api.product import router as product_router
from src.api.studio import router as studio_router

router = APIRouter()
# Product reads and Editor features are available to Guest; mutation routes enforce ownership.
# Review and release keep their explicit Reviewer dependencies.
router.include_router(product_router, dependencies=[Depends(require_contributor)])
router.include_router(studio_router)
router.include_router(auth_router)
router.include_router(demo_session_router)
