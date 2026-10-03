# Execution Plan: Hệ thống đánh giá (tự kiểm cho mọi scene + đối chứng trên dataset)

## Status

IN_PROGRESS — pha 1 xong (02/10/2026). Owner: Quân (Tech Lead / EX-REC).

## Outcome

Hai bộ chỉ số, không trộn lẫn:

- **Tự kiểm** (mọi scene, kể cả dữ liệu người dùng): đo từ chính artifact của job, hiện trong Studio, xuất báo cáo.
- **Đối chứng** (chỉ dataset TorWIC): so với ground truth, chạy bằng evaluator ở `eval/`, ghi theo
  `eval/protocols/BENCHMARKS.md`.

Nguyên tắc: mỗi chỉ số phải trả lời một câu hỏi về việc scene có dùng được để mô phỏng không; số chưa đo ghi "Chưa đo",
không ước lượng; nhãn đạt/không đạt chỉ gán khi ngưỡng đã có trong repo.

## Pha 1 — Bảng tự kiểm trong Studio (XONG)

- `src/services/reconstruction/quality.py`: cổng read-only đọc chỉ số từ artifact REC.
- `src/services/orchestration/evaluation/`: `evaluate_job` dựng 7 nhóm (video, pose, 3DGS, tỉ lệ mét, hình học, vật
  thể, hệ thống); `evaluation_markdown` xuất báo cáo.
- API `GET /jobs/{id}/evaluation`, `GET /jobs/{id}/evaluation/report.md`; UI: panel của màn xem bước + thẻ ở tab Kiểm
  tra & duyệt (STUDIO_UX_SPEC D-16).
- Chạy cả local lẫn deployment có kho file: artifact đọc qua `runtime_resolver.require` (tự tải từ R2), phép kiểm mesh
  dùng numpy và nhớ theo checksum.
- VERIFIED: `pytest tests/ -q` 1188 passed / 40 skipped; vitest 188; `next build`; stack thật trả bảng cho cả 5 scene.
  Đối chiếu độc lập: chỉ số mesh của `job-ac2bfd924cc6` (33/50, 224.745 tam giác) trùng benchmark
  `collision_path_clearance` mức 0,05 m; độ dài track COLMAP tính lại (6,66) trùng header `points3D.txt`.

### Phát hiện từ số liệu thật (chưa xử lý)

- Mesh va chạm chặn nhầm 50% (`job-1bb733ae40ad`) và 66% (`job-ac2bfd924cc6`) vị trí camera đã đi qua.
- Phép kiểm C–D của hai scene trên cho sai lệch đúng 0,0 cm tới 15 chữ số. INFERENCE: số đo C–D được sinh từ chính
  scene (luồng điểm mẫu), không phải số đo độc lập, nên phép kiểm này chưa kiểm được gì ở hai scene đó.
- Lần gọi đầu cho scene có mesh mất khoảng 2–5 giây (đọc GLB); các lần sau lấy từ bộ nhớ đệm.

## Pha 2 — Đối chứng trên TorWIC (mục 1, 2, 3, 5 XONG 03/10/2026; mục 4 chưa)

1. `recon_pose`: ATE/RPE so với `traj_gt.txt`.
2. `recon_geometry`: Chamfer, Precision/Recall/F-score 5 cm và 10 cm so với `groundtruth_map.ply`.
3. `metric_scale`: sai số khoảng cách A–B, C–D so với LiDAR.
4. Đối chứng yếu cho tách vật thể bằng `segmentation_greyscale_left` (mask do model khác dự đoán, không phải GT).
5. Evaluator publish bản ghi theo job (`artifact://jobs/<job>/benchmark/<mã>/…`) để bảng trong Studio hiện thêm khối
   "So với dữ liệu đối chứng" cho scene dataset.

## Pha 3 — Chỉ số còn thiếu của bảng tự kiểm (CHƯA LÀM)

- PSNR/SSIM/LPIPS trong lúc train thật: cần owner chốt việc giữ lại ảnh không train (mặc định bật hay không).
- Kiểm xem chỉ số tự kiểm có dự báo được độ chính xác thật không (cần pha 2 và nhiều lượt chạy hơn), rồi mới đặt ngưỡng
  cảnh báo cho các chỉ số hiện chưa có ngưỡng.
- Ghi `eval/results/report.md` từ các bản ghi.

### Pha 2 — đã làm (03/10/2026)

- `eval/reference/torwic.py` (pose ground truth, ghi bản ghi theo job), `eval/pose/trajectory_error.py`
  (`recon_pose` + `metric_scale`), `eval/geometry/surface_error.py` (`recon_geometry`); giao thức
  `eval/protocols/reference_torwic.md`.
- Bảng đánh giá: khối "So với dữ liệu đối chứng" (chỉ khi job có bản ghi); nhóm "Tỉ lệ mét" của job LiDAR hiện độ
  lệch pose ↔ quỹ đạo thay cho phép kiểm C–D (C–D của luồng này sinh từ chính căn chỉnh nên không độc lập).
