# Triển khai GPU worker và phần cloud (ADR 0003)

Tài liệu này là bảng việc: phần nào đã có sẵn trong repo, phần nào **chỉ chủ tài khoản làm được** (tạo tài
khoản, nạp tiền, nhập secret). Không secret nào được ghi vào repo, image hay chat.

## 1. Ba cách chạy xử lý GPU

| Cách | Khi nào dùng | Cần gì | Trạng thái |
| --- | --- | --- | --- |
| **A. Một máy GPU thuê chạy cả API + worker** (`stack`) | Demo, lấy artifact nhanh | 1 instance vast.ai | Image chưa build thật |
| **B. Chạy lô rồi lấy gói job** (`batch`) | Chỉ cần artifact, tắt máy ngay | 1 instance + Hugging Face | Lệnh đã chạy trên máy local |
| **C. Worker nối vào DB + kho file chung** (`worker`) | Web chạy thường trực, GPU bật khi cần | Railway + Supabase + R2 + vast.ai | Code có sẵn, chưa triển khai |

Kaggle: xem `scripts/kaggle/README.md` (phụ thuộc Vulkan, phải thử trước).

## 2. Đã có trong repo

- `Dockerfile.gpu` + `scripts/gpu/docker_entrypoint.sh`: image GPU đủ COLMAP, Brush, splat-transform, runtime tách
  theo vật; chế độ `worker` / `stack` / `batch` / `preflight`.
- `scripts/gpu/gpu_plan.py`, `run_workers.py`: dò GPU, chia worker theo VRAM từng GPU, ghim job vào GPU.
- `scripts/kaggle/preflight.py`, `probe_vulkan.sh`: kiểm máy trước khi tốn giờ GPU.
- `scripts/kaggle/job_bundle.py`, `run_job.py`: chạy lô và chuyển gói job qua Hugging Face.
- `Dockerfile` (API cho Railway), `scripts/cloud/configure_bucket.py` (CORS + dọn multipart cho R2), đăng nhập hai role.
- Checkpoint/resume train 3DGS; thử lại tách theo vật.

**Chưa kiểm chứng:** `Dockerfile.gpu` chưa build (máy dev thiếu ổ đĩa; image ước 15–20 GB); Vulkan trong container
vast.ai; chạy trên máy nhiều GPU; `sync` artifact giữa worker và R2 ở quy mô thật.

## 3. Việc của bạn — cách B (khuyến nghị làm trước)

1. **Docker Hub** (hoặc GHCR): tạo tài khoản + repo `real2sim-gpu`; `docker login`.
2. **Build + push image** trên một máy có ≥ 40 GB trống và mạng tốt (máy dev hiện còn ~12 GB, không đủ). Cách ít
   việc nhất: thuê một instance vast.ai loại "Docker-in-Docker"/VM, hoặc dùng GitHub Actions nếu organizer mở lại.

   ```bash
   docker build -f Dockerfile.gpu -t <user>/real2sim-gpu:v2 .
   docker push <user>/real2sim-gpu:v2
   ```

3. **vast.ai**: tạo tài khoản, nạp ~10 USD. Thuê instance: GPU ≥ 16 GB VRAM (RTX 3090/4090/A5000), ổ đĩa ≥ 60 GB,
   image `<user>/real2sim-gpu:v2`, launch mode "SSH" (entrypoint không tự chạy ở mode này — bạn chạy lệnh bằng tay).
4. **Trong instance** (qua SSH):

   ```bash
   cd /opt/real2sim/app
   scripts/gpu/docker_entrypoint.sh preflight          # phải ra "đủ điều kiện chạy"
   export HF_TOKEN=...                                  # token Hugging Face quyền write, không lưu vào file
   scripts/gpu/docker_entrypoint.sh batch --video /data/in/*.mp4 --name "Demo" \
       --attestation /data/in/attestation.json --out /data/bundles --hf-repo <user>/real2sim-artifacts
   ```

   Video và `attestation.json` chép lên bằng `scp` (hoặc `hf download` từ repo dataset của bạn).
5. **Trên máy có Studio**: `job_bundle pull` + `import`, chọn điểm đo hệ mét, rồi hoặc xác nhận tại chỗ (cần GPU
   local) hoặc ghi `metric.json` và chạy lượt 2 trên instance (xem `scripts/kaggle/README.md`).
6. **Tắt (destroy) instance** khi xong để không bị tính tiền.

## 4. Việc của bạn — cách C (web thường trực)

| Việc | Ở đâu | Kết quả cần đưa vào biến môi trường |
| --- | --- | --- |
| Tạo project Postgres | Supabase | `DATABASE_URL` (chuỗi kết nối, dùng cho cả API và worker) |
| Tạo bucket + API token | Cloudflare R2 | `ARTIFACT_S3_BUCKET`, `ARTIFACT_S3_ENDPOINT`, `ARTIFACT_S3_ACCESS_KEY_ID`, `ARTIFACT_S3_SECRET_ACCESS_KEY`, `ARTIFACT_S3_REGION=auto` |
| Deploy API từ `Dockerfile` | Railway | đặt các biến trên + `AUTH_REQUIRED=true`; lấy URL công khai của API |
| Deploy `frontend/` | Vercel | `REAL2SIM_API_URL=<URL API>` |
| CORS cho bucket | máy bạn | `python -m scripts.cloud.configure_bucket --origin <URL Vercel>` |
| Tạo Reviewer đầu tiên | Railway shell | `python -m src.services.orchestration.auth.cli create-user --role reviewer ...` |
| Thuê GPU, chạy worker | vast.ai | image `real2sim-gpu`, lệnh `worker`, cùng `DATABASE_URL` + `ARTIFACT_S3_*` |

Giới hạn hiện tại của cách C cần biết trước khi làm:

- Nút "Chạy lại tách theo vật / Dùng hộp" ghi yêu cầu vào đĩa của worker (`PRODUCT_WORKER_ROOT`), nên API trên
  Railway và worker trên vast.ai **chưa** dùng chung được tính năng này (cần chuyển sang DB — chưa làm).
- Kho checkpoint train nằm trên đĩa worker: destroy instance là mất, retry chạy lại từ đầu.
- Tự bật/tắt GPU theo hàng đợi (ADR 0003 §1) chưa có; bạn bật/tắt instance bằng tay.

## 5. Chi phí tham khảo

Chưa đo trên máy thuê. Ước lượng trong ADR 0003 (INFERENCE): GPU khoảng 0,1 USD/job trên RTX 4090 nếu một job
15–20 phút; R2 miễn phí trong 10 GB; Supabase gói miễn phí; Railway 5–10 USD/tháng.
