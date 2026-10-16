# T-028: Đo thời gian máy cho hàng đợi tách vật

## Goal
Tách lại, Tạo mesh, dựng lại vùng, Brush/Lasso chạy trong `objectify_queue` hiện **không** ghi `ResourceUsage`, nên phút máy của
job đếm thiếu. Ghi `ResourceUsage` cho mọi mode để `processing_seconds` và benchmark tính đủ.

## Context
§15.2. `processing/telemetry.py`: `ResourceSampler`, `sampled_section(sampler, on_error=...)`, `ResourceUsage` (có `gpu_name`,
`attempt_id`, `tool`, `config_checksum`, `runtime_manifest_checksum`). Cách job runner ghi: `jobs/runner.py:~300`.
`observed.processing_seconds` lấy lượt chạy xong mới nhất theo `(job_id, tool)`.

## Files
- Sửa: `src/services/orchestration/scene/objectify_queue.py` (vòng chạy worker, quanh khối `if running.mode in {...}` ~dòng 760)
- Sửa (nếu cần): `src/services/orchestration/processing/observed.py`
- Test: `tests/test_orchestration/test_scene_objectify_queue.py`, `tests/test_orchestration/test_observed_budget.py`

## Steps
1. Bọc phần chạy của mỗi mode trong `sampled_section` với sampler như runner; khi xong ghi `ResourceUsage(tool=f"scene.{mode}",
   attempt_id=operation_id, outcome=completed|failed|cancelled, duration_seconds, gpu_name, ...)` vào cùng bảng usage.
   Ghi lỗi đo không làm hỏng việc chạy. Commit.
2. `processing_seconds`: các lượt `scene.*` **cộng dồn từng lượt** (mỗi lần Tạo mesh hay dựng lại vùng là một việc thật), không
   chỉ lấy lượt mới nhất như tool của pipeline. Ghi rõ quy tắc trong docstring + test. Commit.

## Acceptance criteria
1. Một lần Tạo mesh (test double) tạo đúng 1 `ResourceUsage` `scene.geometry` có `duration_seconds > 0`.
2. Hai lần dựng lại vùng → `processing_seconds` cộng cả hai; tool pipeline vẫn chỉ lấy lượt mới nhất.
3. Huỷ / lỗi ghi `outcome` tương ứng, không cộng vào `processing_seconds` (chỉ `completed`).
4. Lỗi đo (sampler raise) không làm hỏng việc dựng.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_observed_budget.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
