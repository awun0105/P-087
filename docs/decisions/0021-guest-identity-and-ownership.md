# 0021 Guest identity, public signup và resource ownership

Date: 2026-10-07

## Status

Proposed — owner đã chỉ đạo product behavior; AUD-21.S1 đã chốt ownership và
migration contract từ source inventory. AUD-21.S2 đã thêm signup/role lifecycle
đằng sau `AUTH_GUEST_SIGNUP_ENABLED=false`; ownership, quota và rollout chưa
runtime-qualified, nên ADR chưa được xem là hoàn tất.

## Context và Decision đề xuất

Owner yêu cầu tên người dùng, creator/role trên scene cards và ba roles.
Tên/signup input đã có, nên reuse. Role hierarchy guest < editor < reviewer;
Guest được Editor workflows trên own resources, shared read giữ hiện tại.
Editor/Reviewer giữ cross-user rights gồm Guest jobs; reviewer-only actions không mở.

Public signup server tạo Guest, không invite; invited signup vẫn Editor/Reviewer.
Email/password/name required; email verification deferred, không hiển thị verified.
Immutable creator ID/name/role snapshot khác run actor và current authorization role.
Legacy owner thiếu thì Guest không mutate. Backend guard toàn bộ mutation/worker
paths; frontend capabilities chỉ UX. Seed Reviewer “Minh An”, Editor “Hà Linh”
được áp dụng có định danh, giữ credentials/IDs/roles và không tạo seed mới.

Schema/default/read compatibility: `user_id` bất biến là owner; `Actor.role` và tên
là snapshot hiển thị. Project owner nằm ở `ProjectRecord.created_by.user_id`, upload
owner ở `uploaded_by.user_id`, import owner ở `created_by`; mỗi job lưu
`owner_user_id` trên authoritative `r2s_jobs` row trong transaction tạo job, không
đưa vào checksum-bound `JobManifest`. Job owner độc lập với project owner và actor
của lần retry. Field nullable cho auth-disabled/legacy records; backfill chỉ từ
creator ID đã lưu, không đoán bằng tên/email/parent/requester. Guest chỉ đọc được
legacy resource có owner unknown; Editor/Reviewer giữ quyền can thiệp.

Guest chỉ sửa resource mình sở hữu; parent và mọi source/descendant thực sự bị
ghi/xóa cũng phải qua policy. Project cascade bị từ chối nguyên tử nếu Guest không
sở hữu bất kỳ descendant nào. Derived artifacts giữ owner của root job/import;
operator hoặc người đưa vào trash không nhận quyền sở hữu. Các API/service/worker
guard dùng server user hiện tại và resource mapping; snapshot role/client claim
không cấp quyền. Forward migration additive trên SQLite/PostgreSQL, không rewrite
artifact checksum hoặc reset DB. Open signup chỉ enable sau khi S3 ownership
guards đã phủ mọi mutation ingress.

Self-demotion Reviewer tới Guest cũng phải bị chặn. Alternative chỉ thêm role rank
hoặc ẩn button không bảo vệ ownership; invitation-only bỏ mất requested public signup.

## Consequences

Mở Guest onboarding với giới hạn rõ và giữ quyền hiện tại của team.
Cần forward migration, typed contracts, permission/quota regression và browser proof.
Không reset DB, rewrite old artifacts hoặc triển khai SMTP trong scope này.

## Follow-Up

- [Task](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-20-user-display-name-and-creator.md).
- [Guest ownership task](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-21-guest-signup-and-ownership.md).
- [Master plan](../plans/active/2026-10-07-codegraph-audit/README.md).
