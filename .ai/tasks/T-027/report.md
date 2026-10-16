# Report T-027

## Done
- **Step 1 — migration 20 + nhật ký sự kiện** (`22d4b892`): bảng `r2s_value_events` và index `(job_id, at)`. `record_event` ghi, lỗi bị log warning rồi bỏ qua. `list_events` trả theo `at` tăng dần, lọc theo `kinds`.
- **Step 2 — phân loại thao tác** (`654455ff`): `HUMAN_OPERATIONS`, `SYSTEM_OPERATIONS`, `operation_origin`. Test quét AST `src/` lấy mọi literal truyền vào `publish_next` và `_publish_reserved` (vị trí thứ 4), cộng các giá trị `ObjectAction` đi qua biến `action`. Test đỏ nếu có thao tác chưa phân loại.
- **Step 3 — ghi `scene_edit`** (`58b9778a`): `publish_next` ghi sau khi `_publish_reserved` thành công. `apply` (Move/Rotate) cũng ghi, xem Deviations. CAS thất bại không ghi gì. Lỗi ghi nhật ký không làm hỏng publish.
- **Step 4 — route và role matrix** (`c60a4aab`): `POST /jobs/{job_id}/value-events/operator-time` và `/walk-session` trong `src/api/studio/value.py`, đăng ký trong `src/api/studio/__init__.py` cùng nhóm `require_contributor`. Route kiểm quyền sở hữu job (`authorize_job_mutation`), 404 khi job không tồn tại, từ chối 422 đúng 5 luật, `actor_id` lấy từ người đăng nhập, bỏ qua `actor_id` trong body. Trả 204.

## Files changed
- `src/services/orchestration/jobs/database.py`: migration 20 (`r2s_value_events`).
- `src/services/orchestration/value/__init__.py`: export gói value.
- `src/services/orchestration/value/events.py`: `ValueEvent`, `record_event`, `list_events`, bảng phân loại, `operation_origin`.
- `src/services/orchestration/scene/editor.py`: `_record_scene_edit`, gọi từ `publish_next` và `apply`.
- `src/api/studio/value.py`: router hai route, model lô, kiểm luật.
- `src/api/studio/__init__.py`: đăng ký router `value`.
- `tests/test_orchestration/test_value_events.py`: sự kiện, phân loại, ghi `scene_edit`.
- `tests/test_api/test_value_routes.py`: quyền, 404, 401, 5 luật, actor, lỗi ghi.
- `tests/test_api/test_role_matrix.py`: thêm hai route vào `AUTHENTICATED`.
- `tests/test_orchestration/test_runtime_migrations.py`: `LATEST_SCHEMA_VERSION == 19` đổi thành `20` (hai chỗ).

## Tests
Lệnh chạy và kết quả thật:
- `.venv/bin/python -m pytest tests/test_orchestration/test_value_events.py tests/test_api/test_value_routes.py tests/test_api/test_role_matrix.py tests/test_orchestration/test_scene_editor.py -q` → **70 passed**.
- `.venv/bin/python -m pytest tests/test_orchestration/test_scene_editor.py tests/test_orchestration/test_scene_head.py tests/test_orchestration/test_value_events.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_scene/test_object_correction.py tests/test_scene/test_object_region.py tests/test_orchestration/test_collision_source_selection.py -q` → **173 passed** (trước khi thêm route).
- `.venv/bin/python -m pytest tests/test_api/test_guest_ownership.py tests/test_api/test_studio_routes.py -q` → **95 passed**.
- `.venv/bin/python -m pytest tests/test_orchestration/test_runtime_migrations.py -q` → passed (cùng lần chạy đầu với events).
- `.venv/bin/ruff check src tests` → All checks passed.
- `.venv/bin/ruff format --check src tests` → 677 files already formatted.
- Không chạy full suite (README mục 4).

## Deviations from plan
1. **`apply()` cũng ghi `scene_edit`** (`transform_edit`, origin `human`). Plan chỉ nói `publish_next`, nhưng Move/Rotate đi qua `apply` (`src/api/product/scene.py:112`), và đó là thao tác người dùng chính cho P3. Nếu chỉ ghi ở `publish_next`, mọi chỉnh sửa vật sẽ không xuất hiện trong nhật ký. Mục Goal của plan nói "khi publish revision", nên tôi chọn ghi cả hai đường. Architect cần xác nhận.
2. **`publish_initial` được phân loại `system` nhưng không ghi sự kiện** vì revision đầu không phải thao tác chỉnh sửa.
3. **Đường dẫn test editor**: plan ghi `tests/test_scene/test_scene_editor.py`, file thật là `tests/test_orchestration/test_scene_editor.py`. Đã dùng file thật.
4. **Không có vai trò Viewer** (`Role = guest | editor | reviewer`). Plan yêu cầu "Viewer 403". Thay bằng hai test: Guest trên job của người khác → 403, và không đăng nhập khi bật auth → 401.
5. **Cập nhật số phiên bản trong test migration** (19 → 20) là hệ quả trực tiếp của migration 20.

## Known issues / TODO
- **`actor_id` của `scene_edit` luôn là `None`**: `publish_next` và `apply` không nhận người gọi. Chỉ `origin` được ghi. Nếu cần biết ai thao tác, phải truyền actor vào editor (thay đổi chữ ký, chưa làm).
- **Bảng `r2s_value_events` không có FK tới `r2s_jobs`**: plan không yêu cầu. Thiếu ràng buộc này có nghĩa là sự kiện có thể trỏ tới job không tồn tại.
- **Lỗi đọc khi kiểm chồng lô** (`_previous_batch_end`) không bị nuốt: DB lỗi thì route trả 500. Chỉ lỗi ghi được nuốt, đúng yêu cầu.
- **Audit noise**: editor/reviewer gửi lô thời gian cho job của người khác sẽ tạo một dòng `operator.intervention` trong audit mỗi lô (hành vi có sẵn của `_authorize_owner`). Có thể gây nhiễu, nên cân nhắc khi làm T-029.
- **Chưa có kiểm thử PostgreSQL** cho migration 20 và `list_events` (bảng `r2s_value_events` và câu `IN (?)` chỉ được kiểm trên SQLite).
- `frontend` chưa đụng tới (T-029).
