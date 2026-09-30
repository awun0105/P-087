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
