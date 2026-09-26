# 0001 Chiến lược và Lộ trình Khôi phục Tỷ lệ Mét (Metric Scale Recovery) cho Real2Sim Studio

Date: 2026-09-26

## Status

Accepted

## Context

1. **Bản chất bài toán:** Tái tạo 3D từ chuỗi ảnh/video monocular RGB qua COLMAP Structure-from-Motion (SfM) và Brush 3D Gaussian Splatting (3DGS) chỉ xác định được hình học và quỹ đạo camera lên tới một tỷ lệ vô hướng tùy ý (*scale ambiguity*). Hệ thống không thể tự biết 1 đơn vị trong máy tính là 1m, 0.1m hay 10m nếu không có dữ liệu đối chiếu bên ngoài.
2. **Yêu cầu sản phẩm:** Theo `docs/PRD.md` (FR-06, AC-03) và `docs/execution/TEAM_EXECUTION_CONTRACT.md`, scene xuất khẩu sang Isaac Sim bắt buộc phải đạt chuẩn `Physics-ready` với tỷ lệ mét thật đã được xác nhận (`CONFIRMED`). Nếu chưa có metric scale, scene bị chặn không cho phép duyệt phát hành (`APPROVED`).
3. **Ràng buộc phần cứng và môi trường:** Môi trường máy trạm hiện tại không có GPU CUDA rời (`CUDA available: False`, chạy CPU Intel Core i7-9850H và Intel UHD 630 iGPU). Việc tích hợp các Foundation Model AI về độ sâu mét (như MoGe-2, Apple Depth Pro, MapAnything) vào worker pipeline của MVP P0 sẽ gây nghẽn hiệu năng CPU nghiêm trọng, tốn RAM và gây rủi ro tiến độ milestone.

## Decision

Nhóm thống nhất phân tách giải pháp Metric Scale thành 2 tầng rõ rệt:

### 1. Phạm vi MVP P0 (Thực thi ngay, không phụ thuộc AI nặng, đảm bảo chuẩn Physics-ready)

Tận dụng tối đa bộ dữ liệu `Aisle_CW` (TorWIC-SLAM) và hạ tầng code hiện có để đóng gói demo:

- **Nhánh Đa phương thức (Multimodal RGB + LiDAR):**
  - Dataset `Aisle_CW` có sẵn 3D LiDAR (Ouster OS1-128) mang đơn vị mét native.
  - Phối hợp: Sau khi hoàn thành RGB reconstruction (REC-03/04), kết hợp với `LiDARGeometryArtifact` (REC-07/08) qua quy trình Alignment (REC-09) để có scene chuẩn xác cho demo.
- **Nhánh Monocular RGB (Khi chỉ có video RGB):**
  - **Phương án A (Trọng tâm sản phẩm — Human-In-The-Loop Known Distance Anchor):**
    - Người dùng quan sát mô hình 3D hoàn chỉnh trên **3D Viewport của Web Studio (Screen 2: Scene Editor)** ngay sau khi hoàn thành Visual 3DGS (REC-04) và trước khi tạo lưới va chạm Voxel (REC-05).
    - Thao tác: Dùng chuột click chọn trực tiếp 2 điểm trong không gian 3D trên mô hình (ví dụ 2 chân kệ kho, 2 góc pallet) và gõ khoảng cách thực tế (ví dụ: `2.40 m`).
    - Backend REC-06 (`DistanceAnchor`, `SimilarityTransform`, `MetricCanonicalizer`) giải hệ số co giãn toàn cục $s$ và xuất bản `MetricConfirmation` trạng thái `CONFIRMED`.
  - **Phương án B (Tự động hình học nhẹ không dùng AI — Camera Height + Ground Plane RANSAC):**
    - Tận dụng đặc thù dataset `Aisle_CW` được quay từ camera gắn cố định trên robot tự hành **OTTO 100**.
    - Sử dụng thuật toán RANSAC fit mặt phẳng sàn từ đám mây điểm thưa COLMAP (chạy vài mili-giây trên CPU), đo khoảng cách camera đến sàn ($d_{\text{colmap}}$) và chia cho chiều cao camera vật lý đã biết ($h_{\text{camera}}$) để giải tỷ lệ mét tự động.

