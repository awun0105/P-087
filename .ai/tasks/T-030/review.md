# Review T-030

Verdict: ACCEPTED

Đọc `value/ground_truth.py` (model, `read_truth`, `write_truth`, `_current_version`), phần route mới trong `api/studio/value.py`,
migration 21. Chạy lại benchmark_truth + value_routes + runtime_migrations: 54 PASS.

## Acceptance criteria
1. Pass. CAS đúng: khoá dòng (`lock_suffix`), so version, `UPDATE … WHERE version=?`, `rowcount != 1` → conflict; tạo lần đầu
   `ON CONFLICT DO NOTHING` nên hai bên cùng tạo thì một bên 409, không 500. Có test hai luồng.
2. Pass. Revision layout kiểm bằng `registry.scene.revision` (theo lineage); vật cản chính kiểm trong scene hiện tại; 422 nêu đúng mục.
3. Pass. GET khi chưa có tài liệu trả version 0 + mặc định.

## Lệch plan
`extra="forbid"` cho mọi model con, `default_factory`, `updated_at` trong payload, thêm validator a ≠ b và id vật cản không trùng:
chấp nhận, đều chặt hơn plan.

## Suggestions (không chặn)
- Vật cản chính bị xoá khỏi scene sau này (đối tượng mất hẳn, không phải tombstone) làm mọi PUT sau đó 422 tới khi bỏ id ấy.
  Panel T-033 nên hiện rõ id nào không còn và cho bỏ chọn.
- Nhánh PostgreSQL chưa chạy thật: ghi vào T-035 để chạy khi có Postgres.
- Phụ thuộc file của T-027 (`value.py`): khi T-027 sửa vòng 2 chỉ đụng `objectify_queue.request` và `events.py`, không xung đột.

## Audit sâu sau khi accept (Architect tự sửa, commit riêng)
1. **`tagged_at` do trình duyệt gửi** được lưu nguyên, trong khi P3 so nó với giờ máy chủ của sự kiện → đồng hồ máy khách lệch là
   P3 sai/âm. Sửa: máy chủ đóng dấu khi revision của layout đổi, giữ mốc cũ khi không đổi.
2. **Layout A và B cùng revision** được chấp nhận → P3 vô nghĩa. Sửa: 422.
3. **Vật cản chính đã lưu mà rời scene** chặn mọi PUT sau đó. Sửa: chỉ kiểm id/revision mới hoặc đổi.
3 test mới; value_routes + benchmark_truth + role_matrix: 49 PASS.
