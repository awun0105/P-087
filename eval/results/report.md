# Evaluation Report (Báo cáo Đánh giá MVP)

> Báo cáo đánh giá chất lượng sản phẩm theo tiêu chí BTC, bao gồm các bằng chứng kiểm thử thực tế.

---

## 1. Metrics Tổng quan

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Tái tạo hình ảnh (3DGS) | PSNR > 20 | Đạt ~24-28 (Tùy cảnh) | ✅ |
| Khôi phục lỗi (Fault Tolerance)| < 5s để tiếp tục | Resume từ Checkpoint | ✅ |
| Chống tràn RAM (Memory Safe) | 100% không crash | Đạt 100% | ✅ |
| Giao diện người dùng | Mượt mà, phản hồi tốt | Xử lý đa nền tảng | ✅ |

---

## 2. Eval Evidences — 5 Test Case Manual Thực Tế

Dưới đây là 5 kịch bản kiểm thử (test case) thủ công đã được thực hiện trực tiếp trên hệ thống MVP.

### Test Case 1: Tải lên Video và Khởi tạo Job Pipeline
- **Mô tả:** Người dùng tải lên video `aisle_cw.mp4` (dài ~100s) qua giao diện Web Studio để bắt đầu tạo Scene 3D.
- **Các bước thực hiện:**
  1. Vào trang "Scene Mới", upload file `aisle_cw.mp4`.
  2. Khai báo các metadata (synthetic, public_or_synthetic, purpose).
  3. Bấm "Bắt đầu xử lý".
- **Kết quả kỳ vọng:** Hệ thống tiếp nhận luồng stream, trả về `upload_id`, sau đó tự động queue Job mới (trả về mã HTTP 201). Giao diện chuyển mượt mà sang trạng thái theo dõi Tiến trình.
- **Output thực tế (Evidence):** API trả về `201 Created` với `job_id` dạng `job-1bb733ae40ad`. Worker nền lập tức nhận lệnh và khởi chạy bước `ST-INPUT-VALIDATE`. Quá trình tách frame (FFmpeg) bắt đầu sau 2s.

### Test Case 2: Resume/Thử lại khi Worker chết đột ngột (Fault Tolerance)
- **Mô tả:** Đảm bảo hệ thống không bắt người dùng cày lại từ đầu khi đang train 3DGS mà máy chủ sập nguồn hoặc quá nhiệt.
- **Các bước thực hiện:**
  1. Trong lúc job `job-9b9aa3dac9f1` đang ở bước `ST-VISUAL-RECON` (Brush), tắt ép (kill) tiến trình worker.
  2. Refresh lại Web UI, quan sát thấy cảnh báo tiến trình ngắt kết nối.
  3. Bấm nút "Thử lại" màu cam.
- **Kết quả kỳ vọng:** Job không chạy lại SfM (COLMAP), mà lập tức nạp checkpoint 3DGS cuối cùng để train tiếp.
- **Output thực tế (Evidence):** Nút gọi API `POST /api/v1/jobs/job-9b9aa3dac9f1/retry`. Job được đưa về lại trạng thái `QUEUED`. Worker khởi động lại báo log: *`Loading checkpoint from <job_id>/resume/step-3000`* và hoàn thành nhanh chóng thay vì tốn thêm 53s SfM.

### Test Case 3: Giao diện bảo lưu tuỳ chọn cấu hình cấu hình máy tính yếu
- **Mô tả:** Đảm bảo giao diện chọn cấu hình (Preset) không bị "nhảy giật lùi" gây khó hiểu cho người dùng máy tính yếu.
- **Các bước thực hiện:**
  1. Truy cập tab thông số, bấm chọn "Tối đa cho máy này".
  2. Máy tính hiện tại là Quadro T2000 (RAM/VRAM thấp), hệ thống tự ép thông số xuống bằng với mức "Tối thiểu".
- **Kết quả kỳ vọng:** Dù thông số bị ép xuống, nút "Tối đa cho máy này" vẫn phải sáng màu để biểu thị đúng ý định người dùng.
- **Output thực tế (Evidence):** Giao diện giữ nguyên màu highlighted ở tuỳ chọn "Tối đa cho máy này". State của form xử lý chính xác `selectedPreset = "machine_maximum"`. Payload gửi xuống API được tính toán chuẩn theo năng lực worker.

### Test Case 4: Giới hạn Voxel Grid an toàn (Chống Crash 34 Tỷ Block)
- **Mô tả:** Bounding box của lưới tọa độ COLMAP đôi lúc bị nhiễu và kéo dài vô tận, khiến thuật toán tạo Voxel văng lỗi `MemoryError` khi cố tạo ma trận hàng chục tỷ block.
- **Các bước thực hiện:**
  1. Gửi vào hệ thống một tập pose bị drift với bounding box rộng ~1000 mét.
  2. Kích hoạt bước `ST-RGB-GEOMETRY` (dựng hình học & collision).
- **Kết quả kỳ vọng:** Hệ thống phát hiện độ phân giải bị quá tải, tự động "hạ cấp" (throttle) resolution để đảm bảo không sập RAM.
- **Output thực tế (Evidence):** Thuật toán `compute_safe_resolution` (đã nâng cấp) can thiệp, giới hạn Node Cap ở mức 1.5 Tỷ block. Log in ra: *`Volume exceeds 1.5B node cap (34B), scaling resolution from 256 to 32`*. Lưới Mesh và Collision được tạo thành công trong 18s, máy tính không bị crash.

### Test Case 5: Đếm ngược thời gian linh hoạt (Dynamic ETA decay) cho Job bị lố giờ
- **Mô tả:** Khi một bước (ví dụ: tạo hình học) dự kiến tốn 18 giây, nhưng vì máy chạy chậm nên tốn 30 giây.
- **Các bước thực hiện:**
  1. Theo dõi tiến trình thanh trạng thái của một job xử lý nặng.
  2. Quan sát đồng hồ khi ETA rớt xuống 0 nhưng chưa xong.
- **Kết quả kỳ vọng:** Thời gian chờ phải giãn ra nhịp nhàng, thay vì kẹt cứng ở 18s hoặc hiển thị số âm.
- **Output thực tế (Evidence):** Công thức `current_elapsed * 0.15` hoạt động chính xác. Khi quá 18s, ETA tự động decay chậm dần (hiển thị còn 4s, 3s kéo dài). Người dùng không bị cảm giác máy "bị treo", thanh progress bar nhích nhẹ đều đặn cho tới khi worker trả kết quả `COMPLETED`.

---

## 3. Demo Results & Feedback

- **Thời gian Demo MVP:** 04/10/2026
- **Trạng thái Codebase:** Tất cả các luồng đã sẵn sàng để review và đóng gói (`r2s-studio-data.zip` via Docker Compose).
- **Feedback chung:** Khắc phục triệt để các rủi ro kẹt giao diện, lỗi crash bộ nhớ và nâng tầm tính ổn định của luồng Data Pipeline.
- **Action Items:** Chuẩn bị triển khai Production và Validation trực tiếp với robot thật trên NVIDIA Isaac Sim.
