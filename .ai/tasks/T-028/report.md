# Report T-028

## Done

- **Step 1 (tách helper, không đổi hành vi):** `_resource_sampler` và `_persist_usage` đã tách sang
  `processing/usage_recording.py` (`build_sampler`, `record_usage`). `runner.py` gọi hai hàm này. Test cũ của runner xanh.
- **Step 2 (đo trong queue):** mọi mode của `process_next` (`objectify`, `boxes`, `membership`, `geometry`, `region`) chạy
  trong `sampled_section`, ghi `ResourceUsage` tool `scene.<mode>`, `attempt_id = request.operation_id`. Quy đổi outcome:
  `done`→`completed`, `cancelled`→`cancelled`, `failed` (kể cả lease lost / reservation lost)→`failed`. Lỗi đo được log, không đổi
  kết quả. Bản ghi được ghi trong `finally`, sau khi sampler đã dừng.
- **Step 3 (`processing_seconds`):** tool `scene.*` cộng dồn mọi lượt `completed`; tool pipeline giữ quy tắc lượt mới nhất.
  Docstring ghi rõ hai quy tắc.

## Files changed

- `src/services/orchestration/processing/usage_recording.py`: mới. `build_sampler`, `record_usage` (tách từ runner).
- `src/services/orchestration/jobs/runner.py`: dùng `build_sampler` / `record_usage`; `_persist_usage` còn là wrapper mỏng.
- `src/services/orchestration/scene/objectify_queue.py`: `_scene_sampler`, `_record_scene_usage`, bọc dispatch bằng
  `sampled_section`, ghi bản ghi trong `finally`.
- `src/services/orchestration/processing/observed.py`: `processing_seconds` theo hai quy tắc.
- `tests/test_orchestration/test_scene_objectify_queue.py`: 5 test mới (region theo 3 outcome, geometry, sampler lỗi,
  sampler `None`).
- `tests/test_orchestration/test_observed_budget.py`: 2 test mới (cộng dồn `scene.*`; `scene.*` không đổi ngân sách).

## Commits

- `8672c5c4` / `11ef9f1d` (của người khác): dòng T-028 đã là `in-progress | engineer` trong HEAD. Tôi không tạo commit
  riêng cho bước này; lần commit của tôi bị bỏ qua vì nội dung đã có sẵn.
- `47f05aa0` Move resource sampler and usage recording into a shared module (Step 1)
- `cc5116e1` Record a resource usage for every scene objectify queue run (Step 2)
- `7ef5123d` Sum completed scene steps in processing seconds (Step 3)
- `1f70a1d4` Test that a geometry build records one scene.geometry usage (test bổ sung cho AC 1)

## Acceptance criteria

1. Tạo mesh (`geometry`) ghi đúng 1 `scene.geometry`, `completed`, `duration_seconds > 0`: **pass**
   (`test_geometry_build_records_one_scene_geometry_usage`).
2. Hai lần dựng lại vùng cộng cả hai; tool pipeline chỉ lấy lượt mới nhất: **pass ở mức hàm**
   (`test_scene_steps_add_up_across_runs_while_pipeline_tools_keep_the_latest`, dữ liệu giả). Chưa có test chạy hai lần
   `process_next` thật.
3. Huỷ/lỗi ghi `cancelled`/`failed` và không cộng: **pass** (test tham số hoá region + test hàm `processing_seconds`).
4. Lỗi đo không làm hỏng việc dựng: **pass** (`test_sampler_failures_never_change_the_region_result`,
   `test_missing_sampler_still_publishes_and_records_nothing`).
5. `observed_budget` không đổi: **pass** (`test_scene_records_do_not_change_the_observed_budget`).
6. Runner không đổi hành vi: **pass** (`test_resource_telemetry.py`, `test_studio_processing_job.py`).

Mode `objectify`, `boxes`, `membership` đi cùng đường `sampled_section` nhưng không có test riêng; chỉ `region` và
`geometry` có test chạy thật qua queue.

## Tests

