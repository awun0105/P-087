# 0027 Chẩn đoán lỗi COLMAP theo kết quả, đoạn trích log đã che và hướng khắc phục trên UI

Date: 2026-10-08

## Status

Proposed — chờ owner duyệt. Kế hoạch triển khai: [AUD-27](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-27-structured-error-diagnostics-and-redacted-excerpts.md).

## Context

1. **COLMAP báo lỗi quá chung.** [`ColmapProcess.run`](../../src/services/reconstruction/adapters/colmap_runtime.py)
   ném `COLMAP_PROCESS_FAILED` với câu "failed (exit N)" cho mọi mã thoát khác 0. Khi
   COLMAP chạy xong mà không dựng được model nào, lỗi thành `COLMAP_ARTIFACT_INVALID`
   với câu "inspect attempt artifacts", dù nguyên nhân là video đầu vào.
   `COLMAP_REGISTRATION_LOW` đã có nhưng không kèm con số.
2. **Brush đã làm tốt hơn.** `brush_runtime.py` có `FATAL_LOG_PATTERNS` để nhận ra hết bộ
   nhớ GPU và treo driver. Cách đó hợp với Brush vì các chuỗi đó chỉ xuất hiện khi hỏng.
3. **Log COLMAP không dùng được theo cách đó.** Trong 29 file `process.log` của các lượt
   chạy thành công, `=> Could not register, trying another image.` xuất hiện 1.011 lần,
   `Linear solver failure` 157 lần, `=> No good initial image pair found.` 29 lần,
   `Discarding reconstruction due to insufficient size` 20 lần. Đây là thông báo bình
   thường của quá trình dựng tăng dần.
4. **Quy tắc bảo mật hiện có.** Docstring của `ColmapError` và `VisualError` cấm đưa đường
   dẫn riêng và stderr thô ra UI. `details` của lỗi được lưu vĩnh viễn trong JobManifest,
   và `GET /jobs/{job_id}/progress` trả lỗi cho mọi người dùng có quyền contributor.
5. **UI chỉ hiện một dòng.** `PipelineTimeline.tsx` hiển thị `human_message (error_code)`;
   `details` và `retryable` có trong contract nhưng không được dùng. `human_message` và
   `details.action` hiện là tiếng Anh.

## Quyết định đề xuất

1. **Phân loại lỗi COLMAP theo kết quả, không theo nội dung log.** Không dừng tiến trình
   dựa trên chuỗi log. Thêm hai mã: `COLMAP_NO_MODEL` (chạy xong, không có model) và
   `COLMAP_OUT_OF_MEMORY` (mã thoát -9 hoặc 137, hoặc đoạn cuối log có `std::bad_alloc`).
   Giữ `COLMAP_REGISTRATION_LOW` và thêm số ảnh dựng được, tổng số ảnh, ngưỡng vào `details`.
2. **Log chỉ dùng để chọn lời giải thích.** Với `COLMAP_NO_MODEL`, đếm số lần xuất hiện
   của `Discarding reconstruction due to no initial pair` và `... insufficient size`, ghi
   vào `details.diagnostics`.
3. **Đoạn trích log đã che.** Khi lệnh COLMAP lỗi, lấy tối đa 40 dòng cuối (tối đa 4.096
   byte) của riêng lệnh đó, thay đường dẫn workspace bằng `<workspace>` và mọi đường dẫn
   tuyệt đối khác bằng `<path>`, ghi vào `details.log_excerpt`.
4. **Che theo vai trò ở server.** Response chỉ giữ `log_excerpt` cho reviewer, hoặc khi
   deployment tắt đăng nhập. Một hàm dùng chung áp dụng cho mọi route trả `ExecutionError`.
5. **Tiếng Việt nằm ở frontend.** Một bảng `error_code → nguyên nhân, cách khắc phục` trong
   frontend phủ cả mã COLMAP lẫn mã Brush đang có. Backend giữ `human_message` tiếng Anh;
   mã chưa có trong bảng thì UI hiện `human_message`.
6. **Hiển thị tại chỗ.** Stage lỗi hiện nguyên nhân, cách khắc phục và khả năng thử lại
   mà không cần bấm; phần "Chi tiết kỹ thuật" là phần tử `<details>` chứa đoạn trích.
   Không thêm endpoint log, drawer hay trang riêng.
7. **Gắn `job_id` và `attempt_id` vào log worker** bằng context của logging. Không dựng
   hạ tầng distributed tracing.

## Hệ quả

- Schema `ExecutionError` không đổi; `details` có thêm các key tùy chọn `log_excerpt`,
  `diagnostics`, `registered_frames`, `input_frames`, `min_registered_ratio`.
- `retryability.py` thêm `COLMAP_OUT_OF_MEMORY` vào nhóm thử lại được. `COLMAP_NO_MODEL`
  không thử lại được vì chạy lại cùng đầu vào cho cùng kết quả.
- Lỗi "không có model" đổi mã từ `COLMAP_ARTIFACT_INVALID` sang `COLMAP_NO_MODEL`; nơi
  nào so khớp mã cũ cho tình huống này phải cập nhật.
- Lỗi Brush được Việt hóa mà không phải sửa `brush_runtime.py`.

## Giới hạn đã biết

- Chưa có file log COLMAP thất bại thật nào ở local. Nhánh nhận diện hết bộ nhớ dựa vào
  mã thoát; nhánh `std::bad_alloc` chưa được kiểm trên runtime thật.
- Việc che đường dẫn dựa trên mẫu chuỗi. Dữ liệu nhạy cảm không có dạng đường dẫn (ví dụ
  tên file ảnh của người dùng) không bị che; vì vậy đoạn trích chỉ dành cho reviewer.
