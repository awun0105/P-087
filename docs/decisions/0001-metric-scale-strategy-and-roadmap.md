# 0001 Chiến lược và Lộ trình Khôi phục Tỷ lệ Mét (Metric Scale Recovery) cho Real2Sim Studio

Date: 2026-09-26

## Status

Accepted

## Context

1. **Bản chất bài toán:** Tái tạo 3D từ chuỗi ảnh/video monocular RGB qua COLMAP Structure-from-Motion (SfM) và Brush 3D Gaussian Splatting (3DGS) chỉ xác định được hình học và quỹ đạo camera lên tới một tỷ lệ vô hướng tùy ý (*scale ambiguity*). Hệ thống không thể tự biết 1 đơn vị trong máy tính là 1m, 0.1m hay 10m nếu không có dữ liệu đối chiếu bên ngoài.
2. **Yêu cầu sản phẩm:** Theo `docs/PRD.md` (FR-06, AC-03) và `docs/execution/TEAM_EXECUTION_CONTRACT.md`, scene xuất khẩu sang Isaac Sim bắt buộc phải đạt chuẩn `Physics-ready` với tỷ lệ mét thật đã được xác nhận (`CONFIRMED`). Nếu chưa có metric scale, scene bị chặn không cho phép duyệt phát hành (`APPROVED`).
3. **Ràng buộc phần cứng và môi trường:** Môi trường máy trạm hiện tại không có GPU CUDA rời (`CUDA available: False`, chạy CPU Intel Core i7-9850H và Intel UHD 630 iGPU). Việc tích hợp các Foundation Model AI về độ sâu mét (như MoGe-2, Apple Depth Pro, MapAnything) vào worker pipeline của MVP P0 sẽ gây nghẽn hiệu năng CPU nghiêm trọng, tốn RAM và gây rủi ro tiến độ milestone.
4. **Phân định phạm vi Demo/Testing vs Sản phẩm thực tế:** Cần phân tách rõ giải pháp dùng tạm thời để kiểm thử pipeline với dataset `Aisle_CW` và giải pháp toàn diện khi người dùng tải lên video monocular RGB bất kỳ trong ứng dụng thực tế.

## Decision

Nhóm thống nhất chiến lược Metric Scale toàn diện như sau:

### 1. Giải pháp Testing Pipeline & Demo với Dataset `Aisle_CW` (Tận dụng LiDAR)

Để kiểm thử thông suốt pipeline tái tạo và mô phỏng mà không cần con người phải phỏng đoán hay tự bịa số mét:

- **Sử dụng 3D LiDAR (Ouster OS1-128) có sẵn của `Aisle_CW`:**
  - File quét LiDAR trong `data/torwic_slam/raw/traversals/aisle_cw/lidar/` đã mang sẵn đơn vị mét vật lý chuẩn xác ($1.0 = 1\text{m}$).
  - *Cách 1 (Nhanh cho REC-06 & REC-05):* Trích xuất khoảng cách laser thực tế giữa 2 cột kệ kho từ đám mây điểm LiDAR làm `DistanceAnchor` cho REC-06 để giải hệ số co giãn $s$.
  - *Cách 2 (Multimodal chuẩn):* Triển khai tiếp `REC-07` (Prefusion gộp 1.092 file `.pcd` bằng Open3D) $\rightarrow$ `REC-08` (`LiDARGeometryArtifact`) $\rightarrow$ `REC-09` (Alignment khớp RGB với LiDAR).
- **Quy chuẩn hạt giống đục rỗng voxel (`navigation_seed_world` của REC-05):**
  - Theo owner clarification 2026-09-26: camera đầu tiên **đã registered** là nguồn
    seed **đề xuất**, không nhất thiết là Frame 0. Chuyển camera center qua confirmed
    metric/world transform trước khi đề xuất; giữ source pose ref/checksum và frame ID.
  - Camera center không chứng minh capsule robot vừa trong không gian đó. Bắt buộc
    kiểm bounds và capsule clearance trên geometry/occupancy tương ứng; không tự
    suy camera-to-ground offset hoặc coi seed là walkable chỉ vì camera từng ở đó.
  - Nếu seed không hợp lệ, từ chối attempt hoặc yêu cầu chọn lại. Không bỏ validation,
    auto-pass hoặc coi upstream relocate/skip carve là chứng nhận seed ban đầu hợp lệ.

### 2. Giải pháp Sản phẩm Thực tế (Khi người dùng tải lên Video Monocular RGB bất kỳ)

