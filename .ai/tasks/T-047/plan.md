# T-047: Tắt worker giữa chừng thì cho chạy lại, kể cả job cũ

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Tắt hoặc khởi động lại worker khi job đang chạy (SIGTERM, Ctrl-C, deploy) cho kết quả giống như máy mất điện: job
FAILED **cho chạy lại**, thông báo nói rõ là bị gián đoạn. Job đã hỏng theo cách cũ trước khi sửa cũng bấm Thử lại được.

## Context (đã kiểm trong code)
- SIGTERM được đổi thành `KeyboardInterrupt` (`worker_cli.py:489-493`).
- `run_video_job`, `run_reviewed_preview_job`, `run_finalize_job` bắt `BaseException` rồi gọi
  `_record_runner_failure` (`runner.py:459-485`). Hàm này gán `PREVIEW_RUNNER_FAILED` với
  `details={"exception_type": "KeyboardInterrupt"}`.
- `classify_retryability("PREVIEW_RUNNER_FAILED", details)` chỉ trả `True` khi `exception_type` thuộc
  `_TRANSIENT_EXCEPTION_TYPES` (`src/models/contracts/retryability.py:46-58`); `KeyboardInterrupt` không có → job FAILED
  **không cho chạy lại**.
- Ngược lại, khi worker chết cứng thì lease hết hạn và `recover_expired_leases` ghi `INTERRUPTED_SHUTDOWN`, cho chạy lại
  (`worker_cli.py:342-372`). Hai đường cho cùng sự kiện ra hai kết quả.
- Cổng chạy lại: `POST /retry` dùng `is_execution_error_retryable(failure)` (`src/api/product/jobs.py:115`). Hàm này
  đòi `error.retryable` **và** chính sách cho phép (`retryability.py:79-81`), nên job cũ có `retryable=False` không cứu
  được chỉ bằng đổi phân loại.
- Tiến trình chiếu lại cờ theo chính sách hôm nay nhưng **chỉ hạ** (`jobs/progress.py:228-230`).

## Thiết kế
1. `retryability.py`:
   - Thêm `_SHUTDOWN_EXCEPTION_TYPES = frozenset({"KeyboardInterrupt", "SystemExit"})`.
   - `is_execution_error_retryable(error)` thêm một nhánh **đứng trước** nhánh hiện có:
     `error.error_code == "PREVIEW_RUNNER_FAILED"` và `error.details.get("exception_type") in _SHUTDOWN_EXCEPTION_TYPES`
     → `True` (bỏ qua cờ `retryable` do bên ghi đặt). Docstring nói rõ: lỗi do tắt worker là gián đoạn, luôn chạy lại được.
2. `runner._record_runner_failure`: nếu `isinstance(error, KeyboardInterrupt | SystemExit)` thì
   `code = "INTERRUPTED_SHUTDOWN"`, `message = "Worker dừng giữa chừng (tắt hoặc khởi động lại máy xử lý). Bấm Thử lại để chạy tiếp."`.
   Các nhánh khác giữ nguyên.
3. `progress.py:228-230`: thay bằng chiếu hai chiều
   `failure = failure.model_copy(update={"retryable": is_execution_error_retryable(failure)})` khi `failure is not None`.
   Comment: "Cờ theo chính sách hôm nay, cả hạ lẫn nâng, để UI khớp với POST /retry."
4. Kiểm `frontend/src/features/studio/errorGuidance.ts` có hướng dẫn cho `INTERRUPTED_SHUTDOWN`; nếu chưa có, thêm:
   nguyên nhân "Máy xử lý bị tắt hoặc khởi động lại khi đang chạy", việc nên làm "Bấm Thử lại; kết quả các bước đã xong
   được giữ".

## Steps
1. Test `tests/test_orchestration/test_retryability.py` (file có sẵn), thêm:
   - `test_legacy_shutdown_failure_is_retryable`: `ExecutionError(error_code="PREVIEW_RUNNER_FAILED", retryable=False,
     details={"exception_type": "KeyboardInterrupt"}, stage_id=StageId.VISUAL_RECON, human_message="x")` →
     `is_execution_error_retryable(...) is True`.
   - `test_system_exit_failure_is_retryable`: tương tự với `"SystemExit"`.
   - `test_other_runner_failure_stays_non_retryable`: `exception_type="ValueError"`, `retryable=False` → `False`.
   FAIL. Cài thiết kế 1. PASS. Commit `fix(retry): treat runner failures caused by worker shutdown as retryable`.
2. Test `tests/test_orchestration/test_job_progress.py`, thêm `test_progress_upgrades_legacy_shutdown_failure`: job
   FAILED có lỗi như bước 1 → `job_progress(...).error.retryable is True`; và
   `test_progress_still_downgrades_unknown_retryable_flag`: lỗi mã lạ `retryable=True` → `False`. FAIL. Cài thiết kế 3.
   PASS. Commit `fix(progress): project retry flags through current policy in both directions`.
3. Test runner: `tests/test_orchestration/test_runner_shutdown_failure.py`,
   `test_keyboard_interrupt_records_interrupted_shutdown`: dựng `_Attempt` giả theo cách các test runner hiện có
   (xem `tests/test_orchestration/test_runner_expected_deadline.py`), gọi `_record_runner_failure(attempt, KeyboardInterrupt())`;
   kỳ vọng job FAILED, `error.error_code == "INTERRUPTED_SHUTDOWN"`, `error.retryable is True`. FAIL. Cài thiết kế 2.
   PASS. Commit `fix(runner): record worker shutdown as an interrupted, retryable attempt`.
4. Test API: trong `tests/test_api/` file có test `POST /retry` (tìm bằng `grep -rln "/retry" tests/test_api`), thêm
   `test_retry_accepts_legacy_shutdown_failure` với job FAILED mang lỗi như bước 1 → trả 2xx và job về QUEUED. PASS ngay
   sau bước 1 (không cần code mới); nếu FAIL thì sửa route cho dùng `is_execution_error_retryable`. Commit.
5. Frontend thiết kế 4, test hướng dẫn lỗi hiện có (`grep -rl "errorGuidance" frontend/tests`). Commit.

## Acceptance criteria
1. SIGTERM giữa lúc chạy → job FAILED, mã `INTERRUPTED_SHUTDOWN`, cho chạy lại.
2. Job FAILED cũ với `PREVIEW_RUNNER_FAILED` + `KeyboardInterrupt` hiện nút Thử lại và `POST /retry` nhận.
3. Lỗi khác không đổi phân loại.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_retryability.py tests/test_orchestration/test_job_progress.py tests/test_orchestration/test_runner_shutdown_failure.py tests/test_orchestration/test_runner_expected_deadline.py -q
.venv/bin/python -m pytest <file test API có /retry> -q
cd frontend && ./node_modules/.bin/vitest run <test errorGuidance> && npm run typecheck
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
