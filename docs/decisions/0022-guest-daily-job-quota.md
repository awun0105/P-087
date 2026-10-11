# 0022 Guest calendar-day quota và accepted run identity

Date: 2026-10-07

## Status

Accepted — owner-confirmed policy and local UX are implemented through AUD-22.S3,
including migration v14 and API enforcement. Local SQLite/API/frontend checks
pass; browser acceptance and shared-PostgreSQL concurrency qualification remain
pending because the Chrome profile is locked and `R2S_TEST_POSTGRES_URL` is unset.

## Implementation status

The durable ledger is enforced for `scene.create`, `job.create`, and `job.retry`.
`/auth/me` returns a Guest-only summary; accepted responses replay the exact
immutable job manifest by its stored artifact reference. The three routes fail
closed when their required persistent runtime database is unavailable. Objectify
is explicitly excluded from Guest's daily counter and continues through existing
worker/resource admission. AUD-22.S3 renders the `/auth/me` summary in Account,
scene creation and Retry;
accepted runs refresh that summary, and a stable quota 429 refreshes stale tabs.
The browser remains the final visual acceptance gate.

## Context và decision

Owner đã chốt 3 accepted runs mỗi ngày, tính manual Retry; reset 00:00
Asia/Ho_Chi_Minh. Worker automatic retry, admission wait và duplicate request cùng
intent không tính thêm. Failed/cancelled sau accepted intent vẫn tính; rejected
input/permissions/transaction không tính. Quota charge actor, không resource owner.
Editor giữ configurable rolling24h policy, Reviewer unlimited; Guest cap fixed3.

Authoritative DB reservation/counter và durable queued intent/transition phải atomic,
unique actor-scoped idempotency key+fingerprint; không dùng audit count-then-insert.
UTC persisted calendar windows, explicit 429/summary DTO. Cancellation/edit/delete
own job vẫn được khi hết quota. Preview→final job mới tính lượt mới, auto-resume
cùng run không tính. Promotion/demotion dùng current role và retain usage history.

## Contract chốt tại AUD-22.S1

Guest policy `guest_calendar_day_v1` có fixed limit 3. Window là nửa mở
`[window_start_utc, resets_at_utc)`, được tính từ hai mốc 00:00 liên tiếp trong
`Asia/Ho_Chi_Minh`, rồi lưu/trả về bằng UTC. Không cộng cố định 24 giờ hoặc dựa
vào timezone máy chủ. Pure helper `guest_quota_window()` và immutable Pydantic
contracts `GuestQuotaWindow`, `GuestQuotaSummary`, `GuestQuotaExceededDetail` đã
được thêm; AUD-22.S2 now uses them in `/auth/me` and API 429 responses.

Quota unit là một user-initiated run được durable queue/job nhận: tạo
reconstruction job qua cả `/scenes/from-upload` và `/projects/{project_id}/jobs`,
hoặc manual Retry được chấp nhận. Theo xác nhận của owner ngày 2026-10-08,
objectify/tách vật không trừ quota 3 lượt/ngày của Guest, kể cả khi worker nhận yêu
cầu. Thao tác này vẫn đi qua worker/resource admission; behavior quota rolling24h
hiện có của Editor không đổi. Một lần worker resume/automatic continuation,
admission wait, duplicate với cùng `Idempotency-Key` và fingerprint không thêm
unit. Validation/permission/CAS
failure trước durable acceptance không charge; accepted intent vẫn charge nếu job
sau đó fail hoặc bị cancel. Các thao tác edit/delete/cancel/view/metric preview/
simulation-package không bị tính thêm quota unit.

Schema migration additive tạo `r2s_guest_quota_windows` với unique key
`(actor_user_id, policy_id, window_start_utc)`, `policy_limit`, `used_count`, UTC
reset time, FK tới user và CHECK `0 <= used_count <= policy_limit`. Bảng
`r2s_quota_intents` lưu operation, actor, policy/window, idempotency key, request
fingerprint, acceptance time và result ID; unique key
`(actor_user_id, operation_kind, idempotency_key)` chạy xuyên ngày và role change.
Audit log giữ cho chẩn đoán/Editor policy, không là source-of-truth Guest.

Một transaction giữ quota-window row, kiểm duplicate/fingerprint, kiểm tra lại
target ownership/status/CAS, tăng counter, ghi accepted intent và queued job/attempt
(kèm project/upload links với scene-from-upload). Nếu job/transition không commit,
quota cũng rollback; worker dispatch chỉ sau commit. PostgreSQL dùng row lock.
SQLite `BEGIN IMMEDIATE` chỉ đồng bộ process dùng chung một file; quota across
replicas yêu cầu shared PostgreSQL, không nhiều SQLite cục bộ rời nhau.

`GuestQuotaSummary` có `policy_id`, `limit`, `used`, `remaining`, window start/reset
UTC và timezone. Exhaustion trả 429 `code=guest_daily_job_quota_exceeded` cùng
summary; frontend không parse message. Editor giữ rolling24h configurable và
Reviewer unlimited.

Alternatives rolling24h cho Guest hoặc quota frontend không đúng requested policy.
Counting objectify against Guest's daily counter was an earlier source-based
assumption; the owner's explicit clarification supersedes it.
Global Editor quota rewrite ngoài scope. Need multi-process real DB race/crash tests
và browser midnight/reset UX; GPU runtime không cần cho quota proof.

## Consequences

Mở Guest onboarding với giới hạn rõ và giữ quyền hiện tại của team.
Forward migration, typed contracts and local permission/quota regression are
implemented. Local quota UX and Guest edit-at-cap behavior are covered; browser
acceptance and shared PostgreSQL proof remain open.
Không reset DB, rewrite old artifacts hoặc triển khai SMTP trong scope này.

## AUD-22.S3 implementation evidence

- Guest usage and reset time are read from `/auth/me`; the UI uses the server's
  `Asia/Ho_Chi_Minh` timezone and does not use localStorage as quota authority.
- Quota exhaustion disables only new scene creation and manual Retry. Existing
  ownership-checked edit/cancel/delete actions remain available. A Retry rejected
  with `guest_daily_job_quota_exceeded` refreshes the current summary for stale tabs.
- No migration was needed in S3: migration v14 already persists the counter and
  accepted intent. `/auth/me` and the stable 429 response remain the diagnostic
  contract; no personal data or idempotency keys are logged.
- Local verification: 284 frontend tests across 42 files, typecheck, ESLint,
  14 Guest quota/ownership API tests, repo Ruff check and format check passed.
- Pending: Chrome DevTools visual acceptance (profile locked) and shared-PostgreSQL
  concurrency/restart proof (`R2S_TEST_POSTGRES_URL` unset).

## Follow-Up

- [Task](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-22-guest-daily-job-quota.md).
- [Master plan](../plans/active/2026-10-07-codegraph-audit/README.md).
