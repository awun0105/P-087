# Execution Plan: Luồng video + LiDAR trong Studio

## Status

IN_PROGRESS — bắt đầu 02/10/2026. Owner: Quân (Tech Lead / EX-REC). Authority: [ADR 0009](../../decisions/0009-user-lidar-input-and-routing.md),
`docs/PRD.md` v1.17 (§4.2, §5.2), `docs/STUDIO_UX_SPEC.md` (`/new/import-video`).

## Outcome

Kỹ sư nộp video kèm một gói LiDAR; Studio tự ghép scan (nếu là scan thô), dựng pose camera bám theo quỹ đạo, dựng
3DGS thẳng trong hệ mét của LiDAR, và dùng LiDAR cho tỉ lệ mét, mesh va chạm và lớp đối chiếu. Người dùng không chọn
điểm nào; chỉ xem sai số rồi bấm xác nhận. Job chỉ có video (luồng A) không đổi.

## Gói LiDAR (đã khoá)

Một `.zip` gồm: quỹ đạo TUM, calibration camera ↔ LiDAR, thời điểm frame, và hoặc các scan `.pcd` (luồng C), hoặc một
đám mây `.ply`/`.pcd` đã đăng ký (luồng B). Thiếu một trong ba file đi kèm, hoặc nộp đám mây trần, thì từ chối kèm
hướng dẫn.

## Các bước

| # | Việc | Trạng thái |
|---|---|---|
| L1 | Nhận diện gói LiDAR theo nội dung + thông báo từ chối (`inputs/detect.py`, upload kinds) | **DONE** (test + chạy trên gói TorWIC thật) |
| L2 | Thử nghiệm cách dựng pose bám quỹ đạo (COLMAP) trên Aisle_CW | **DONE** (SfM + chất lượng 3DGS; số ở ADR 0009) |
| L3 | Ghép scan trong worker bằng numpy (`reconstruction/lidar/fusion.py`), không thêm Open3D vào runtime | **DONE** (20 scan thật: 133.978 điểm trong 3 s; lệch bản Open3D tối đa 6 cm) |
| L4 | Stage `ST-LIDAR-INGEST`: giải gói, ghép (luồng C), REC-08 nhận đám mây, ghi provenance (quỹ đạo ground truth hay tự tính) | **DONE** (`lidar/package.py`; sàn ước lượng −0,2235 m, owner đo −0,2345 m; worker chạy sau bước tách frame, gói hỏng thì job dừng ở đây trước khi tốn GPU) |
| L5 | Pose camera từ quỹ đạo + calibration + thời điểm frame; REC-03 chạy `point_triangulator` rồi `pose_prior_mapper --input_path` thay cho `mapper` khi job có gói LiDAR | TODO |
| L6 | Bước tỉ lệ mét cho job LiDAR: không chọn điểm; bản ghi căn chỉnh + màn xác nhận (tỉ lệ, sai số, số frame) | TODO |
| L7 | Job mang gói LiDAR: API tạo scene nhận `lidar`, `InputManifest.lidar_metadata`, bundle `registered_lidar_present` | Phần tạo scene + manifest **DONE** (chỉ qua API, chưa có ô trên UI); bundle chờ L6 |
| L8 | UI `/new/import-video`: ô LiDAR, giải thích ba luồng và dữ liệu cần, kết quả nhận diện; timeline có hai bước LiDAR | TODO |
| L9 | Bộ mẫu TorWIC ở cả hai dạng, kèm video camera trái cùng traversal; nâng giới hạn upload cho gói LiDAR | TODO |
| L10 | Mesh va chạm từ LiDAR (vùng LiDAR phủ) + phần còn lại từ 3DGS; đo bằng `collision_path_clearance` và `metric_click_error` | TODO |
| L11 | Lớp LiDAR chồng lên scene trong viewer | TODO |

Thứ tự: L3 → L4 → L5 → L6 → L7 → L8 → L9 → L10 → L11. L5 là thay đổi sâu nhất (scene ra khỏi REC-03 đã có đơn vị mét
thay vì `arbitrary_sfm`), nên làm thành một nhánh rõ ràng theo kind của job, không đụng luồng A.

## Kết quả đã có

### L1

- `registered_lidar` và `lidar_scan_sequence` là hai kind mới; gói TorWIC thật (20 scan Aisle_CW; và đám mây đã ghép
  133.039 điểm) được nhận đúng, file `.ply`/`.pcd` trần bị từ chối kèm hướng dẫn.
