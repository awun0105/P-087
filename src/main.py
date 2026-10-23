import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.api.routes import router
from src.config import get_settings
from src.services.orchestration.jobs.database import RuntimeDatabase

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.samples.catalog import prepare_library
    from src.services.orchestration.samples.distributed import enabled
    from src.services.orchestration.samples.sessions import purge_sessions

    # Thư viện mẫu: catalog trong DB + kho file là nguồn sự thật; đĩa thiếu/sai được tải lại, không làm API chết.
    report = await run_in_threadpool(prepare_library, settings, RuntimeDatabase(settings.database_url))
    if report.repaired or report.broken:
        logger.warning("Demo library: repaired=%s broken=%s", report.repaired, report.broken)

    async def collect_sessions() -> None:
        while True:
            try:
                await run_in_threadpool(purge_sessions, settings)
            except Exception as error:  # noqa: BLE001 - retry maintenance without stopping the API
                logger.warning("Demo janitor deferred: %s", type(error).__name__)
            await asyncio.sleep(30)

    janitor = asyncio.create_task(collect_sessions()) if enabled(settings) else None
    try:
        yield
    finally:
        if janitor is not None:
            janitor.cancel()
            try:
                await janitor
            except asyncio.CancelledError:
                pass
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
    # T-053: trình duyệt giữ kết quả preflight một ngày thay vì hỏi lại mỗi 10 phút.
    max_age=86400,
)
# T-053: nén JSON (SceneIR ~650 KB) và GLB; bỏ qua file đã nén sẵn (SOG, ảnh, video) để không tốn CPU.
app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
    compresslevel=5,
    exclude_content_types=(
        *DEFAULT_EXCLUDED_CONTENT_TYPES,
        "application/octet-stream",
        "image/png",
        "image/jpeg",
        "image/webp",
        "video/mp4",
        "application/zip",
    ),
)

app.include_router(router, prefix="/api/v1")


@app.middleware("http")
async def private_demo_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    if "/demo-sessions/" in request.url.path or request.url.path.endswith("/sessions"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


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


@app.get("/ready")
async def ready() -> JSONResponse:
    """Report runtime and demo readiness separately from process liveness."""

    def inspect() -> dict[str, object]:
        from src.services.orchestration.jobs.worker_runtimes import has_live_runtime
        from src.services.orchestration.projects import get_project_registry
        from src.services.orchestration.samples.bundle import DemoLibrary
        from src.services.orchestration.samples.distributed import unpublished
        from src.services.orchestration.samples.workspace import load_workspace

        current = get_settings()
        registry = get_project_registry()
        assert registry.persistence is not None
        registry.persistence.database.ping()
        samples = []
        for sample_id, bundle in DemoLibrary(current.product_demo_dir).bundles().items():
            if not unpublished(current, sample_id):
                load_workspace(bundle)
                samples.append(sample_id)
        profile = registry.job_profile()
        available = profile is not None and has_live_runtime(
            registry.persistence.database, profile.runtime_manifest_checksum
        )
        catalog_available = False
        if current.product_gpu_release_catalog is not None:
            from src.services.orchestration.gpu.catalog import load_catalog

            catalog_available = profile is not None and any(
                release.execution.accepts_runtime(profile.job_runtime_checksum)
                and release.execution.config_checksum == profile.config_checksum
                for release in load_catalog(current.product_gpu_release_catalog).compatible("pipeline")
            )
        healthy = (available or catalog_available) and (bool(samples) or not current.product_demo_required)
        return {
            "status": "ready" if healthy else "waiting",
            "runtime_published": available,
            "compute_available": available,
            "catalog_available": catalog_available,
            "samples": samples,
        }

    try:
        result = await run_in_threadpool(inspect)
    except Exception as error:  # noqa: BLE001 - readiness boundary must not expose configuration/secrets
        logger.warning("Readiness unavailable: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)
