# Review T-008

Verdict: ACCEPTED

Đã đọc `report.md`, diff `7d348ea4` (chọn surface theo vật) và phần kiểm runtime/quan sát. Chạy lại
`test_object_geometry_build_objectgs.py`, `test_object_geometry_build.py`, `test_objectgs_objectify_flow.py`: 55 passed.
Hai test hỏng trong `test_objectify_draft.py` do T-009 gây ra (fixture giả thiếu `config_checksum`/`job`), không thuộc T-008;
đã mở T-009 Round 3 để sửa.

## Acceptance criteria
1. A qua QA → surface ObjectGS; B không qua → vỏ + `surface_selection` có `reason` và `quality_reasons`; evidence ObjectGS publish cho cả hai: **pass**.
2. ObjectGS lỗi toàn cục → build thất bại, không tạo collider từ vỏ, scene không đổi: **pass**.
3. Thiếu runtime ObjectGS → lỗi rõ, kiểm trước khi ghi gì: **pass**.
4. Mask dựng lại từ nhãn hiện tại phản ánh chỉnh vùng: **pass**.
5. `geometry_method=shell` không gọi ObjectGS: **pass**.
`raise_on_quality_failure` mặc định `True` nên luồng ObjectGS cũ trong `objectify()` giữ hành vi.

## Quyết định
1. **Mask từ nhãn hiện tại thay vì mask SAM2 lúc tách:** chấp nhận. Đây là cách duy nhất để chỉnh vùng trong Draft có tác dụng lên ObjectGS.
   Rủi ro chất lượng mask chỉ kiểm được trên GPU với scene thật; ghi vào handoff T-019.
2. **Dựng lại một phần bằng ObjectGS:** chốt cho T-011 — khi `geometry_method=objectgs` và build có `object_ids` (sửa vùng sau Ready),
   **không** chạy ObjectGS (mô hình dùng chung, train lại cả scene mất hàng giờ). Vật bị ảnh hưởng dựng lại bằng vỏ, ghi
   `surface_selection = {"chosen": "gaussian_shell", "reason": "partial_rebuild_uses_shell"}`. Vật khác giữ surface ObjectGS cũ.
   Đây là quy tắc công bố, hiển thị trong Studio, không phải fallback âm thầm. Lỗi "từ chối" hiện tại trong code phải đổi theo quy tắc này ở T-011.
3. **ObjectGS chạy trước collider:** chấp nhận; `architecture.md` §7.4 đã sửa thứ tự phase.
4. **Lớp lỗi thử lại:** RuntimeError/OSError retryable, ValueError không: chấp nhận.

## Quy trình
Lần sau đặt `in-progress` khi bắt đầu.
