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

### Phân biệt hệ thống thật và adapter demo

Owner clarification tiếp theo 2026-09-26: **hệ thống vẫn có ba hướng riêng**:

| Hướng hệ thống | Nguồn metric thật | Adapter dùng thử dataset |
| --- | --- | --- |
| RGB-only + anchor | Người dùng nhập số đo thực tế cho A/B | LiDAR cung cấp số đo gợi ý cho A/B để trải nghiệm thao tác nhập/xác nhận |
| RGB + LiDAR | LiDAR đã registered, căn chỉnh cùng RGB | Dùng bộ RGB + LiDAR có sẵn |
| RGB + auto-estimate scale | Thuật toán suy scale từ RGB, phát triển sau | LiDAR tạm cung cấp scale **thay estimator trong demo**, không phải implementation estimator |

Ba chế độ bên dưới chỉ là adapter demo cho ba hướng này, không thay kiến trúc
hệ thống bằng ba pipeline phụ thuộc LiDAR. Upload RGB thông thường không được
tự chuyển sang LiDAR-assisted. Khi estimator thật chưa có, hướng auto-estimate
ngoài demo phải báo chưa khả dụng, không âm thầm lấy scale demo. Nhãn `ESTIMATED`
của estimator cũng không thay bước xác nhận metric trước downstream.

### 1. Giải pháp Testing Pipeline & Demo với Dataset `Aisle_CW` (Tận dụng LiDAR)

Owner clarification 2026-09-26: chuẩn bị **cả ba chế độ dùng thử** trên dataset
có sẵn, không chọn một shortcut thay cho hai chế độ còn lại:

| Chế độ demo | Trải nghiệm | Vai trò LiDAR |
| --- | --- | --- |
| RGB + LiDAR | Xem/fuse hai modality cùng scene | Geometry source và nguồn metric sau căn chỉnh |
| RGB demo auto-scale | Chọn dữ liệu RGB mẫu, không phải tự đo/nhập khoảng cách | Proxy tạm cho estimator qua measurement/alignment đã chuẩn bị |
| RGB + chọn hai điểm | Chọn A/B; hệ thống gợi ý khoảng cách để nhập/xác nhận | Đo hai vị trí tương ứng trên LiDAR đã căn chỉnh |

- “Ẩn LiDAR” là ẩn thao tác kỹ thuật/layer khỏi luồng dùng thử, **không** xóa
  nguồn LiDAR khỏi provenance hoặc gọi kết quả là RGB-only auto-estimation.
  Hai chế độ RGB hỗ trợ là demo LiDAR-assisted, không thay bằng chứng nghiệm thu
  RGB-only độc lập. AI auto-scale vẫn là backlog, chưa được thực thi bởi shortcut này.
- Chuẩn bị chung: REC-07 prefusion → REC-08 registered LiDAR → REC-09 đối chiếu
  same-scene RGB/metric evidence. REC-07/08 không chờ REC-06 DONE. RGB master từ
  REC-03/04 vẫn bất biến; metric transform phải có trước REC-05 voxel/capsule.
- Runtime chỉ nhận registered LiDAR/product-safe prepared evidence, không đọc
  raw scan sequence, `traj_gt.txt` hoặc evaluation map. Nếu offline prefusion dùng
  trajectory GT thì giữ nhãn GT-assisted và checksum dependency tới downstream.
- Chọn A/B phải có correspondence với đúng vị trí vật lý trên LiDAR. Không có
  mapping/đủ coverage thì báo không đo được hoặc yêu cầu chọn lại; không đo khoảng
  cách pixel, dùng điểm gần bất kỳ hoặc tự điền số giả. Measurement không tự cấp
  `CONFIRMED`; giữ review/confirmation gate và bind exact RGB/LiDAR/selection.
- Native unit mét không chứng minh phép đo không có sai số. Không dùng cùng
  measurement để vừa calibration vừa claim independent evaluation accuracy.
