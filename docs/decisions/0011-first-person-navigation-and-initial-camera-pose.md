# 0011 Điều hướng First-Person và Camera ban đầu cho Viewer 3DGS toàn hệ thống

Date: 2026-10-06

## Status

Proposed — Đang trình duyệt kế hoạch kiến trúc cho hai cải tiến:
1. Tự động đặt Camera ban đầu vào bên trong không gian (Initial Camera Pose).
2. Tự động chuyển và thống nhất chế độ điều khiển First-Person (Fly / Walk) trên toàn hệ thống.

## Context

- Khi mở scene 3DGS (đặc biệt là video mẫu trong `PreviewScene` hoặc các bước trong `StageViewer`), người dùng hiện bị văng ra ngoài không gian đen hư không (chế độ `orbit` nhìn từ khoảng cách xa bên ngoài Bounding Box).
- Lý do:
  1. Thư viện PlayCanvas `supersplat-viewer` mặc định khởi tạo `state.cameraMode = "orbit"`.
  2. Khi thiếu `initialCamera`, viewer tự động tính Bounding Box toàn cảnh và lùi camera ra ngoài xa gấp nhiều lần đường chéo của scene (vướng cả điểm rác floaters).
  3. Hiện tại chỉ có `StageViewer` và `MetricSceneView` trích xuất `recordingCameraPose` từ `cameras` của COLMAP, còn `PreviewScene` (dùng cho video mẫu, import scene, preview thô) chưa nhận thông tin camera này.
  4. Hợp đồng dữ liệu `DemoManifest` (video mẫu xử lý sẵn) chưa đóng gói danh sách camera từ job gốc, khiến frontend khi xem video mẫu không có quỹ đạo camera thật.
  5. Các viewer (`PreviewScene`, `StageViewer`, `MetricSceneView`) chưa có giao diện thống nhất để người dùng thấy và chuyển đổi giữa 3 chế độ camera: Xoay (Orbit), Bay (Fly), Đi bộ (Walk).
- Yêu cầu kỹ thuật:
  - Giải pháp phải áp dụng **chung trong pipeline xử lý và toàn hệ thống**, không hardcode cho một màn hình hay một video mẫu cụ thể.
  - Chia nhỏ thành các nhóm commit độc lập (contracts, core viewer logic, UI components, tests).

## Decision

1. **Chuẩn hoá Hợp đồng Dữ liệu Camera (Contract & Pipeline):**
   - Bổ sung trường tuỳ chọn `cameras: list[CameraMarker]` vào schema `DemoManifest` trong `src/services/orchestration/samples/models.py` và frontend `contracts/studio.ts`.
   - Cập nhật script `scripts/demo/export_demo_bundle.py` để khi export job thành demo bundle sẽ tự động đọc `camera_poses.json` (từ `rec03` hoặc `rec06`) và lưu vào manifest.
   - Bổ sung camera poses cho các bundle mẫu hiện có trong `data/demo/library/` (TorWIC scene 01, Aisle CW).

2. **Cơ chế Tính toán Vị trí Camera Ban đầu Toàn diện (Generic Initial Camera Resolution):**
   - Nâng cấp hàm `recordingCameraPose(frame, cameras)` trong `frontend/src/features/viewer/source-frame.ts`.
   - Bổ sung hàm fallback hình học `interiorFallbackPose(frame, bbox)`: Với scene độc lập không có COLMAP camera (như file `.ply`/`.sog` người dùng tự tải lên), hệ thống tự động xác định điểm đứng ở tâm ngang của scene, độ cao tầm mắt (1.5m), hướng nhìn theo trục chính thay vì lùi ra ngoài hư không.

3. **Cơ chế Khởi tạo Camera Controller trong Core Viewer (`PlayCanvasScene`):**
   - Thêm thuộc tính `initialCameraMode?: CameraMode` vào `PlayCanvasSceneProps` (mặc định là `"fly"` khi có vị trí camera ban đầu hoặc khi xem môi trường trong nhà).
   - Khi viewer nạp xong (`loaded:changed`), tự động kích hoạt `initialCameraMode`. Nếu chọn `"walk"` nhưng scene chưa có lưới va chạm (`!walkAllowed`), tự động fallback an toàn sang `"fly"`.

4. **Thống nhất Giao diện Điều khiển Camera trên Toàn bộ Viewport:**
   - Đưa cụm nút chuyển chế độ Camera (Orbit, Fly, Walk) vào thanh công cụ `extraControls` dùng chung:
     - `PreviewScene` (video mẫu, import file).
     - `StageViewer` (xem từng bước pipeline).
     - `MetricSceneView` (xem scene hệ mét).
   - Hiển thị gợi ý phím tắt điều khiển (WASD, chuột, Shift, Space) tương ứng với từng chế độ đang chọn.

## Alternatives Considered

1. **Hardcode toạ độ camera riêng cho từng video mẫu trong frontend:**
   - Nhược điểm: Phá vỡ tính toàn vẹn kiến trúc; khi người dùng tải video mới hoặc xuất job mới sẽ lại bị lỗi văng ra ngoài không gian đen. Đã bị loại bỏ.
2. **Luôn ép chế độ Walk (Đi bộ):**
   - Nhược điểm: Walk yêu cầu phải có collision mesh và scene đã định dạng hệ mét (sau bước REC-05/REC-06). Với các bước đầu (preview SfM, 3DGS thô), chưa có collision mesh nên Walk sẽ bị khoá. Chế độ `fly` là lựa chọn tối ưu cho toàn bộ giai đoạn xem trước.

## Consequences

Positive:

- Mọi scene mở ra đều đặt người dùng ở ngay bên trong không gian, tầm nhìn tự nhiên của camera thực tế.
- Trải nghiệm di chuyển mượt mà (WASD + chuột nhìn quanh) đồng nhất ở cả video mẫu, kết quả từng bước và scene cuối.
- Dễ dàng mở rộng cho bất kỳ định dạng scene hoặc quy trình xử lý mới nào trong tương lai.

Tradeoffs:

- Bundle mẫu cần chứa thêm mảng toạ độ camera trong `manifest.json` (tăng ~10–20 KB dung lượng file manifest dạng text).

## Plan & Commit Groups

- **Nhóm 1 (Backend & Contracts):** Bổ sung `cameras` vào `DemoManifest`, script `export_demo_bundle.py`, và cập nhật manifest của demo library.
- **Nhóm 2 (Core Viewer & Math):** Nâng cấp `source-frame.ts` (fallback nội thất) và `PlayCanvasScene.tsx` (hỗ trợ `initialCameraMode` + tự động kích hoạt).
- **Nhóm 3 (Unified UI & Components):** Tích hợp điều khiển camera Orbit/Fly/Walk và truyền `initialCamera` vào `PreviewScene`, `StageViewer`, `SceneWorkspace`, `SampleScene`.
- **Nhóm 4 (Tests & Verification):** Bổ sung unit tests cho backend models, `source-frame`, UI components và chạy kiểm thử toàn diện.
