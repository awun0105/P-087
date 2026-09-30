# 0004 Nhận diện loại đầu vào và định tuyến luồng xử lý

Date: 2026-09-29

## Status

Accepted — Tech Lead / EX-REC owner (Quân) chốt ngày 2026-09-29:
"hỗ trợ tất cả các cách, đầu vào cần bước đọc file và kiểm tra file thuộc dạng nào
thì đi qua luồng xử lý của dạng đó". Phần 4 chốt cùng ngày: không nới shared contract.

## Context

- Studio hiện chỉ nhận video `.mp4/.mov` (`uploads/models.py:VIDEO_EXTENSIONS`),
  chạy prepare → COLMAP → Brush → preview → xác nhận tỉ lệ (REC-06).
- Owner muốn nhận thêm file 3DGS `.ply` có sẵn (từ Brush, Postshot, Nerfstudio…),
  có hoặc không kèm model COLMAP, và demo ba hướng tỉ lệ để so sánh.
- Các bước sau preview dùng camera pose + frame set đi kèm `BrushVisualArtifact`:
  REC-06 chọn chiều pháp tuyến sàn và kiểm độ cao camera; canonical poses; REC-05
  đọc visual qua `VisualResolver` (bắt buộc manifest REC-04); REC-10 bundle bắt
  buộc `rgb_frame_refs`/`camera_pose_refs`. File `.ply` trần không có các thứ này.

## Decision

### 1. Loại đầu vào, nhận diện theo nội dung

Server nhận diện **theo bytes sau khi upload đã verify checksum**, không tin đuôi
file hay `Content-Type` của trình duyệt. Không khớp loại nào → từ chối với lý do
cụ thể, không đoán.

| Kind | Nhận diện | Luồng |
|---|---|---|
| `rgb_video` | container MP4/QuickTime (`ftyp`), ffprobe có video stream | Như hiện tại: prepare → COLMAP → Brush → preview |
| `gaussian_ply` | header PLY có `x y z`, `f_dc_0..2`, `opacity`, `scale_0..2`, `rot_0..3` | Import visual không camera → SOG để xem → editor/xác nhận tỉ lệ |
| `gaussian_ply_colmap` | ZIP chứa đúng một PLY 3DGS + model COLMAP (`cameras`, `images`, `points3D` dạng `.bin` hoặc `.txt`) | Import visual **có** camera pose → đi tiếp như video sau REC-04 |

Từ chối có hướng dẫn:
- PLY chỉ có `x y z` (± màu) là point cloud, không phải 3DGS. LiDAR của người dùng
  chưa hỗ trợ ở P0; hướng LiDAR chỉ chạy trên dataset đã chuẩn bị (ADR 0001).
- `.splat`, `.ksplat`, `.spz`, `.sog`: chưa hỗ trợ ở P0.

ZIP phải an toàn: giới hạn số entry và tổng dung lượng giải nén, cấm đường dẫn
tuyệt đối/`..`/symlink, không giải nén ra ngoài workspace của job.

### 2. Kind đi vào job, không là state ở trình duyệt

Kind và bằng chứng nhận diện (header/entry list + checksum) được lưu cùng upload và
InputManifest provenance. Worker chọn luồng theo kind đã lưu, không nhận diện lại
từ tên file. Chỉ `rgb_video` tiêu tốn quota GPU cho bước dựng; import vẫn ghi nhật ký.

### 3. Bù phần thiếu cho `gaussian_ply` (không camera)

- REC-06: người dùng click thêm một điểm "phía trên sàn" thay cho tâm camera khi
  chọn chiều pháp tuyến; bỏ kiểm độ cao camera, UI ghi rõ đã bỏ.
- REC-05: nhận visual import; seed robot do người dùng click trên sàn (không có
  camera để đề xuất). Capsule theo quyết định owner trong REC-05.
- Provenance ghi `visual_source = "user_import"`; không gắn nhãn là output Brush.

### 4. Bundle cho visual import — không nới contract (owner chốt 2026-09-29)

`ReconstructionBundle` **giữ nguyên**. Luồng `gaussian_ply` (không camera/ảnh) dừng
sau xem / xác nhận tỉ lệ / REC-05 với trạng thái rõ ràng, không tạo bundle. Lý do:
EX-SCENE cần frame ảnh gốc (SCENE-02 tách vật thể bằng SAM2 trên ảnh), nên nới
contract cũng không đi tiếp được. Cần đi hết pipeline thì dùng `gaussian_ply_colmap`
kèm ảnh. Chỉ cần thông báo EX-SCENE/EX-SIM, không cần review contract.

### 5. Ba hướng tỉ lệ cho demo (cùng video Aisle_CW)

| Hướng | Cách tính tỉ lệ | Trạng thái |
|---|---|---|
| RGB only | MoGe-2 → ColmapSparseDepthProjector → RobustScaleAligner (ADR 0001 §2, P1) | **Mock trong demo**: hiện luồng các bước, nhãn "Mô phỏng · P1 chưa triển khai", **không điền số tỉ lệ giả**; scene giữ không đơn vị |
| RGB + anchor người dùng | A/B + 3 điểm sàn trên scene 3DGS (REC-06) | Đã có |
| RGB + LiDAR | REC-07/08 LiDAR → REC-09 alignment | Chỉ dataset đã chuẩn bị |

### 6. Dataset mẫu: số đo lấy từ LiDAR (owner chốt 2026-09-29)

Trên dataset có LiDAR (Aisle_CW), người thử demo **không tự đo ngoài đời**: vẫn click
A/B, C/D và 3 điểm sàn trên 3DGS để mô phỏng luồng thật, nhưng khoảng cách do hệ
thống lấy từ LiDAR (ô số chỉ đọc, nhãn "Số đo từ LiDAR · mô phỏng số đo ngoài đời").
Video thật của người dùng vẫn nhập tay. Điểm click được đưa sang LiDAR qua căn chỉnh
SfM → world theo quỹ đạo camera (REC-09, GT-assisted, chỉ cho demo). Bản xác nhận ghi
nguồn số đo ở `measurement_ref`, không ghi là người dùng đo.

## Consequences

- Upload nhận thêm `.ply` và `.zip`; UI một ô tải lên, server báo loại nhận diện
  được trước khi tạo scene.
- Model upload/InputManifest thêm kind; REC có thêm một đường import visual tách
  khỏi Brush, dùng chung SOG packaging và REC-06/05 phía sau.
- Rủi ro: file 3DGS từ công cụ ngoài có quy ước trục khác (Y-up/Z-up); xác nhận
  tỉ lệ bằng 3 điểm sàn đặt lại hướng nên không phụ thuộc quy ước đó.

## Follow-Up

1. Nhận diện kind + lưu bằng chứng (EX-PRODUCT upload, EX-REC validator).
2. Import `gaussian_ply` tới xem/chỉnh sửa/xác nhận tỉ lệ.
3. Import `gaussian_ply_colmap`.
4. Demo ba hướng trên Aisle_CW (RGB only là mock).
5. Thông báo EX-SCENE/EX-SIM về phần 4 (không đổi contract).
