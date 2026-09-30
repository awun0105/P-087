# Giao thức `recon_visual_quality`

Đo chất lượng ảnh render của 3DGS (Brush) để chọn cấu hình lấy mẫu/COLMAP/Brush tốt nhất cho
một loại video, và so các góc quay (camera trái/phải) của cùng một lượt.

## Phương pháp

Theo cách báo cáo của 3DGS gốc, SuGaR và Frosting (`gaussian_splatting/metrics.py`,
`full_eval.py`, `metrics.py` trong `private/SuGaR` @7c10c4a, `private/Frosting` @08b1cb2).
Các file đó mang **Gaussian-Splatting License (Inria/MPII, phi thương mại)** — theo
`docs/execution/audits/00_cross_repo_reuse_matrix.md` không chép/vendor code; chỉ dùng phương
pháp đo (công thức và quy ước là kiến thức chung):

| Hạng mục | Quy ước |
|---|---|
| Ảnh giữ lại | mỗi ảnh thứ 8 của tập ảnh đã đăng ký (Brush `--eval-split-every 8`, như `llffhold = 8`) |
| PSNR | trên ảnh [0, 1], cao hơn là tốt hơn — Brush tự tính |
| SSIM | cửa sổ Gaussian 11 px, σ = 1,5, cao hơn là tốt hơn — Brush tự tính |
| LPIPS | mạng VGG, thấp hơn là tốt hơn — `eval/visual/lpips_score.py`, gói `lpips` 0.1.4 (BSD-2) |
| Mốc bước | 7k, 14k, 21k, 28k, 30k (`--eval-every 7000`); báo mốc cuối, giữ cả đường cong |
| Render | nền đen, làm tròn 8-bit trước khi so (Brush `eval_stats`) |

Brush v0.3.0 (Apache-2.0) cung cấp eval split và in `Eval iter N: PSNR x, ssim y`; ảnh render
lưu ở `output/eval_<iter>/<tên>.png` và được chấm LPIPS với ảnh train đã undistort cùng tên.

## Ranh giới dữ liệu

- Ảnh giữ lại là ảnh **của chính video đầu vào**, không phải `evaluation_only/` của dataset.
- Video TorWIC đưa vào job chỉ gồm `train_frame_ids` của benchmark split
  (`scripts/demo/make_torwic_video.py --train-split`); frame held-out không vào runtime.
- Lượt chấm bỏ ~12,5% ảnh khỏi train; đây là chế độ thí nghiệm. Lượt chạy sản phẩm vẫn train trên
  toàn bộ ảnh — điểm tuyệt đối của sản phẩm vì vậy cao hơn một chút so với số đo ở đây.

## Cách chạy

1. Tạo job sản phẩm từ video với cấu hình lấy mẫu/COLMAP cần so (Brush tối thiểu để nhanh); job
   publish ảnh + camera pose REC-03.
2. Chấm Brush trên đúng pose đó:

```bash
set -a; . scripts/gpu/studio.env; set +a
python -m eval.visual.brush_quality --job <job-id> --label <nhãn> --work <thư mục tạm> \
    --iters 30000 --max-splats 1500000 --max-resolution 1280 \
    --out eval/results/recon_visual_quality/<nhãn>.jsonl
```

Mỗi dòng kết quả ghi: job, số ảnh đăng ký, tham số xử lý của job, cấu hình Brush, phiên bản
Brush, thời gian train, PSNR/SSIM từng mốc, LPIPS mốc cuối, dung lượng PLY, máy chạy.

## Giới hạn

- PSNR/SSIM của Brush và của 3DGS gốc có thể lệch nhỏ do cách cài đặt; dùng để so **giữa các cấu
  hình của mình**, không so thẳng với số công bố trên Mip-NeRF 360.
- Ảnh giữ lại nằm xen giữa ảnh train (cùng quỹ đạo), nên đo khả năng tái tạo góc nhìn gần quỹ đạo,
  không đo góc nhìn xa quỹ đạo.
