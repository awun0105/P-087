# Evaluation Report (Báo cáo Đánh giá MVP)

**Thông tin phiên bản đánh giá:**
- **Ngày đánh giá:** 04/10/2026
- **Branch:** `develop` (chuẩn bị merge từ `feat/pipeline-v2`)
- **Commit Hash:** `577ae32a3ad35dbc341c36c8499f1588d449d75c`

> Báo cáo đánh giá chất lượng sản phẩm dựa trên các Metric và Benchmark được định nghĩa trong `eval/protocols/BENCHMARKS.md`. Tài liệu này bổ sung diễn giải chi tiết về ý nghĩa các độ đo, kết quả hiện tại cũng như hướng cải thiện cho hệ thống Real2Sim Studio.

---

## 1. Metrics Tổng quan và Giải thích Chi tiết

Dưới đây là các độ đo (metrics) được sử dụng để đánh giá chất lượng của hệ thống, bao gồm ý nghĩa, đơn vị, dải giá trị, ngưỡng đạt (baseline) và phân tích kết quả hiện tại.

### 1.1 Chất lượng Hình ảnh 3D (`recon_visual_quality`)
* **Metric sử dụng:** PSNR, SSIM, LPIPS.
  * **PSNR (Peak Signal-to-Noise Ratio):** Đo tỷ số tín hiệu cực đại trên nhiễu, đánh giá độ lệch mức pixel. Đơn vị: dB. Khoảng giá trị: `[0, ∞)` (Càng cao càng tốt).
  * **SSIM (Structural Similarity Index):** Đánh giá độ tương đồng về cấu trúc và cảm nhận độ sáng/tương phản. Đơn vị: Không có. Khoảng giá trị: `[0, 1]` (Càng gần 1 càng tốt).
  * **LPIPS (Learned Perceptual Image Patch Similarity):** Đánh giá độ lệch dựa trên mạng neural (VGG/AlexNet), mô phỏng cảm nhận của mắt người. Đơn vị: Không có. Khoảng giá trị: `[0, 1]` (Càng nhỏ càng tốt).
* **Lý do sử dụng:** Nhằm đảm bảo Scene 3D tạo ra có độ chân thực cao, gần nhất với không gian thật để cung cấp bối cảnh thị giác chuẩn cho quá trình mô phỏng.
* **Ngưỡng đạt:** PSNR > 20 dB, SSIM > 0.8, LPIPS < 0.3.
* **Kết quả hiện tại:** PSNR ~28.61, SSIM ~0.896, LPIPS ~0.264.
* **Đánh giá & Suy luận:**
  * **Tình trạng:** **✅ Đạt xuất sắc**. Chất lượng hiển thị rất tốt.
  * **Điểm mạnh:** Hình ảnh rõ nét, giữ được cấu trúc môi trường nguyên bản, rất phù hợp cho việc hiển thị và nhận diện trong mô phỏng (Computer Vision / RL).
  * **Điểm yếu:** LPIPS ở mức 0.264 cho thấy ở một số góc khuất hoặc bề mặt thiếu vân (texture-less) vẫn có thể bị mờ (blur).
  * **Hướng cải thiện:** Tăng số lượng iteration (vòng lặp huấn luyện) của Gaussian Splatting hoặc sử dụng các biến thể mạnh hơn như Mip-Splatting để chống răng cưa (aliasing) và giảm mờ ở khoảng cách xa.

### 1.2 Sai số Tỉ lệ Kích thước Đề xuất (`metric_scale`)
* **Metric sử dụng:** Tỉ lệ phần trăm sai lệch (`proposal_error_percent`) giữa kích thước ước lượng và kích thước đo đạc thực (LiDAR/GT).
* **Lý do sử dụng:** Hệ thống Real2Sim bắt buộc phải xuất ra tỉ lệ mét chính xác 1:1. Nếu tỉ lệ sai, robot trong trình giả lập (Isaac Sim) sẽ bị khổng lồ hoặc tí hon so với môi trường.
* **Đơn vị & Khoảng:** `%` (Phần trăm sai lệch). Khoảng: `[0, 100%]`. Càng gần 0 càng tốt.
* **Ngưỡng đạt:** < 5%.
* **Kết quả hiện tại:** Sai lệch khoảng `0.106% - 0.238%`.
* **Đánh giá & Suy luận:**
  * **Tình trạng:** **✅ Tốt**.
  * **Điểm mạnh:** Thuật toán MoGe-2 ước lượng tỉ lệ tuyệt đối (Absolute Scale) cực kỳ chuẩn xác với sai số dưới 1%, giúp người dùng không cần tinh chỉnh tay.
  * **Điểm yếu:** Phụ thuộc vào chất lượng của Depth Map trích xuất; nếu quay video bị nhòe (motion blur) mạnh, suy đoán kích thước có thể thiếu chính xác hơn.
  * **Hướng cải thiện:** Bổ sung cơ chế tinh chỉnh thủ công (Manual scaling) trong UI phòng trường hợp thuật toán tự động nhận diện sai trên các cảnh có cấu trúc đặc thù.

