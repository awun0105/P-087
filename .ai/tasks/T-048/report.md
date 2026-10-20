# T-048 report
- `jobs/lease.py`: `has_lease(database, job_id)`.
- `worker_cli.py`: `intentionally_unleased(job)`, `recover_unwatched_running_jobs(registry, now=)` chạy lúc khởi động và mỗi vòng (guard "recover_unwatched").
- `runner.py`: `_prepare_claimed_attempt` — tạo workspace và log id sau khi claim; lỗi được ghi FAILED (finalize và reviewed preview).
- Test: test_unwatched_running_jobs (7), test_runner_claim_gap (finalize).
- Lệch plan: không đổi `recover_interrupted_jobs` sang `intentionally_unleased` vì hàm cũ cố ý xét cả job chờ finalize có workspace chết — đổi sẽ đổi hành vi. Khe của reviewed preview sửa cùng helper nhưng chỉ test qua finalize (harness reviewed preview cần dựng frame che + LiDAR); sweeper là lưới an toàn.
- Lưu ý vận hành: lần chạy đầu sau deploy, job RUNNING cũ không lease quá 10 phút sẽ thành FAILED cho chạy lại.
