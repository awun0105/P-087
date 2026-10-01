# Chạy pipeline trên Kaggle (hoặc GPU thuê không có Docker) để lấy artifact

Đường này **thêm bên ngoài** luồng chính: nó bật đúng API + worker của stack trên máy GPU, không có
giao diện web, chạy video → artifact, rồi đóng gói job và lưu lên Hugging Face. Studio trên máy bạn kéo
gói về để xem, sửa scene và xuất USD.

```text
Kaggle (GPU)                         Hugging Face (dataset repo private)        Máy có Studio
run_job → export → push  ─────────►  jobs/<job_id>/bundle.json + artifacts  ──►  pull → import → Studio
          ▲                                                                       │ chọn điểm đo hệ mét
          └──────────────── metric.json (lượt 2) ◄────────────────────────────────┘
```

| File | Việc |
| --- | --- |
| `setup_kaggle.sh` | Cài COLMAP (apt, CPU), Vulkan, Brush, Node + splat-transform, venv app, runtime tách theo vật; ghi `kaggle.env` |
| `preflight.py` | Kiểm từng công cụ pipeline cần; thiếu mục bắt buộc → dừng trước khi tốn giờ GPU |
| `run_job.py` | Video (+ điểm đo) → job chạy tới chỗ dừng → xuất gói → đẩy Hugging Face |
| `job_bundle.py` | `export` / `import` / `push` / `pull` gói job |
| `real2sim_kaggle.ipynb` | Notebook gồm các ô lệnh dưới đây |

## Trạng thái kiểm chứng

- **VERIFIED (máy local, 2026-10-01):** xuất job thật `job-1421190ff700` (298 file, 537 MB) → nạp vào DB
  sạch → đọc lại được job + scene rev-007; `run_job --job-id` bật API + worker, báo scene, xuất gói;
  `preflight` chạy đủ 8 mục; URL + checksum Brush, URL Node.
- **UNVERIFIED (chưa chạy trên Kaggle):** `setup_kaggle.sh` trọn vẹn; Vulkan thấy GPU trong container
  Kaggle (rủi ro lớn nhất — không có thì Brush không train được và hiện chưa có trainer thay thế); COLMAP
  bản apt thay cho image đã ghim; `push`/`pull` lên Hugging Face (chưa có token trong phiên làm việc này).
  Lần chạy Kaggle đầu tiên: chạy `preflight` và ghi kết quả vào đây.

## Chuẩn bị (một lần)

1. Hugging Face: tạo token quyền **write**. Trên Kaggle: *Add-ons → Secrets* → thêm `HF_TOKEN`. Repo
   dataset (vd `<user>/real2sim-artifacts`) được tạo tự động ở chế độ private lần đẩy đầu.
2. Mã nguồn: repo này là private → thêm secret `GITHUB_TOKEN` (quyền đọc repo) hoặc tải repo lên thành
   một Kaggle Dataset rồi copy vào `/kaggle/working/app`.
3. Notebook: bật **GPU** và **Internet**.
4. `attestation.json` — lời khai nguồn dữ liệu, do người chạy tự điền (lệnh không điền thay):

```json
{"data_origin": "self_collected_no_pii", "declared_owner": "<ai sở hữu video>",
 "declared_purpose": "<mục đích>", "rights_to_use_confirmed": true,
 "anonymization_confirmed": true, "retention_acknowledged": true}
```

## Các ô lệnh trên Kaggle

```bash
# Ô 1 — mã nguồn + cài đặt (khoảng 15–25 phút lần đầu; gsplat biên dịch kernel CUDA)
git clone --branch feat/pipeline-v2 https://$GITHUB_TOKEN@github.com/<org>/<repo>.git /kaggle/working/app
cd /kaggle/working/app && bash scripts/kaggle/setup_kaggle.sh /kaggle/working/r2s

# Ô 2 — kiểm máy (phải "đủ điều kiện chạy" mới đi tiếp)
cd /kaggle/working/app && set -a && source /kaggle/working/r2s/kaggle.env && set +a
.venv/bin/python -m scripts.kaggle.preflight

# Ô 3 — lượt 1: video → 3DGS, dừng ở bước chờ xác nhận hệ mét, đẩy gói lên Hugging Face
.venv/bin/python -m scripts.kaggle.run_job --video /kaggle/input/<dataset>/video.mp4 --name "Kho A" \
  --attestation /kaggle/input/<dataset>/attestation.json \
  --out /kaggle/working/bundles --hf-repo <user>/real2sim-artifacts
```

Trên máy có Studio (cùng file env của stack, có `HF_TOKEN` trong môi trường):

```bash
set -a; source scripts/gpu/studio.env; set +a
.venv/bin/python -m scripts.kaggle.job_bundle pull <job_id> --repo <user>/real2sim-artifacts --out data/bundles
.venv/bin/python -m scripts.kaggle.job_bundle import data/bundles/<job_id>
# khởi động lại stack → mở scene → chọn điểm và nhập số đo ở bước "Xác nhận tỉ lệ mét"
```

Sau bước xác nhận có hai cách đi tiếp:

- **Chạy tiếp trên máy Studio** (cần GPU ở máy đó): bấm xác nhận trên Studio, worker local chạy hình học +
  tách theo vật.
- **Chạy tiếp trên Kaggle:** ghi 7 điểm + 2 số đo vào `metric.json` (đúng dạng `UserMetricInput`: `floor_points`,
  `point_a`, `point_b`, `distance_m`, `check_a`, `check_b`, `check_distance_m`), rồi:

```bash
# Ô 4 — lượt 2 trên Kaggle (phiên mới thì chạy lại ô 1–2 trước)
.venv/bin/python -m scripts.kaggle.job_bundle pull <job_id> --repo <user>/real2sim-artifacts --out /kaggle/working/in
.venv/bin/python -m scripts.kaggle.job_bundle import /kaggle/working/in/<job_id>
.venv/bin/python -m scripts.kaggle.run_job --job-id <job_id> --metric-input /kaggle/input/<dataset>/metric.json \
  --out /kaggle/working/bundles --hf-repo <user>/real2sim-artifacts
```

Rồi `pull` + `import` lại trên máy Studio: gói mới là bản chạy tiếp của job nên job được cập nhật tại chỗ.

## Quy tắc của gói

- Gói mang nguyên trạng thái job lúc xuất; artifact giữ URI `artifact://jobs/...` nên không sửa nội dung.
- `import` chỉ nhận gói là **bản chạy tiếp** của job đang có (hoặc job chưa có). Hai máy cùng chạy tiếp một
  job theo hai hướng thì gói bị từ chối, DB không đổi.
- Mọi file được kiểm sha256 trước khi nạp. Token không bao giờ nằm trong gói, file env hay tham số lệnh.
- Giới hạn Kaggle: phiên tối đa 12 giờ, hết phiên mất `/kaggle/working/r2s` (phải cài lại); đẩy gói lên
  Hugging Face ngay sau mỗi lượt là cách giữ kết quả.

## Khi đã có kho S3 + DB chung (ADR 0003)

Stack đã hỗ trợ sẵn kho file S3-compatible (`ARTIFACT_S3_*`) và PostgreSQL (`DATABASE_URL`). Khi có hai
thứ đó, worker trên Kaggle/GPU thuê nối thẳng vào hàng đợi chung và không cần gói + Hugging Face nữa.
Đường gói này dành cho lúc chưa có hạ tầng đó.
