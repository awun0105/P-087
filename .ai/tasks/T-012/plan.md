# T-012: Khoá Walk/USD/Move/Rotate khi Draft

## Goal
Khi scene `awaiting_review`, backend từ chối rõ ràng các thao tác cần hình học, để không ai Walk hay xuất USD trên
scene chưa có collider vật. Các thao tác duyệt vẫn được phép.

## Context
`architecture.md` §7.1, §9. Helper `require_geometry_ready(scene, action)` (T-003, `src/services/scene/geometry_state.py`).

| Thao tác | Draft |
| --- | --- |
| Confirm, Ignore, Hide/Show, Delete, Restore, đổi tên, region preview/apply | Cho phép |
| Move, Rotate (đổi `transform`), sửa collider tay | **Từ chối** |
| Walk collision (`GET /jobs/{id}/walk-collision/...`) | **Từ chối** (409) |
| Simulation package / USD (`POST /jobs/{id}/simulation-package`) | **Từ chối** (409) |

## Files
- Sửa: `src/services/orchestration/scene/editor.py` (nơi áp lệnh transform/collider; dùng `codegraph_explore SceneEditor`
  để tìm hàm áp từng action)
- Sửa: `src/api/product/artifacts.py` (`get_walk_collision`, ~dòng 111)
- Sửa: `src/api/studio/simulation.py` (POST simulation-package, ~dòng 41)
- Test: `tests/test_scene/test_geometry_state.py`, test editor hiện có (`tests/test_orchestration/test_scene_editor*.py`
  hoặc tương đương — tìm bằng grep tên `SceneEditor`), `tests/test_api/test_scene_v2_routes.py`,
  test simulation package hiện có.

## Steps
1. Trong SceneEditor: trước khi áp lệnh làm đổi `transform` hoặc `collider`, gọi `require_geometry_ready(scene, "di chuyển/xoay vật")`.
   Lỗi trả về client như các `SceneEditRejectedError` khác (giữ HTTP code đang dùng cho lỗi này, thường 409/422). Test. Commit.
2. Walk collision route: scene `awaiting_review` → 409, body `{"code": "OBJECT_GEOMETRY_NOT_READY", "message": "Cần tạo mesh trước khi Walk"}`
   (theo định dạng lỗi API hiện có). Test. Commit.
3. Simulation package POST: tương tự, message "Cần tạo mesh trước khi xuất USD". Test. Commit.

## Acceptance criteria
1. Draft: lệnh Move/Rotate → bị từ chối với code `OBJECT_GEOMETRY_NOT_READY`; scene không đổi.
2. Draft: Confirm/Ignore/Hide/Delete/Restore → thành công như cũ.
3. Draft: walk-collision và simulation-package → 409 code đúng.
4. Scene ready hoặc scene cũ (không có khóa) → mọi thao tác như trước (test cũ PASS).

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_geometry_state.py tests/test_api/test_scene_v2_routes.py \
  <test SceneEditor hiện có> <test simulation package hiện có> tests/test_api/test_role_matrix.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
UI khoá nút (T-013).
