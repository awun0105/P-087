# Đánh giá Real2Sim Studio

## 0. Phạm vi và cách đọc

| Thuộc tính | Nội dung |
| --- | --- |
| Ngày đối chiếu | 20/10/2026 |
| Snapshot source | `develop`, HEAD `4fb0f8f9`, có thay đổi chưa commit |
| Vai trò | Dữ liệu dùng để đo, cách tránh rò rỉ đáp án, từng phép đo đang có trong code, cách chạy lại và cách đọc kết quả đã lưu |
| Trạng thái | Đối chiếu source, protocol và file kết quả; chạy test của evaluator. Chưa chạy lại phép đo trên dữ liệu thật, chưa có bộ nghiệm thu đã khóa |

[PRD](PRD.md) giữ mục tiêu, mã chỉ số `SM`, tiêu chí `AC` và danh sách những gì phải khóa trước lần chạy cuối (PRD mục 2.2, 10 và 11). [CONTRACTS](CONTRACTS.md) giữ định nghĩa lớp dữ liệu (mục 1.2) và các model `ValidationReport`, `EvaluationReport`, `ReleaseManifest` (mục 8). [PIPELINE](PIPELINE.md) mô tả các mức bằng chứng của một lần chạy (mục 11.3). Tài liệu này không lặp các phần đó; nó trả lời: **đo cái gì, bằng dữ liệu nào, bằng lệnh nào, kết quả nằm ở đâu và được phép kết luận đến mức nào**.

### 0.1 Bốn việc khác nhau thường bị gọi chung là "đánh giá"

| Việc | Câu hỏi trả lời | Có dùng đáp án tham chiếu | Nơi trong code |
| --- | --- | --- | --- |
| Tự kiểm trong Studio | Scene của job này có điểm nào yếu theo số liệu chính job tạo ra? | Không | `src/services/orchestration/evaluation/`, API `/jobs/{id}/evaluation` |
| So với dữ liệu đối chứng | Kết quả lệch bao nhiêu so với quỹ đạo, bản đồ hoặc ảnh tham chiếu của dataset? | Có, chỉ evaluator đọc | `eval/` |
| Bảng giá trị theo scene | Scene có dùng được cho bài thử robot và tiết kiệm bao nhiêu công so với làm tay? | Có, do người dùng đo thước và khai báo | `src/services/orchestration/value/`, trang `/benchmark` |
| Kiểm định sản phẩm | Gói mô phỏng có nạp và chạy được trong Isaac theo cấu hình đã chọn? | Không được mang nhãn kỳ vọng | `ValidationReport`, xem [CONTRACTS mục 8](CONTRACTS.md) |

Kết quả của việc này không thay cho việc kia. Ví dụ: PSNR cao ở mục 3.2 không chứng minh collision đúng; một `ValidationReport` PASS không cho biết sai số mét.

## 1. Dữ liệu dùng để đo

### 1.1 TorWIC-SLAM và phạm vi kết quả hiện có

Mọi số đối chứng đang lưu trong repo lấy từ dataset TorWIC-SLAM, chủ yếu traversal `Aisle_CW` (cảnh kho). Dataset có giấy phép CC BY-NC 4.0; chỉ dùng cho nghiên cứu, không đưa vào sản phẩm thương mại. Các thành phần được dùng:

| Thành phần | Dùng để |
| --- | --- |
| Ảnh RGB theo traversal | Tạo video đầu vào cho job (`scripts/demo/make_torwic_video.py`) |
| `traj_gt.txt` (TUM, quaternion `xyzw`) và `calibrations.txt` | Quỹ đạo camera tham chiếu sau khi nhân calibration (`eval/reference/torwic.py`) |
| `groundtruth_map.ply` | Bề mặt tham chiếu cho hình học và LiDAR odometry |
| Scan LiDAR theo traversal | Tạo gói LiDAR demo; đo odometry |

Quy ước khung tọa độ của `Aisle_CW` (mét, Z hướng lên, độ cao sàn, nguồn từng quyết định) nằm trong [`coordinate_bridge.json`](../configs/datasets/torwic_aisle_cw/coordinate_bridge.json). Ảnh thứ `i` của video tương ứng ảnh `start + i` của traversal; mọi evaluator phải nhận đúng giá trị `--start` đã dùng khi tạo video.