### 1.3 Độ thông thoáng của Quỹ đạo (Lưới Va chạm) (`collision_path_clearance`)
* **Metric sử dụng:** Tỉ lệ chặn giả (False Positive Collision Rate) - Tỉ lệ phần trăm các vị trí mà camera thực tế đã đi qua nhưng bị lưới va chạm (Mesh) cản lại.
* **Lý do sử dụng:** Đánh giá tính ứng dụng của file Mesh được tạo ra. Nếu lưới mesh sinh ra "nhiễu" bay lơ lửng hoặc sát sàn quá nhiều, robot mô phỏng sẽ liên tục va chạm vào không khí và bị kẹt.
* **Đơn vị & Khoảng:** `%` số điểm bị chặn / tổng số điểm. Khoảng: `[0, 100%]`. Càng gần 0 càng tốt.
* **Ngưỡng đạt:** < 10% (Lý tưởng là 0%).
* **Kết quả hiện tại:** Lưới 0.05m có tỉ lệ chặn lên tới 66% (33/50 vị trí).
* **Đánh giá & Suy luận:**
  * **Tình trạng:** **⚠️ Cần cải thiện**. Mesh bao bọc tốt nhưng nhiễu quá nhiều.
  * **Điểm mạnh:** Giữ được hình dáng chi tiết của các vật thể rắn để tính toán vật lý tốt.
  * **Điểm yếu:** Sinh ra nhiều đa giác nhiễu lơ lửng sát mặt đất (floaters). Điều này khiến không gian đường đi bị đánh dấu là "có vật cản", ảnh hưởng nghiêm trọng tới thuật toán tìm đường (Navigation) của robot.
  * **Hướng cải thiện:** Thêm bước tiền xử lý lọc nhiễu tĩnh (Outlier Removal / Radius Outlier Filter) trên Point Cloud trước khi chạy TSDF (Truncated Signed Distance Field). Phát triển tính năng cắt bỏ phần sàn nhiễu tự động để giữ cho không gian di chuyển hoàn toàn phẳng và trống.

### 1.4 Thời gian Thực thi Hệ thống (`pipeline_runtime`)
* **Metric sử dụng:** Thời gian chạy thực tế của toàn bộ pipeline ngầm.
* **Lý do sử dụng:** Đánh giá năng lực đáp ứng và hiệu suất (Throughput) của hệ thống trước khi scale up cho người dùng thật.
* **Đơn vị & Khoảng:** Giây (s). Khoảng: `[0, ∞)`.
* **Ngưỡng đạt:** < 3600s (1 tiếng) cho đoạn video trung bình (~300-500 frames).
* **Kết quả hiện tại:** `2200s - 2800s` (~40 - 45 phút) cho 1 job.
* **Đánh giá & Suy luận:**
  * **Tình trạng:** **✅ Đạt**. 
  * **Điểm mạnh:** Tốc độ ổn định, không bị crash Out-Of-Memory, tận dụng tốt tài nguyên GPU hạn chế (Quadro T2000).
  * **Điểm yếu:** Vẫn tương đối lâu đối với trải nghiệm chờ đợi của người dùng UI trực tiếp.
  * **Hướng cải thiện:** Triển khai cơ chế Multi-GPU / Cluster Worker để chạy song song. Có thể cung cấp tính năng "Preview Mode" (chỉ chạy 7000 iterations) trong vòng 5-10 phút để người dùng xem trước, sau đó mới huấn luyện tiếp High-Quality Mode.

