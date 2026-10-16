# Hướng dẫn cho coding agent (đọc trước mọi task)

1. Đọc `architecture.md`, `roadmap.md`, rồi `tasks/T-xxx/plan.md` của task được giao. Chỉ làm task có trạng thái `planned`
   và mọi task ở cột "Cần" (roadmap) đã `accepted`.
2. Đặt `status.md` của task thành `in-progress` khi bắt đầu.
3. Trước khi sửa code: dùng `codegraph_explore` (hoặc `codegraph explore "<tên>"`) cho các symbol trong plan; chạy
   `graphify query "<câu hỏi>"` khi cần định hướng.
4. **Không chạy full test suite.** Chỉ chạy đúng lệnh trong mục "Tests required" của plan, cộng ruff/eslint cho file đã sửa
   và `npm run typecheck` nếu sửa TypeScript. Full suite chỉ ở T-019.
5. **Commit sau mỗi thay đổi nhỏ** đã qua test liên quan (theo mục "Commit" của plan). `git add` đúng đường dẫn file đã sửa,
   không dùng `git add -A` hay `git add .` (có agent khác cùng sửa cây). Commit message tiếng Anh, mô tả hành vi.
   **Không** thêm `Co-Authored-By` hay "Generated with …".
6. Branch `mvp-pipeline-v2`. Không tạo branch mới, không push, không merge, không tạo PR.
7. Không viết lại COLMAP, Brush, SAM2, ObjectGS, CoACD, physics. Không fallback âm thầm sang OBB/hull để báo thành công.
   Không hardcode theo scene Room. Không train scene mới.
8. Sau khi sửa code: `graphify update .` ở root. Dọn file tạm ngay.
9. Xong task: viết `tasks/T-xxx/report.md` (đã làm gì, file nào, lệnh test + kết quả thật, quyết định lệch plan và lý do,
   việc còn dở), đặt `status.md` → `implemented`.
10. Gặp câu hỏi thiết kế mà plan không trả lời: dừng, ghi câu hỏi vào cuối `report.md`, đặt trạng thái `changes-requested`
    kèm ghi chú "cần Architect", không tự đoán các quyết định khó đảo ngược.
11. **Không bao giờ xoá gì ngoài thư mục tạm của chính bạn và file bạn tạo trong repo.** Cấm `rm -rf` trên `/tmp`,
    `/tmp/claude-*`, thư mục home hay thư mục của phiên khác. Dọn file tạm bằng đường dẫn đầy đủ của từng file/thư mục bạn tạo.
