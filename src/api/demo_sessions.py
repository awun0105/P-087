"""Public capability-scoped Studio API for disposable demo sessions."""

from functools import lru_cache

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

from src.api.studio import deps
from src.config import Settings
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.projects.errors import JobNotFoundError
from src.services.orchestration.samples import DemoUnavailableError
from src.services.orchestration.samples.session_context import DemoRuntime, demo_runtime
from src.services.orchestration.samples.sessions import (
    DemoSession,
    DemoSessionUnavailableError,
    close_session,
    create_session,
    get_session,
    hold_session,
    load_runtime,
    purge_sessions,
    touch_session,
)
from src.services.orchestration.scene.errors import SceneError

router = APIRouter(tags=["demo sessions"])


class SessionView(BaseModel):
    session_id: str
    sample_id: str
    job_id: str
    source_revision: str
    expires_at: str


@router.post("/samples/{sample_id}/sessions", response_model=SessionView, status_code=201)
def open_demo_session(sample_id: str) -> SessionView:
    try:
        session = create_session(deps.settings(), deps.registry(), sample_id)
    except (DemoUnavailableError, JobNotFoundError, SceneError, ArtifactStoreError) as error:
        raise HTTPException(status_code=409, detail="Không mở được workspace mẫu: " + str(error)) from error
    return SessionView(
        session_id=session.session_id,
        sample_id=sample_id,
        job_id=session.job_id,
        source_revision=session.source_revision,
        expires_at=session.expires_at.isoformat(),
    )


@router.delete("/demo-sessions/{session_id}", status_code=202)
def end_demo_session(session_id: str) -> dict[str, str]:
    try:
        close_session(deps.settings(), session_id)
        purge_sessions(deps.settings())
    except DemoSessionUnavailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"status": "closed"}


@router.post("/demo-sessions/{session_id}/heartbeat", status_code=204)
def heartbeat_demo_session(session_id: str) -> Response:
    try:
        touch_session(deps.settings(), session_id)
    except DemoSessionUnavailableError as error:
        raise HTTPException(status_code=410, detail=str(error)) from error
    return Response(status_code=204)


@lru_cache(maxsize=1)
def _session_api() -> FastAPI:
    # Import after the composition root has finished loading the regular routers.
    from src.api.auth import MeResponse, me
    from src.api.product import router as product_router
    from src.api.studio import router as studio_router
    from src.services.orchestration.jobs.dispatch import prepared_frame_reference
    from src.services.orchestration.jobs.progress import sanitized_frame_stage
    from src.services.orchestration.jobs.stage_views import StageViewList, stage_views
    from src.services.reconstruction import frame_images

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_api_route("/api/v1/auth/me", me, response_model=MeResponse)

    @app.get("/api/v1/jobs/{job_id}/stage-views", response_model=StageViewList)
    def demo_stage_views(job_id: str) -> StageViewList:
        registry = deps.registry()
        result = stage_views(registry, job_id)
        job = registry.get_job(job_id)
        if sanitized_frame_stage(job) is not None:
            reference = prepared_frame_reference(job)
            images = frame_images(reference, registry.runtime_resolver.require) if reference is not None else []
            result = result.model_copy(
                update={
                    "views": [
                        view.model_copy(update={"refs": images[:48], "note": "Ảnh đã che thông tin riêng tư của mẫu"})
                        if view.kind == "frames"
                        else view
                        for view in result.views
                    ]
                }
            )
        return result

    app.include_router(product_router, prefix="/api/v1")
    app.include_router(studio_router, prefix="/api/v1")
    return app


class _SessionResponse(Response):
    def __init__(self, runtime: DemoRuntime, session: DemoSession, path: str, settings: Settings) -> None:
        super().__init__()
        self.runtime, self.session, self.path = runtime, session, path
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with hold_session(self.settings, self.session.session_id):
                token = demo_runtime.set(self.runtime)
                try:
                    child = dict(scope)
                    child["path"] = self.path
                    child["raw_path"] = self.path.encode()
                    child["root_path"] = ""
                    await _session_api()(child, receive, send)
                finally:
                    demo_runtime.reset(token)
        except (DemoSessionUnavailableError, FileNotFoundError):
            await JSONResponse(status_code=410, content={"detail": "Phiên demo đã kết thúc; mở lại mẫu"})(
                scope, receive, send
            )


@router.api_route("/demo-sessions/{session_id}/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def demo_api(session_id: str, path: str, request: Request) -> Response:
    current, source = deps.settings(), deps.registry()
    try:
        session = await run_in_threadpool(get_session, current, session_id)
        parts = path.split("/")
        allowed = (
            len(parts) >= 2
            and parts[0] == "jobs"
            and parts[1] == session.job_id
            or len(parts) >= 2
            and parts[0] == "projects"
            and parts[1] == session.project_id
            or request.method == "GET"
            and path.startswith("scene/catalog")
            or request.method == "GET"
            and path.startswith("value-metrics/benchmark")
            or request.method == "GET"
            and path == "auth/me"
            or parts[0] in {"uploads", "input-assemblies", "samples"}
        )
        if not allowed:
            raise HTTPException(status_code=404, detail="Resource không thuộc phiên demo")
        if request.query_params.get("artifact_uri") in session.protected_uris:
            raise HTTPException(status_code=403, detail="Mẫu chỉ công khai ảnh đã che; không tải được đầu vào chưa che")
        if session.protected_uris and path.endswith("/thumbnail.jpg"):
            raise HTTPException(status_code=404, detail="Mẫu chỉ dùng ảnh đã che trong bộ frame công khai")
        runtime = await run_in_threadpool(load_runtime, current, source, session)
    except DemoSessionUnavailableError as error:
        raise HTTPException(status_code=410, detail=str(error)) from error
    return _SessionResponse(runtime, session, "/api/v1/" + path, current)