PRD mục 10.1 yêu cầu thêm một cảnh trong nhà thực và một case có kiểm soát. Repo hiện **chưa có kết quả đối chứng nào ngoài TorWIC**. Không suy chất lượng cảnh phòng ở hoặc cảnh tự quay từ số của `Aisle_CW`.

### 1.2 Đáp án không được lọt vào nhánh dự đoán

Bốn lớp dữ liệu (`product_input`, `derived`, `ground_truth`, `evaluation_only`) được định nghĩa ở [CONTRACTS mục 1.2](CONTRACTS.md). Với việc đánh giá, các điểm đang được code thực thi là:

- Manifest job và tham chiếu artifact phía sản phẩm chỉ nhận hai lớp đầu (`ProductDataClass`, [`artifacts.py`](../src/models/contracts/artifacts.py)). API liệt kê và đọc artifact lọc theo danh sách lớp được phép ([`registry.py`](../src/services/orchestration/projects/registry.py), [`api/product/artifacts.py`](../src/api/product/artifacts.py)).
- Ảnh TorWIC đưa vào job phải là `product_input` ([`torwic_frame_source.py`](../src/services/reconstruction/adapters/torwic_frame_source.py)). Bản xuất demo bỏ tham chiếu `ground_truth`/`evaluation_only` ([`snapshot.py`](../src/services/orchestration/samples/snapshot.py)).
- `groundtruth_map.ply` chỉ được evaluator đọc từ đường dẫn truyền vào lệnh, không qua artifact của job.
- Calibration không bị coi là rò rỉ đáp án, nhưng phải khai báo nguồn.

**Ngoại lệ cần ghi rõ:** gói LiDAR demo được dựng từ `traj_gt.txt` với `trajectory_origin = ground_truth` ([`make_torwic_lidar_samples.py`](../scripts/demo/make_torwic_lidar_samples.py)). Job dùng gói này được đánh dấu "có hỗ trợ của đáp án" (`ground_truth_assisted`) và validator buộc cờ này khớp với danh sách phụ thuộc ([`reconstruction.py`](../src/models/contracts/reconstruction.py)). Với các job đó, sai số pose và tỉ lệ đo bằng chính quỹ đạo này **không phải bằng chứng độc lập**; evaluator ghi `job_used_this_trajectory` và `scale_is_independent = false`.

Một điểm lệch hiện có: bản ghi kết quả đối chứng của từng job (`ReferenceBenchmark`, [`eval/reference/torwic.py`](../eval/reference/torwic.py)) được lưu với lớp `derived`, nên Studio đọc và hiển thị được. Bản ghi chỉ chứa số đo, không chứa đáp án, nhưng đây là quyết định phải giữ có chủ ý nếu sau này siết quy tắc lớp dữ liệu.

### 1.3 Chuẩn bị dữ liệu offline

Các công cụ trong `scripts/torwic/` chạy ngoài Studio:

| Công cụ | Việc |
| --- | --- |
| `prepare_dataset.py`, `canonical_dataset.py` | Chuẩn hóa traversal vào cấu trúc raw/normalized/derived/evaluation_only, gán lớp dữ liệu, ghi checksum manifest |
| `normalize_rgb.py`, `normalize_calibration.py`, `normalize_timestamps.py`, `dedupe_rgb_frames.py` | Chuẩn hóa ảnh, calibration, thời gian; tránh nhân bản ảnh bằng hardlink chỉ đọc |
| `build_registered_lidar.py`, `publish_demo_lidar.py` | Tạo LiDAR đã đăng ký cho demo; luôn đánh dấu có hỗ trợ của đáp án |
| `align_sfm_to_world.py` | Căn quỹ đạo SfM về khung thế giới của dataset |
| `rec02_quality.py`, `rec02_evidence.py`, `rec02_privacy_issue.py` | Hồ sơ chất lượng ảnh và kiểm quyền riêng tư |

`create_benchmark_split.py` và `validate_dataset.py` hiện chỉ là file giữ chỗ, chưa có logic. Không ghi trong tài liệu khác rằng hai bước này đã chạy.

### 1.4 Tách ảnh huấn luyện và ảnh giữ lại

Có hai cách tách đang tồn tại, phục vụ hai mục đích khác nhau:

