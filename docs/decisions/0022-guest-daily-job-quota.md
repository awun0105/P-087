# 0022 Guest calendar-day quota và accepted run identity

Date: 2026-10-07

## Status

Proposed — product behavior được owner chỉ đạo; technical schema/migration cần
chốt trong sprint S1. Chưa implement hoặc runtime-qualified.

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

Alternatives rolling24h cho Guest hoặc quota frontend không đúng requested policy.
Global Editor quota rewrite ngoài scope. Need multi-process real DB race/crash tests
và browser midnight/reset UX; GPU runtime không cần cho quota proof.

## Consequences

Mở Guest onboarding với giới hạn rõ và giữ quyền hiện tại của team.
Cần forward migration, typed contracts, permission/quota regression và browser proof.
Không reset DB, rewrite old artifacts hoặc triển khai SMTP trong scope này.

## Follow-Up

- [Task](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-22-guest-daily-job-quota.md).
- [Master plan](../plans/active/2026-10-07-codegraph-audit/README.md).
