# Report T-030: Ground truth của benchmark

## Done
- **Step 1 (model + validator):** `BenchmarkTruth` và các model con (`RobotProfile`, `MeasuredDistance`, `GapCheck`,
  `LayoutRef`, `L4Declaration`) trong `value/ground_truth.py`. Validator: `height_min_m < height_max_m`; `|b−a|` của khe
  trong [0.1, 10] m; `a ≠ b` cho đoạn đo; id không trùng giữa `distances` và `gaps`; `key_obstacle_ids` không trùng.
- **Step 2 (migration 21 + CAS):** migration 21 tạo `r2s_benchmark_truth(job_id, version, payload)`. Hai hàm
  `read_truth` và `write_truth`. `write_truth` là CAS: khớp `expected_version` thì ghi với version + 1, lệch thì
  raise `TruthVersionConflictError`. Hai assert `LATEST_SCHEMA_VERSION == 20` đổi thành 21.
- **Step 3 (route + role matrix):** `GET /api/v1/jobs/{job_id}/benchmark-truth` trả `{version, truth, updated_at}`. Job
  chưa có tài liệu trả version 0 và giá trị mặc định, không 404. `PUT` kiểm quyền như route sửa job (`authorize_job_mutation`),
  kiểm tham chiếu (422 với thông điệp tiếng Việt nêu đúng mục sai), rồi ghi CAS (409 khi lệch version).
  Hai route được khai báo trong `AUTHENTICATED` của `test_role_matrix.py`.

## Files changed
- `src/services/orchestration/value/ground_truth.py`: model, validator, CAS repository (tạo mới).
- `src/services/orchestration/jobs/database.py`: thêm migration 21 (hunk duy nhất, không đụng migration khác).
- `src/api/studio/value.py`: hai route benchmark-truth; tách `_job_exists`; `_authorize` nhận tham số `operation`
  (mặc định giữ nguyên hành vi cũ).
- `tests/test_orchestration/test_benchmark_truth.py`: 14 test model + 5 test CAS (gồm ghi đồng thời bằng hai luồng).
- `tests/test_orchestration/test_runtime_migrations.py`: hai assert 20 → 21.
- `tests/test_api/test_value_routes.py`: 6 test route mới (thêm vào cuối, không sửa test có sẵn).
- `tests/test_api/test_role_matrix.py`: khai báo GET và PUT benchmark-truth.

## Tests
Lệnh trong plan (kết quả thật, lần chạy cuối):
```
.venv/bin/python -m pytest tests/test_orchestration/test_benchmark_truth.py tests/test_api/test_value_routes.py tests/test_api/test_role_matrix.py tests/test_orchestration/test_runtime_migrations.py -q
→ 60 passed

.venv/bin/ruff check src tests                      → All checks passed!
.venv/bin/ruff format --check <các file đã sửa>      → 9 files already formatted
.venv/bin/python scripts/check_contract_mirror.py   → PASS
```
Ghi chú: `ruff format --check src tests` toàn bộ báo 1 file chưa format là
`tests/test_orchestration/test_scene_objectify_queue.py`. File này do agent T-028 đang sửa trong working tree, không thuộc
T-030 nên không đụng.
Test đồng thời (`test_concurrent_writers_from_the_same_version_yield_one_winner`) chạy 3 lần liên tiếp, đều pass.

## Commits
- `f5aeebdb` Start T-030 benchmark ground truth (status: in-progress)
- `484ed240` Validate benchmark ground truth models: robot heights, gap spans, unique ids
- `60c02e64` Store benchmark ground truth per job with compare-and-set versioning
- `d93bd35d` Expose benchmark ground truth GET and versioned PUT routes for jobs

## Deviations from plan
1. **`extra="forbid"` trên mọi model con**, không chỉ `BenchmarkTruth`. Lý do: nếu không, một khoá gõ sai trong
   `distances` bị âm thầm bỏ rồi PUT ghi tài liệu thiếu dữ liệu.
2. **Các trường danh sách có `default_factory`** (`distances`, `gaps`, `key_obstacle_ids`, `layouts`), không bắt buộc như
   plan ghi. Lý do: GET phải trả "giá trị mặc định" khi job chưa có tài liệu; `BenchmarkTruth()` cần chạy được.
3. **`updated_at` không có cột riêng.** Bảng giữ đúng schema plan
   `(job_id, version, payload)`. `updated_at` nằm trong JSON của `payload` cùng với `truth`.
4. **Thêm validator** ngoài plan: đoạn đo phải có `a ≠ b` (không tính được khoảng cách 0); `key_obstacle_ids` không trùng id.
5. **Tạo lần đầu dùng `ON CONFLICT(job_id) DO NOTHING`** và kiểm `rowcount`. Lý do: trên PostgreSQL, hai ghi tạo lần đầu cùng
   lúc sẽ gây lỗi unique 500 thay vì 409.
6. **Hành vi khi job chưa có scene** (plan không nói): nếu PUT có `layouts` hoặc `key_obstacle_ids` mà job không đọc được scene,
   trả 422 với thông điệp "job chưa có scene đọc được nên chưa đối chiếu được…". Không trả 500.
7. **Thứ tự kiểm trong PUT:** quyền → tham chiếu (422) → CAS (409). Nếu vừa lệch version vừa sai tham chiếu thì trả 422.

## Known issues / TODO
- **Postgres chưa được kiểm thử.** Môi trường test chỉ có SQLite. Nhánh `FOR UPDATE` (`lock_suffix`) và `ON CONFLICT` chưa chạy
  thật trên PostgreSQL.
- **Test tham chiếu dùng `as_user(None)`.** Với người dùng có vai trò, `authorize_job_mutation` gọi `auth_service().audit()` khi
  job không có chủ sở hữu, và audit ghi vào database cấu hình sẵn (PostgreSQL trong môi trường này). Vì vậy test gọi ở chế độ
  không đăng nhập, giống workspace cục bộ. Quyền ghi của Guest với job không có chủ được kiểm bằng `test_foreign_guest_can_read_but_not_write_the_truth`.
- **Phụ thuộc T-027.** T-030 dựa trên `value/__init__.py`, `api/studio/value.py` và `tests/test_api/test_value_routes.py` của T-027,
  mà T-027 đang ở trạng thái `changes-requested`. Nếu review T-027 đổi các file này thì có thể xung đột khi rebase.
- Không có việc nào còn dở trong phạm vi plan.
