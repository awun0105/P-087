# Giao thức benchmark `pipeline_runtime`

**Đo gì:** một job đi qua pipeline Studio (kiểm video → privacy → tách frame → COLMAP →
Brush → SOG) mất bao lâu, tốn bao nhiêu, trên máy nào, với thông số nào.

**Khi nào ghi:** worker tự publish sau mỗi attempt preview
(`artifact://jobs/<job>/benchmark/pipeline_runtime/attempt-<n>.json`). Tổng hợp:

```bash
python -m scripts.benchmark.collect --all --label aisle-cw-demo --gpu-hourly-usd 0.34
# → eval/results/pipeline_runtime/aisle-cw-demo.jsonl (bỏ qua job+attempt đã ghi)
```

| Field | Đơn vị | Nguồn | Ghi chú |
|---|---|---|---|
| `stages[].seconds` | giây | journal chuyển stage | Stage chạy chung một CLI (privacy, tách frame trong prepare) có thể trống |
| `total_seconds` | giây | stage đầu bắt đầu → stage cuối xong | Không tính thời gian chờ hàng đợi |
| `processing` | — | `config/processing.json` của job | Đúng thông số đã chạy (checksum `config_checksum`) |
| `machine` | — | worker tự đo (`r2s_workers`) | GPU, VRAM, CPU, RAM, đĩa |
| `input_size_bytes` | byte | video upload | |
| `sog_size_bytes` | byte | file SOG giao cho trình duyệt | Trống nếu chưa có preview |
| `gpu_hourly_usd` | USD/giờ | tham số `--gpu-hourly-usd` / `BENCHMARK_GPU_HOURLY_USD` | Giá thuê thực tế lúc chạy |
| `estimated_gpu_cost_usd` | USD | `total_seconds/3600 × gpu_hourly_usd` | Ước tính, không phải hóa đơn |

**So sánh hợp lệ:** chỉ so các dòng cùng nhãn, cùng `config_checksum` hoặc ghi rõ thông số khác.
Không dùng số này để kết luận chất lượng 3D — đó là `recon_visual_quality`.