1. **Tách theo dataset.** `prepare_dataset.py` nhận danh sách frame huấn luyện và frame giữ lại qua tham số, ghi `BenchmarkSplit` và gán ảnh giữ lại lớp `evaluation_only`. `make_torwic_video.py --train-split` chỉ đưa ảnh huấn luyện vào video. File split của `Aisle_CW` không có trong checkout này.
2. **Tách trong chính job.** Khi huấn luyện Gaussian, cứ 8 ảnh của video giữ lại 1 ảnh để chấm (`eval_split_every: 8` trong [`processing_presets_v1.json`](../configs/product/processing_presets_v1.json)); kết quả lưu thành `holdout_quality`. Mục 3.2 dùng cách này.

Cách 2 cho ảnh giữ lại thường sát ảnh huấn luyện bên cạnh, nên số đo dễ lạc quan. Bộ nghiệm thu cần ảnh giữ lại có góc nhìn khác rõ rệt theo cách 1; việc này chưa làm (mục 7).

## 2. Trạng thái của một con số

PRD mục 2.2 định nghĩa bốn trạng thái: `MEASURE`, `BASELINE`, `PROPOSED_TARGET`, `LOCKED_ACCEPTANCE_THRESHOLD`. Áp dụng vào repo hiện tại:

- **Chưa có ngưỡng nào ở trạng thái khóa.** Mọi số trong `eval/results/` là `MEASURE` hoặc `BASELINE` trên một cảnh.
- [`evaluation_reference_v1.json`](../configs/product/evaluation_reference_v1.json) chứa PSNR/SSIM/LPIPS giữ lại của các job đã chạy, chỉ để Studio hiển thị khoảng tham chiếu, ghi rõ "không phải ngưỡng đạt". Studio chỉ đưa ra kết luận đạt/không đạt khi ngưỡng có trong repo.
- [`BENCHMARK_REPORT.md`](../eval/results/BENCHMARK_REPORT.md) (04/10/2026) ghi các "ngưỡng đạt" như PSNR > 20 dB, SSIM > 0.8, LPIPS < 0.3, sai số tỉ lệ < 5%, ATE RMSE < 0.1 m. Các ngưỡng này **không có trong protocol hay code**, và báo cáo chỉ dẫn hàng kết quả tốt nhất. Đọc báo cáo này như bản tóm tắt demo, không dùng làm tiêu chí nghiệm thu.
- Đề xuất ngưỡng theo trình tự: đo baseline trên bộ dữ liệu đã khóa → ghi `PROPOSED_TARGET` kèm lý do → chủ dự án duyệt → khóa trước lần chạy cuối. Không đổi ngưỡng sau khi thấy kết quả.

## 3. Các phép đo so với dữ liệu đối chứng

### 3.1 Quy ước chung

Danh mục mã phép đo và trạng thái nằm ở [`eval/protocols/BENCHMARKS.md`](../eval/protocols/BENCHMARKS.md); mỗi mã có protocol riêng trong `eval/protocols/`. Quy ước đầu ra:

- Dòng tổng hợp ghi thêm vào `eval/results/<mã>/<nhãn>.jsonl`, mỗi lần chạy một dòng.
- Bản ghi theo job là artifact bất biến `artifact://jobs/<job>/benchmark/<mã>/attempt-<n>.json`; lần chạy sau tạo `attempt` mới, không ghi đè.
- Nhãn chỉ gồm chữ thường, số, `.`, `_`, `-`.
- Lệnh chạy từ root checkout bằng Python của `.venv`. Đường dẫn `<ds>` là thư mục traversal TorWIC trên máy đo.

### 3.2 Chất lượng hình ảnh — `recon_visual_quality`

- **Đo:** PSNR, SSIM, LPIPS trên ảnh giữ lại 1/8 của video (mục 1.4, cách 2).
- **Cách làm:** [`eval/visual/brush_quality.py`](../eval/visual/brush_quality.py) huấn luyện lại Brush trên pose camera của job với `--eval-split-every 8`, đọc PSNR/SSIM từ log, tính LPIPS (vgg hoặc alex) bằng runtime scene. Bản ghi có thời gian huấn luyện, cấu hình Brush và tên máy.
- **Cần:** nạp `scripts/gpu/studio.env`; GPU. Xóa thư mục làm việc nặng sau khi chạy.
- **Lệnh và cách so sánh:** xem [`recon_visual_quality.md`](../eval/protocols/recon_visual_quality.md). Chỉ so hai lần chạy khi cùng ảnh đầu vào và cùng cấu hình.
- **Giới hạn:** chỉ nói về độ giống ảnh, không nói về hình học hay collision. Video có chứa ảnh giữ lại của dataset thì kết quả là số demo.

