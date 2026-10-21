# T-072 — Báo cáo (phần A)

Phạm vi: chỉ phần A của `plan.md` (A1, A2, A3) và các test của phần A. Phần B và C được thay bằng T-073 nên không làm
ở đây. Phần D không cần sửa code. Commit: dd855c85.

## Đã làm

### A1. Dùng số đo của cấu hình nặng hơn làm cận trên
- `src/services/orchestration/jobs/admission.py:81` — kiểu mới `MeasuredScope = "exact" | "upper_bound" | "estimate"`.
- `admission.py:303-312` — `Demand` bỏ trường `measured`, thay bằng `measured_scope`; `measured` thành thuộc tính
  tính ra (`measured_scope != "estimate"`), nên mọi chỗ đang đọc `demand.measured` vẫn chạy như cũ.
- `admission.py:392-431` (`_demand`) — bỏ bộ lọc `usage.params == observation_params`; đưa hết số đo vào
  `observed_budget`, để lượt chạy nặng hơn ở mọi thông số (`dominates`) được dùng làm cận trên. Gọi `observed_budget`
  thêm một lần với các lượt đo đúng cấu hình: có kết quả thì là `exact`, không có thì là `upper_bound`. Thiếu số đo của
  bất kỳ tool bắt buộc nào của phase thì vẫn không có ngân sách.
- `admission.py:108` — `ResourceWait.estimate_scope` có thêm `"upper_bound"`; `admission.py:315` ánh xạ
  `exact → measured`, `upper_bound → upper_bound`, `estimate → configured_preview`.
- Giao diện: `frontend/src/lib/contracts/studio.ts:207,549` nhận `"upper_bound"`;
  `frontend/src/features/studio/scene/ResourceWaitDetail.tsx:15-31` hiện "VRAM GPU: theo số đo của cấu hình nặng hơn,
  cần tối đa … GB".

### A2. Cho chạy chung khi ước lượng nhỏ so với VRAM còn trống
- `admission.py:78` — hằng `UNMEASURED_SHARE_RATIO = 0.5`.
- `admission.py:308` — `Demand.exhausted`, gán từ `exhausted_before(...)` trong `_demand`.
- `admission.py:762-772` (`_assess`) — job phải chạy một mình được chạy chung khi: là `Demand`, cần GPU, chưa từng hết
  bộ nhớ, đo được VRAM trống, và ước lượng VRAM ≤ 50% VRAM trống. Worker khác đang chạy một mình thì
  `available["vram"]` = 0 nên job mới vẫn chờ.

### A3. `shares_gpu()`
Không sửa, đúng kế hoạch.

## Kiểm thử
`tests/test_orchestration/test_resource_admission.py` (máy giả lập 24 GB, trống 23,5 GB):
- Cận trên từ cấu hình nặng hơn (preview, finalize): `upper_bound`, không chạy một mình, worker thứ hai chạy chung được.
  Thay test cũ `test_heavier_config_measurement_does_not_block_first_exclusive_run` vì nó kiểm hành vi A1 bỏ đi.
- Số đo đúng cấu hình → `exact`; bản ghi chờ ghi `estimate_scope == "upper_bound"`.
- Ước lượng 2,67 GB chạy chung; 13 GB chạy một mình; job từng hết bộ nhớ vẫn chạy một mình.
- Job nhỏ vẫn chờ khi worker khác đang chạy một mình.
- `test_unmeasured_job_runs_alone_and_blocks_sharing` giữ máy 4 GB: 2,67 GB > 50% của 3,8 GB nên vẫn chạy một mình.
- Frontend `studio-resource-wait.test.tsx`: hiện chữ và đọc được `upper_bound`.

Kết quả: `test_resource_admission.py` 58 passed; `tests/test_orchestration` 1431 passed, 7 skipped; cả `tests/`
4319 passed, 41 skipped; ruff đạt; `check_contract_mirror` PASS; frontend lint 0 lỗi, typecheck đạt, vitest 1113 passed.

## Phần D
Không cần sửa code: `ae7e3aca` đã có trong `develop`, image v5 build từ commit đó. Thời gian bước `prepare` cho video
5 phút đo lại khi chứng nhận image mới.

## Phần B và C
Không làm; được thay bằng T-073.
