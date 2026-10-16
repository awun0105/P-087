# Review T-043

Verdict: CHANGES REQUESTED (1 sửa nhỏ)

Audit: 12 commit `73fcfb46` → `5d974325`. Đọc giới hạn mới ở `colmap_runtime.py`, `brush_runtime.py`, `src/config.py`,
`runner._expected_limit` / `_run_tool`, file mẫu env. Chạy `test_process_stall.py`, `test_expected_duration.py`,
`test_rec03_colmap.py`, `test_rec04_brush.py`: 88 PASS, 5 skip. Full backend engineer báo 3935 PASS.

Đã kiểm, đúng: bộ canh tiến độ dùng chung, mã `PROCESS_STALLED` riêng; hạn tự tính `max(10 phút, 3 × ước)` chặn bởi giới hạn cố
định, thiếu số đo giữ hành vi cũ; trần giờ GPU tắt mặc định; câu thông báo tiếng Việt cho ba mã mới. Ngưỡng treo COLMAP 600 s có
bằng chứng (khoảng im lặng dài nhất 16,5 s trên 10 log thật), chấp nhận lệch plan.

## Required changes

### 1. Giới hạn bao ngoài của bước preview nhỏ hơn tổng giới hạn bên trong
`src/config.py:72` `product_preview_timeout_seconds` vẫn 21600 s (6 giờ); `docker_entrypoint.sh:56` và
`scripts/gpu/studio.env.example:50` cũng 21600. Bước preview chạy COLMAP rồi Brush trong một lần `_run_tool`; sau T-043 hai giới
hạn bên trong là 14400 + 21600 = 36000 s. Lớp ngoài vì vậy thành giới hạn thật: scene lớn có COLMAP 4 giờ + Brush 3 giờ, cả hai
vẫn tiến triển, bị cắt ở giờ thứ 6 với lỗi hết giờ chung — đúng điều task muốn tránh.

Sửa: nâng mặc định `product_preview_timeout_seconds` lên 36000 s (bằng tổng hai lưới bên trong) ở cả ba chỗ trên, cùng
`deploy/studio/*.env.example` nếu có (sinh lại bằng `python -m scripts.studio.deploy_env render --examples`). Test (đỏ trên code
cũ): mặc định của `product_preview_timeout_seconds` ≥ tổng mặc định `ColmapRuntimeSettings.timeout_seconds` +
`BrushRuntimeSettings.timeout_seconds`. Kiểm tương tự `product_finalize_timeout_seconds` so với các công cụ chạy trong bước
finalize (voxel, MoGe nếu có) và ghi kết quả vào report.

## Ghi chú cho T-045
- Ngưỡng treo COLMAP 600 s được chọn từ log scene nhỏ. Bộ Mip-NeRF 360 có ảnh tới ~2500 px; theo dõi khoảng im lặng dài nhất
  của COLMAP trong T-045 và báo nếu vượt 300 s.
- Laptop vẫn đặt COLMAP/Brush 3600 s trong `scripts/gpu/studio.env` (file riêng của máy, task không sửa). Chủ dự án nên bỏ hai
  dòng đó (để mặc định mới) trước khi chạy T-045 Phần B.
