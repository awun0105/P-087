# Execution Plans

Execution plan là Git-native working memory cho công việc phức tạp. Với một
assigned execution task thông thường, dùng chính task file; không tạo plan trùng
lifecycle.

Tạo một plan trong `active/` khi work qua nhiều task/session/contributor, có
dependency đáng kể hoặc cần recovery. Dùng `docs/templates/exec-plan.md`, cập
nhật trong quá trình làm, rồi chuyển sang `completed/` chỉ sau validation.

Lasting product/architecture decision phải được promote vào authoritative source
hoặc `docs/decisions/`; task-local decision giữ trong task/plan.
