# AUD-11 — Baseline tests đúng registry và subprocess protocol

## Metadata và goal

- PLANNED; P0; PRODUCT + REC test owners; canonical PRODUCT-02/09, REC-11.
- SELF-CODE fixture correction; REUSE real subprocess trong bounded smoke.
- Goal: hai audit failures được giải quyết bằng tests phản ánh behavior hiện tại,
  giữ quota/retry và process cleanup invariants.
- [Agent guide](../AGENT_GUIDE.md). Không cần ADR mới cho fixture correction.

## Baseline và scope

Audit tại ef3a421: backend 1.522 passed, 2 failed, 40 skipped.
`test_retry_counts_against_gpu_quota`: fixture patch studio deps nhưng request
đi product deps; registry default chạm PostgreSQL và lỗi role.
`test_visual_interrupt_kills_its_separate_group`: fake Popen thiếu poll/returncode
protocol của implementation polling mới. Probe real child đã kill/reap, return -9.

CodeGraph trước sửa: secured fixture, retry_job/enforce_gpu_quota callers,
VisualProcess._invoke/_kill_group và preview cancellation tests.
Owned: tests/test_api/test_auth_routes.py, tests/test_reconstruction/test_preview_cancellation.py
và narrow test fixture helpers nếu cần. Không sửa production quota ordering,
remove eligibility guards hoặc đổi polling về mock cũ để làm suite xanh.

## Input / output / data contract

Input: isolated temp runtime DB, valid FAILED retryable job + editor session/quota;
fake/real subprocess đáp ứng poll/wait/returncode/PID group protocol.
Output: meaningful quota/retry/process tests không phụ thuộc developer PostgreSQL.
Test data giữ typed job/config/error contracts và transient exception eligibility.
Tests không kết nối DB/store production, không tạo GPU work hoặc kill process ngoài fixture.

## Dependencies

Hai sprints độc lập implementation AUD-01–10. Đây là baseline trước tích hợp.
Nếu xuất hiện production regression có repro thật, ghi finding/task riêng;
không tự mở rộng fixture task sang unrelated code changes.

## Sprint AUD-11.S1 — Isolate product registry và seed eligible retry

**Input:** existing secured/auth fixture, product retry route và quota policy.
**Output:** quota regression với valid failed job, isolated DB và no default PG access.
**Contract:** route resolves fixture registry qua đúng dependency boundary;
eligibility kiểm trước quota vẫn được giữ; denied quota không launch retry.

Implement: patch/inject product registry/settings cùng auth/studio consumers
thực sự được request dùng. Tạo real typed FAILED retryable job thay nonexistent
job-x; seed GPU usage ở fixture DB. Keep control case unknown/nonretryable job.
Tests: exhausted quota → 429 cho eligible retry; available quota → accepted retry
và usage counted đúng một lần; unknown/ineligible job theo current error contract;
unauthorized/role denial; no dependency access vào developer DB.
**Exit:** [ ] failing test corrected; [ ] semantic quota/eligibility assertions pass.

## Sprint AUD-11.S2 — Fake subprocess protocol và real cleanup regression

**Input:** VisualProcess polling implementation, fake Popen và isolated child session.
**Output:** accurate interrupt/timeout/fatal-log tests và bounded real child cleanup proof.
**Contract:** child process group riêng; interrupt kill/reap; no remaining child;
fatal-log/hang detection mới được bảo vệ; assertions không phụ thuộc wait call count.

Implement: fake có poll()/returncode/wait() theo protocol, inject interrupt vào
polling path đúng; assert outcome cleanup thay brittle exact method counts.
Real child sleep có start_new_session, capture PID do fixture tạo, bounded timeout,
finally cleanup; không signal inherited shell group hoặc actual worker.
Tests: KeyboardInterrupt, timeout, fatal GPU log marker, successful exit, subprocess
already-exited race; real returncode/signal + reaped child on supported platform.
**Exit:** [ ] cancellation suite pass; [ ] real cleanup evidence; [ ] no weakened polling behavior.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_api/test_auth_routes.py tests/test_reconstruction/test_preview_cancellation.py tests/test_orchestration/test_retryability.py -q
.venv/bin/ruff check tests/test_api/test_auth_routes.py tests/test_reconstruction/test_preview_cancellation.py
.venv/bin/ruff format --check tests/test_api/test_auth_routes.py tests/test_reconstruction/test_preview_cancellation.py
```

Sau hai fixes, chạy full backend suite một lần để cập nhật baseline counts và
ghi tất cả failures/skips, không ép số expected 1.524 khi suite đã đổi.
DONE khi corrected regressions và related suites pass; broader failures ghi đúng.

## Result / Evidence

Pending — commands/counts, isolated dependency proof, child PID/exit/reap evidence.
