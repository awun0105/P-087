# Visual evaluation

- `brush_quality.py` — benchmark `recon_visual_quality` (giao thức `eval/protocols/recon_visual_quality.md`):
  train Brush có eval split trên camera pose của một job, chấm PSNR/SSIM/LPIPS.
- `lpips_score.py` — LPIPS-VGG giữa ảnh render và ảnh thật; chạy trong runtime có torch
  (`PRODUCT_SCENE_RUNTIME_PYTHON`).

## Ghi quá trình train ra Rerun (tuỳ chọn)

Brush 0.3.0 nhúng SDK Rerun 0.24.1 và tự gửi dữ liệu tới viewer đang nghe ở `127.0.0.1:9876`: camera COLMAP, ảnh
render ↔ ảnh thật của các view giữ lại ở mỗi mốc eval, PSNR/SSIM, loss, learning rate, số Gaussian và đám Gaussian
theo thời gian. Viewer phải đúng 0.24.1 (bản khác không đọc được luồng):

```bash
uv venv --python 3.12 data/tools/rerun-0.24.1 && uv pip install --python data/tools/rerun-0.24.1/bin/python rerun-sdk==0.24.1

# Lưu thành file để Studio hiển thị ở bước 3DGS › "Quá trình train (Rerun)":
python -m eval.visual.brush_quality --job <job-id> --label <nhãn> --work <thư mục tạm> --out <kết quả.jsonl> \
    --rerun-save data/rerun_recordings/<job-id>.rrd

# Hoặc xem trực tiếp trong lúc train: mở viewer trước, rồi chạy script với --rerun
data/tools/rerun-0.24.1/bin/rerun --bind 127.0.0.1
```

Đây là **một lượt train đánh giá riêng** (giữ lại 1/8 ảnh), không phải scene mà job sản phẩm đã publish; pipeline
sản phẩm không bật ghi Rerun. `--rerun-splats-every` càng nhỏ file càng nặng (toàn bộ Gaussian mỗi lần ghi). Mỗi máy
chỉ chạy được một lượt ghi tại một thời điểm vì Brush dùng cổng cố định.