### 3.3 Pose camera và tỉ lệ mét — `recon_pose`, `metric_scale`, `metric_scale_proposal`

- **`recon_pose`** ([`trajectory_error.py`](../eval/pose/trajectory_error.py)): ATE sau khi khớp đồng dạng (cho phép xoay, dời, co giãn) với p50/p75/p90/max; RPE dịch chuyển (m) và xoay (độ) giữa các frame liên tiếp.
- **`metric_scale`** (cùng script, khi job có pose mét): tỉ lệ thật trên một đơn vị scene, `scale_error_percent`, ATE khớp cứng. Bản ghi có `distance_source` và `scale_is_independent`.
- **`metric_scale_proposal`** ([`scale_proposal_error.py`](../eval/pose/scale_proposal_error.py)): sai số của tỉ lệ do hệ thống tự đề xuất (MoGe-2 hoặc LiDAR) so với tỉ lệ đồng dạng SfM → đáp án. `--create` chạy bước đề xuất, cần `R2S_MOGE_PYTHON` và `R2S_MOGE_MODEL`; không có đề xuất thì script dừng, không tự điền số.

```bash
.venv/bin/python -m eval.pose.trajectory_error --job <job_id> --traversal <ds>/Aisle_CW \
  --calibration <ds>/calibrations.txt --start 100 --label <nhan> --out-dir eval/results
```

Hàng `metric_scale` trong `BENCHMARKS.md` có nhắc "sai số khoảng cách A/B"; chưa evaluator nào ở `eval/` tính số này. Sai số khoảng cách người dùng đo thước nằm ở bảng giá trị, mục 4.2.

### 3.4 Hình học bề mặt — `recon_geometry`

[`surface_error.py`](../eval/geometry/surface_error.py) lấy tâm Gaussian có độ đục ≥ 0.5, khớp đồng dạng theo camera, rồi so với `groundtruth_map.ply` trong phạm vi `--window` (mặc định 8 m) quanh đường đi camera:

| Trường | Ý nghĩa |
| --- | --- |
| `accuracy_m` | Từ điểm dựng tới bản đồ tham chiếu (trung bình, trung vị) |
| `completeness_m` | Từ bản đồ tham chiếu tới điểm dựng |
| `chamfer_m` | Tổng hai giá trị trung bình trên |
| `at_5cm`, `at_10cm` | Precision, recall, F-score ở ngưỡng khoảng cách 5 và 10 cm |

```bash
.venv/bin/python -m eval.geometry.surface_error --job <job_id> --traversal <ds>/Aisle_CW \
  --calibration <ds>/calibrations.txt --map <ds>/groundtruth_map.ply --start 100 \
  --label <nhan> --out-dir eval/results
```

File PLY phải ở dạng binary little-endian. Số đo dùng tâm Gaussian, chưa phải mesh collision của vật.

### 3.5 Sai số chấm điểm khi xác nhận mét — `metric_click_error`

[`click_error.py`](../eval/geometry/click_error.py) ước lượng sai số `e` khi người dùng chấm hai điểm để xác nhận mét. Script đo khoảng cách từ bề mặt Gaussian tới LiDAR trong dải 1–8 m quanh camera (chỉ tính vùng có ít nhất 5 điểm LiDAR trong 1 m), cộng sai số chấm lệch 2 và 5 pixel theo độ sâu, rồi gộp thành `e_estimate_m`. Giá trị `e` này đi vào dung sai kiểm C–D của bước xác nhận mét (xem [PIPELINE mục 6](PIPELINE.md)).

Cần job có gói LiDAR demo, nên kết quả luôn mang nhãn có hỗ trợ đáp án. Script chỉ ghi JSONL, không tạo bản ghi theo job như quy ước mục 3.1.

```bash
.venv/bin/python -m eval.geometry.click_error --job <job_id> --label <nhan> \
  --out eval/results/metric_click_error/<nhan>.jsonl
```

### 3.6 LiDAR odometry — `lidar_odometry`

Hai công cụ, hai mục đích:

