# 0022 Guest calendar-day quota và accepted run identity

Date: 2026-10-07

## Status

Proposed — product behavior được owner chỉ đạo; AUD-22.S1 đã chốt calendar,
idempotency và transaction design. Migration/enforcement chưa implement hoặc
runtime-qualified.

## Context và Decision đề xuất

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
được thêm; `/auth/me` và API 429 bắt đầu dùng chúng ở sprint sau.

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
Cần forward migration, typed contracts, permission/quota regression và browser proof.
Không reset DB, rewrite old artifacts hoặc triển khai SMTP trong scope này.

## Follow-Up

- [Task](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-22-guest-daily-job-quota.md).
- [Master plan](../plans/active/2026-10-07-codegraph-audit/README.md).
