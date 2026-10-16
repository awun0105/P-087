# Review T-031

Verdict: ACCEPTED (Architect tự sửa 2 lỗi logic, commit riêng)

Đọc trọn `value/measure.py` (325 dòng) và test; đối chiếu `effective_environment` với đường Walk
(`physics_collision.effective_collision_for_revision`: cùng hàm, cùng `carve_margin_m`; Walk thêm phục hồi ownership cho revision
hiện tại, measure đọc revision bất kỳ nên từ chối revision cũ thiếu ownership — đã ghi trong docstring, chấp nhận).

## Acceptance criteria
1. Pass. Hàm thuần, xác định.
2. Pass. Không đọc ground truth, không ghi.
3. Pass. Sai số bề rộng ≤ 1 cm trên test hộp.
4. Pass. Chọn vật theo `resolve_representation(...).export_as_object`, có test đối chiếu với `scene_representations` của USD.

## Lỗi tìm ra khi audit và đã sửa
1. **Kiểm "trung điểm ở trong vật" dùng chẵn lẻ trên cả vật.** Collider CoACD gồm nhiều mảnh lồi chồng nhau: điểm trong vùng chồng
   cắt 2 + 2 mặt → báo "ngoài" → bề rộng khe sai. Sửa: kiểm theo từng mảnh kín (`face_part`, `solid_parts`).
2. **Kiểm vết cũ sau khi dời tính cả collider vật khác.** Ghế dưới bàn hoặc vật khác được dời tới chỗ cũ làm `old_cleared = False`.
   Ý đồ quy tắc là collision **môi trường** còn sót. Sửa: chỉ xét tam giác môi trường. §15.3 quy tắc 3–4 đã cập nhật.
Hai test mới đỏ trên logic cũ, xanh trên logic mới (đã kiểm bằng cách tạm đặt lại logic cũ). `test_value_measure.py`: 26 PASS.

## Suggestions (không chặn)
- `_inside_solid` duyệt từng mảnh × mỗi độ cao: ổn với vài chục vật; nếu bảng benchmark chậm thì lọc mảnh theo hộp bao trước.
- Tia đi qua đúng cạnh/đỉnh chung có thể đếm đôi (chẵn lẻ sai); xác suất thấp với toạ độ đo tay.
