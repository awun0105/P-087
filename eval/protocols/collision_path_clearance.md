# collision_path_clearance — collision mesh có chặn giả đường robot đã đi không

**Đo gì:** tỉ lệ vị trí camera trên quỹ đạo (chiếu xuống sàn) mà collision mesh REC-05 chiếm
chỗ trong capsule robot (bán kính/chiều cao theo `configs/product/geometry_v1.json`). Trên
Aisle_CW camera gắn trên robot OTTO nên mọi vị trí đó phải trống: chỗ bị chiếm là **chặn giả**
(REC-05 tiêu chí "Aisle không bị ghost-block").

**Nguồn:** camera canonical của chính scene + mesh REC-05; không dùng GT (không leak).

**Chạy:** `python -m eval.path.path_clearance --input-ply <metric input.ply> --poses <canonical
camera_poses.json> --profile configs/product/geometry_v1.json --gpu <adapter> --label <nhãn>
--work <thư mục tạm> --out eval/results/collision_path_clearance/<nhãn>.jsonl`

**Chỉ số:** `blocked_positions`/`blocked_fraction` (đỉnh mesh trong capsule, z 0,03–0,308 m),
`triangles`, `seconds`. Khi đọc cần tách lớp sàn dày (Gaussian nhiễu sát sàn): báo thêm số vị
trí bị chặn bởi phần mesh cao hơn 0,10 m và 0,15 m.

**Giới hạn:** camera không ở đúng tâm robot (lệch vài cm theo extrinsic); capsule ngoại tiếp
0,461 m có thể chạm kệ thật ở lối hẹp — kết quả cần đối chiếu ảnh/Isaac trước khi kết luận.

## Hình học va chạm từ LiDAR (ADR 0009, L10)

**Chạy:** `python -m eval.path.lidar_clearance --job-root <artifacts/jobs/job-…> --profile
configs/product/geometry_v1.json [--package <gói scan thô .zip>] --label <nhãn> --out
eval/results/collision_path_clearance/<nhãn>.jsonl`

Cùng phép kiểm (khối robot đặt tại từng vị trí camera canonical), áp lên ô voxel bị chiếm của đám mây LiDAR đã đặt vào
hệ `world` (khớp cứng tâm camera theo quỹ đạo ↔ pose canonical). Dòng đầu là mesh 3DGS đã publish của chính job để so.

**Kết quả đã đo** (`aisle-cw-100-lidar-job.jsonl`, job `job-101e9b56344c`, Aisle_CW frame 100–599, 100 frame video,
100 scan, quỹ đạo là ground truth của dataset — số liệu demo, không phải benchmark split):

| Hình học | Tầm gần bỏ qua | Dải sàn | Vị trí bị chặn nhầm |
| --- | --- | --- | --- |
| Mesh 3DGS của job (REC-05) | — | 3 cm | 38 / 100 |
| LiDAR, đám mây của job | 0,5 m | 3 cm và 15 cm | 100 / 100 |
| LiDAR, ghép lại | 2 m | 3 cm | 49 / 100 |
| LiDAR, ghép lại | 2 m | 15 cm | 0 / 100 |
| LiDAR, ghép lại | 3 m | 3 cm | 43 / 100 |
| LiDAR, ghép lại | 3 m | 15 cm | 0 / 100 |

Đọc kết quả:

- Đám mây LiDAR dùng nguyên trạng **không** làm hình học va chạm được: chặn nhầm toàn bộ đường đi. Trong scan thô có
  một khối điểm cách cảm biến khoảng 1 m về phía sau, cao tới khoảng 1,2 m so với sàn, đi cùng robot ở mọi scan (thứ
  đi theo robot); khi ghép, nó trải thành một dải dọc theo cả đường đi.
- Bỏ điểm gần cảm biến hơn 2 m thì phần chặn còn lại đều nằm trong dải 15 cm sát sàn: sàn LiDAR dày hơn ngưỡng 3 cm
  của phép kiểm (nhiễu đo cộng độ lệch pose ↔ quỹ đạo, trung vị 12 cm ở job này).
- Xử lý cả hai thì LiDAR không chặn nhầm vị trí nào, so với 38/100 của mesh 3DGS. Vật cản tĩnh nằm trên đường đi vẫn
  được giữ vì nó được nhìn thấy từ các scan ở xa hơn 2 m.

Chưa đo: traversal khác, quỹ đạo không phải ground truth, và chiều ngược lại (LiDAR có bỏ sót vật cản thật không — cần
bề mặt tham chiếu độc lập).

## AUD-12.S1 — evidence contract và fixture acceptance đã khóa

### Cách diễn giải các JSONL đã lưu

- `blocked_positions / camera_positions` chỉ là **free-space path proxy**. Nó
  đo hình học va vào capsule quanh các pose đầu vào; không đo vật cản thật bị bỏ
  sót. Independent obstacle recall phải có một reference scan/CAD/contact set
  độc lập và được lưu riêng.
- Mọi dòng LiDAR có `trajectory_origin=ground_truth` là **GT-assisted**. Không
  dùng các dòng này làm benchmark độc lập hoặc claim safety.
