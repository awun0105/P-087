"""Artifact của job: danh sách được phép thấy, bytes theo allow-list, preview 3DGS, bản ghi Rerun."""

from pathlib import Path
from threading import Thread
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError

from src.api import schemas
from src.api.product import deps
from src.api.product.http_cache import IMMUTABLE_PRIVATE, checksum_etag, not_modified
from src.models.contracts.artifacts import ArtifactRef, Checksum
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import ArtifactNotFoundError, ArtifactStoreError
from src.services.orchestration.jobs.display_glb import display_space_glb
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects import JobNotFoundError, ProjectRegistry
from src.services.orchestration.scene.collision_cache import CollisionKey, CollisionPayload, WalkCollisionCache
from src.services.orchestration.scene.errors import (
    ObjectGeometryNotReadyError,
    SceneError,
    SceneHeadNotReadyError,
    SceneNotAvailableError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.physics_collision import (
    effective_collision_bytes,
    effective_collision_for_revision,
)
from src.services.scene.collision_ownership import SourceCollisionOwnershipError
from src.services.scene.geometry_state import require_geometry_ready

router = APIRouter()


@router.get("/jobs/{job_id}/artifacts", response_model=schemas.ArtifactListResponse)
def list_job_artifacts(job_id: str) -> schemas.ArtifactListResponse:
    """Artifact product được phép thấy.

    Ref lấy từ `data_class` có type trong JobManifest, không phải từ việc liệt kê
    thư mục — nên `ground_truth`/`evaluation_only` không thể lọt ra ngoài.
    """
    try:
        visible, excluded = deps.registry().list_job_artifacts(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return schemas.ArtifactListResponse(job_id=job_id, artifacts=visible, excluded_artifact_count=excluded)


@router.get("/jobs/{job_id}/preview", response_model=ReconstructionPreview)
def get_job_preview(job_id: str) -> ReconstructionPreview:
    """Không cần SceneIR; chỉ trả preview trong journal của đúng job."""
    try:
        return deps.registry().get_preview(job_id)
    except (JobNotFoundError, ArtifactNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ArtifactStoreError, ValueError) as error:
        raise HTTPException(status_code=409, detail="Preview identity/schema/checksum không hợp lệ") from error


@router.get("/jobs/{job_id}/artifacts/content")
def get_artifact_content(
    job_id: str,
    artifact_uri: str = Query(..., min_length=1),
    artifact_checksum: Checksum = Query(...),
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Trả bytes của một artifact **đã nằm trong allow-list của job**.

    URI không được tự do: registry đối chiếu với danh sách product-visible của
    chính job rồi mới resolve và verify checksum byte. Nhờ vậy
    `evaluation_only/`/`ground_truth` cùng thư mục không gọi tới được, và không
    có tham số đường dẫn nào đi qua API.
    """
    deps.job_or_404(job_id)
    try:
        reference = ArtifactRef(
            artifact_type="ArtifactContent",
            schema_version="1.0",
            artifact_uri=artifact_uri,
            artifact_checksum=artifact_checksum,
            data_class="derived",
            producer_stage="ST-EDIT",
            job_id=job_id,
        )
        registry = deps.registry()
        # T-051: kiểm quyền trước; trình duyệt đã có đúng bản (checksum trong URL) thì trả 304, không đọc file.
        etag = checksum_etag(registry.authorized_artifact(job_id, reference).artifact_checksum)
        if not_modified(if_none_match, etag):
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag, "Cache-Control": IMMUTABLE_PRIVATE}
            )
        # Có kho file: trình duyệt tải thẳng từ R2 bằng link có hạn (ADR 0003), API không
        # cõng file lớn qua băng thông tính phí. Quyền đọc vẫn kiểm theo allow-list ở trên.
        presign_seconds = deps.settings().artifact_presign_seconds
        link = registry.presigned_artifact_url(job_id, reference, presign_seconds)
        if link is not None:
            # Link được tái dùng khi còn ≥ nửa thời hạn (ArtifactRemote): trình duyệt giữ redirect trong khoảng đó.
            keep = max(0, presign_seconds // 2 - 60)
            return RedirectResponse(
                link,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Cache-Control": f"private, max-age={keep}"},
            )
        path = registry.resolve_artifact(job_id, reference)
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    # FileResponse stream/range: không copy toàn bộ SOG/video lớn vào RAM của API.
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": IMMUTABLE_PRIVATE,
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/jobs/{job_id}/artifacts/content/{filename}")
def get_named_artifact_content(
    job_id: str,
    filename: str,
    artifact_uri: str = Query(..., min_length=1),
    artifact_checksum: Checksum = Query(...),
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Tên file dùng chọn parser; quyền đọc vẫn bind URI/checksum canonical."""
    if filename != artifact_uri.rsplit("/", 1)[-1]:
        raise HTTPException(status_code=404, detail="artifact filename does not match its reference")
    return get_artifact_content(job_id, artifact_uri, artifact_checksum, if_none_match)


def _require_walk_allowed(registry: ProjectRegistry, job_id: str) -> None:
    """Walk chỉ dùng cho scene đã có hình học theo vật; job chưa có SceneIR giữ đường xem trước theo bản tái dựng."""
    try:
        scene = registry.scene.current(job_id).scene
    except SceneHeadNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.user_message) from error
    except SceneNotAvailableError:
        return
    require_geometry_ready(scene, "Walk")


_WALK_CACHES: dict[Path, WalkCollisionCache] = {}


def _walk_cache(registry: ProjectRegistry) -> WalkCollisionCache:
    """Một đệm cho mỗi kho artifact; thư mục đĩa cạnh ARTIFACT_ROOT (không ghi được thì chỉ dùng bộ nhớ)."""
    root = registry.runtime_resolver.artifact_root.parent / "cache" / "walk-collision"
    cache = _WALK_CACHES.get(root)
    if cache is None:
        cache = _WALK_CACHES[root] = WalkCollisionCache(root)
        # Dọn file đệm không dùng quá 7 ngày một lần mỗi tiến trình, ở luồng nền.
        Thread(target=cache.prune, name="walk-collision-prune", daemon=True).start()
    return cache


@router.get("/jobs/{job_id}/walk-collision/{filename}")
def get_walk_collision(
    job_id: str,
    filename: str,
    artifact_uri: str = Query(..., min_length=1),
    artifact_checksum: Checksum = Query(...),
    dynamic: list[str] = Query(default=[]),
    scene_revision: str | None = Query(default=None),
    frame: Literal["display", "canonical"] = Query(default="display"),
    preview: bool = Query(default=False),
    reconstruction: bool = False,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Shared effective environment for SceneIR consumers; raw preview only before scene review.

    Both output frames use the same source removal mask. Deprecated `dynamic` never controls carving.
    """
    if filename != artifact_uri.rsplit("/", 1)[-1] or not filename.lower().endswith(".glb"):
        raise HTTPException(status_code=404, detail="artifact filename does not match its reference")
    deps.job_or_404(job_id)
    try:
        reference = ArtifactRef(
            artifact_type="ArtifactContent",
            schema_version="1.0",
            artifact_uri=artifact_uri,
            artifact_checksum=artifact_checksum,
            data_class="derived",
            producer_stage="ST-EDIT",
            job_id=job_id,
        )
        registry = deps.registry()
        if reconstruction:
            if scene_revision is not None or dynamic or preview is True:
                raise ValueError("Bản tái dựng gốc không dùng trạng thái vật thể đang chỉnh sửa.")
            bundle = job_bundle(registry, registry.get_job(job_id))
            source = bundle.canonical_geometry_ref if bundle is not None else None
            if source is None or (artifact_uri, artifact_checksum) != (source.artifact_uri, source.artifact_checksum):
                raise ValueError("Walk bản tái dựng cần đúng collision gốc của job.")
        else:
            _require_walk_allowed(registry, job_id)
        # Resolve allow-list before composition; never accept an arbitrary source URI.
        source_path = registry.resolve_artifact(job_id, reference)
        identity = artifact_checksum
        shared = 0
        floor = 0
        repaired = 0
        etag = '"' + identity.removeprefix("sha256:") + ":" + frame + '"'
        cache_control = "private, no-cache"
        if scene_revision is not None:
            # T-052: revision phải là head hiện tại (như trước) rồi mới đọc đệm; dựng chỉ khi đệm chưa có.
            if registry.scene.current(job_id).scene.scene_revision != scene_revision:
                raise SceneRevisionConflictError("collision request does not match current SceneIR revision")
            key = CollisionKey(
                job_id=job_id,
                scene_revision=scene_revision,
                source_checksum=artifact_checksum,
                preview=preview is True,
                frame=frame,
                config_checksum=registry.get_job(job_id).config_checksum,
                source_uri=artifact_uri,
            )
            if not_modified(if_none_match, key.etag):
                return Response(
                    status_code=status.HTTP_304_NOT_MODIFIED,
                    headers={"ETag": key.etag, "Cache-Control": IMMUTABLE_PRIVATE},
                )

            def build() -> CollisionPayload:
                scene, background = effective_collision_for_revision(
                    registry, job_id, scene_revision, preview_pending=preview is True
                )
                selected = scene.environment.collision_source_ref or scene.environment.geometry_ref
                if (artifact_uri, artifact_checksum) != (selected.artifact_uri, selected.artifact_checksum):
                    raise SourceCollisionOwnershipError("collision URL does not bind the selected SceneIR source")
                return CollisionPayload(
                    body=effective_collision_bytes(background, display=frame == "display"),
                    identity=background.identity,
                    shared=background.retained_shared_triangles,
                    floor=background.protected_surface_triangles,
                    repaired=background.repaired_triangles,
                )

            composed = _walk_cache(registry).get_or_build(key, build)
            payload, identity = composed.body, composed.identity
            shared, floor, repaired = composed.shared, composed.floor, composed.repaired
            etag, cache_control = key.etag, IMMUTABLE_PRIVATE
        else:
            if dynamic or preview is True:
                raise SourceCollisionOwnershipError("object collision composition requires scene_revision")
            # Reconstruction-stage preview has no SceneIR lifecycle yet.
            raw = source_path.read_bytes()
            payload = display_space_glb(raw) if frame == "display" else raw
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ObjectGeometryNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (ValueError, SceneError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Không dùng được lưới va chạm: {error}"
        ) from error
    return Response(
        payload,
        media_type="model/gltf-binary",
        # Nội dung gắn với checksum trong URL nên trình duyệt được giữ lại.
        headers={
            "Cache-Control": cache_control,
            "X-Content-Type-Options": "nosniff",
            "X-Scene-Revision": scene_revision or "source-preview",
            "X-Collision-Composition": identity,
            "X-Retained-Shared-Triangles": str(shared),
            "X-Protected-Surface-Triangles": str(floor),
            "X-Repaired-Surface-Triangles": str(repaired),
            "X-Collision-Mode": "reconstruction"
            if reconstruction
            else "studio-preview"
            if preview is True
            else "confirmed"
            if scene_revision
            else "source-preview",
            "ETag": etag,
        },
    )


def _training_recording(job_id: str) -> Path:
    """File bản ghi Rerun của job; tên lấy từ job đã tra được, không từ tham số đường dẫn."""
    job = deps.job_or_404(job_id)
    return deps.settings().product_rerun_recording_dir / f"{job.job_id}.rrd"


@router.get(
    "/jobs/{job_id}/training-recording",
    response_model=schemas.TrainingRecordingResponse,
    responses={404: {"model": schemas.ApiErrorResponse}},
)
def get_training_recording(job_id: str) -> schemas.TrainingRecordingResponse:
    """Job có bản ghi Rerun của quá trình train 3DGS không (chế độ xem tuỳ chọn, ngoài pipeline)."""
    path = _training_recording(job_id)
    available = path.is_file()
    return schemas.TrainingRecordingResponse(available=available, size_bytes=path.stat().st_size if available else None)


@router.get("/jobs/{job_id}/training-recording.rrd", responses={404: {"model": schemas.ApiErrorResponse}})
def download_training_recording(job_id: str) -> FileResponse:
    """Bản ghi Rerun (.rrd) cho viewer Rerun nhúng trong Studio."""
    path = _training_recording(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="job chưa có bản ghi quá trình train")
    return FileResponse(path, media_type="application/octet-stream")