- **Quy chuẩn hạt giống đục rỗng voxel (`navigation_seed_world` của REC-05):**
  - Theo owner clarification 2026-09-26: camera đầu tiên **đã registered** là nguồn
    seed **đề xuất**, không nhất thiết là Frame 0. Chuyển camera center qua confirmed
    metric/world transform trước khi đề xuất; giữ source pose ref/checksum và frame ID.
  - Camera center không chứng minh capsule robot vừa trong không gian đó. Bắt buộc
    kiểm bounds và capsule clearance trên geometry/occupancy tương ứng; không tự
    suy camera-to-ground offset hoặc coi seed là walkable chỉ vì camera từng ở đó.
  - Nếu seed không hợp lệ, từ chối attempt hoặc yêu cầu chọn lại. Không bỏ validation,
    auto-pass hoặc coi upstream relocate/skip carve là chứng nhận seed ban đầu hợp lệ.
  - **Owner amendment 2026-09-27 — seed relocation có kiểm soát:** bổ sung lựa chọn
    thứ ba bên cạnh *từ chối* và *yêu cầu chọn lại*: **tự tìm seed hợp lệ trong
    không gian liên thông rồi ghi cả hai điểm vào evidence.** Điều kiện bắt buộc:
    1. Tìm kiếm phải **có kiểm tra liên thông (connectivity)** trên vùng không khí
       tự do, không được dùng quét vỏ cube/Chebyshev như `findNearestFreeCell` của
       upstream `splat-transform` 3.6.6. Ô trống bên kia bức tường không phải ứng viên.
    2. **Có giới hạn khoảng cách** tính bằng mét. Vượt ngưỡng thì từ chối, không nới.
    3. **Ghi rõ relocation** trong clearance evidence: `requested_seed_world`,
       `accepted_seed_world`, khoảng cách dịch chuyển, phương pháp tìm kiếm, và
       occupancy checksum đã dùng làm căn cứ. Không được ghi đè seed đã yêu cầu.
    4. `capsule_clearance_verified` trong `CameraSeedProposal` **vẫn là `False`**;
       việc xác thực thuộc adapter/occupancy, không thuộc proposal của camera.
    5. Consumer phải **tự kiểm lại** từ bytes occupancy đã publish, không được tin
       trường `status` do producer ghi.
    6. Lựa chọn này **không** thay thế `CLEAR/BLOCKED` của EX-SIM: capsule vừa và cùng
       vùng liên thông không chứng minh robot đi tới được. Nếu không tìm được ứng viên
       trong ngưỡng thì quay về hành vi từ chối như trước.
  - Việc chọn lại seed thủ công trên **3D viewport** vẫn thuộc `PRODUCT-06`
    (`EX-PRODUCT`) và chưa có đặc tả UX; relocation ở trên là đường không phụ thuộc
    EX-PRODUCT, không phải sự thay thế cho UX đó.

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
- Giữ luồng HITL khoảng cách đo ngoài đời cho upload RGB không có LiDAR; không
  giả định video bất kỳ đều có LiDAR đi kèm.
- Có đường triển khai dùng lại artifacts cho cả ba chế độ; performance, real
  correspondence, metric confirmation và collision vẫn phải có runtime evidence.

Tradeoffs:
- Với video tải lên tùy ý của người dùng ở bản P0, người dùng cần thao tác click 2 điểm trên 3D viewer thay vì hệ thống tự động hoàn toàn.

## Follow-Up

- Chuẩn bị registered LiDAR và correspondence dùng chung cho ba chế độ; nối
  EX-REC measurement/preview với EX-PRODUCT demo controls theo shared boundary.
- Tách metric preparation trước REC-05 khỏi final geometry-bound AlignmentRecord
  sau REC-05; không thêm scale vào shared rigid Transform hoặc sửa schema ngầm.
- Kết nối camera đầu registered làm seed đề xuất cho REC-05, với bounds/capsule
  clearance validation bắt buộc trước khi coi seed hợp lệ.
