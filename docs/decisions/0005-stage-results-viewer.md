# 0005 Xem kết quả từng bước của pipeline trên Web Studio

Date: 2026-09-29

## Status

Accepted — Tech Lead / Integration Owner (Quân) chốt ngày 2026-09-29. Phần hiển thị
physics chỉ quy định cách Web **hiển thị** kết quả; cách chạy và báo cáo physics vẫn
thuộc EX-SIM (Đạt), cần thông báo.

## Context

- Màn hình scene của Studio (`ScenePage` → `SceneWorkspace`) chỉ hiện 3DGS.
- Viewer cũ `/jobs/[jobId]/viewer` (`ViewerPanel`) đã có 4 chế độ: 3DGS, Geometry
  mesh, Point cloud, Collider, nhưng chỉ cho scene cuối và chưa nằm trong Studio.
- Mỗi bước pipeline đã publish artifact bất biến (URI + checksum) vào JobManifest,
  nên hiển thị từng bước không cần dựng lại gì.
- ADR 0003 §2 (ngân sách trình duyệt): trình duyệt không nạp bản gốc nặng, chỉ nạp
  bản vừa sức; không làm pixel streaming.

## Decision

1. **Chọn bước trên timeline → khung 3D hiện kết quả của bước đó.** Chỉ bước đã
   có artifact thành công mới chọn được; bước chưa có thì ghi rõ "chưa có kết quả".

   | Bước | Hiển thị |
   | --- | --- |
   | Chuẩn bị frame | Lưới ảnh frame đã chọn |
   | COLMAP | Point cloud thưa + hình chóp camera |
   | Brush | 3DGS |
   | REC-06 tỉ lệ mét | 3DGS canonical + lưới mét, trục, mặt sàn z=0 |
   | REC-05 hình học | Collision mesh, voxel chiếm chỗ, seed + capsule robot |
   | LiDAR (REC-08) | Point cloud LiDAR |
   | REC-09 căn chỉnh | LiDAR chồng lên 3DGS |
   | Scene cuối | 3DGS + mesh + collider, chế độ đi bộ có va chạm |

2. **Physics không chạy trong trình duyệt.** Physics thật chạy trong Isaac Sim
   (EX-SIM) trên máy GPU. Web chỉ hiện collider và đi bộ có va chạm của viewer;
   kết quả mô phỏng hiện dưới dạng báo cáo (`ValidationReport`) và video/ảnh do
   EX-SIM xuất ra.

3. **Ngân sách trình duyệt (ADR 0003 §2) áp cho mọi bước:**
   - mỗi lúc chỉ nạp **một lớp**, nạp khi người dùng chọn bước; đổi bước thì giải
     phóng lớp cũ (GPU memory, listener);
   - file định dạng nội bộ nặng hoặc trình duyệt không đọc được (voxel binary,
     COLMAP `.bin`, point cloud lớn) được **server chuyển sang bản xem** (GLB cho
     mesh/voxel, PLY/point cloud đã giảm mẫu cho point cloud) và publish như artifact
     dẫn xuất có checksum. Trình duyệt không tự đọc file gốc nặng;
   - bản xem là artifact **chỉ để hiển thị**, không thay artifact gốc trong bundle.

4. Danh sách "bước nào có gì để xem" do backend trả (từ JobManifest), UI không tự
   suy đường dẫn.

## Alternatives Considered

1. Chỉ xem 3DGS và scene cuối: đơn giản hơn nhưng không cho thấy quá trình xử lý,
   trái mục tiêu demo so sánh ba hướng (ADR 0004 §5).
2. Pixel streaming từ server: không lag trên máy yếu nhưng tốn GPU theo số người
   xem; ADR 0003 đã loại.

## Consequences

Positive:

- Người xem thấy từng bước biến đổi dữ liệu; dễ chẩn đoán bước nào làm hỏng scene.
- Tái dùng artifact đã có và viewer PlayCanvas/three.js sẵn có.

Tradeoffs:

- Thêm bước server tạo bản xem (GLB/point cloud giảm mẫu) cho các bước có file nặng.
- Bước REC-05 trở đi chỉ hiện được khi worker đã chạy các bước đó (kế hoạch tổng thể,
  gói 3).
