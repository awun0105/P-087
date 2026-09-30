# Mục lục benchmark

Mỗi loại benchmark có **mã riêng**; mã là tên thư mục kết quả và tên giao thức.

| Quy ước | Đường dẫn |
|---|---|
| Giao thức (đo gì, đơn vị, cách chạy) | `eval/protocols/<mã>.md` |
| Kết quả tổng hợp | `eval/results/<mã>/<nhãn>.jsonl` — mỗi dòng một lần chạy |
| Bản ghi theo job (artifact bất biến) | `artifact://jobs/<job>/benchmark/<mã>/attempt-<n>.json` |

**Nhãn** gom các lần chạy cùng mục đích: dataset + cấu hình + máy, ví dụ `aisle-cw-demo`,
`local-t2000`, `vast-4090-30k`. Chỉ chữ thường, số, `.`, `_`, `-`. Số liệu chưa đo để trống;
không điền ước đoán như kết quả.

| Mã | Đo gì | Chỉ số chính | Nguồn / ranh giới | Thư mục evaluator | Trạng thái |
|---|---|---|---|---|---|
| `pipeline_runtime` | Thời gian, chi phí xử lý một job | giây từng stage, tổng giây, kích thước input/SOG, GPU, $ ước tính | Product runtime (journal job) | `src/services/orchestration/benchmark.py` | **Có** — worker tự ghi |
| `recon_visual_quality` | Chất lượng ảnh render 3DGS | PSNR, SSIM, LPIPS trên frame giữ lại | Evaluation-only split | `eval/visual/` | Chưa |
| `recon_pose` | Độ chính xác quỹ đạo camera | ATE/RPE so với `traj_gt` | Evaluation-only GT | `eval/pose/` | Chưa |
| `recon_geometry` | Độ chính xác hình học | Chamfer, F-score so với GT `.ply` | Evaluation-only GT | `eval/geometry/` | Chưa |
| `metric_scale` | Sai số tỉ lệ mét | sai số scale %, sai số khoảng cách A/B (m) | So với LiDAR/GT (ADR 0001) | `eval/geometry/` | Chưa |
| `browser_render` | Trình duyệt có mượt không | thời gian tải scene, FPS theo LOD/thiết bị | Client gửi lên | `eval/visual/` | Chưa (cần LOD) |
| `workflow_time` | SM-06: thời gian thao tác tay vs dùng công cụ | phút hands-on, số bước thủ công | Đo tay | `eval/protocols/` | Chưa |
| `collision_path_clearance` | REC-05: collision mesh có chặn giả đường robot đã đi | % vị trí camera bị mesh chiếm capsule, theo mức voxel | Camera canonical + mesh REC-05 (không GT) | `eval/path/path_clearance.py` | **Có** — chạy tay |
| `path_validation` | SM-04: va chạm/đường đi | CLEAR/BLOCKED khớp nhãn 5/5 | EX-SIM | `eval/path/` | Chưa |
| `object_coverage` | SM-05: độ phủ candidate object | recall theo danh sách gán nhãn | EX-SCENE | `eval/object/` | Chưa |

Dữ liệu evaluation-only (GT, split giữ lại) chỉ dùng trong evaluator, không bao giờ vào runtime
(`docs/DATASET_PLAYBOOK.md`).
