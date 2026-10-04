# Evaluation Report (Báo cáo Đánh giá MVP)

> Báo cáo đánh giá chất lượng sản phẩm dựa trên các Pain Point cốt lõi mà Real2Sim Studio giải quyết.

---

## 1. Mục tiêu giải quyết Pain Point

| Pain Point của Kỹ sư Mô phỏng | Giải pháp của Real2Sim Studio | Đánh giá MVP |
|--------|--------|--------|
| Phải dùng nhiều công cụ thủ công để dựng 3D từ Video | Pipeline 1-click tự động hoàn toàn từ Video -> 3DGS -> Mesh. | ✅ Đạt |
| Mô hình 3D sai kích thước, không theo đơn vị mét | Tích hợp MoGe-2 ước lượng tỉ lệ và cho phép người dùng xác nhận qua UI. | ✅ Đạt |
| Mô hình cảnh thật thiếu lưới va chạm (Collider) | Tự động sinh lưới Voxel/Geometry từ 3DGS để Robot tương tác vật lý. | ✅ Đạt |
| Các vật thể bị dính liền thành một khối tĩnh | Pipeline v2 tích hợp SAM2 tách vật thể thành SceneIR độc lập. | ✅ Đạt |
| Tốn thời gian tải file và mở bằng phần mềm nặng | Tích hợp Web Viewer trực tiếp (SuperSplat/PlayCanvas) trên trình duyệt. | ✅ Đạt |

---

## 2. Eval Evidences — 5 Test Case Manual Giải Quyết Pain Point

Dưới đây là 5 kịch bản kiểm thử (test case) thủ công đã được thực hiện để chứng minh sản phẩm giải quyết đúng các Pain Point đã đề ra.

### Test Case 1: Tự động hoá End-to-End từ Video thô (Giải quyết Pain Point: Phải dùng nhiều công cụ)
- **Pain point cũ:** Kỹ sư phải tách frame bằng ffmpeg, chạy COLMAP lấy pose, đưa vào Blender, rồi mới train 3DGS bằng công cụ console. Tốn nhiều giờ và dễ sai sót cài đặt.
- **Các bước thực hiện:** 
  1. Vào trang "Scene Mới", upload video kho hàng `aisle_cw.mp4`.
  2. Bấm "Bắt đầu xử lý" và đi uống cà phê.
- **Kết quả thực tế (Evidence):** Hệ thống API tự động xếp hàng và kích hoạt chuỗi worker: `ST-INPUT-VALIDATE` -> `ST-CAMERA-POSE` -> `ST-VISUAL-RECON`. Không cần thao tác thủ công, sau thời gian xử lý, hệ thống trả về cảnh 3DGS trực quan hiển thị ngay trên Web.

### Test Case 2: Xác nhận Tỉ lệ Chuẩn Mét (Giải quyết Pain Point: Mô hình sai kích thước thực tế)
- **Pain point cũ:** Mô hình 3D xuất ra bị sai tỉ lệ (to hoặc nhỏ bất thường), đưa vào Isaac Sim thì robot khổng lồ hoặc bé tí so với kho hàng.
- **Các bước thực hiện:**
  1. Truy cập tab "Kích thước" của Scene đã xử lý.
  2. Hệ thống (MoGe-2) đã tự động gợi ý hệ số quy đổi. Người dùng quan sát mặt sàn lưới (Grid) 1x1 mét trên trình duyệt để đối chiếu và bấm "Xác nhận tỷ lệ".
- **Kết quả thực tế (Evidence):** Tỉ lệ được lưu vào canonical metric transform của `SceneIR`. Tránh được hoàn toàn lỗi sai lệch tỉ lệ môi trường khi chuyển giao cho Simulation.

### Test Case 3: Tự động trích xuất Lưới Va Chạm - Collider (Giải quyết Pain Point: Thiếu vùng va chạm vật lý)
- **Pain point cũ:** Gaussian Splatting nhìn thì đẹp nhưng chỉ là các đốm màu ảo, robot đi xuyên qua tường vì không có khối lượng hay mặt phẳng vật lý.
- **Các bước thực hiện:**
  1. Đợi pipeline chạy đến bước `ST-RGB-GEOMETRY`.
  2. Chuyển đổi Viewport sang chế độ xem "Lưới hình học" (Geometry Mesh).
- **Kết quả thực tế (Evidence):** Thuật toán `splat-transform` đã tự động sinh ra lưới khối Voxel an toàn (thuật toán đã chặn crash bộ nhớ với Node Cap 1.5 Tỷ). Lưới này cung cấp mặt phẳng vật lý vững chắc để export sang định dạng collider chuẩn cho NVIDIA Isaac Sim.

### Test Case 4: Tách vật thể khỏi cảnh nền (Giải quyết Pain Point: Môi trường đóng băng, dính liền)
- **Pain point cũ:** Toàn bộ cảnh nhà kho là 1 khối lưới duy nhất, kỹ sư không thể nhấc một cái hộp hay dời một cái kệ đi chỗ khác để thử nghiệm kịch bản cho robot.
- **Các bước thực hiện:**
  1. Khởi chạy luồng Pipeline v2 có bật xử lý tách vật thể (`ST-OBJECT-EXTRACT`).
- **Kết quả thực tế (Evidence):** Worker chạy SAM2 kết hợp LaMa để bóc tách vật thể độc lập và vá nền phía sau. Output trả về là các `SceneObject` có transform (vị trí, xoay) riêng biệt, sẵn sàng cho việc xuất "USD lai" để chỉnh sửa động trong mô phỏng.

### Test Case 5: Tương tác kiểm thử ngay trên Web Viewer (Giải quyết Pain Point: Cấu hình phần mềm nặng)
- **Pain point cũ:** Để Review một cảnh 3D xem có lỗi không, kỹ sư (hoặc sếp) phải tải file nặng hàng GB về, cài Unreal/Unity hoặc Isaac Sim rất phức tạp.
- **Các bước thực hiện:**
  1. Mở URL của Scene trên trình duyệt Chrome/Edge thông thường.
  2. Dùng thanh công cụ Viewport mới được hợp nhất (PreviewScene) để chuyển đổi giữa 3 góc nhìn: "Visual 3DGS", "Lưới Hình Học", "Point Cloud".
- **Kết quả thực tế (Evidence):** App tải file `.sog` siêu nhẹ (đã nén), render mượt mà bằng WebGPU/WebGL2 qua thư viện PlayCanvas. Người Reviewer (Tech Lead) có thể dễ dàng xoay, kiểm tra điểm ảnh, xem lưới va chạm ngay trên trình duyệt mà không cần cài thêm bất kỳ phần mềm nào.

---

## 3. Tổng kết

Sản phẩm MVP hiện tại đã bám sát và chứng minh năng lực giải quyết thành công 5 pain point cốt lõi nhất của bài toán **Real2Sim**. Các luồng data flow hoạt động ổn định và sẵn sàng cho giai đoạn hoàn thiện giao tiếp với Isaac Sim.
