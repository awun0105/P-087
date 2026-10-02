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
| `recon_visual_quality` | Chất lượng ảnh render 3DGS | PSNR, SSIM, LPIPS-VGG trên mỗi ảnh thứ 8 của chính video (7k…30k bước) | Ảnh của job (video chỉ train split) | `eval/visual/brush_quality.py` | **Có** — chạy tay |
| `recon_pose` | Độ chính xác quỹ đạo camera | ATE/RPE so với `traj_gt` | Evaluation-only GT | `eval/pose/` | Chưa |
| `recon_geometry` | Độ chính xác hình học | Chamfer, F-score so với GT `.ply` | Evaluation-only GT | `eval/geometry/` | Chưa |
| `metric_scale` | Sai số tỉ lệ mét | sai số scale %, sai số khoảng cách A/B (m) | So với LiDAR/GT (ADR 0001) | `eval/geometry/` | Chưa |
| `browser_render` | Trình duyệt có mượt không | thời gian tải scene, FPS theo LOD/thiết bị | Client gửi lên | `eval/visual/` | Chưa (cần LOD) |
| `workflow_time` | SM-06: thời gian thao tác tay vs dùng công cụ | phút hands-on, số bước thủ công | Đo tay | `eval/protocols/` | Chưa |
| `metric_click_error` | REC-06: `e` = sai số một lần click trên 3DGS | khoảng cách bề mặt 3DGS→LiDAR (vùng LiDAR phủ), lệch k px quy ra mét | Căn chỉnh quỹ đạo GT-assisted (chỉ dataset demo) | `eval/geometry/click_error.py` | **Có** — chạy tay |
| `collision_path_clearance` | REC-05: collision mesh có chặn giả đường robot đã đi | % vị trí camera bị mesh chiếm capsule, theo mức voxel | Camera canonical + mesh REC-05 (không GT) | `eval/path/path_clearance.py` | **Có** — chạy tay |
| `path_validation` | SM-04: va chạm/đường đi | CLEAR/BLOCKED khớp nhãn 5/5 | EX-SIM | `eval/path/` | Chưa |
| `object_coverage` | SM-05: độ phủ candidate object | recall theo danh sách gán nhãn | EX-SCENE | `eval/object/` | Chưa |

Dữ liệu evaluation-only (GT, split giữ lại) chỉ dùng trong evaluator, không bao giờ vào runtime
(`docs/DATASET_PLAYBOOK.md`).

## Chỉ số tự kiểm trong Studio (không phải benchmark)

Bảng đánh giá của từng scene trong Studio (`src/services/orchestration/evaluation/`, STUDIO_UX_SPEC D-16) đo từ chính
artifact của job, không dùng GT, nên có cho cả dữ liệu người dùng. Nó không thay các benchmark ở trên: benchmark trả lời
"hệ thống chính xác tới đâu trên dataset đối chứng", bảng tự kiểm trả lời "scene này có dấu hiệu sai không".

Một chỉ số dùng chung phép đo với benchmark: "vị trí camera đã đi qua bị mesh chặn" là phép kiểm của
`collision_path_clearance` áp lên mesh đã publish của job. Đối chiếu ngày 02/10/2026 trên `job-ac2bfd924cc6`: bảng tự
kiểm cho 33/50 vị trí, 224.745 tam giác — trùng dòng 0,05 m của `eval/results/collision_path_clearance/`.
