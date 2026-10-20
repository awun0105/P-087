# T-048: Không còn job RUNNING mà không ai trông

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Job RUNNING luôn có một worker giữ lease, hoặc đang chờ người / chờ worker một cách có chủ ý. Mọi job RUNNING khác bị đưa
về FAILED cho chạy lại sau tối đa một TTL lease. Đóng hai khe code để không sinh thêm job như vậy, và dọn các job đang treo.

## Context (đã kiểm trong code)
- `run_reviewed_preview_job`: `registry.record_stage_progress(...)` ghi revision mới (`runner.py:1673`) **trước**
  `workspace.mkdir` (1675), `_Attempt(...)` và `_attempt_log_id(...)`; khối `try` chỉ bắt đầu ở 1679.
- `run_finalize_job`: `transition_job(... RUNNING ...)` / `record_stage_progress(RGB_GEOMETRY)` (1760-1766) trước
  `workspace.mkdir` (1773) và `try` (1777).
- Lỗi trong khe đó: `_record_runner_failure` không chạy; với finalize, `_record_finalize_failure` bỏ qua vì checksum đã
  đổi (`worker_cli.py:85-89`); `leased()` thả lease; không có thư mục attempt nên `recover_interrupted_jobs` bỏ qua
  (`worker_cli.py:178-179`); `recover_expired_leases` không thấy vì lease đã bị xoá. Job treo RUNNING mãi.
- Job chỉ RUNNING "có chủ ý" mà không có lease trong các trường hợp đã có hàm nhận biết:
  `awaiting_anonymization_review(job)`, `awaiting_reviewed_preview(job)`, `awaiting_finalize(job)` và chờ xác nhận mét
  (`current_stage == METRIC_CANONICALIZE` và chưa có StageArtifact METRIC) — xem `worker_cli.py:155-170`.
- Mọi lượt chạy runner đi qua `_leased_call` (`worker_cli.py:331-339`): lease được giữ **trước** khi runner chuyển
  trạng thái, nên "RUNNING, không lease, không chờ có chủ ý" chỉ xảy ra khi có lỗi.
- `LEASE_TTL = 10 phút` (`jobs/lease.py:23`).

## Thiết kế
1. Đóng khe: trong cả hai hàm, tạo `workspace`, `_Attempt(registry, settings, job, workspace)` **trước** lần ghi revision
   đầu tiên; chuyển lần ghi đó (`record_stage_progress` / `transition_job`) vào trong `try` và gán `attempt.job = ...`.
   `_record_runner_failure` so checksum với `attempt.job` nên sẽ ghi đúng revision vừa tạo. `_attempt_log_id` cũng vào
   trong `try` hoặc gọi trước lần ghi đầu.
2. Hàm dùng chung trong `worker_cli.py`:
   `def intentionally_unleased(job: JobManifest) -> bool` — gom bốn điều kiện chờ có chủ ý ở trên; dùng lại trong
   `recover_interrupted_jobs` thay cho khối `if` hiện tại (hành vi không đổi).
3. Sweeper mới trong `worker_cli.py`:
   ```python
   def recover_unwatched_running_jobs(registry: ProjectRegistry, *, now: datetime | None = None) -> int:
   ```
   Chọn job có journal mới nhất `status == "RUNNING"` (dùng lại câu SQL ở `worker_cli.py:146-152`), rồi với từng job:
   bỏ qua nếu `intentionally_unleased(job)`; bỏ qua nếu bảng `r2s_job_leases` còn dòng của job (thêm hàm
   `has_lease(database, job_id) -> bool` vào `jobs/lease.py`); bỏ qua nếu sự kiện journal mới nhất mới hơn
   `now - LEASE_TTL`. Còn lại: `transition_job(... FAILED, error=ExecutionError(error_code="INTERRUPTED_SHUTDOWN",
   human_message="Không còn máy xử lý nào chạy bước này. Bấm Thử lại để chạy tiếp.", retryable=True, details={"job_id":
   ..., "stage": ..., "reason": "no_lease"}))`. `RuntimeStateConflictError` → bỏ qua. Lỗi khác của một job → log, sang
   job sau.
4. Gọi `recover_unwatched_running_jobs(registry)` ngay sau `recover_expired_leases(registry)` lúc khởi động và trong mỗi
   vòng lặp (qua `QueueGuard` tên `"recover_unwatched"` của T-046).
5. Job treo từ trước (kể cả job chạy trước khi có lease) sẽ được sweeper xử lý ở lần chạy đầu sau deploy. Ghi vào report
   số job bị xử lý khi chạy thử trên DB local (`data/studio_local`), **không** chạy trên production.

## Steps
1. Test `tests/test_orchestration/test_unwatched_running_jobs.py`:
   - `test_running_job_without_lease_older_than_ttl_is_failed_retryable`: job RUNNING ở `CAMERA_POSE`, không lease,
     journal cũ hơn 11 phút → sau sweeper: FAILED, `INTERRUPTED_SHUTDOWN`, `retryable is True`, hàm trả `1`.
   - `test_running_job_with_lease_is_untouched`.
   - `test_recent_running_job_without_lease_is_untouched` (journal 1 phút trước).
   - `test_job_waiting_for_metric_confirmation_is_untouched`.
   - `test_job_awaiting_anonymization_review_is_untouched`.
   - `test_job_awaiting_finalize_is_untouched`.
   Dựng job theo fixture của `tests/test_orchestration/test_job_lease.py`. FAIL. Cài thiết kế 2, 3 và `has_lease`.
   PASS. Commit `fix(worker): fail running jobs that no worker holds a lease for`.
2. Test khe: `tests/test_orchestration/test_runner_claim_gap.py`,
   `test_reviewed_preview_failure_right_after_claim_is_recorded`: monkeypatch `_attempt_log_id` (hoặc hàm đầu tiên sau
   lần ghi revision) ném `OSError` → job FAILED (không còn RUNNING). Tương tự
   `test_finalize_failure_right_after_claim_is_recorded`. FAIL. Cài thiết kế 1. PASS.
   Commit `fix(runner): create the attempt before claiming so early failures are recorded`.
3. Nối sweeper vào `main` (thiết kế 4). Chạy test worker hiện có. Commit.

## Acceptance criteria
1. Không đường code nào ghi job RUNNING trước khi có `_Attempt` để ghi lỗi.
2. Job RUNNING không lease, không chờ có chủ ý, quá 10 phút → FAILED cho chạy lại.
3. Job đang chờ người hoặc chờ worker nhận không bị đụng.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_unwatched_running_jobs.py tests/test_orchestration/test_runner_claim_gap.py tests/test_orchestration/test_job_lease.py tests/test_orchestration/test_worker_cleanup.py tests/test_orchestration/test_worker_queue_guard.py -q
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