Trước khi sửa (baseline, 4 file của plan): `104 passed`.

Sau Step 1 (`test_resource_telemetry.py`, `test_studio_processing_job.py`, `test_observed_budget.py`): `44 passed`.

Sau Step 2 (`test_scene_objectify_queue.py`, `test_resource_telemetry.py`): `94 passed`.

Sau Step 3 (lệnh trong "Tests required" của plan):
- `pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_observed_budget.py -q`: `79 passed`
- `pytest tests/test_orchestration/test_resource_telemetry.py tests/integration/test_studio_processing_job.py -q`: `32 passed`

Sau khi thêm test geometry (4 file gộp):
- `pytest test_scene_objectify_queue.py test_observed_budget.py test_resource_telemetry.py test_studio_processing_job.py -q`:
  `112 passed`

Lint:
- `ruff check src tests`: `All checks passed!`
- `ruff format --check src/services/orchestration`: `128 files already formatted`
- `ruff format --check src tests` (toàn bộ): **1 file lệch format**: `tests/test_api/test_value_routes.py` (đang có thay đổi
  chưa commit của người khác, không thuộc T-028; tôi không sửa).

Không chạy full test suite (theo hướng dẫn). `graphify update .` đã chạy, không có thay đổi topology.

## Deviations from plan

1. **Giả định về scorecard/benchmark trong plan không đúng với code — xem câu hỏi cho Architect bên dưới.** Tôi đã không sửa
   `scorecard.py` / `benchmark.py` như plan yêu cầu, vì kiểm tra cho thấy thay đổi này có tác động thật.
2. Step 1: `runner._persist_usage` giữ lại như wrapper mỏng (gọi `record_usage`), vì `test_observed_budget.py` gọi trực tiếp
   `runner._persist_usage`. Hành vi không đổi.
3. Step 2: plan không quy định outcome khi `BaseException` (ví dụ `KeyboardInterrupt`). Tôi ghi `interrupted` (giống runner).
4. Step 2: `_scene_sampler` tự `mkdir` workspace trước khi lấy mẫu, vì `resource-usage.jsonl` được ghi vào đó.

## Câu hỏi cho Architect (cần Architect)

**Q1 (chặn việc chốt T-028): `scene.*` làm đổi số trong scorecard.** Plan giả định `scorecard.py` và `benchmark.py` lọc theo
`config_checksum`. Thực tế:

- `src/services/orchestration/evaluation/scorecard.py:810`: `completed = [u for u in usages if u.job_id == job.job_id and
  u.outcome == "completed"]`. Không lọc theo tool hay config_checksum, nên bản ghi `scene.*` lọt vào.
- `scorecard.py:713-760` (`_ram_metric`, `_vram_metric`): lấy max trên `completed`. Đỉnh RAM/VRAM của Tạo mesh hoặc dựng lại
  vùng sẽ thay đổi số, và nhãn "(bước scene.geometry)" sẽ xuất hiện.
- `scorecard.py:762-772` (`_config_metric`): lấy bản ghi `completed_at` mới nhất. Nếu bản ghi đó là `scene.*` (params `None`),
  thẻ "Cấu hình xử lý" hiện "Chưa đo — job này không có bản ghi tài nguyên", dù job có đo. Đây là lỗi hiển thị rõ ràng.
- `benchmark.py:262-290` (`_tool_timings`): có lọc `config_checksum` và `runtime_manifest_checksum` của job. Theo đọc code,
  `scene.*` có `config_checksum` theo mode nên bị loại, nhưng tôi chưa chạy kiểm chứng.

Đề xuất: lọc `scene.*` khỏi `_system_metrics` (chỉ lấy tool không bắt đầu bằng `scene.`) trong T-028, để scorecard giữ
nguyên số như trước. Đỉnh RAM/VRAM của `scene.*` để T-032 đọc như đã chốt. Chờ Architect chọn trước khi làm.

Chưa chạy job thật trên GPU, nên thời gian máy thật của `scene.*` chưa được đo.
