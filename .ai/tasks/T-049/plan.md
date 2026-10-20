# T-049: Chịu lỗi DB thoáng qua khi gia hạn và kiểm hủy

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Một lần DB chập chờn không giết lượt GPU đang chạy dài (Brush, Tạo mesh, kiểm định Isaac). Chỉ dừng khi lỗi kéo dài tới mức
lease thật sự có thể đã mất, hoặc khi lỗi không phải lỗi thoáng qua. Ba hàng đợi dùng chung một quy tắc.

## Context (đã kiểm trong code)
- Hàng đợi job: luồng gia hạn lease chịu được lỗi DB, thử lại chu kỳ sau (`jobs/lease.py:148-149`). Nhưng vòng poll 1 giây
  trong `_run_tool` (`runner.py:302-314`) gọi `touch_job_reservation` và `registry.get_job` không bọc gì: lỗi DB → công cụ
  bị giết → `PREVIEW_RUNNER_FAILED` với `exception_type` kiểu `OperationalError` → **không cho chạy lại**.
- Hàng đợi tách vật: `_start_heartbeat.beat` (`scene/objectify_queue.py:600-638`) — **bất kỳ** `Exception` nào cũng đặt
  `abort_reason="lease_lost"` và hủy. TTL 90 s, gia hạn mỗi 20 s, poll hủy mỗi 0,5 s (dòng 61-63).
- Hàng đợi kiểm định: `_ValidationHeartbeat._run` (`review/validation_worker.py:111-130`) — `Exception` khác
  `RuntimeStateConflictError` → `"heartbeat_failed"` và hủy. Chu kỳ 20 s, TTL 90 s.
- `RuntimeDatabase` không bọc lỗi driver (`jobs/database.py`), nên lỗi là `sqlite3.OperationalError` hoặc lỗi của
  psycopg (`psycopg.OperationalError`, `psycopg.InterfaceError`).

- Phiên khác đã thêm pool kết nối PostgreSQL rảnh vào `jobs/database.py` (commit `e2735834`, `7fc53c0d`:
  `_borrow`/`_give_back`/`_begin`, tối đa 8 kết nối rảnh, hạn 60 s, `prepare_threshold=None` cho Supabase transaction
  pooler cổng 6543). `_begin` đã tự thay kết nối rảnh bị server cắt. Làm trên bản hiện tại của file; không đổi các hàm đó.
  Test của họ: `tests/test_orchestration/test_runtime_connection_reuse.py` (cần `R2S_GPU_TEST_DATABASE_URL`, tự skip nếu
  không có) — phải còn xanh / skip như trước.

## Thiết kế
1. `jobs/database.py`: `def is_transient_database_error(error: BaseException) -> bool` — `True` cho
   `sqlite3.OperationalError` có chuỗi `"locked"` hoặc `"busy"` (không phân biệt hoa thường), `psycopg.OperationalError`,
   `psycopg.InterfaceError` (import muộn trong `try`, thiếu psycopg thì bỏ qua), `ConnectionError`, `TimeoutError`.
   `False` cho mọi thứ khác, kể cả `RuntimeStateConflictError`.
2. Module mới `src/services/orchestration/jobs/heartbeat.py`:
   ```python
   class HeartbeatTolerance:
       def __init__(self, ttl: timedelta, *, clock: Callable[[], float] = time.monotonic) -> None: ...
       def succeeded(self) -> None: ...
       def tolerate(self, error: BaseException) -> bool: ...
   ```
   `tolerate` trả `True` (tiếp tục, thử lại nhịp sau) khi `is_transient_database_error(error)` **và** thời gian từ lần
   `succeeded` gần nhất (hoặc từ lúc tạo) nhỏ hơn `ttl * 2 / 3`; ngược lại `False`. Mỗi lần `True` ghi
   `logger.warning` có loại lỗi và số giây đã chịu.