### 1.5 Độ chính xác Vị trí Không gian (`recon_pose`)
* **Metric sử dụng:** ATE (Absolute Trajectory Error) và RPE (Relative Pose Error) - tính bằng độ lệch căn quân phương (RMSE).
* **Lý do sử dụng:** Đo lường xem quỹ đạo di chuyển của camera ảo có trùng khớp hoàn toàn với thiết bị quay ngoài đời thực không. Việc định vị sai góc sẽ dẫn đến bối cảnh tổng thể bị xiên vẹo.
* **Đơn vị & Khoảng:** Mét (m). Khoảng: `[0, ∞)`. Càng gần 0 càng tốt.
* **Ngưỡng đạt:** RMSE < 0.1m.
* **Kết quả hiện tại:** RMSE ~`0.068m` (6.8 cm).
* **Đánh giá & Suy luận:**
  * **Tình trạng:** **✅ Tốt**.
  * **Điểm mạnh:** Sai số dưới 7cm là cực kỳ xuất sắc đối với việc dùng Monocular Video (Video 1 camera thường, không chiều sâu) trong không gian kho bãi.
  * **Điểm yếu:** Với các bài toán Manipulation gắp vật nhỏ đòi hỏi chính xác từng milimet, sai số 7cm có thể gây trượt tay kẹp.
  * **Hướng cải thiện:** Kế hoạch nâng cấp hỗ trợ Input từ video định dạng RGB-D (có sẵn chiều sâu như iPhone LiDAR/RealSense) để kết hợp vào quá trình Bundle Adjustment, đưa mức sai lệch về giới hạn dưới 1cm.

---

## 2. Eval Evidences — Tóm tắt Test Case
> Phần dưới đây tóm tắt các kịch bản kiểm thử đã chạy (Logs lưu tại thư mục `eval/results/`).

### Test Case 1: Đánh giá Chất lượng (`recon_visual_quality`)
- **Evidences:** Log `aisle-cw-local-t2000.jsonl` (PSNR: 28.61, SSIM: 0.896). Hệ thống đã tự tách holdout 1/8 số ảnh để làm Test-set độc lập.

### Test Case 2: Đánh giá Sai số Tỉ lệ (`metric_scale`)
- **Evidences:** Dataset TorWIC-SLAM (có Ground Truth) cho thấy độ lệch chỉ `0.106%`. Thuật toán căn tỷ lệ tự động hoàn thành xuất sắc.

### Test Case 3: Đánh giá Lưới Va chạm (`collision_path_clearance`)
- **Evidences:** Mesh mức 0.05m (224,745 tam giác) chặn 33/50 vị trí (66%). Phản ánh rõ ràng khuyết điểm nhiễu (noise) lơ lửng của 3DGS khi chuyển sang lưới rắn. Cần ưu tiên khắc phục trong pha tới.

### Test Case 4: Đánh giá Thời gian & Độ ổn định (`pipeline_runtime`)
- **Evidences:** Stress-test với video `seg-3fps` / `seg-5fps` chạy liên tục. Kết thúc trong ~45 phút / luồng, memory GPU ổn định, không sụt giảm.

### Test Case 5: Tách vật thể khỏi cảnh nền (`ST-OBJECT-EXTRACT`)
- **Evidences:** Pipeline v2 với SAM2/LaMa tách thành công mảng `SceneObject`. Inpaint chạy tự động, cho kết quả vật thể độc lập sẵn sàng đẩy sang Isaac Sim.

---

## 3. Tổng kết

Nhìn chung, hệ thống **Real2Sim Studio MVP đã chạy thành công End-to-End**. Các thế mạnh nổi bật là việc ước lượng kích thước tuyệt đối (Scale) cực kỳ chính xác và hiển thị hình ảnh ở mức độ chi tiết cao. 

Tuy nhiên, nút thắt hiện tại cần tập trung giải quyết ở Sprint tiếp theo là **chất lượng Lưới va chạm (Collision Mesh)** (Metric: `collision_path_clearance`). Do nhiễu bám sàn, tỷ lệ cản trở đường đi còn cao, điều này ảnh hưởng trực tiếp đến việc giả lập di chuyển của Robot trong Isaac Sim. Cần bổ sung ngay thuật toán xử lý màng nhiễu (Floater removal/Ground clipping) để khắc phục điểm yếu chí mạng này, đưa sản phẩm đạt trạng thái Production-ready 100%.
