# Report T-012

## Done

- **Step 1 — `1cd7a859`**: `SceneEditor.apply()` (lệnh `TransformEdit`, `POST /jobs/{id}/scene/edits`) gọi
  `require_geometry_ready(scene, "di chuyển/xoay vật")` sau kiểm revision, trước khi dựng revision mới.
  `edit_collider_scene()` gọi `require_geometry_ready(scene, "sửa collider")` ở cùng vị trí. Scene Draft: Move/Rotate và
  sửa collider bị từ chối bằng `ObjectGeometryNotReadyError` (HTTP 422 theo mapping `SceneError` sẵn có), không publish revision.
- **Step 2 — `00404b8b`**: `GET /jobs/{id}/walk-collision/{filename}` gọi `_require_walk_allowed()` trước
  `resolve_artifact`, không phụ thuộc `scene_revision`. Scene Draft → 409 `{"detail": "Cần tạo mesh trước khi Walk."}`.
- **Step 3 — `3f417bd3`**: `build_simulation_package()` gọi `require_geometry_ready(current.scene, "xuất USD")` ngay sau khi
  đọc revision, trước `_recover_legacy_source_ownership` (hàm này có thể publish). `POST /jobs/{id}/simulation-package` →
  409 `{"detail": "Cần tạo mesh trước khi xuất USD."}`, không publish revision.
- Không đổi hành vi: Confirm, Ignore, Hide/Show, Delete, Restore, đổi tên (`apply_object_action`), region preview/apply,
  `GET simulation-package`, `GET .../simulation-package/download`. Scene ready hoặc legacy (không có khoá
  `object_geometry`) đi qua như trước.

## Files changed

- `src/services/orchestration/scene/editor.py`: gate transform trong `apply()`.
- `src/services/orchestration/scene/objects.py`: gate collider trong `edit_collider_scene()`.
- `src/api/product/artifacts.py`: `_require_walk_allowed()`, gate walk, nhánh 409 cho `ObjectGeometryNotReadyError` trong `get_walk_collision`.
- `src/services/orchestration/review/simulation_package.py`: gate trong `build_simulation_package()`.
- `tests/test_orchestration/test_scene_editor.py`: Draft từ chối transform và giữ revision; Draft giữ các thao tác duyệt.
- `tests/test_scene/test_collider_edit.py`: Draft từ chối sửa collider trước mọi thay đổi.
- `tests/test_api/test_scene_v2_routes.py`: Draft move/collider → 422 không publish; Draft walk (có và không `scene_revision`) → 409; Draft POST simulation-package → 409 không publish.
- `tests/test_api/test_scene_routes.py`: scene headless hỏng → walk 409 cùng câu người dùng với các route scene khác.
- `tests/test_orchestration/test_simulation_package.py`: Draft từ chối xuất USD trước khi khôi phục quyền sở hữu hoặc publish.
- `.ai/tasks/T-012/report.md` (mới), `.ai/status.md` (chỉ dòng T-012).

## Tests

```
.venv/bin/python -m pytest tests/test_scene/test_geometry_state.py tests/test_api/test_scene_v2_routes.py \
  tests/test_orchestration/test_scene_editor.py tests/test_scene/test_collider_edit.py \
  tests/test_orchestration/test_simulation_package.py tests/test_api/test_role_matrix.py \
  tests/test_scene/test_effective_collision.py tests/test_api/test_scene_routes.py -q
→ 162 passed in 15.66s
```

Baseline trước khi sửa (7 file, không có `test_scene_routes.py`): 122 passed.

Caller của `build_simulation_package` (nằm trên đường gate, ngoài danh sách bắt buộc):

```
.venv/bin/python -m pytest tests/test_orchestration/test_simulation_package.py tests/test_api/test_scene_v2_routes.py \
  tests/test_orchestration/test_review_workflow.py tests/test_simulation/test_object_aware_usd.py \
  tests/test_simulation/test_simulation_config_override.py tests/test_simulation/test_isaac_process.py -q
→ 108 passed in 26.75s
.venv/bin/python -m pytest tests/test_api/test_studio_routes.py -k simulation -q
→ 2 passed
```

Lint (9 file đã sửa):

```
.venv/bin/ruff check <9 file>          → All checks passed!
.venv/bin/ruff format --check <9 file> → 9 files already formatted
graphify update .                      → exit 0 (graph.json, GRAPH_REPORT.md; thư mục bị gitignore)
```

Không chạy full test suite.

## Deviations from plan

- **Gate simulation ở builder, không ở route**: plan ghi sửa `src/api/studio/simulation.py`. Không cần đổi vì route đã map
  `SceneError` → 409 với `detail=str(error)`, nên câu của gate đến thẳng client. Gate đặt trong
  `build_simulation_package()` để chặn mọi đường vào builder và chạy trước khôi phục quyền sở hữu (có thể publish).
  Route là caller duy nhất trong `src/`.
- **Walk không phụ thuộc `scene_revision`**: plan không nói rõ. Studio gửi walk URL không kèm `scene_revision` khi preview,
  nên gate chỉ theo revision sẽ để lọt raw preview. Gate đọc scene hiện tại của job.
- **Fail-closed khi head không đọc được**: `SceneHeadNotReadyError` trên walk → 409 với `user_message`. Trước đây preview
  thô trả 200 khi không kèm revision; có revision thì trả nguyên thông điệp vận hành trong `detail`. Job không có SceneIR
  (`SceneNotAvailableError`, preview tái dựng) vẫn giữ đường cũ. Đây là thay đổi hành vi có chủ đích.
- **Thông điệp collider khác**: `edit_collider_scene()` dùng `"sửa collider"` thay vì `"di chuyển/xoay vật"`, để câu trả
  về đúng thao tác. Transform giữ `"di chuyển/xoay vật"`.
