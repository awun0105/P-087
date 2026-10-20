# T-055: Một hàm trạng thái hình học theo vật

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Mọi chỗ đọc `provenance["object_geometry"]` của SceneIR cho cùng một câu trả lời. Scene cũ thiếu khoá được hiểu là "không có
bước duyệt vật, coi như đã xong" ở mọi nơi.

## Context (đã kiểm trong code)
- `src/services/scene/geometry_state.py:11` — `object_geometry_state(scene)`: thiếu khoá → `"ready"`; giá trị lạ (kể cả
  `None` tường minh) → `ValueError`. Là cổng chặn thao tác ở ~15 chỗ (scorecard, object_region, object_geometry_build,
  extraction, editor, simulation_package…). Test: `tests/test_scene/test_geometry_state.py`.
- `scene/objectify_queue.py:138` — `object_geometry_status(provenance)`: thiếu khoá hoặc `None` → `None`; giá trị lạ →
  `"awaiting_review"`. Dùng ở `state()` (dòng 327) và `src/api/studio/scenes.py:345`.
- `jobs/stage_results.py:160-194` mã hoá lần thứ tư thành `pending/succeeded/failed` và **tự đọc SQL** bảng
  `r2s_scene_requests` (dòng 171-172), lặp quy tắc của `geometry_review()` (`objectify_queue.py:150-177`).
- Frontend `frontend/src/lib/scene/geometry-state.ts:196` coi thiếu khoá là `ready`.

## Thiết kế
Trong `src/services/scene/geometry_state.py`:
- Giữ `object_geometry_state(scene)` làm cổng chặt; đổi duy nhất: `None` tường minh coi như thiếu khoá → `"ready"`.
- Thêm `def object_geometry_view(scene: SceneIR) -> ObjectGeometryState | None` cho mọi chỗ **hiển thị**: thiếu khoá hoặc
  `None` → `None`; hai giá trị hợp lệ → giữ; giá trị lạ → `"awaiting_review"` kèm `logger.warning` có `scene_revision`.
  Không bao giờ ném.
- Thêm `def has_geometry_review(scene: SceneIR) -> bool` = `object_geometry_view(scene) is not None`.

Thay thế:
- Xoá `objectify_queue.object_geometry_status`; `state()` và `scenes.py:345` dùng `object_geometry_view`. Kiểu
  `ObjectGeometry` trong `objectify_queue.py` thành alias của `ObjectGeometryState`.
- `stage_results.py`: lấy trạng thái từ `object_geometry_view`; "failed" dùng
  `objectify_queue.geometry_review(settings, job_id, state, scene_revision) == "failed"` thay câu SQL tự viết.

## Steps
1. `tests/test_scene/test_geometry_state.py`: bỏ `None` khỏi parametrize của `test_unknown_geometry_state_is_an_error`;
   thêm `test_explicit_none_is_treated_as_legacy_ready`, `test_view_returns_none_for_legacy_scene` (thiếu khoá và `None`),
   `test_view_returns_explicit_states`, `test_view_locks_unknown_value_as_awaiting_review` (`"building"` →
   `"awaiting_review"`, có log), `test_has_geometry_review`. FAIL. Cài. PASS. Commit
   `refactor(scene): add a single display view of object geometry state`.
2. Thay ở `objectify_queue.py`, `scenes.py`; sửa test gọi hàm cũ. Commit `refactor(scene): read object geometry state through one helper`.
3. `stage_results.py` + `test_stage_results_geometry_failed_matches_geometry_review` (Draft + yêu cầu geometry `failed`
   đúng revision → `"failed"`; revision khác → `"pending"`). Test stage results hiện có xanh. Commit.

## Acceptance criteria
1. Chỉ còn `object_geometry_state` (cổng) và `object_geometry_view` (hiển thị) đọc khoá.
2. Không còn SQL đọc `r2s_scene_requests` ngoài `objectify_queue.py`.
3. Scene cũ thiếu khoá: không có bước duyệt, cổng cho qua.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_geometry_state.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_routes.py tests/test_api/test_scene_v2_routes.py <test stage_results> -q
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
