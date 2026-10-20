# T-046: Vòng lặp worker không chết vì một lỗi

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md` (quy tắc chung).

## Goal
Một lỗi bất ngờ trong một hàng đợi (DB chập chờn, bản ghi hỏng) chỉ làm hỏng lượt đó, không giết cả tiến trình worker.
Worker ghi log rõ hàng đợi nào lỗi, nghỉ tăng dần rồi chạy tiếp.

## Context (đã kiểm trong code)
- Vòng lặp chính `src/services/orchestration/jobs/worker_cli.py:511-538` gọi lần lượt
  `dispatch_next`, `registration_worker.process_next`, `validation_worker.process_next`,
  `process_next(registry, settings)` (tách vật), `import_service.process_next`, `process_demo_session` **không có
  try/except**. Chỉ `dispatch_next` tự bắt lỗi theo job (`worker_cli.py:322-327`).
- `recover_expired_leases(registry)` gọi mỗi vòng (dòng 512) cũng không được bọc ở mức vòng lặp.
- Trong `scene/objectify_queue.py:788-791` các bước `recover_interrupted` và `_claim` chạy trước `try`; trong
  `review/validation_worker.py:163-183` `claim_next` và `queue.fail` cũng ngoài `try`. Một lỗi ở đó lan ra vòng lặp.
- Ngoại lệ thoát ra khỏi `while True` làm worker kết thúc; chỉ còn Docker `restart unless-stopped` cứu.
- `KeyboardInterrupt` (SIGTERM được đổi thành nó ở dòng 489-493) phải vẫn thoát như cũ (`return 130`).

## Thiết kế
Thêm vào `worker_cli.py`:

```python
@dataclass
class QueueGuard:
    """Đếm lỗi liên tiếp theo hàng đợi; quyết định thời gian nghỉ sau lỗi."""
    failures: dict[str, int] = field(default_factory=dict)

    def run(self, name: str, step: Callable[[], bool]) -> bool: ...
    def backoff_seconds(self) -> float: ...
```

- `run`: gọi `step()`. Thành công thì xoá đếm của `name` và trả kết quả. `Exception` thì
  `logger.exception("Hàng đợi %s lỗi lần %d liên tiếp", name, n)`, tăng đếm, trả `False`. `BaseException` khác
  (`KeyboardInterrupt`, `SystemExit`) đi thẳng ra ngoài.
- `backoff_seconds`: `0` khi không hàng đợi nào đang lỗi; ngược lại `min(2 ** (max_failures - 1), 60)` giây
  (1, 2, 4, …, tối đa 60).
- Tên hàng đợi cố định: `"recover_leases"`, `"pipeline"`, `"registration"`, `"validation"`, `"scene"`, `"import"`,
  `"demo"`.
- Vòng lặp: mỗi lời gọi trong chuỗi `or` (dòng 525-531) và nhánh `demo_operation` (dòng 517-522) đi qua
  `guard.run(name, ...)`; `recover_expired_leases` cũng vậy. Cuối vòng, nếu `not handled`:
  `pause.wait(max(settings.product_queue_poll_seconds, guard.backoff_seconds()))`. Nếu `handled` nhưng có lỗi ở hàng đợi
  khác trong vòng: không nghỉ thêm (việc thật vẫn chạy).
- Không bọc riêng phần trước `try` trong objectify/validation: lỗi đó giờ được `QueueGuard` bắt; bản ghi đã claim sẽ được
  khôi phục khi lease 90 giây hết hạn (`recover_interrupted`, `recover_expired`) — hành vi sẵn có.

## Steps
1. Test `tests/test_orchestration/test_worker_queue_guard.py`:
   - `test_guard_returns_step_result_and_resets_failures`: step trả `True` → `run` trả `True`; trước đó lỗi 2 lần thì
     sau khi thành công `backoff_seconds() == 0`.
   - `test_guard_swallows_exception_and_backs_off`: step ném `RuntimeError` 3 lần → mỗi lần `run` trả `False`;
     `backoff_seconds()` lần lượt `1`, `2`, `4`; ném 10 lần → `60`.
   - `test_guard_lets_keyboard_interrupt_through`: step ném `KeyboardInterrupt` → `pytest.raises(KeyboardInterrupt)`.
   - `test_guard_logs_queue_name`: `caplog` chứa `"scene"` và `"lần 1"`.
   Chạy, thấy FAIL vì chưa có `QueueGuard`.
2. Cài `QueueGuard`. Chạy test, PASS. Commit `fix(worker): keep the worker loop alive when one queue step fails`.
3. Nối `QueueGuard` vào vòng lặp `main`. Test tích hợp trong cùng file:
   `test_worker_loop_survives_scene_queue_error`: dựng `main(["--once", ...])` theo cách test hiện có của worker
   (đọc `tests/test_orchestration/test_worker_cleanup.py` để lấy fixture dựng settings/registry), monkeypatch
   `process_next` của tách vật ném `sqlite3.OperationalError("database is locked")`; kỳ vọng `main` trả `0`, không ném.
   Nếu `--once` không đi qua nhánh lỗi, dùng monkeypatch `pause.wait` để dừng sau 2 vòng và kiểm `process_next` của
   kiểm định vẫn được gọi ở vòng thứ hai.
4. Chạy test, PASS. Commit `fix(worker): route every queue in the main loop through the failure guard`.

## Acceptance criteria
1. Một hàng đợi ném lỗi không làm worker thoát; các hàng đợi khác vẫn chạy ở vòng sau.
2. Log có tên hàng đợi và số lần lỗi liên tiếp.
3. Lỗi lặp lại làm worker nghỉ tăng dần, tối đa 60 giây; hết lỗi thì về nhịp poll thường.
4. SIGTERM / Ctrl-C vẫn thoát với mã 130.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_worker_queue_guard.py tests/test_orchestration/test_worker_cleanup.py tests/test_orchestration/test_job_lease.py -q
.venv/bin/ruff check src/services/orchestration/jobs/worker_cli.py tests/test_orchestration/test_worker_queue_guard.py
.venv/bin/ruff format --check src/services/orchestration/jobs/worker_cli.py tests/test_orchestration/test_worker_queue_guard.py
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md` → `implemented`.
