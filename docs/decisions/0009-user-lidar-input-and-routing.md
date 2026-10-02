# 0009 LiDAR của người dùng: loại đầu vào và ba luồng xử lý

Date: 2026-10-02

## Status

- **Mục 1–3: Accepted** — Tech Lead / EX-REC owner (Quân) chốt ngày 2026-10-02: "nên nhận tất cả loại, tuỳ theo đầu
  vào mà hệ thống sẽ kiểm tra rồi cho ra thông báo rồi sẽ phân luồng xử lý … luồng hai phải là scan thô + quỹ đạo chứ
  không được chỉ scan thô, phải có hiển thị thông báo cho người dùng rõ ràng".
- **Mục 6 và 7: Accepted** — owner chốt cùng ngày: LiDAR dùng cho "tất cả vai trò"; bộ mẫu có "tất cả" các dạng,
  "nhớ phải chia ra cho user hiểu là luồng nào cần data dạng nào".
- **Mục 4–5: Proposed** — chưa phải authority; chờ owner chốt (xem "Câu hỏi còn mở").

Thay thế câu "LiDAR của người dùng chưa hỗ trợ ở P0; hướng LiDAR chỉ chạy trên dataset đã chuẩn bị" của
[0004](0004-input-kinds-and-routing.md) mục 1. Các phần khác của 0004 giữ nguyên.

## Context (VERIFIED trên repo ngày 2026-10-02)

- Studio chỉ nhận video, PLY 3DGS và ZIP (PLY 3DGS + COLMAP). PLY chỉ có `x y z` bị từ chối với câu "LiDAR của người
  dùng chưa được hỗ trợ" (`src/services/reconstruction/inputs/detect.py`).
- Backend đã có: đọc header PLY/PCD (`lidar/cloud_header.py`), REC-08 nhận đám mây đã đăng ký
  (`lidar/ingest.py`, đơn vị mét, tối đa 20 triệu điểm), REC-09 ghi bản ghi căn chỉnh (`alignment/`). Worker của
  Studio **không** gọi bước nào; bundle luôn ghi `registered_lidar_present=False` (`finalize.py`).
- Shared contract đã có chỗ cho đầu vào hỗn hợp: `InputConfiguration.registered_lidar_present`, `LidarMetadata`,
  `LiDARGeometryArtifact`, `AlignmentRecord`, stage `ST-LIDAR-INGEST`, `ST-RGB-LIDAR-ALIGN`. Bundle hỗn hợp bắt buộc
  căn chỉnh ở trạng thái `CONFIRMED`.
- Ghép scan thô chỉ có ở script offline `scripts/torwic/build_registered_lidar.py` (Open3D 0.19 trong runtime riêng;
  môi trường app và `data/scene_runtime` đều không có Open3D). Script gắn chặt với TorWIC: cần `frame_times.txt`,
  `calibrations.txt`, bản ghi bằng chứng hệ toạ độ.
- Căn chỉnh hiện có (`scripts/torwic/align_sfm_to_world.py`) khớp tâm camera COLMAP với tâm camera thật lấy từ
  `traj_gt.txt` — dùng ground truth, chỉ hợp lệ cho demo dataset.
- Dữ liệu TorWIC trên ổ ngoài: Aisle_CCW 915 scan / 2,7 GB; Aisle_CW 1092 scan / 3,3 GB; Hallway_Straight_CW 1810
  scan / 5,4 GB; mỗi scan 262.144 điểm, `traj_gt.txt` có đúng một pose cho mỗi scan (định dạng TUM:
  `t x y z qx qy qz qw`). Giới hạn upload hiện tại là 2 GiB (`product_upload_max_bytes`).
- PRD xếp "xử lý chuỗi LiDAR thô, LiDAR odometry hoặc LiDAR SLAM" vào P2 và "căn chỉnh cảm biến tự động" vào P2.

## Decision

### 1. Loại đầu vào LiDAR, nhận diện theo nội dung (Accepted)

LiDAR là đầu vào **tuỳ chọn đi kèm video** ở trang `/new/import-video`; không có job chỉ-LiDAR (PRD: P1).

| Kind | Nhận diện | Xử lý |
|---|---|---|
| `registered_lidar` | Một file `.ply` hoặc `.pcd` có `x y z`, **không** có thuộc tính 3DGS | Kiểm tra rồi dùng thẳng (REC-08) |
| `lidar_scan_sequence` | Một `.zip` gồm nhiều scan `.pcd` **và đúng một** file quỹ đạo | Ghép scan theo quỹ đạo thành đám mây đã đăng ký, rồi như trên |

Từ chối có hướng dẫn (thông báo hiện cho người dùng, không đoán):

- ZIP có scan nhưng **không có quỹ đạo**: "Tìm thấy N scan nhưng không có file quỹ đạo. Hệ thống không tự ước lượng
  quỹ đạo (LiDAR odometry/SLAM chưa hỗ trợ). Thêm file quỹ đạo dạng TUM vào ZIP, hoặc tải lên đám mây đã đăng ký."
- Nhiều hơn một file quỹ đạo; số pose không khớp scan; pose không hữu hạn/quaternion không chuẩn hoá; scan rỗng.
- PLY 3DGS tải vào ô LiDAR, hoặc point cloud tải vào ô 3DGS: báo đúng loại nhận diện được và chỉ sang đúng trang.

### 2. Ba luồng xử lý (Accepted)

| Luồng | Đầu vào | Khác biệt |
|---|---|---|
| A — chỉ RGB | video | Như hiện tại |
| B — RGB + LiDAR đã đăng ký | video + `registered_lidar` | Thêm `ST-LIDAR-INGEST` (kiểm tra) và `ST-RGB-LIDAR-ALIGN` |
| C — RGB + scan thô + quỹ đạo | video + `lidar_scan_sequence` | Như B, nhưng `ST-LIDAR-INGEST` ghép scan trước |

