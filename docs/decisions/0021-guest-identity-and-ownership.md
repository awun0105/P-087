# 0021 Guest identity, public signup và resource ownership

Date: 2026-10-07

## Status

Proposed — product behavior được owner chỉ đạo; technical schema/migration cần
chốt trong sprint S1. Chưa implement hoặc runtime-qualified.

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

Schema defaults/read compatibility phải chốt S1; không rewrite checksum artifacts cũ.
Self-demotion Reviewer tới Guest cũng phải bị chặn. Alternative chỉ thêm role rank
hoặc ẩn button không bảo vệ ownership; invitation-only bỏ mất requested public signup.

## Consequences

Mở Guest onboarding với giới hạn rõ và giữ quyền hiện tại của team.
Cần forward migration, typed contracts, permission/quota regression và browser proof.
Không reset DB, rewrite old artifacts hoặc triển khai SMTP trong scope này.

## Follow-Up

- [Task](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-20-user-display-name-and-creator.md).
- [Master plan](../plans/active/2026-10-07-codegraph-audit/README.md).
