# Review T-013 — nhận xét giữa chừng (bước 1–6)

Chưa có verdict: task còn bước 7. Đã chạy lại `geometry-review-banner`, `object-review`, `progress-objectify`: 74 passed; typecheck PASS.

## Bước 7: chờ T-009 accepted (đồng ý với Engineer)
Đổi preset trước khi T-009 accepted sẽ làm mọi job mới dừng ở Draft trong lúc đường "Tạo mesh" chưa được chấp nhận. Giữ nguyên.
Đính chính: thay đổi chưa commit trong `object_geometry_build.py`/`objectify.py` là của **T-008** đang làm, không phải T-009.
T-009 chỉ còn một sửa nhỏ trong `extraction.py`.

## Bước 1–6: đạt, chấp nhận các lệch plan
- Nút Walk khoá riêng khi Draft (viewer tự ẩn Walk khi không có collision): đúng.
- Lớp collision rỗng khi Draft vì không gọi walk-collision: đúng, khớp backend 409.
- Trạng thái lạ trong `object_geometry` → coi như Draft và khoá: an toàn, chấp nhận.
- Số "N vật" đếm vật chưa bị xoá/gộp/bỏ qua: hợp với người dùng, giữ nguyên (backend dựng thêm collider cho vật bị bỏ qua chỉ để ghép collision).

## Làm thêm cùng bước 7 (bắt buộc trước khi đặt implemented)
1. Khoá trong UI khi Draft, cùng tooltip `GEOMETRY_NOT_READY_REASON`: thêm box, thêm vật từ thư viện, nhân bản, đánh dấu/xoá/lấp bề mặt va chạm.
   Backend đã từ chối (T-012) nhưng để người dùng bấm rồi nhận lỗi 422 là UX kém. Test: Draft → các nút disabled; ready → như cũ.
2. Bước 7 theo plan, sau khi `.ai/status.md` ghi T-009 `accepted`.