- Chưa có ô LiDAR trên UI: hiện tải gói LiDAR vào ô video/3DGS thì trang báo "đây là dữ liệu LiDAR" và không dùng nó.

### L2 (số đo ở ADR 0009, mục "Số đo thử nghiệm")

- Cách chọn: pose từ quỹ đạo → `point_triangulator` → `pose_prior_mapper --input_path` (σ vị trí 5 cm). 100/100 ảnh,
  một mảnh, sai số chiếu lại 0,52 px, lệch quỹ đạo trung vị 8,0 cm, tỉ lệ 1,0003; 22 giây so với 49 giây của `mapper`.
- `mapper` hiện tại trên cùng ảnh: 91/100 ảnh và đứt thành hai mảnh (71 + 20).
- Chất lượng 3DGS trên cùng 71 ảnh: `mapper` 23,93 dB; bám quỹ đạo 23,46 dB (σ 5 cm) và 23,64 dB (σ 20 cm). Kém
  0,3–0,5 dB, đổi lại dựng đủ ảnh thành một mảnh trong hệ mét. Một lượt chạy mỗi cách.
- Quy tắc giữ lại ảnh của Brush (`chỉ số % N == 0` theo thứ tự tên) đã đối chiếu với ảnh Brush lưu ra: khớp. Đây là
  phần còn nợ của `2026-10-02-evaluation-system.md`.

## Rủi ro và giới hạn

- Mọi số đo dùng quỹ đạo ground truth của TorWIC, một traversal. Quỹ đạo tự tính của kỹ sư sẽ kém hơn; cần một thử
  nghiệm thêm nhiễu vào quỹ đạo để biết ngưỡng chịu được.
- Video trong sản phẩm được trích frame theo `sample_fps`; thời điểm frame phải quy về đồng hồ của quỹ đạo qua
  `frame_times`. Video mẫu dựng từ mọi ảnh của traversal nên frame thứ *k* của video là dòng *k*; video cắt bớt hoặc
  bỏ frame sẽ lệch — phải phát hiện và từ chối, không đoán.
- Calibration hiện chỉ hỗ trợ camera trái của TorWIC và một định dạng JSON tối giản.
- Giới hạn upload 2 GiB nhỏ hơn một traversal scan thô đầy đủ (2,7–5,4 GB).

## Proof khi hoàn tất

Một job thật trên Aisle_CW đi từ `/new/import-video` (video + gói scan thô) tới scene có tỉ lệ mét từ LiDAR mà không
chọn điểm nào; bundle ghi `registered_lidar_present=true` với căn chỉnh `CONFIRMED`; số đo L10 ghi vào `eval/results/`.

## Trạng thái giữa chừng (02/10/2026, tối)

- Đi được tới đâu: tạo scene qua API với `lidar` → worker chuẩn bị video → `ST-LIDAR-INGEST` publish đám mây đã
  đăng ký + `LidarPackageRecord` → sang COLMAP. Timeline hiện bước "Nhận dữ liệu LiDAR" cho job có gói.
- **Chưa dùng LiDAR cho việc gì sau bước nhận:** COLMAP vẫn chạy `mapper` như job chỉ có video, bước tỉ lệ mét vẫn là
  màn chọn điểm, bundle vẫn ghi `registered_lidar_present=False`. Vì vậy **chưa mở ô LiDAR trên UI** (L8): mở trước
  L5/L6 sẽ thành "nhận LiDAR rồi bỏ qua", điều PRD §4.2 cấm trình bày như đóng góp.
- Trong lúc bước nhận LiDAR chạy, timeline tạm hiện bước kế tiếp ("Ước lượng camera") là đang chạy, vì bước này chỉ
  ghi một lần khi xong. Sửa cùng L5.
- Bước tiếp theo: L5 — `LidarPackageRecord` + frame set → pose camera theo thời điểm frame → REC-03 chạy
  `point_triangulator` rồi `pose_prior_mapper --input_path`.
- Validation: `pytest tests/ -q` 1386 passed, 40 skipped; frontend 222 passed, typecheck + lint sạch. Test tích hợp
  chạy worker thật trên video + gói LiDAR (đạt và hỏng). Chưa chạy job thật trên TorWIC qua stack.
