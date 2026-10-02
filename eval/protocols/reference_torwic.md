# Đối chứng trên TorWIC: `recon_pose`, `metric_scale`, `recon_geometry`

**Câu hỏi:** scene dựng từ một video của TorWIC đúng tới đâu so với ground truth của dataset.

**Ranh giới dữ liệu:** `traj_gt.txt` và `groundtruth_map.ply` là evaluation-only (DATASET_PLAYBOOK). Evaluator đọc job
đã chạy xong qua registry của deployment; không có đường nào đưa ground truth vào runtime sản phẩm.

**Ghép frame:** frame `i` của video là ảnh `start + i` của traversal (video demo ghép từ ảnh liên tiếp). Truyền đúng
`--start` của video; sai thì ATE tăng vọt.

## Chạy

Cần biến môi trường của deployment (`DATABASE_URL`, `ARTIFACT_ROOT`, … như API đang dùng) để đọc job.

```bash
python -m eval.pose.trajectory_error --job <job-id> --traversal "<dataset>/Aisle_CW" \
    --calibration "<dataset>/calibrations.txt" --start <start> --label <nhãn> --out-dir eval/results
python -m eval.geometry.surface_error --job <job-id> --traversal "<dataset>/Aisle_CW" \
    --calibration "<dataset>/calibrations.txt" --map "<dataset>/groundtruth_map.ply" --start <start> \
    --label <nhãn> --out-dir eval/results
```

Mỗi lệnh ghi bản ghi theo job (`artifact://jobs/<job>/benchmark/<mã>/attempt-<n>.json`, Studio hiện lượt mới nhất) và
một dòng vào `eval/results/<mã>/<nhãn>.jsonl`.

## Chỉ số

| Mã | Chỉ số | Cách tính |
| --- | --- | --- |
| `recon_pose` | ATE (RMSE, trung vị, p90, lớn nhất; mét) | Khớp đồng dạng tâm camera của job vào ground truth, đo khoảng cách còn lại |
| `recon_pose` | RPE dịch chuyển (mét), RPE góc quay (độ) | Giữa hai frame đã đăng ký liên tiếp, sau khi đưa về hệ ground truth |
| `metric_scale` | Sai số tỉ lệ (%) | `1/scale − 1` của phép đồng dạng pose hệ mét → ground truth; âm = scene nhỏ hơn thật |
| `metric_scale` | ATE khớp cứng (mét) | Như ATE nhưng không cho đổi tỉ lệ |
| `recon_geometry` | Accuracy, completeness, Chamfer (mét) | Tâm Gaussian có độ đục ≥ 0,5 ↔ bản đồ chuẩn, trong 8 m quanh đường camera |
| `recon_geometry` | Precision / Recall / F-score ở 5 cm và 10 cm | Tỉ lệ điểm có khoảng cách dưới ngưỡng, hai chiều |

## Đọc số cho đúng

- Job dựng từ **gói LiDAR có quỹ đạo ground truth** đã dùng chính quỹ đạo này (`job_used_this_trajectory: true`):
  `recon_pose` và `metric_scale` khi đó đo mức bám quỹ đạo, không phải độ chính xác độc lập. Muốn số độc lập, chấm job
  chỉ có video của cùng đoạn.
- Completeness và recall là cận dưới: bản đồ chuẩn có cả chỗ camera không nhìn thấy.
- Mọi số hình học đã gồm sai số của phép khớp (`alignment_rms_m`) và mật độ bản đồ (`reference_spacing_p50_m`).
- Chưa có ngưỡng đạt/không đạt nào được chấp nhận cho các chỉ số này; Studio chỉ hiện số.

## Kết quả đã đo

`aisle-cw-100-lidar-job-local` — job `job-101e9b56344c` (Aisle_CW frame 100–599, 100 frame, Brush ở mức preview trên
máy local, dựng bám quỹ đạo ground truth): ATE 13,2 cm (RMSE), RPE 3,5 cm và 0,55° (trung vị), sai số tỉ lệ 0,00%
(không độc lập); bề mặt lệch bản đồ chuẩn 14,6 cm (trung vị), precision 32,9% và recall 2,3% ở 10 cm với 8.056 điểm.
Recall thấp chủ yếu vì bản 3DGS mức preview thưa; cần chấm lại trên lượt train đủ bước.