- **Test ngoài danh sách**: `tests/test_api/test_scene_routes.py` (walk trên scene headless), vì route walk và helper
  headless nằm ở đó.
- **Status**: chuyển thẳng `planned` → `implemented`, không có commit `in-progress` riêng.

## Known issues / TODO

- **UI chưa khoá (T-013, ngoài phạm vi)**: Studio vẫn gửi Walk/USD trên Draft; người dùng sẽ thấy lỗi 409 với câu
  "Cần tạo mesh trước khi …" cho tới khi T-013 khoá nút.
- **Chưa gate, không nằm trong bảng plan, cần Architect quyết**: `add_box_object`, `add_catalog_object`,
  `duplicate_object`, `set_object_semantics` (nhãn), `edit_collision_surfaces`, `restore_revision` (hoàn tác).
  Riêng `restore_revision` lấy `provenance` từ revision đích, nên hoàn tác về revision cũ không có khoá `object_geometry`
  (hoặc `ready`) có thể đưa scene Draft về ready mà không qua bước tạo mesh.
- Walk trên job có SceneIR nhưng chưa nhận head sẽ kích hoạt nhận head (ghi head vào DB) như các route GET scene khác.
  Hành vi có sẵn của `registry.scene.current`, không mới.
- Working tree có thay đổi của phiên khác, không thuộc T-012: `tests/test_scene/test_object_geometry_build.py` (đang sửa),
  `BRAINSTORM.md` và `MASTER_PITCH.md` (chưa track), các `tasks/CFG-*` đã xoá. Không stage các mục này; mỗi commit T-012
  chỉ gồm đường dẫn của T-012.

## Round 2

Làm theo Required changes 1–4 của `review.md`.

**Quyết định cho thao tác ngoài bảng** (theo review; mục "Chưa gate" ở Round 1 đã được chốt):

| Thao tác | Draft | Cài đặt |
| --- | --- | --- |
| Thêm box (`add_box_object`) | Chặn: `"thêm vật"` | Gate ngay sau kiểm revision, trước khi ghi GLB |
| Thêm asset catalog (`add_catalog_object`) | Chặn: `"thêm vật từ thư viện"` | Gate ngay sau kiểm revision, trước khi ghi GLB |
| Nhân bản (`apply_object_action`, action `duplicate`) | Chặn đúng action: `"nhân bản vật"` | Gate trong nhánh `duplicate`; confirm/ignore/hide/delete/restore/rename/label vẫn chạy |
| Sửa bề mặt va chạm (`edit_collision_surfaces`) | Chặn: `"sửa bề mặt va chạm"` | Gate sau kiểm revision, áp cho mark, fill và remove |
| Khôi phục revision (`restore_revision`) | Cho phép | Không đổi code, chỉ thêm test |
| Gán nhãn (`label`) | Cho phép | Không đổi code |

**Files changed (Round 2)**
- `src/services/orchestration/scene/objects.py`: gate trong `add_box_object()`, `add_catalog_object()` và nhánh `duplicate` của `apply_object_action()`.
- `src/services/orchestration/scene/collision_surfaces.py`: gate trong `edit_collision_surfaces()`.
- `tests/test_api/test_scene_v2_routes.py`: 4 test route.
- `tests/test_orchestration/test_scene_editor.py`: 2 test `restore_revision`.

**Test**
- Route (Required change 2): mỗi test làm request trên scene ready trước (201), rồi chuyển sang Draft. Request với revision hiện tại bị 422 với `detail` đúng, và không có revision mới được publish:
  - `POST /scene/objects` → `Cần tạo mesh trước khi thêm vật.`
  - `POST /scene/catalog-objects` → `Cần tạo mesh trước khi thêm vật từ thư viện.`
  - `POST /scene/objects/{id}/duplicate` → `Cần tạo mesh trước khi nhân bản vật.`
  - `POST /scene/collision-surfaces` → `Cần tạo mesh trước khi sửa bề mặt va chạm.`
- Restore (Required change 3), trên `SceneEditor` trực tiếp:
  - Ready → Draft: `restore_revision` đưa `object_geometry` về `awaiting_review`.
  - Draft → Ready: `object_geometry` là `ready`; collider của vật pallet, `membership` và `object_aware_collision_ref` khớp revision đích.
  - Scene đích object-aware được dựng như helper ở `tests/test_contracts/test_object_geometry.py`, vì validator yêu cầu `membership` và `collider_ref` đi kèm `object_aware_collision_ref`.
- Chạy lại (Required change 4): 16 file test gồm 8 file của Round 1 cùng `test_collision_surfaces.py`, `test_object_restore.py`, `test_editing_review.py`, `test_release_sealing_recovery.py`, `test_review_workflow.py`, `test_demo_routes.py`, `test_editing_v2.py`, `test_collision_edit_composition.py`: **276 passed in 27.38s**.
- `ruff check` và `ruff format --check` sạch trên 4 file đã sửa. `graphify update .`: exit 0.

**Commit**
- `558c164b` — Refuse adding objects, duplicating and editing collision surfaces on a scene awaiting geometry review.
- `f3e79825` — Cover restore_revision across Draft and ready revisions.

**Ghi chú**
- Gate của `edit_collision_surfaces` áp cho cả `remove` và `fill`, không chỉ `mark`: review ghi "sửa collision surfaces" nên chặn mọi thao tác sửa.
- Thêm box và thêm asset chặn trước khi ghi GLB, nên request bị từ chối không để lại artifact nào.

**Known issues còn lại**
- Studio vẫn gửi Walk/USD khi Draft tới T-013 (đã chấp nhận theo review).
- `restore_revision` có thể đưa scene Draft về `ready` mà không qua tạo mesh; đây là quyết định của review và đã có test.
