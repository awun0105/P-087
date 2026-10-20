# T-046 report
- Thêm `QueueGuard` và `poll_queues` vào `src/services/orchestration/jobs/worker_cli.py`; vòng lặp `main` chạy mọi hàng đợi và `recover_expired_leases` qua guard; nghỉ `max(poll, backoff)`.
- Test: `tests/test_orchestration/test_worker_queue_guard.py` (6 test). Lệnh: `pytest test_worker_queue_guard.py test_worker_cleanup.py test_job_lease.py` → 41 passed.
- Lệch plan: test tích hợp gọi `poll_queues` (đúng đoạn code `main` chạy) thay vì dựng `main` — `main` cần đủ settings/registry/GPU.
- Commit: 45dff6bb.