Khi ứng dụng chính thức vận hành và người dùng gửi video thực tế của họ (không có cảm biến LiDAR đi kèm), hệ thống **bắt buộc hỗ trợ đầy đủ các phương án xử lý**:

- **Phương án Cốt lõi P0 (Human-In-The-Loop Known Distance Anchor):**
  - Người dùng quan sát mô hình 3D hoàn chỉnh trên **3D Viewport của Web Studio (Screen 2: Scene Editor)** ngay sau khi hoàn thành Visual 3DGS (REC-04) và trước khi tạo lưới va chạm Voxel (REC-05).
  - Thao tác: Dùng chuột click chọn trực tiếp 2 điểm trong không gian 3D trên mô hình (cơ chế raycast bắt điểm bề mặt 3 chiều lấy $A(x_1, y_1, z_1)$ và $B(x_2, y_2, z_2)$, không chọn trên ảnh 2D phẳng) và nhập khoảng cách thực tế (ví dụ: `2.40 m`).
  - Backend REC-06 (`DistanceAnchor`, `SimilarityTransform`, `MetricCanonicalizer`) giải hệ số co giãn toàn cục $s$ và xuất bản `MetricConfirmation` trạng thái `CONFIRMED`.
- **Lộ trình Mở rộng P1 (AI Auto-Scale Assist):**
  - Tích hợp bộ ba chức năng khi hệ thống có hạ tầng GPU CUDA:
    1. *MoGe2Backend (hoặc Tiny Model như DepthART):* Dự đoán bản đồ độ sâu mét $z_{\text{metric}}$.
    2. *ColmapSparseDepthProjector (học từ DN-Splatter):* Chiếu điểm 3D sparse của COLMAP lên ảnh 2D để bắt cặp $(z_{\text{colmap}}, z_{\text{metric}})$.
    3. *RobustScaleAligner (học từ MonoSplat):* Giải toán co giãn thuần túy (*scale-only* $z_{\text{metric}} \approx s \cdot z_{\text{colmap}}$ qua median/least-squares), triệt tiêu hoàn toàn hệ số dịch chuyển $b$ ($b=0$) để bảo toàn tâm quang học và cấu trúc 3D.
  - Kết quả mang nhãn `ESTIMATED`, tự động điền gợi ý kích thước trên Web Studio để người dùng chỉ cần duyệt (`[Accept]`) hoặc hiệu chỉnh.

## Alternatives Considered

1. **Phương án Chiều cao Camera Robot OTTO 100:** Bị loại bỏ vì khảo sát thực tế file `calibrations.txt` cho thấy dataset chỉ cung cấp extrinsics `T_cam1_os`, hoàn toàn không có thông số chiều cao từ camera xuống mặt đất. Loại bỏ để tuân thủ quy tắc không tự bịa số liệu.
2. **Phương án ArUco / AprilTag Marker:** Bị loại bỏ vì không phù hợp với luồng quay video kho bãi tự nhiên và dataset `Aisle_CW` không có marker.
3. **Dùng thuật toán Affine Shift ($s \cdot z + b$) của DN-Splatter:** Bị từ chối vì hệ số dịch $b$ phá vỡ tính nhất quán của phép biến đổi đồng dạng toàn cục $p' = s R p + t$.

## Consequences

Positive:
- Phân định rõ ràng: LiDAR giải quyết nhanh chóng bài toán testing pipeline/demo cho `Aisle_CW` mà không cần đoán số liệu.
- Sản phẩm thực tế có thiết kế hoàn chỉnh: Luồng HITL 2 điểm trên 3DGS đảm bảo xử lý được mọi video monocular RGB của người dùng.
- Pipeline P0 chạy hoàn toàn mượt mà trên CPU/iGPU hiện có, không phụ thuộc GPU rời đắt đỏ.
- Tháo gỡ hoàn toàn điểm nghẽn cho REC-05/06, mở đường cho REC-05 chạy 3 mức phân giải Voxel Collision.

Tradeoffs:
- Với video tải lên tùy ý của người dùng ở bản P0, người dùng cần thao tác click 2 điểm trên 3D viewer thay vì hệ thống tự động hoàn toàn.

## Follow-Up

- Bổ sung kịch bản trích xuất anchor từ LiDAR cho testing `Aisle_CW` tại REC-06.
- Kết nối camera đầu registered làm seed đề xuất cho REC-05, với bounds/capsule
  clearance validation bắt buộc trước khi coi seed hợp lệ.
