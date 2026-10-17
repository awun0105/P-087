# Review T-028

Verdict: ACCEPTED (round 2)

Engineer phát hiện đúng: `scorecard._system_metrics` (dòng 810) không lọc tool, nên `scene.*` làm đổi thẻ RAM/VRAM và làm
`_config_metric` hiện "Chưa đo". Plan của Architect giả định sai. Kiểm thêm mọi nơi gọi `load_usages` thì còn hai chỗ nữa:

| Nơi đọc usage | Ảnh hưởng của `scene.*` | Quyết định |
| --- | --- | --- |
| `evaluation/scorecard.py` `_system_metrics` | Đổi số RAM/VRAM, mất thẻ cấu hình | **Loại** `scene.*` |
| `jobs/runner.py:344` (đếm usage `exhausted` của job để quyết định xếp lại) | Một lần Tạo mesh hết bộ nhớ làm job pipeline không được xếp lại | **Loại** `scene.*` |
| `jobs/admission.py` `exhausted_before(usages, job_id)` | Tương tự: chặn ước lượng ngân sách của job | **Loại** `scene.*` |
| `scripts/resources/calibrate_resource_model.py` | Hiệu chỉnh mô hình tài nguyên pipeline bằng số của việc khác | **Loại** `scene.*` |
| `observed.processing_seconds` | Cần `scene.*` (T-028 Step 3) | Giữ |
| `benchmark._tool_timings`, `observed_budget`, `observed_for_config` | Đã lọc theo tool / config / params | Giữ, **thêm test** chứng minh `scene.*` không lọt |
| T-032 bảng giá trị | Cần `scene.*` (đỉnh VRAM, phút máy) | Đọc trực tiếp, không qua bộ lọc |

## Required changes
1. Thêm vào `processing/observed.py`: `SCENE_TOOL_PREFIX = "scene."`, `is_scene_operation(usage) -> bool` và
   `pipeline_usages(usages) -> list[ResourceUsage]` (bỏ mọi usage có tool bắt đầu bằng `scene.`).
2. Dùng `pipeline_usages` ở bốn chỗ "Loại" trong bảng trên (`scorecard.py` là sửa có chủ đích: được phép trong task này).
3. Test: (a) job có usage pipeline + một `scene.geometry` completed → các thẻ RAM/VRAM/cấu hình **giống hệt** khi không có
   `scene.*`; (b) `scene.geometry` có `exhausted=True` không làm đổi quyết định xếp lại của runner và `exhausted_before`;
   (c) `benchmark` và `observed_budget` bỏ qua `scene.*` (chứng minh bằng test, không chỉ đọc code).
4. Cập nhật report: bảng trên và kết quả test thật. Sau đó đặt `implemented`.

## Ghi chú
- Giữ `_persist_usage` làm wrapper mỏng trong runner: chấp nhận.
- `tests/test_api/test_value_routes.py` lệch format thuộc T-030: không sửa trong T-028.
- Plan T-028 cũ ghi "không sửa scorecard.py": quyết định này thay thế điều đó.

## Round 2 — ACCEPTED (audit sâu)

Đọc toàn bộ diff source của `47f05aa0`, `cc5116e1`, `7ef5123d`, `1f70a1d4`, `e745d56d`. Chạy lại observed_budget, evaluation,
resource_admission, resource_telemetry, scene_objectify_queue: 175 PASS.

Kiểm thêm, không tìm thấy lỗi:
- `gpu_name` của `scene.*`: `ResourceSampler` tự điền khi lấy mẫu GPU (`telemetry.py:183`), nên T-032 tính được giờ GPU.
- `workspace.mkdir` sớm trong `_scene_sampler`: mọi hàm dựng đều `mkdir(exist_ok=True)` → không đổi hành vi.
- Lấy mẫu cây tiến trình của worker: `worker_cli` chạy các hàng đợi tuần tự trong một vòng lặp (dòng ~378), nên đỉnh RAM/VRAM của
  `scene.*` không lẫn việc khác cùng tiến trình.
- `observed_for_config` (deps) lọc theo `PHASE_TOOLS` → `scene.*` không lọt; `observed_budget` cũng vậy.
- Lỗi trước khi tạo sampler (chờ tài nguyên) → không ghi bản ghi rỗng; ngoại lệ ngoài dự kiến → `interrupted`, không cộng vào phút máy.

Ba test (c) là test bảo vệ tính chất có sẵn (không đỏ khi bỏ bộ lọc mới): chấp nhận, engineer đã ghi rõ.
