# 0021 Guest identity, public signup và resource ownership

Date: 2026-10-07

## Status

Accepted — owner đã chốt role/ownership behavior; code-level signup, backend
ownership and quota enforcement are implemented in AUD-21/AUD-22. Public Guest
signup remains disabled until browser, shared-PostgreSQL and seed acceptance pass.

## Context và Decision

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

Guest đăng ký bằng email, display name và password, không cần invite; email
verification bị hoãn. Visitor chưa đăng nhập vẫn chỉ dùng các mẫu. Guest có hạn
mức ba job-create hoặc manual-Retry intents được chấp nhận mỗi ngày lịch
Asia/Ho_Chi_Minh; objectify/tách vật, duplicate idempotent request và worker resume
không tính. Editor/Reviewer tiếp tục can thiệp cross-user, còn purge và review/release
giữ reviewer-only. `AUTH_GUEST_SIGNUP_ENABLED` mặc định `false` tới khi browser,
shared-PostgreSQL và seed acceptance hoàn tất.

`GET /scenes`, `/jobs/{job_id}/progress`, `/imports` và `/trash` trả typed,
caller-specific `capabilities` để UI ẩn thao tác không phù hợp. Đây chỉ là gợi ý
hiển thị: API mutation vẫn chạy cùng owner/role guard độc lập, vì client có thể gửi
request trực tiếp hoặc dùng dữ liệu capabilities cũ.

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