- [`lidar_odometry_error.py`](../eval/pose/lidar_odometry_error.py) chấm **một** quỹ đạo ước lượng (artifact có checksum) với quỹ đạo tham chiếu TUM độc lập. Script từ chối dữ liệu sai khung, đơn vị lạ hoặc quan hệ đồng hồ không rõ; chỉ nội suy trong khoảng hở cho phép, không ngoại suy; ít hơn 2 cặp khớp thì trả `inconclusive`. Lệnh mẫu trong [`lidar_odometry.md`](../eval/protocols/lidar_odometry.md).
- [`lidar_odometry_benchmark.py`](../eval/pose/lidar_odometry_benchmark.py) chạy KISS-ICP trên mọi traversal có `traj_gt.txt`, báo drift %, ATE, RPE và sai số bản đồ so với `groundtruth_map.ply`. Dùng cấu hình mặc định của sản phẩm, trừ giới hạn số điểm.

```bash
.venv/bin/python -m eval.pose.lidar_odometry_benchmark --scenes <TorWIC_Raw_Scenes> \
  --map <groundtruth_map.ply> --odometry-python <python_cua_runtime> \
  --out eval/results/lidar_odometry_torwic.json
```

Protocol ghi rõ chưa có ngưỡng nghiệm thu cho tới khi đo trên traversal giữ lại.

### 3.7 Vật cản trên đường đi camera — `collision_path_clearance`

- [`path_clearance.py`](../eval/path/path_clearance.py) dựng lại mesh môi trường ở nhiều độ phân giải voxel (mặc định 0.10, 0.05, 0.025 m) rồi đếm vị trí camera mà khối robot (bán kính 0.461 m, cao 0.308 m theo [`geometry_v1.json`](../configs/product/geometry_v1.json)) chạm đỉnh mesh cao hơn 3 cm. Camera đã đi qua được, nên mỗi vị trí bị chặn là dấu hiệu "khối ma".
- [`lidar_clearance.py`](../eval/path/lidar_clearance.py) làm cùng phép thử trên lưới chiếm chỗ từ LiDAR, có tùy chọn dải sàn và khoảng cách tối thiểu.
- [`collision_quality.py`](../eval/path/collision_quality.py) đọc lại JSONL đã lưu, phân loại nguồn quỹ đạo (có hỗ trợ đáp án / khai báo / không ghi nguồn) và luôn ghi `independent_obstacle_recall_measured = false`.

Phép đo này **không dùng đáp án** và chỉ phát hiện vật cản thừa trên đường đã đi được. Nó không đo vật cản bị bỏ sót, không phải phép so đường đi Start–Goal của PRD (SM-04). Ngưỡng trong fixture tổng hợp ([`eval/fixtures/collision_quality.py`](../eval/fixtures/collision_quality.py)) chỉ để kiểm code, không phải ngưỡng sản phẩm. Chi tiết và kết quả: [`collision_path_clearance.md`](../eval/protocols/collision_path_clearance.md). Protocol có nhắc báo thêm số vị trí bị chặn ở độ cao 0.10 và 0.15 m; `path_clearance.py` chưa tính hai số này.

### 3.8 Tách vật trên dữ liệu tổng hợp

[`segmentation_quality.py`](../eval/object/segmentation_quality.py) chạy 8 case tổng hợp ([`eval/fixtures/segmentation.py`](../eval/fixtures/segmentation.py)) qua hai cách gộp vật (`legacy` và `multiview_v1`), ghép một-một theo IoU và báo độ đầy đủ, độ sạch, lỗi tách, lỗi gộp, rò sang nền. Đầu ra ghi `source = annotated_synthetic`, `real_scene_acceptance = false`.

```bash
.venv/bin/python -m eval.object.segmentation_quality --output /duong/dan/ket_qua.json
```

Đây không phải `object_coverage` (SM-05) trên cảnh thật; repo chưa có nhãn vật thủ công cho cảnh thật nào.

### 3.9 Thời gian xử lý — `pipeline_runtime`

Worker tự ghi bản ghi thời gian sau mỗi lần chạy job ([`benchmark.py`](../src/services/orchestration/benchmark.py)). [`scripts/benchmark/collect.py`](../scripts/benchmark/collect.py) gom các bản ghi đó vào JSONL:

```bash
.venv/bin/python -m scripts.benchmark.collect --all --label <nhan> [--gpu-hourly-usd <gia>]
```

Đầu ra mặc định `eval/results/pipeline_runtime/<nhan>.jsonl`; thư mục này chưa có trong repo. Quy tắc so sánh (cùng checksum đầu vào, số frame, GPU) và mục tiêu tối ưu chưa đạt nằm ở [`pipeline_runtime.md`](../eval/protocols/pipeline_runtime.md).

