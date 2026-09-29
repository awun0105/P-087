import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.config import get_settings
from src.services.orchestration.jobs.database import RuntimeDatabase

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    yield
    print("Shutting down...")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health() -> JSONResponse:
    """Kiểm backend + runtime DB (`SELECT 1`).

    UptimeRobot gọi 5 phút/lần (ADR 0003): vừa cảnh báo khi sập, vừa là truy vấn
    giữ Supabase Free không tạm dừng. DB lỗi → 503, không lộ URL/secret.
    """
    try:
        await run_in_threadpool(lambda: RuntimeDatabase(get_settings().database_url).ping())
    except Exception:
        # Process boundary của health check: ghi log đủ cause, trả trạng thái chung.
        logger.exception("Health check: runtime database không phản hồi")
        return JSONResponse(
            status_code=503, content={"status": "degraded", "database": "error", "env": settings.app_env}
        )
    return JSONResponse(content={"status": "ok", "database": "ok", "env": settings.app_env})
