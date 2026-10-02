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
| L5 | Pose camera từ quỹ đạo + calibration + thời điểm frame; REC-03 chạy `point_triangulator` rồi `pose_prior_mapper --input_path` thay cho `mapper` khi job có gói LiDAR | **DONE** (`lidar/camera_priors.py`, `adapters/colmap_priors.py`; job thật 100/100 frame) |
| L6 | Bước tỉ lệ mét cho job LiDAR: không chọn điểm; bản ghi căn chỉnh + màn xác nhận (tỉ lệ, sai số, số frame) | **DONE** (`lidar/metric.py`, nguồn `lidar_trajectory`, `LidarMetricConfirm.tsx`); màn hình chưa mở trên trình duyệt |
| L7 | Job mang gói LiDAR: API tạo scene nhận `lidar`, `InputManifest.lidar_metadata`, bundle `registered_lidar_present` | **DONE** (03/10/2026). Bước hoàn tất gắn `lidar_geometry_ref` + `AlignmentRecord` CONFIRMED (`world_from_lidar_map` khớp cứng tâm camera canonical ↔ quỹ đạo) khi người dùng xác nhận tỉ lệ từ căn chỉnh quỹ đạo; job LiDAR mà người dùng tự nhập số đo vẫn ra bundle chỉ có RGB. VERIFIED: chạy lại bước hoàn tất thật của `job-101e9b56344c` → bundle `registered_lidar_present=true`, căn chỉnh CONFIRMED (lệch trung vị 12,4 cm, lớn nhất 24,4 cm), `ground_truth_assisted=true`; `load_reconstruction_bundle` của EX-SCENE đọc được |
| L8 | UI `/new/import-video`: ô LiDAR, giải thích ba luồng và dữ liệu cần, kết quả nhận diện; timeline có bước LiDAR | **DONE** (`LidarPackageSection.tsx`, test); chưa mở trên trình duyệt |
| L9 | Bộ mẫu TorWIC ở cả hai dạng, kèm video camera trái cùng traversal; nâng giới hạn upload cho gói LiDAR | Công cụ **DONE** (`scripts/demo/make_torwic_lidar_samples.py`); đã dựng Aisle_CW 100–599 trên ổ ngoài. Chưa có: chọn mẫu ngay trong UI (hiện phải tải file lên), nâng giới hạn upload |
| L10 | Mesh va chạm từ LiDAR (vùng LiDAR phủ) + phần còn lại từ 3DGS; đo bằng `collision_path_clearance` và `metric_click_error` | Đo `collision_path_clearance` **DONE** (`eval/path/lidar_clearance.py`, kết quả ở `eval/protocols/collision_path_clearance.md`): LiDAR nguyên trạng chặn nhầm 100/100, sau khi bỏ điểm gần cảm biến < 2 m và dải sàn 15 cm còn 0/100 (mesh 3DGS: 38/100). Thay mesh canonical bằng LiDAR: **chờ quyết định** — `GeometryArtifact.source_modality` của shared contract chỉ nhận `rgb_3dgs` và cấm phụ thuộc ground truth |
| L11 | Lớp LiDAR chồng lên scene trong viewer | **DONE** (03/10/2026): `GET /jobs/{id}/lidar-overlay` (điểm ở hệ `world` theo đúng `AlignmentRecord`, thu gọn ≤ 300.000 điểm, cache theo checksum căn chỉnh); nút "Đám mây LiDAR" trong màn scene hệ mét và collision. VERIFIED trên bundle thật: 206.491 điểm, 2,5 MB, sàn ở z ≈ 0. Chưa mở trên trình duyệt |

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

## Lượt chạy thật đầu-cuối (02/10/2026, 22:59–23:26) — VERIFIED

Job `job-101e9b56344c` trong kho tách riêng `data/studio_local/qa/lidar-run-20261002/`, qua API + worker thật (Quadro
T2000). Đầu vào: video camera trái Aisle_CW frame 100–599 (500 frame) + gói scan thô 100 scan kèm quỹ đạo, calibration,
thời điểm frame (luồng C). Thông số: 2 fps → 100 frame, Brush 7000 bước, 960 px, 400k Gaussian.

| Bước | Kết quả |
|---|---|
| Nhận diện gói | `lidar_scan_sequence`, 100 scan, 500 pose |
| `ST-LIDAR-INGEST` | 45 giây; 26,2 triệu điểm vào → 1.128.772 điểm; sàn ước lượng −0,2466 m (owner đo −0,2345 m) |
| `ST-CAMERA-POSE` bám quỹ đạo | 100/100 frame, sai số chiếu lại 0,53 px; pose lệch quỹ đạo trung vị 10,6 cm, p90 28 cm, lớn nhất 33 cm |
| `ST-VISUAL-RECON` | PSNR 24,82 dB · SSIM 0,875 · LPIPS 0,367 trên 13 ảnh giữ lại |
| Đề xuất tỉ lệ từ LiDAR | tỉ lệ 0,9980; đường đi camera 40,1 m; độ bất định 0,3% |
| Xác nhận tỉ lệ | qua API với nguồn `lidar_trajectory`, **không chọn điểm**; camera cao 0,31–0,38 m trên sàn |
| Hình học, bundle, tách vật | SUCCEEDED; 14 vật |

Thời gian máy: chuẩn bị 87 s, nhận LiDAR 45 s, pose + 3DGS 457 s, hình học 271 s, tách vật 760 s (tổng ≈ 27 phút).

Giới hạn của bằng chứng này: một job, một traversal, quỹ đạo ground truth; xác nhận gọi qua API chứ chưa bấm trên giao
diện; chưa đo mesh so với LiDAR; mesh va chạm của job này vẫn dựng từ 3DGS; bundle chưa ghi LiDAR.

## Còn lại

L10 (mesh va chạm từ LiDAR + số đo, bundle ghi LiDAR), L11 (lớp LiDAR trong viewer), chọn mẫu trong UI, nâng giới hạn
upload, và hiện đúng bước "Nhận dữ liệu LiDAR" là đang chạy trong lúc nó chạy.