### 3.10 Phép dò phụ

| Công cụ | Mục đích | Ghi chú |
| --- | --- | --- |
| [`colmap_fusion_benchmark.py`](../eval/pose/colmap_fusion_benchmark.py) | Kiểm giả thuyết khung của `traj_gt` khi ghép COLMAP với LiDAR | File kết quả E2 được chép tay từ console, không tái lập được |
| [`floor_tilt_probe.py`](../eval/pose/floor_tilt_probe.py) | Đo độ nghiêng sàn trong khung cảm biến, khung thế giới và bản đồ | Chỉ hợp lệ với TorWIC (giả định cảm biến gần thẳng đứng) |
| [`preview_readiness.py`](../scripts/benchmark/preview_readiness.py) | Đo thời gian kiểm preview trên dữ liệu giả cục bộ | Không gồm DB, HTTP, GPU; không có kết quả lưu |

## 4. Bảng giá trị theo scene

Phần này đo giá trị cho người làm bài thử robot, dùng số đo thật do người dùng nhập trong Studio, không dùng dataset.

### 4.1 Khai báo số đo thật

Trong tab kiểm tra vật, panel Benchmark cho người dùng khai báo `BenchmarkTruth` ([`ground_truth.py`](../src/services/orchestration/value/ground_truth.py)):

| Trường | Nội dung |
| --- | --- |
| `include_in_benchmark` | Có đưa scene vào bảng tổng hợp hay không; mặc định không |
| `data_source` | `self_capture`, `hf_room` hoặc `synthetic` |
| `robot` | Chiều rộng, biên an toàn, dải chiều cao |
| `distances` | Tối đa 32 đoạn đo thước: hai điểm trên scene và độ dài thật (m) |
| `gaps` | Khe hở giữa hai điểm, có đi qua được trong thực tế hay không, kèm bố trí A/B |
| `key_obstacle_ids`, `layouts`, `manual_baseline_minutes`, `l4` | Vật cản chính, revision của từng bố trí, thời gian làm tay để so, khai báo mức L4 |

Tọa độ theo khung chuẩn của scene (mét, Z hướng lên, sàn tại z = 0). Lưu với số phiên bản; lưu đè bản cũ hơn bị từ chối (HTTP 409).

### 4.2 Phép đo trên scene

[`measure.py`](../src/services/orchestration/value/measure.py) là các hàm thuần, không tự đọc đáp án:

- **Sai số khoảng cách:** độ dài trên scene so với độ dài đo thước, theo mét và phần trăm.
- **Khe hở:** bắn tia theo các độ cao trong dải chiều cao robot, bước 5 cm. Khe đi được khi rộng ít nhất `chiều rộng robot + 2 × biên an toàn`. So với khai báo cho ra `ok`, `missed_obstacle` (scene cho qua, thực tế không) hoặc `false_obstacle` (scene chặn, thực tế qua được).
- **Nhất quán khi di chuyển vật:** vật được coi là đã dời khi lệch hơn 1 cm hoặc 1°; vùng chân cũ không còn tam giác môi trường và collider ở vị trí mới phải có.

### 4.3 Scorecard và mức L0–L4

[`scorecard.py`](../src/services/orchestration/value/scorecard.py) tổng hợp: thời gian thao tác tay trước và sau khi scene sẵn sàng, thời gian máy, giờ GPU, chi phí, số lần can thiệp, kết quả khe hở và khoảng cách, thời gian sửa → thử lại, mức sẵn sàng. Mỗi số có nguồn `measured`, `declared` hoặc `unavailable`; thiếu dữ liệu thì để trống, không ghi 0. Chi phí là `declared` vì phụ thuộc giá GPU khai báo.

| Mức | Điều kiện |
| --- | --- |
| L1 | Tỉ lệ mét đã xác nhận và geometry vật sẵn sàng |
| L2 | Có khai báo số đo thật; vật cản chính có collider; đã đi Walk trên revision hiện tại; bố trí A không có khe bị bỏ sót |
| L3 | Có lần kiểm định Isaac được chọn, hoàn tất và PASS |
| L4 | Người dùng tự khai báo |

Thời gian thao tác tay được Studio gửi theo lô (`/value-events/operator-time`, tối đa 300 giây mỗi lô, không chồng lấn) và phiên Walk (tối đa 2 giờ).

### 4.4 Trang `/benchmark` và xuất file