3. Tách vật: trong `beat()`, tạo `tolerance = HeartbeatTolerance(_LEASE_TTL)`; gọi `succeeded()` sau mỗi lượt kiểm hủy và
   gia hạn thành công; ở nhánh `except Exception` gọi `tolerance.tolerate(error)` — `True` thì `continue`, `False` thì giữ
   hành vi cũ (`lease_lost`, hủy).
4. Kiểm định: tương tự trong `_ValidationHeartbeat._run`, TTL là hằng TTL lease của `validation_queue.py` (90 s, dòng 28).
   Nhánh `RuntimeStateConflictError` giữ nguyên (mất lease thật).
5. `_run_tool`: bọc phần `touch_job_reservation` + `progress.poll()` + `get_job` trong `try`; lỗi thì
   `tolerance.tolerate(error)` với `HeartbeatTolerance(LEASE_TTL)` — `True` thì bỏ qua nhịp đó (không kiểm hủy ở nhịp
   này), `False` thì ném lại. `PreviewCancelledError` và các kiểm hạn/ngân sách vẫn chạy mỗi nhịp như cũ.
6. `retryability.py`: thêm `"OperationalError"` và `"InterfaceError"` vào `_TRANSIENT_EXCEPTION_TYPES` để lỗi DB kéo dài
   cho ra job FAILED **cho chạy lại**.

## Steps
1. Test `tests/test_orchestration/test_heartbeat_tolerance.py` với đồng hồ giả:
   - `test_transient_error_within_window_is_tolerated`: TTL 90 s, lỗi `sqlite3.OperationalError("database is locked")`
     ở giây 20 và 40 → `True`, `True`.
   - `test_transient_error_after_two_thirds_ttl_gives_up`: lỗi ở giây 61 → `False`.
   - `test_success_resets_window`: lỗi ở 50 (`True`), `succeeded()` ở 55, lỗi ở 100 → `True`.
   - `test_non_transient_error_gives_up_immediately`: `ValueError` → `False`.
   - `test_is_transient_database_error_cases`: locked/busy → `True`; `sqlite3.OperationalError("no such table")` →
     `False`; `ConnectionResetError()` → `True`; `RuntimeStateConflictError("x")` → `False`.
   FAIL. Cài thiết kế 1, 2. PASS. Commit `feat(runtime): tolerate brief database outages in worker heartbeats`.
2. Test tách vật trong `tests/test_orchestration/test_scene_objectify_queue.py`:
   `test_objectify_heartbeat_survives_one_locked_database_error` — monkeypatch `_cancel_reason` ném lỗi locked một lần rồi
   bình thường; kỳ vọng `cancel_event` không bật, `abort_reason[0] is None`. Và
   `test_objectify_heartbeat_aborts_on_persistent_errors` với đồng hồ giả vượt 60 s → `abort_reason[0] == "lease_lost"`.
   FAIL. Cài thiết kế 3. PASS. Commit.
3. Test kiểm định trong `tests/test_orchestration/test_isaac_validation_worker.py`: hai test tương tự cho
   `_ValidationHeartbeat` (`queue.heartbeat` ném lỗi locked một lần). Cài thiết kế 4. Commit.
4. Test runner `tests/test_orchestration/test_runner_db_blip.py`:
   `test_run_tool_survives_one_get_job_failure` — monkeypatch `registry.get_job` ném lỗi locked ở lần gọi thứ 2, công cụ là
   lệnh `python -c "import time; time.sleep(3); print('{}')"`; kỳ vọng `_run_tool` trả exit code 0. Cài thiết kế 5, 6.
   Commit.

## Acceptance criteria
1. Một lỗi DB thoáng qua không hủy lượt đang chạy ở cả ba hàng đợi.
2. Lỗi DB kéo dài quá 2/3 TTL vẫn hủy như cũ; lỗi không thoáng qua hủy ngay.
3. Lỗi DB kéo dài làm job FAILED thì cho chạy lại.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_heartbeat_tolerance.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_isaac_validation_worker.py tests/test_orchestration/test_runner_db_blip.py tests/test_orchestration/test_retryability.py tests/test_orchestration/test_runner_expected_deadline.py -q
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
