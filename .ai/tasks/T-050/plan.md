# T-050: Chờ tài nguyên và hạn tự tính không lặp vô hạn

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Việc của hàng đợi tách vật và kiểm định không nằm "đang chờ tài nguyên" mãi khi cổng tài nguyên hỏng hoặc máy không bao
giờ đủ. Công cụ bị cắt vì vượt hạn tự tính không bị cắt lặp lại ở lần chạy lại.

## Context (đã kiểm trong code)
- `ResourceAdmission.admit_operation` gặp **bất kỳ** lỗi nào thì trả `waiting_resources` với lý do `"unmeasured"` cho mọi
  tài nguyên (`jobs/admission.py:934-951`). Người dùng không phân biệt được "máy bận" với "cổng hỏng".
- Tách vật: `_requeue_wait` đưa yêu cầu về `queued` kèm `resource_wait` và thả lease (`scene/objectify_queue.py:663-704`),
  không giới hạn số lần, không mốc bắt đầu chờ.
- Kiểm định: `queue.wait_for_resources(claim)` (`review/validation_queue.py:416-433`) chuyển operation sang
  `WAITING_RESOURCES`, cũng không giới hạn. Model operation có checksum (`_seal_operation`).
- `WaitReason = Literal["busy", "external", "exceeds_machine", "unmeasured"]` (`admission.py:64`), dùng trong
  `ResourceWait`, `OperationAdmissionResult`, `ObjectifyResourceWait` (đều được lưu JSON).
- `_expected_limit` (`runner.py:220-242`) thay hạn cố định bằng hạn tính từ số đo. Lượt bị cắt vì vượt hạn ghi usage với
  `outcome="timeout"` (`ExpectedDurationError` là con của `TimeoutError`, `runner.py:340-342`). Lần chạy lại đọc lại cùng
  số đo nên có thể bị cắt lặp lại.

## Thiết kế
1. `WaitReason` thêm `"gate_error"`. Nhánh `except` ở `admission.py:934` dùng `reasons={name: "gate_error"}` thay
   `"unmeasured"`. (Giá trị mới; bản ghi cũ vẫn đọc được. API và worker phải lên cùng lúc.)
2. Setting mới `product_resource_wait_max_seconds: float = Field(default=1800, ge=60, le=86400)` trong `src/config.py`,
   biến môi trường theo quy ước có sẵn của file (đọc cách các `product_*` khác được đặt). Thêm vào
   `scripts/gpu/studio.env.example` và các file mẫu mà `scripts.studio.deploy_env render --examples` sinh ra.
3. Hàm thuần dùng chung trong `admission.py`:
   ```python
   def wait_exceeded(reasons: Mapping[str, str], waiting_since: datetime, now: datetime, limit_seconds: float) -> bool:
   ```
   `True` khi **không** lý do nào là `"busy"` và `now - waiting_since >= limit_seconds`. Chờ vì máy khác đang chạy
   (`busy`) không bao giờ hết hạn.
4. Tách vật: `_Record` thêm `resource_wait_since: datetime | None = None`. `_requeue_wait` đặt nó bằng `now` nếu đang
   `None`, giữ nguyên nếu đã có. Khi được admit thì xoá về `None`. Trước khi gọi `_requeue_wait` ở `process_next`
   (dòng ~846), nếu `wait_exceeded(...)`: kết thúc yêu cầu `failed`, `retryable=True`, `error` =
   `"Không xếp được tài nguyên sau {N} phút ({lý do}). Kiểm tra máy xử lý rồi thử lại."`. Lý do in bằng tiếng Việt:
   `gate_error` → "cổng tài nguyên lỗi", `unmeasured` → "chưa đo được máy", `exceeds_machine` → "cấu hình vượt khả năng
   máy", `external` → "chương trình khác đang chiếm".
5. Kiểm định: operation thêm `waiting_since: datetime | None = Field(default=None, exclude_if=lambda v: v is None)`.
   `wait_for_resources` đặt khi chuyển sang `WAITING_RESOURCES` lần đầu (giữ nếu đã có), xoá khi `start`. Trong
   `IsaacValidationWorker.process_next`, trước `wait_for_resources`, nếu `wait_exceeded(...)` thì
   `self.queue.fail(claim, error_code="RESOURCE_WAIT_EXCEEDED", retryable=True)`.
6. `retryability.py`: thêm `"RESOURCE_WAIT_EXCEEDED"` vào `_RETRYABLE_ERROR_CODES`. `errorGuidance.ts` thêm hướng dẫn
   cho mã này.
7. `_expected_limit`: nếu `load_usages` có usage cùng `job_id`, cùng `tool` và `outcome == "timeout"` thì trả
   `(fixed_timeout, None)` (lần chạy lại dùng lưới an toàn cố định). Log một dòng giải thích.

## Steps
1. Test `tests/test_orchestration/test_resource_admission.py`, thêm `test_admission_error_reports_gate_error`: monkeypatch
   một bước trong `admit_operation` ném `RuntimeError` → `result.status == "waiting_resources"` và mọi giá trị trong
   `result.reasons` là `"gate_error"`. Thêm `test_wait_exceeded_ignores_busy` và `test_wait_exceeded_after_limit`
   (1800 s, lý do `gate_error`, chờ 1801 s → `True`; 1799 s → `False`; có một lý do `busy` → `False`). FAIL. Cài thiết kế
   1, 3. PASS. Commit `feat(admission): distinguish gate errors and bound non-busy resource waits`.
2. Test `test_scene_objectify_queue.py`: `test_objectify_wait_fails_after_limit` (admission giả trả `gate_error`, đặt
   `resource_wait_since` lùi 31 phút → yêu cầu `failed`, `retryable is True`, `error` chứa "cổng tài nguyên lỗi");
   `test_objectify_busy_wait_never_fails`; `test_old_record_without_wait_since_reads` (JSON `_Record` cũ không có trường
   → đọc được, `resource_wait_since is None`). FAIL. Cài thiết kế 2, 4. PASS. Commit.
3. Test `test_validation_queue.py` / `test_isaac_validation_worker.py`: `test_validation_wait_fails_after_limit`,
   `test_legacy_operation_checksum_unchanged` (operation dựng từ JSON cũ, `_seal_operation` cho cùng checksum như
   trước khi có trường). Cài thiết kế 5, 6. Commit.
4. Test `tests/test_orchestration/test_runner_expected_deadline.py`, thêm
   `test_retry_after_expected_timeout_uses_fixed_limit`: usage cũ cùng job/tool `outcome="timeout"` →
   `_expected_limit(...) == (fixed, None)`. Cài thiết kế 7. Commit.

## Acceptance criteria
1. Lỗi cổng tài nguyên hiện lý do riêng; chờ không phải vì máy bận quá 30 phút (mặc định) thì việc FAILED cho chạy lại.
2. Chờ vì máy khác đang chạy không bị giới hạn.
3. Lượt chạy lại sau khi bị cắt vì vượt hạn tự tính dùng hạn cố định.
4. Bản ghi cũ của cả hai hàng đợi đọc được, checksum operation cũ không đổi.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_resource_admission.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_validation_queue.py tests/test_orchestration/test_isaac_validation_worker.py tests/test_orchestration/test_runner_expected_deadline.py tests/test_orchestration/test_expected_duration.py tests/test_orchestration/test_retryability.py -q
cd frontend && ./node_modules/.bin/vitest run <test errorGuidance> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
