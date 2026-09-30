# Visual evaluation

- `brush_quality.py` — benchmark `recon_visual_quality` (giao thức `eval/protocols/recon_visual_quality.md`):
  train Brush có eval split trên camera pose của một job, chấm PSNR/SSIM/LPIPS.
- `lpips_score.py` — LPIPS-VGG giữa ảnh render và ảnh thật; chạy trong runtime có torch
  (`PRODUCT_SCENE_RUNTIME_PYTHON`).
