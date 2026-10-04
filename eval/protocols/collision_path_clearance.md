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
