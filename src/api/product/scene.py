"""SceneIR của job (PRODUCT-06/07, pipeline v2): revision, sửa transform, thao tác vật thể, danh mục asset, tách lại theo vật."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from src.api import schemas
from src.api.auth import enforce_gpu_quota, record_gpu_run, require_contributor
from src.api.ownership import authorize_job_mutation
from src.api.product import deps
from src.config import Settings
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.scene import SceneEditCommand, SceneError, SceneRevisionConflictError, objectify_queue
from src.services.orchestration.scene.catalog import load_catalog, suggest_classes
from src.services.orchestration.scene.errors import SceneNotAvailableError
from src.services.orchestration.scene.objectify_queue import ObjectifyRequestError, ObjectifyState
from src.services.orchestration.scene.objects import (
    OBJECT_ACTIONS,
    add_box_object,
    add_catalog_object,
    apply_object_action,
    restore_revision,
)

router = APIRouter()


# ── PRODUCT-06: scene revision cho viewer ────────────────────────────────────


@router.get("/jobs/{job_id}/scene", response_model=schemas.SceneResponse)
def get_job_scene(job_id: str) -> schemas.SceneResponse:
    """SceneIR hiện tại của job, kèm ref và trạng thái visual.

    `visual.brush_compatibility_proof` đi kèm payload vì fixture hiện chỉ có
    visual tổng hợp — thiếu cờ này thì viewer rất dễ bị đọc thành AC-11.
    """
    deps.job_or_404(job_id)
    editor = deps.registry().scene
    try:
        return schemas.scene_response(editor.current(job_id), editor.visual_binding(job_id))
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ArtifactStoreError, SceneError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/scene/edits",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}},
)
def edit_job_scene(
    job_id: str,
    command: SceneEditCommand,
    user: UserRecord | None = Depends(require_contributor),
) -> schemas.SceneEditResponse:
    """Áp transform edit và persist thành revision mới (PRODUCT-06).

    `expected_scene_revision` là khoá optimistic: client sửa trên revision đã cũ
    sẽ bị 409 chứ không ghi đè thay đổi của người khác.

    `ArtifactStoreError` map sang 409 theo đúng precedent của `/validation` và
    `/review`: nó nổi lên khi bytes của một revision đã niêm phong không còn khớp
    ref, tức là xung đột bất biến artifact — không phải lỗi command của client.
    """
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="sửa scene của")
    deps.job_or_404(job_id)
    try:
        return schemas.scene_edit_response(registry.scene.apply(job_id, command))
    except SceneRevisionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ArtifactStoreError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SceneError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


# ── PRODUCT-07: object actions ───────────────────────────────────────────────


@router.post(
    "/jobs/{job_id}/scene/objects/{object_id}/{action}",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def object_action(
    job_id: str,
    object_id: str,
    action: str,
    request: schemas.ObjectActionRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> schemas.SceneEditResponse:
    """confirm/ignore ứng viên, hide/delete/rename vật thể — lệnh domain EX-SCENE, revision mới."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="sửa vật thể của")
    deps.job_or_404(job_id)
    if action not in OBJECT_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action {action} không được hỗ trợ",
        )
    return deps.scene_mutation(
        lambda editor: apply_object_action(
            editor,
            job_id,
            object_id,
            action,  # type: ignore[arg-type] - đã kiểm trong OBJECT_ACTIONS
            request.expected_scene_revision,
            active=request.active,
            name=request.name,
            semantic_class=request.semantic_class,
            mass_kg=request.mass_kg,
            asset_family=request.asset_family,
        )
    )