Trang `/benchmark` lấy job mới nhất của mỗi project có bật `include_in_benchmark`, hiển thị số scene, trung vị thời gian thao tác và thời gian máy, kết quả khe hở, số scene đạt L2/L3, trung vị thời gian làm tay; lọc theo nguồn dữ liệu. API:

| Route (dưới `/api/v1`) | Trả về |
| --- | --- |
| `GET/PUT /jobs/{id}/benchmark-truth` | Đọc, lưu khai báo số đo thật |
| `GET /jobs/{id}/value-metrics` (`.md`, `.csv`) | Scorecard của một scene |
| `GET /value-metrics/benchmark` (`.md`, `.csv`) | Bảng tổng hợp các scene |

Repo chưa có bảng giá trị nào được nghiệm thu trên cảnh thật; trạng thái tổng hợp sẽ nằm ở `docs/STATUS.md` (lượt chuẩn hóa kế tiếp).

## 5. Tự kiểm trong Studio

`GET /jobs/{id}/evaluation` và `/evaluation/report.md` ([`api/studio/evaluation.py`](../src/api/studio/evaluation.py)) trả bảng tự kiểm của job, dựa trên số liệu chính job tạo ra (chất lượng ảnh giữ lại, độ phủ, trạng thái geometry…). Khối "So với dữ liệu đối chứng" đọc bản ghi `attempt` mới nhất của `recon_pose`, `metric_scale`, `recon_geometry`, `metric_scale_proposal` nếu evaluator ở mục 3 đã chạy cho job đó, và đánh dấu nguồn là `reference`. Khoảng tham chiếu lấy từ `evaluation_reference_v1.json` (mục 2). Bảng này giúp người dùng tìm điểm yếu; nó không phải `EvaluationReport` và không đủ để nghiệm thu.

## 6. Kết quả đã lưu và cách đọc

Mọi kết quả dưới đây là cảnh `Aisle_CW` hoặc traversal TorWIC, chạy trên máy cục bộ (T2000) hoặc CPU, ngày 30/09–11/10/2026. Số cụ thể đọc trực tiếp trong file, không chép sang tài liệu khác.

| Kết quả | File | Cách đọc |
| --- | --- | --- |
| Chất lượng ảnh giữ lại | `eval/results/recon_visual_quality/` | Ba job, giữ lại 1/8 trong cùng video; số demo |
| Pose, tỉ lệ, đề xuất tỉ lệ | `eval/results/recon_pose/`, `metric_scale/` | Job có LiDAR demo dùng chính `traj_gt` nên không độc lập; đề xuất MoGe-2 có hai lần đo với kết quả khác nhau |
| Hình học bề mặt | `eval/results/recon_geometry/` | Recall ở 10 cm rất thấp; tâm Gaussian không phải bề mặt kín |
| Sai số chấm điểm | `eval/results/metric_click_error/` | Một job; chỉ khoảng một nửa vùng có LiDAR phủ |
| Vật cản trên đường camera | `eval/results/collision_path_clearance/` | Proxy không gian trống; hàng dùng `traj_gt` có hỗ trợ đáp án |
| LiDAR odometry | `eval/results/lidar_odometry_torwic*.json`, [`LIDAR_ODOMETRY_BENCHMARK.md`](../eval/results/LIDAR_ODOMETRY_BENCHMARK.md) | Nhiều traversal; dùng để chọn cấu hình, không phải nghiệm thu trên traversal giữ lại |
| COLMAP + LiDAR, độ nghiêng sàn | `colmap_fusion_*.json`, `floor_tilt_torwic.json` | Phép dò giả thuyết; E2 không tái lập được |
| Hồ sơ chất lượng ảnh REC-02 | `rec02_aisle_cw_quality_probe.json` | Trạng thái `PROPOSAL_NOT_LOCKED` |
| Tóm tắt 04/10 | [`BENCHMARK_REPORT.md`](../eval/results/BENCHMARK_REPORT.md) | Có ngưỡng tự đặt không có nguồn (mục 2); một số số liệu không có file gốc |

Khi trích một số trong báo cáo hay pitch, ghi kèm: file nguồn, job, ngày, máy, dữ liệu có hỗ trợ đáp án hay không, và trạng thái theo mục 2.

## 7. Những gì còn thiếu để nghiệm thu

