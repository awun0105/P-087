# T-047 report
- `retryability.is_execution_error_retryable`: `PREVIEW_RUNNER_FAILED` với `exception_type` KeyboardInterrupt/SystemExit luôn cho chạy lại (cứu job cũ).
- `progress.job_progress`: chiếu cờ chạy lại theo chính sách hiện tại cả hạ lẫn nâng.
- `runner._record_runner_failure`: KeyboardInterrupt/SystemExit → `INTERRUPTED_SHUTDOWN` (retryable).
- `errorGuidance.ts`: hướng dẫn cho `INTERRUPTED_SHUTDOWN`.
- Test: test_retryability (3 mới), test_job_progress (1), test_runner_shutdown_failure (2), test_product_routes `test_retry_accepts_legacy_shutdown_failure` (xanh ngay sau sửa chính sách, đúng dự đoán của plan), frontend error-guidance-interrupted.