### 2. Phạm vi P1 / Backlog Mở rộng (AI Auto-Scale Assist)

Lưu vết kiến trúc cho giai đoạn sau khi hệ thống có hạ tầng GPU CUDA để hỗ trợ tính năng tự động gợi ý thước đo cho người dùng:

- **Bộ ba chức năng AI Metric Alignment:**
  1. *MoGe2Backend (hoặc Tiny Model như DepthART):* Nhận ảnh RGB dự đoán bản đồ độ sâu mét $z_{\text{metric}}$.
  2. *ColmapSparseDepthProjector (học từ DN-Splatter):* Chiếu điểm 3D sparse của COLMAP lên ảnh 2D để bắt cặp điểm tương ứng $(z_{\text{colmap}}, z_{\text{metric}})$.
  3. *RobustScaleAligner (học từ MonoSplat):* Giải toán co giãn thuần túy (*scale-only* $z_{\text{metric}} \approx s \cdot z_{\text{colmap}}$ qua median/least-squares), triệt tiêu hoàn toàn hệ số dịch chuyển $b$ ($b=0$) để bảo toàn tâm quang học và cấu trúc hình học 3D.
- **Quy tắc phân định trạng thái:** Kết quả từ mô hình AI chỉ được mang nhãn `ESTIMATED`, phục vụ xem trước (preview) hoặc gợi ý sẵn cho người dùng trên Web Studio, người dùng vẫn bấm xác nhận để chuyển thành `CONFIRMED` trước khi sang mô phỏng vật lý.

## Alternatives Considered

1. **Tích hợp ngay MoGe-2 / Depth Pro vào MVP P0:** Bị từ chối vì thiếu GPU CUDA, suy luận CPU quá chậm, kéo theo nhiều dependency nặng và làm trễ hạn bàn giao lưới va chạm REC-05 sang team Simulation.
2. **Dùng phương pháp ArUco / AprilTag Marker:** Bị từ chối vì không phù hợp với luồng thu thập dữ liệu tự nhiên của kho hàng và không có marker trong dataset `Aisle_CW`.
3. **Dùng thuật toán Affine Shift ($s \cdot z + b$) của DN-Splatter:** Bị từ chối vì hệ số dịch $b$ phá vỡ tính nhất quán của phép biến đổi đồng dạng toàn cục $p' = s R p + t$.

## Consequences

Positive:
- Pipeline P0 chạy hoàn toàn mượt mà trên CPU/iGPU hiện có, không phụ thuộc tài nguyên máy chủ đắt đỏ.
- Tháo gỡ nút thắt dữ liệu thật cho `Aisle_CW` tại REC-06, mở đường cho REC-05 chạy 3 mức phân giải Voxel Collision ngay lập tức.
- Giữ vững hợp đồng chất lượng và an toàn vật lý của PRD (không tự ý gán scale giả định, provenance truy vết đầy đủ, chống double-scaling).
- Có tài liệu thiết kế sẵn sàng cho việc nâng cấp AI ở P1.

Tradeoffs:
- Ở P0, với video tải lên tùy ý ngoài `Aisle_CW`, người dùng cần thao tác click 2 điểm trên 3D viewer thay vì hệ thống tự động hoàn toàn.

## Follow-Up

- Bổ sung mốc khoảng cách thực tế $2.40\text{ m}$ của `Aisle_CW` vào kịch bản nghiệm thu thật của REC-06.
- Cập nhật hướng dẫn giao diện chọn 2 điểm trên 3D Viewport vào `docs/WIREFRAME_AND_UI_FLOW.md`.