@router.post(
    "/jobs/{job_id}/scene/objects",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def add_object(
    job_id: str,
    request: schemas.AddObjectRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> schemas.SceneEditResponse:
    """Thêm vật cản hộp do người dùng đặt (PRODUCT-07A); `position_xyz` là tâm hộp (mét, world)."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="thêm vật thể vào")
    deps.job_or_404(job_id)
    if request.collider_type != "AABB" or request.origin != "user_added":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="chỉ hỗ trợ vật cản hộp (AABB) do người dùng thêm",
        )
    return deps.scene_mutation(
        lambda editor: add_box_object(
            editor,
            job_id,
            request.expected_scene_revision,
            request.name,
            request.dimensions_xyz_m,
            request.position_xyz,
        )
    )


def _preview_path(settings: Settings, family: str) -> Path | None:
    """Hình xem trước của một họ asset: bản CC0/tự dựng trước; bản chuyển từ asset Isaac chỉ khi deployment cho phép.

    Bản Isaac không được phát trên staging/production theo mặc định vì giấy phép asset của NVIDIA (ADR 0010 mục 3).
    """
    cc0 = settings.product_catalog_preview_dir / f"{family}.glb"
    if cc0.is_file():
        return cc0
    isaac = settings.product_asset_preview_dir / f"{family}.glb"
    return isaac if settings.isaac_asset_previews_enabled and isaac.is_file() else None


@router.get("/scene/catalog", response_model=schemas.SceneCatalogResponse)
def get_scene_catalog() -> schemas.SceneCatalogResponse:
    """Danh mục nhãn + asset Isaac đặt được (ADR 0007); giá trị vật lý là mặc định tham khảo."""
    catalog = load_catalog()
    settings = deps.settings()
    return schemas.SceneCatalogResponse(
        classes=catalog.classes(),
        entries=[
            schemas.CatalogEntryResponse(
                family=entry.family,
                semantic_class=entry.semantic_class,
                size_xyz_m=entry.size_xyz_m,
                dynamic=bool(entry.physics.get("dynamic", True)),
                default_mass_kg=entry.physics.get("mass_kg"),
                has_preview=_preview_path(settings, entry.family) is not None,
            )
            for entry in catalog.placeable()
        ],
        physics_note=catalog.physics_note,
    )


@router.get("/scene/catalog/{family}/preview.glb", responses={404: {"model": schemas.ApiErrorResponse}})
def get_catalog_preview(family: str) -> FileResponse:
    """Hình khối của một asset danh mục (GLB, mét, Z lên, tâm hộp bao tại gốc) để Studio vẽ thay cho hộp."""
    entry = load_catalog().family(family)
    # Tên file lấy từ danh mục, không từ tham số đường dẫn: không đọc được file ngoài thư mục xem trước.
    path = _preview_path(deps.settings(), entry.family) if entry is not None else None
    if path is None:
        raise HTTPException(status_code=404, detail="asset chưa có bản xem trước")
    return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "public, max-age=86400"})


@router.get(
    "/jobs/{job_id}/scene/objectify",
    response_model=ObjectifyState,
    responses={404: {"model": schemas.ApiErrorResponse}},
)
def get_objectify_state(job_id: str) -> ObjectifyState:
    """Scene đang là scene theo vật hay đường hộp, và yêu cầu chạy lại gần nhất đang ở đâu."""
    deps.job_or_404(job_id)
    try:
        return objectify_queue.state(deps.registry(), deps.settings(), job_id)
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/jobs/{job_id}/scene/objectify",
    response_model=ObjectifyState,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": schemas.ApiErrorResponse}, 409: {"model": schemas.ApiErrorResponse}},
)
def request_objectify(
    job_id: str, request: schemas.ObjectifyRequest, user: UserRecord | None = Depends(require_contributor)
) -> ObjectifyState:
    """Xếp hàng chạy lại tách theo vật (hoặc dùng hộp ứng viên); worker thực hiện, ghi revision SceneIR kế tiếp.

    Tập vật mới là ứng viên mới: xác nhận/nhãn của revision hiện tại không mang sang (vẫn hoàn tác được).
    Thao tác này vẫn chịu worker/resource admission. Guest objectify không trừ
    quota ba job dựng scene mỗi ngày; Editor giữ rolling quota 24 giờ hiện tại.
    """
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="tách lại vật thể của")
    deps.job_or_404(job_id)
    enforce_gpu_quota(user)
    try:
        result = objectify_queue.request(
            registry, deps.settings(), job_id, request.expected_scene_revision, request.mode
        )
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ObjectifyRequestError, SceneRevisionConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    record_gpu_run(user, job_id, {"kind": f"scene.{request.mode}"})
    return result


@router.get(
    "/jobs/{job_id}/scene/objects/{object_id}/label-suggestions",
    response_model=schemas.LabelSuggestionResponse,
    responses={404: {"model": schemas.ApiErrorResponse}},
)
def get_label_suggestions(job_id: str, object_id: str) -> schemas.LabelSuggestionResponse:
    """Gợi ý nhãn theo kích thước hộp bao của vật; chỉ để sắp danh sách chọn, không tự gán."""
    deps.job_or_404(job_id)
    try:
        scene = deps.registry().scene.current(job_id).scene
    except SceneNotAvailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    target = next((item for item in scene.objects if item.id == object_id), None)
    dimensions = target and (
        target.primitive_dimensions_xyz_m or (target.collider.dimensions_xyz_m if target.collider else None)
    )
    if target is None or dimensions is None:
        raise HTTPException(status_code=404, detail="vật không tồn tại hoặc không có kích thước")
    return schemas.LabelSuggestionResponse(
        object_id=object_id,
        suggestions=suggest_classes(dimensions),
        basis="kích thước hộp bao so với danh mục asset",
    )


@router.post(
    "/jobs/{job_id}/scene/catalog-objects",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def add_catalog_scene_object(
    job_id: str,
    request: schemas.AddCatalogObjectRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> schemas.SceneEditResponse:
    """Thêm một vật từ danh mục asset Isaac: nhãn + vật lý mặc định, revision mới."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="thêm asset vào")
    deps.job_or_404(job_id)
    return deps.scene_mutation(
        lambda editor: add_catalog_object(
            editor, job_id, request.expected_scene_revision, request.family, request.position_xyz, request.name
        )
    )


@router.post(
    "/jobs/{job_id}/scene/restore",
    response_model=schemas.SceneEditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": schemas.ApiErrorResponse},
        409: {"model": schemas.ApiErrorResponse},
        422: {"model": schemas.ApiErrorResponse},
    },
)
def restore_scene_revision(
    job_id: str,
    request: schemas.RestoreRevisionRequest,
    user: UserRecord | None = Depends(require_contributor),
) -> schemas.SceneEditResponse:
    """Hoàn tác: nội dung revision cũ thành revision kế tiếp; lịch sử không bị xoá."""
    registry = deps.registry()
    authorize_job_mutation(user, registry, job_id, operation="khôi phục revision của")
    deps.job_or_404(job_id)
    return deps.scene_mutation(
        lambda editor: restore_revision(editor, job_id, request.expected_scene_revision, request.target_revision)
    )