- VERIFIED trên `job-101e9b56344c`: số ở `eval/results/{recon_pose,metric_scale,recon_geometry}/`.
- Chấm hai job chỉ có video trong kho thật (`job-ac2bfd924cc6`, `job-1bb733ae40ad`): ATE 6,8 cm trên 16,7 m; đề xuất tỉ
  lệ tự động MoGe-2 lệch −0,24% và −0,11% (`eval/pose/scale_proposal_error.py`, bước 4 của H6). Chi tiết ở
  `eval/protocols/reference_torwic.md`.
- Chưa làm: đối chứng tách vật thể (mục 4); mới có một video (Aisle_CW) nên chưa đặt ngưỡng.

## Next step

Chấm lại trên các lượt chạy đủ bước ở máy thuê GPU (cả job chỉ có video lẫn job có LiDAR của cùng đoạn) để có số độc
lập; rồi mới xét ngưỡng cảnh báo (pha 3).

## Decision (owner, 02/10/2026): để dành ảnh cho PSNR/SSIM/LPIPS

Owner chốt: **có** để dành ảnh để đo chất lượng dựng hình ("phải có metric để đo lường kết quả"). Áp dụng cho pha 3.
PROPOSAL cách làm, chưa code: giữ lại 1/8 số frame đã trích (cách làm quen thuộc của các bộ dữ liệu NeRF/3DGS), không
đưa vào train; COLMAP vẫn dựng pose cho mọi frame để có pose của ảnh giữ lại. Hệ quả: số ảnh train giảm 12,5%. Cần ghi
vào cấu hình xử lý của job (đổi `config_checksum`) và hiện trong scorecard là số đo trên ảnh giữ lại.

### Implementation (02/10/2026) — VALIDATING

Làm đúng đề xuất trên, dùng cơ chế eval split có sẵn của Brush (cùng giao thức `eval/protocols/recon_visual_quality.md`):

- `configs/product/processing_presets_v1.json`: `fixed.brush.eval_split_every = 8` → mọi job mới giữ lại mỗi ảnh thứ
  8 (theo thứ tự tên trong số ảnh COLMAP đã đăng ký). Checksum của presets đổi nên `config_checksum` của job mới khác
  job cũ; job cũ chạy lại bằng cấu hình đã lưu của nó (không có khoá này) vẫn train trên mọi ảnh.
- `BrushConfig.eval_split_every` (tuỳ chọn). Trường **không xuất hiện trong JSON khi không dùng**, nên checksum của
  cấu hình và của mọi `BrushVisualArtifact` đã publish giữ nguyên (có test khoá checksum cũ).
- `brush_command`: thêm `--eval-split-every N --eval-every <tổng bước> --eval-save-to-disk` → Brush chấm một lần ở
  bước cuối. `VisualProcess.qualify` kiểm runtime có các cờ này; thiếu thì dừng với `BRUSH_CLI_UNSUPPORTED`.
- `BrushVisualArtifact`: `training_frame_ids` chỉ còn ảnh thật sự train; thêm `held_out_frame_ids` và
  `holdout_quality` (PSNR, SSIM, LPIPS, số ảnh, bước). Resolver kiểm train + giữ lại = đúng tập ảnh đã đăng ký. Nếu Brush
  lưu ảnh chấm khác với danh sách ghi nhận thì bước dựng hình dừng (không còn biết ảnh nào đã train).
- LPIPS-VGG: `src/services/reconstruction/adapters/lpips_runner.py` (chuyển từ `eval/visual/lpips_score.py`, dùng chung
  với benchmark), chạy bằng `REC04_BRUSH_LPIPS_PYTHON` (runtime scene). Không cấu hình, thiếu trọng số hoặc lỗi → LPIPS
  ghi "chưa đo"; không làm hỏng job.
- Bảng tự kiểm: ba dòng PSNR / SSIM / LPIPS "trên ảnh không train", kèm số ảnh giữ lại; scene cũ ghi rõ lý do chưa đo.
  Chưa gán ngưỡng đạt/không đạt (repo chưa có ngưỡng).
- INFERENCE cần kiểm bằng lượt chạy thật: quy tắc chọn ảnh giữ lại của Brush là "chỉ số chia hết cho N theo thứ tự
  tên" (suy từ bản ghi benchmark: 50 ảnh, N = 8 → 7 ảnh chấm). Code tự đối chiếu với tên ảnh Brush lưu ra và dừng nếu lệch.
- Hệ quả đã biết: số ảnh train giảm 12,5% (điểm tuyệt đối thấp hơn một chút so với train trên mọi ảnh); bước dựng hình
  thêm một lượt render các ảnh giữ lại và (nếu bật) LPIPS.