- Dòng RGB cũ không ghi `source`, checksum hình học/profile, robot envelope,
  hardware ID hay `trajectory_origin`; parser giữ các trường đó là thiếu và
  đánh dấu `origin_unrecorded_free_space_proxy`, không suy từ `label` hoặc tên
  file. Protocol xác định evaluator dùng camera path canonical nhưng JSONL chưa
  mang metadata đó. File-level SHA-256 giữ nguyên danh tính JSONL.
- Log 0/100 sau `min_range=2–3 m` và `floor_band=0,15 m` chứng minh riêng proxy
  free-space trong một traversal GT-assisted. Chưa biết tỉ lệ giữ vật cản độc
  lập, contact trong Isaac, hoặc kết quả ở capture/hardware khác.

Đọc lại các file đã lưu bằng:

```bash
python -m eval.path.collision_quality \
  eval/results/collision_path_clearance/aisle-cw-local-t2000.jsonl \
  eval/results/collision_path_clearance/aisle-cw-100-lidar-job.jsonl
```

Mỗi report chuẩn hóa giữ units mét, counts gốc, evidence class, missing
provenance và checksum file. Không ghi ngược vào JSONL nguồn.

### Fixture matrix và split

Các fixture có unit/gốc hình học biết trước. Bản test hiện tại đóng các mẫu
tổng hợp tối thiểu dưới đây để làm tuning inputs; chưa có held-out capture thật
trong repo. Cột held-out là ma trận đã chốt cho capture/checksum khác, không phải
kết quả đã chạy.

| Nhóm | Tuning fixture | Held-out fixture | Metrics/acceptance đã đóng cho fixture |
| --- | --- | --- | --- |
| Vật cản mảnh | Chân kệ và chân pallet | Dịch vị trí/chỉnh mật độ mẫu | Mỗi vật cản có reference sample; retain 100% samples ở ngưỡng sai số đã khai báo; test dương phải báo BLOCKED. |
| Vật cản thấp | Dây/cáp và low box | Dịch cao độ trong dải capsule | Giữ từng class; low obstacle không bị coi là floor. |
| Tường và dốc | Tường cắt đường đi, ramp edge | Đổi hướng tường/độ cao dốc | Support/wall reference được giữ; vùng capsule overlap phải báo BLOCKED. |
| Sàn/support | Mặt sàn phẳng | Sàn có dốc và biên coverage | Retain 100% support samples đã gán; floor samples không tự bị tính thành chặn thân robot. Không chấp nhận output rỗng. |
| Lối hẹp | Passage rộng 0,90 m | Passage rộng 1,05 m | Với capsule đường kính 0,922 m: trường hợp overlap phải BLOCKED; trường hợp clearance lớn hơn phải CLEAR. |
| Lệch camera | Offset ngang 0,05 m tại biên capsule | Cùng vật cản với pose/yaw khác | Ghi offset/extrinsic đã đo; nếu thiếu offset hoặc không truyền được theo pose, kết quả là UNRESOLVED, không là verified clear. |
| Motion/coverage | Static observed region | Motion-suspected và unobserved/inferred region | Flag diagnostic/state; không được nâng thành verified physics. |

Ngưỡng frozen cho **synthetic fixtures** trước khi chạy test: mọi sample vật
cản/sàn tham chiếu phải còn (100%); geometry rỗng luôn fail; known-clear fixture
phải có 0/1 blocked; known-blocked fixture phải có 1/1 blocked. Dùng sai số mẫu
được khai báo theo mét trong fixture (synthetic sample tolerance hiện là
0,001 m), không đổi ngầm theo profile. Đây không phải
production acceptance threshold. Ngưỡng production và nguồn ground truth sẽ được
ghi/freeze trên tuning set trước khi mở held-out run trong AUD-12.S4; held-out
không dùng để chỉnh filter.

### Typed source/report boundary

`CollisionSourceSelection` (version 1.0) bind mode/input mode, source artifact
checksum, source-QA ref, LiDAR alignment-QA kind/ref theo input mode,
profile/config checksum, effective resolution và output collision ref.
`CollisionQualityReport` bind selection/report checksums, source/output refs,
hardware/robot profile refs, resolution, robot capsule, frozen acceptance-profile
result, floor/support retention, free-space proxy, independent obstacle
reference, per-region observation/coverage, và Isaac contact ref.
Consumer ghi selected output vào `SceneEnvironment.collider_ref`; helper kiểm
exact URI + byte checksum và source/config/report identity trước khi tiêu thụ.

`free_space_proxy` không thể thay `obstacle_retention`. `UNOBSERVED`, `INFERRED`
hay `MOTION_SUSPECTED` region, geometry rỗng, reference cùng input/synthetic,
thiếu floor support hoặc thiếu exact-candidate Isaac contact đều chặn
`physics_claim=verified`. Claim cũng cần `quality_result=PASS` theo đúng
acceptance profile được bind; chưa freeze profile thì report chỉ là
`NOT_EVALUATED`. Contract hiện được thêm nội bộ; producer/API/SceneIR chưa bật
source selection trong production ở S1.
