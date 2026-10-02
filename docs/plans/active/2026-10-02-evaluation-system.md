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

## Pha 2 — Đối chứng trên TorWIC (CHƯA LÀM)

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

## Next step

Pha 2 mục 1–2, dùng dữ liệu đã có trên ổ ngoài (`/media/usb/AI20K/TorWIC SLAM Dataset`).
