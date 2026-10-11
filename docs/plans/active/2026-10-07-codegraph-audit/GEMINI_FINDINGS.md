# Đối chiếu audit Gemini với source và evidence

Date: 2026-10-07; code base `ef3a421`. Files log được đọc trực tiếp trong lần
mở rộng plan này. Không chạy lại GPU benchmark hoặc sửa data artifacts.

## Findings đã đối chiếu

| Nhận định Gemini | Kết quả kiểm tra | Task |
|---|---|---|
| Mesh 3DGS 0,05 m chặn 33/50 = 66% | Đúng log ngày 30/09: 224.745 triangles, 20,55 s geometry benchmark; 0,10 m: 28/50, 0,025 m: 34/50 | AUD-12 |
| LiDAR với floor_band 0,15 m cho 0/100 | Cần thêm điều kiện: raw scans được ghép lại với min_range_m 2 hoặc 3 m. Registered cloud dùng nguyên trạng vẫn chặn 100/100, cả floor_band 0,03 và 0,15 | AUD-12 |
| 0/100 chứng minh collider an toàn | Chưa đủ: trajectory_origin=ground_truth, demo một traversal, alignment median 0,1244 m; chưa đo bỏ sót vật cản thật và chưa chạy Isaac | AUD-12, AUD-05 |
| Full job 300–500 frames mất 40–45 phút | Chưa xác nhận đúng mô tả full job. Hai artifacts local ghi Brush 2.696,27 s và 2.553,53 s (~45/~42,6 phút), status RUNNING, metric waiting, geometry/object pending. max_frames=300 là config cap, không số frame thực xử lý | AUD-15 |
| Pipeline geometry là TSDF mesh | Đường FinalizeWorker._execute được kiểm dùng RgbGeometryService + SplatTransformVoxelAdapter. Không gọi toàn bộ geometry hiện tại là TSDF | AUD-12, AUD-15 |
| Chưa có LiDAR calibration projection QA | detect/package có syntax/count/transform checks; LiDAR overlay đang là cloud 3D trong scene, không là scored 2D calibration QA | AUD-13 |
| floor_clearance_m=0,06 cố định | Đúng GeometricConfig default và z-threshold của find_candidates; threshold còn được configure qua object context, cần fit-floor + uncertainty thay vì đổi số cố định | AUD-14 |
| Chưa thể chạy 7.000 iterations | Param brush.total_train_iters đã nhận 1.000–60.000, step 1.000. Thiếu first-class Fast Preview preset/lifecycle/UX; không cần thêm training knob trùng | AUD-16 |
| 7.000 iterations luôn ~5 phút | Chưa có guarantee. Log cũ 50 frames/7k tổng 7m41s là một cấu hình khác; cần benchmark paired, pin input/config/hardware | AUD-15, AUD-16 |
| Thiếu trajectory bị reject | Đúng detect._detect_lidar_package. Odometry có thể bổ sung opt-in; không biến nó thành guarantee drift-free SLAM | AUD-17 |
| Video chưa anonymize luôn được detector phát hiện và reject | Chưa đúng current Studio MVP: self_attested + PRELIMINARY_SCREENED có thể dispatch nếu đủ attestation/no findings. QA gate riêng đòi verified evidence; chưa có auto face/plate detector producer | AUD-18 |

## Evidence pointers

- [3DGS clearance log](../../../../eval/results/collision_path_clearance/aisle-cw-local-t2000.jsonl).
- [LiDAR clearance log](../../../../eval/results/collision_path_clearance/aisle-cw-100-lidar-job.jsonl).
- [Clearance protocol và caveats](../../../../eval/protocols/collision_path_clearance.md).
- [30k Brush attempt (~45 phút, chưa finalize)](../../../../data/studio_local/artifacts/jobs/job-1bb733ae40ad/benchmark/pipeline_runtime/attempt-2.json).
- [30k Brush attempt (~42,6 phút; COLMAP ~26,2 phút)](../../../../data/studio_local/artifacts/jobs/job-6bc02e5de4ed/benchmark/pipeline_runtime/attempt-1.json).
- [Processing parameters hiện có](../../../../configs/product/processing_presets_v1.json).
- [Geometry runtime](../../../../src/services/reconstruction/finalize.py).
- [Input detection](../../../../src/services/reconstruction/inputs/detect.py).
- [Scene geometric extraction](../../../../src/services/scene/geometric.py).
- [Current self-attestation dispatch](../../../../src/services/orchestration/projects/privacy.py).
- [ADR 0009 owner note giữ RGB mesh ngày 03/10](../../../decisions/0009-user-lidar-input-and-routing.md).

Artifacts trong data/ có thể gitignored và chỉ có ở checkout local. Agent khác
phải resolve artifact tương đương/checksum hoặc báo UNVERIFIED, không coi đường
dẫn local tồn tại trên mọi máy. Không dùng fixture thay số đo thật.

## Quy tắc acceptance mới

- Tách clearance consistency trên camera path khỏi independent obstacle recall
  và Isaac contact/path outcomes. Camera extrinsic/robot envelope có thể làm một
  vị trí bị chặn dù camera đi qua; cần đối chiếu protocol.
- Không tune filter hoặc chọn source để đạt 0% trên chính test traversal rồi
  gọi đó là benchmark độc lập. Freeze tuning profile trước held-out acceptance.
- Giữ low obstacles, pallet feet, shelf legs, ramp, wall, floor support và
  obstacles trong vùng gần sensor; deletion/filter phải có source provenance.
- Không dùng 1°/5 cm là accuracy guarantee trên data thực thiếu reference.
  Đây là perturbation test cases khi extrinsic gốc biết trước.
- Các tính năng ngoài MVP nhưng khả thi được đưa vào AUD-17/18 theo yêu cầu
  owner mới. Không cần mặc định enable chúng trên mọi job.

## Công nghệ và giới hạn

Đọc [TECHNOLOGY_LIMITS.md](TECHNOLOGY_LIMITS.md). Tài liệu phân biệt thiếu input/
observability, runtime chưa qualification, feature chưa implement và research
chưa chứng minh physics fidelity. Không gán mọi phần khó thành “công nghệ thế giới
không làm được”.

## Follow-up: automatic registration thay manual landmarks mặc định

Owner đồng ý bổ sung [AUD-19](tasks/AUD-19-automatic-rgb-lidar-registration.md)
sau đối chiếu đề xuất floor-constrained BEV + ICP. Trajectory camera-center
alignment hiện có không cần manual points; new independent-map mode thêm
geometric candidates/refinement, mode-specific QA và manual fallback. Map fit
khác camera↔LiDAR rig calibration; thiếu rig metadata không phải exclusion cho
hai static maps có đủ geometry overlap. Không kế thừa các promise “100%”,
“MoGe metric error 0,1%” hoặc “ICP đạt milimet” từ mô tả chưa được benchmark.