Luồng được chọn theo kind đã lưu cùng upload (như 0004 mục 2), không theo tên file và không là state ở trình duyệt.

### 3. Thông báo cho người dùng (Accepted)

- Ngay sau khi tải lên: loại nhận diện được, số điểm hoặc số scan + số pose, và luồng sẽ chạy (A, B hay C).
- Trước khi tạo job: người dùng khai báo hai nguồn là **cùng một không gian** (contract yêu cầu) và đơn vị là mét.
- Với luồng C: người dùng khai báo nguồn gốc quỹ đạo (do SLAM/odometry bên ngoài tính, hay ground truth của dataset).
  Quỹ đạo ground truth được ghi vào provenance là "có dùng ground truth" (contract đã bắt buộc).
- Trên timeline: hai bước LiDAR hiện như mọi bước khác, có trạng thái, thời gian và lỗi cụ thể.
- LiDAR chưa căn chỉnh xong thì scene ghi rõ "chưa đủ bằng chứng LiDAR"; không tự ghép hai nguồn (PRD §5.2).

### 4. Ghép scan trong worker (Proposed)

Chuyển phần ghép vào `src/services/reconstruction/lidar/` và viết bằng numpy (đọc PCD/PLY bằng reader đã có, áp
pose, gộp, lưới voxel) thay vì thêm Open3D vào runtime của worker. Ghép theo chỉ số: scan thứ *i* (theo tên) ↔ pose
thứ *i*; có file thời gian thì kiểm lệch trong ngưỡng. Quỹ đạo là pose của **cảm biến LiDAR** trong một hệ cố định.
Giới hạn upload phải nâng (hoặc cho phép lấy thưa scan) vì một traversal TorWIC đã 2,7–5,4 GB.

### 5. Căn chỉnh LiDAR ↔ scene 3DGS (Proposed)

Video người dùng không có quỹ đạo camera thật, nên cách khớp tâm camera không áp dụng được. Đề xuất: người dùng chọn
ít nhất 3 cặp điểm tương ứng (trên 3DGS và trên LiDAR), hệ thống fit phép đồng dạng (Umeyama, đã có ở
`alignment/similarity.py`) rồi tinh chỉnh bằng ICP, hiện sai số còn lại; người dùng xác nhận thì bản ghi mới thành
`CONFIRMED`. Phép đồng dạng cho luôn tỉ lệ mét. Riêng dataset có quỹ đạo camera + calibration thì giữ thêm đường khớp
tâm camera (ghi rõ là có ground truth).

### 6. LiDAR dùng vào việc gì (Accepted — cả ba)

(a) Tỉ lệ mét lấy từ căn chỉnh thay cho số đo tay; (b) mesh va chạm dựng từ LiDAR thay cho mesh từ 3DGS — đây là
"bằng chứng LiDAR đóng góp" của PRD §4.2; (c) lớp LiDAR chồng lên scene để đối chiếu.

Số đo hiện có trên Aisle_CW (`eval/results/`, căn chỉnh có dùng ground truth): bề mặt 3DGS lệch LiDAR trung vị
15,5 cm ở vùng LiDAR phủ (chỉ 34% điểm trong 10 cm); mesh va chạm từ 3DGS chặn nhầm 56–68% vị trí camera đã đi qua.
Chưa có số đo cho mesh dựng từ LiDAR — phải đo bằng cùng hai benchmark trước khi kết luận nó tốt hơn. Vùng LiDAR không
quét tới (48% bề mặt 3DGS ở lượt đo trên) vẫn phải lấy từ 3DGS, và UI ghi rõ phần nào đến từ nguồn nào.

### 7. Bộ LiDAR mẫu (Accepted)

Trang `/new/import-video` có sẵn dữ liệu TorWIC ở cả hai dạng (đám mây đã đăng ký; scan thô + quỹ đạo), mỗi mẫu đi
kèm video cùng traversal. Trang giải thích rõ từng luồng cần dữ liệu dạng nào trước khi người dùng chọn.

## Consequences

- `docs/PRD.md` cần sửa: ghép scan thô **khi có sẵn quỹ đạo** chuyển từ P2 sang phạm vi làm; LiDAR odometry/SLAM vẫn
  P2. `docs/STUDIO_UX_SPEC.md` nguyên tắc 3 ("không suy thành tính năng upload LiDAR phổ quát"), S03 và S05 cần sửa.
  Chưa sửa các file này; chờ owner giao.
- Upload nhận thêm `.pcd`; nhận diện ZIP có thêm một nhánh; `UploadRecord.input_kind` thêm hai giá trị.
- Job có thêm hai stage cho luồng B/C; job luồng A không đổi.
- Rủi ro: quỹ đạo người dùng nộp có thể là pose của khung khác (camera, thân robot) → đám mây ghép bị nhoè. Cần số đo
  độ sắc của đám mây ghép và ảnh xem trước để người dùng tự kiểm trước khi căn chỉnh.

## Câu hỏi còn mở

1. Cách căn chỉnh (mục 5). Owner nêu hướng (02/10/2026): luồng LiDAR + video dành cho kỹ sư nên họ nộp kèm quỹ đạo.
   Còn phải chốt: quỹ đạo chỉ đủ để căn chỉnh tự động khi có thêm phép biến đổi camera ↔ LiDAR (calibration) và quan
   hệ thời gian giữa video và quỹ đạo. Bắt buộc cả ba cho mọi luồng LiDAR, hay giữ đường chọn cặp điểm cho trường hợp
   thiếu (vd. chỉ nộp đám mây đã đăng ký)?