| Thiếu | Hệ quả |
| --- | --- |
| Bộ dữ liệu nghiệm thu đã khóa (input, split, vật cản mục tiêu, kích thước chuẩn, geometry độc lập, robot, 5 cặp Start–Goal kèm nhãn, cấu hình; danh sách ở PRD mục 10.1) | Chưa đánh giá được SM-03, SM-04, AC-03, AC-08 theo PRD |
| Bộ chạy tạo `EvaluationReport` | Model có trong [CONTRACTS mục 8.4](CONTRACTS.md) nhưng chưa code nào tạo; `ReleaseManifest` loại `BENCHMARK` hoặc `LOCKED_MVP_ACCEPTANCE` chưa có nguồn checksum hợp lệ |
| So đường đi Start–Goal với nhãn (`path_validation`) và độ phủ vật (`object_coverage`) | Chưa có code; các evaluator mục 3.7 và 3.8 không thay thế được |
| Tách ảnh giữ lại theo góc nhìn khác rõ | Số ảnh hiện tại thiên lạc quan (mục 1.4) |
| Ngưỡng ở trạng thái khóa | Không có kết luận đạt/không đạt nào hợp lệ |
| Kết quả ngoài TorWIC | PRD mục 10.1 yêu cầu cảnh trong nhà thực và case có kiểm soát; cần chủ dự án chốt bộ cảnh |
| Ghi chép thời gian làm tay công bằng | SM-06 chỉ có công cụ ghi, chưa có phép so trên cảnh thật |

## 8. Chạy lại kiểm tra của evaluator

Các test dưới đây kiểm logic evaluator, bảng giá trị và model hợp đồng trên dữ liệu giả; chúng không chạy phép đo thật.

```bash
APP_ENV=test LLM_PROVIDER=openai OPENAI_API_KEY=test-key .venv/bin/python -m pytest \
  tests/test_reconstruction/test_reference_evaluators.py \
  tests/test_reconstruction/test_collision_quality.py \
  tests/test_reconstruction/test_lidar_odometry_evaluation.py \
  tests/test_scene/test_segmentation_quality.py \
  tests/test_scene/test_membership_refinement.py \
  tests/test_orchestration/test_evaluation.py \
  tests/test_orchestration/test_value_scorecard.py \
  tests/test_orchestration/test_value_measure.py \
  tests/test_orchestration/test_value_events.py \
  tests/test_orchestration/test_benchmark_truth.py \
  tests/test_orchestration/test_pipeline_timing.py \
  tests/test_api/test_value_routes.py \
  tests/test_contracts/test_validation.py \
  tests/test_contracts/test_release.py -q
```

```bash
cd frontend && npx vitest run tests/benchmark-page.test.tsx tests/benchmark-panel.test.tsx \
  tests/value-card.test.tsx tests/value-api.test.ts tests/evaluation-card.test.tsx
```

Chưa có test cho `brush_quality`, `click_error`, `lidar_clearance`, `lidar_odometry_benchmark`, `colmap_fusion_benchmark`, `floor_tilt_probe`, `collect.py` và `preview_readiness`. Sửa các script này cần chạy lại trên dữ liệu thật và ghi kết quả mới.

## 9. Nguồn

- Evaluator: [`eval/`](../eval/), protocol trong [`eval/protocols/`](../eval/protocols/), kết quả trong [`eval/results/`](../eval/results/).
- Bảng giá trị: [`src/services/orchestration/value/`](../src/services/orchestration/value/), [`src/api/studio/value.py`](../src/api/studio/value.py), [`frontend/src/features/studio/value/`](../frontend/src/features/studio/value/).
- Tự kiểm: [`src/services/orchestration/evaluation/`](../src/services/orchestration/evaluation/), [`evaluation_reference_v1.json`](../configs/product/evaluation_reference_v1.json).
- Lớp dữ liệu và hợp đồng: [`artifacts.py`](../src/models/contracts/artifacts.py), [`validation.py`](../src/models/contracts/validation.py), [`release.py`](../src/models/contracts/release.py).
- Chuẩn bị dataset: [`scripts/torwic/`](../scripts/torwic/), [`scripts/demo/`](../scripts/demo/).
- Tài liệu cũ đã đối chiếu: [`archived/DATASET_PLAYBOOK.md`](archived/DATASET_PLAYBOOK.md), `docs/execution/TEAM_EXECUTION_CONTRACT.md` chương 5, `docs/plans/active/2026-10-02-evaluation-system.md`.
