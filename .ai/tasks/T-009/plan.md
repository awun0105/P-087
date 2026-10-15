# T-009: Hàng đợi mode `geometry` + API build

## Goal
Người dùng bấm "Tạo mesh" → API xếp việc vào hàng đợi objectify hiện có với `mode = "geometry"`, worker chạy
`build_object_geometry` (T-007) có lease, huỷ, revision fence, tiến độ. Cũng hỗ trợ `geometry_review = "auto"`.

## Context
`architecture.md` §7.4. Code:
- `src/services/orchestration/scene/objectify_queue.py`: `ObjectifyMode = Literal["objectify", "boxes", "membership"]` (dòng 49),
  `request(...)` (~258), nhánh chạy `if running.mode == "membership":` (~704). Chép đúng cách mode `membership` truyền
  `commit_guard`, `cancel_event`, `progress`, `operation_id`.
- `src/api/product/scene.py`: route `membership/regenerate` (~362) là mẫu cho route mới.
- `tests/test_api/test_role_matrix.py`: phải khai báo route mới.
- Frontend type `ObjectifyMode` trong `frontend/src/lib/api/studio.ts` (T-013 sẽ dùng; task này chỉ cập nhật type).

## Files
- Sửa: `src/services/orchestration/scene/objectify_queue.py`
- Sửa: `src/api/product/scene.py`
- Sửa: `src/services/orchestration/scene/extraction.py` (chế độ `auto`)
- Sửa: `tests/test_api/test_role_matrix.py`
- Sửa: `frontend/src/lib/api/studio.ts` (chỉ thêm `"geometry"` vào `ObjectifyMode`)
- Test: `tests/test_orchestration/test_scene_objectify_queue.py`, `tests/test_api/test_scene_v2_routes.py`

## Interfaces
```
POST /api/v1/jobs/{job_id}/scene/geometry/build
body: {"expected_scene_revision": "rev-003"}
202 → ObjectifyState {status: "queued", mode: "geometry", operation_id, base_revision, phase: null}
409 → revision lệch hoặc đang có việc objectify khác chạy
422 → scene không ở trạng thái awaiting_review (code "OBJECT_GEOMETRY_ALREADY_READY")
```
Guard: `Depends(require_contributor)` + `authorize_job_mutation(user, registry, job_id, operation="tạo hình học vật của")`.
Phase gửi qua `progress`: `shell`, `quality`, `collider`, `objectgs`, `environment`, `publish` (ghi vào `ObjectifyState.phase`).

## Steps
1. Thêm `"geometry"` vào `ObjectifyMode`; `request()` chấp nhận mode này, kiểm scene `awaiting_review` và revision.
   Ước lượng tài nguyên: `geometry` với `geometry_method=shell` chỉ cần CPU + GPU nhỏ cho inpaint (dùng profile như mode
   `boxes` nếu có; nếu không, profile `gpu_required=True` với VRAM như inpaint). Test. Commit.
2. Worker: nhánh `elif running.mode == "geometry":` gọi `build_object_geometry(registry, settings, job_id,
   expected_revision=running.base_revision, workspace=…, commit_guard=…, cancel_event=…, progress=…)`.
   Lỗi `ObjectGeometryBuildError` → state `failed`, `error` = thông điệp (có tên vật), `retryable` theo lỗi. Test. Commit.
3. Route API + role matrix + test 202/409/422. Commit.
4. Chế độ `auto`: trong `extract_scene`, sau khi publish Draft, nếu job config `geometry_review == "auto"`, gọi
   `objectify_queue.request(..., mode="geometry", expected_revision=<rev mới>)` (dùng actor hệ thống như các nơi khác).
   Test: job `auto` → có việc `geometry` queued ngay sau tách vật. Commit.
5. Frontend type. `npm run typecheck`. Commit.

## Acceptance criteria
1. POST build trên Draft → 202, state queued, `mode == "geometry"`.
2. Worker chạy xong → `result_revision` mới, scene `ready`; phase đi qua đúng thứ tự (ghi lại trong test bằng callback).
3. Huỷ bằng `objectify/cancel?operation_id=…` khi đang chạy → `cancelled`, scene giữ revision Draft.
4. Lỗi build (vỏ lỗi) → `failed`, `error` chứa tên vật, scene giữ Draft; gửi lại POST sau khi sửa → chạy được (retry).
5. POST khi scene đã `ready` → 422; revision sai → 409; đang có job objectify khác → 409.
6. Route mới có trong role matrix; người chưa đăng nhập → 401/403 theo quy ước hiện có.
7. Job `auto` tự xếp build sau tách vật; job `required` thì không.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py \
  tests/test_api/test_role_matrix.py tests/test_orchestration/test_scene_extraction.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
cd frontend && npm run typecheck
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
UI (T-013). Rebuild một phần (T-011).
