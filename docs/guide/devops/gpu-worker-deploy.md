# Triển khai GPU worker và phần cloud (ADR 0003)

Tài liệu này là bảng việc: phần nào đã có sẵn trong repo, phần nào **chỉ chủ tài khoản làm được** (tạo tài
khoản, nạp tiền, nhập secret). Không secret nào được ghi vào repo, image hay chat.

## 1. Ba cách chạy xử lý GPU

| Cách | Khi nào dùng | Cần gì | Trạng thái |
| --- | --- | --- | --- |
| **A. Một máy GPU thuê chạy cả API + worker** (`stack`) | Demo, lấy artifact nhanh | 1 instance vast.ai | Image chưa build thật |
| **B. Chạy lô rồi lấy gói job** (`batch`) | Chỉ cần artifact, tắt máy ngay | 1 instance + Hugging Face | Lệnh đã chạy trên máy local |
| **C. Worker nối vào DB + kho file chung** (`worker`) | Web chạy thường trực, GPU tự bật khi có việc | Railway + Supabase + R2 + vast.ai | Code có sẵn (kể cả tự bật/tắt GPU), chưa triển khai thật |

Kaggle và Colab không còn được hỗ trợ; dùng image GPU (`Dockerfile.gpu`) trên máy thuê.

Image GPU mặc định `APP_ENV=production` và `AUTH_REQUIRED=true` (đổi được bằng `-e`; production không chạy được khi tắt đăng nhập).
Chế độ `stack` dùng hai tài khoản seed có sẵn trong dữ liệu Studio (`reviewer@real2sim.dev`, `editor@real2sim.dev`); nạp dữ liệu Studio rồi đăng nhập, không cần tạo tài khoản. Chỉ khi chạy với DB trống mới phải tạo Reviewer bằng CLI (xem README, mục Xác thực và phân quyền).

## 2. Đã có trong repo

- `Dockerfile.gpu` + `scripts/gpu/docker_entrypoint.sh`: image GPU đủ COLMAP, Brush, splat-transform, runtime tách
  theo vật; chế độ `worker` / `stack` / `batch` / `preflight`.
- `scripts/gpu/gpu_plan.py`, `run_workers.py`: dò GPU, chia worker theo VRAM từng GPU, ghim job vào GPU.
- `scripts/kaggle/preflight.py`: kiểm máy trước khi tốn giờ GPU (tên thư mục là lịch sử, vẫn được image GPU dùng).
- `scripts/kaggle/job_bundle.py`, `run_job.py`: chạy lô và chuyển gói job qua Hugging Face.
- `Dockerfile` (API cho Railway), `scripts/cloud/configure_bucket.py` (CORS + dọn multipart cho R2), đăng nhập hai role.
- Checkpoint/resume train 3DGS; thử lại tách theo vật.

Với checkout P-087 hiện tại, `Dockerfile` là image API/control-plane CPU và
`Dockerfile.gpu` là image worker NVIDIA. Stack Studio local dùng Compose ở root:

```bash
# CPU: API + web + restore data package
docker compose --env-file .env.studio -f docker-compose.yml up --build -d --wait

# Linux/NVIDIA: thêm worker và preflight runtime thật
docker compose --env-file .env.studio -f docker-compose.yml \
  -f docker-compose.gpu.yml up --build -d --wait
```

Trên Linux, `make -f Makefile.studio docker` và
`make -f Makefile.studio docker GPU=1` là alias tương ứng. Windows/macOS dùng
Docker Compose trực tiếp; phần GPU NVIDIA chỉ áp dụng cho Linux hoặc máy thuê
được Docker cấp NVIDIA runtime.

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
   local) hoặc ghi `metric.json` và chạy lượt 2 trên instance.
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

Biến cần đặt thêm trên **API** (Railway) khi worker ở máy khác:

- `PRODUCT_OBJECTIFY_REMOTE_WORKER=true` — báo cho Studio biết có worker lo việc tách theo vật (API không tự kiểm
  được runtime GPU của máy khác). Thiếu biến này nút "Chạy lại tách theo vật" bị ẩn.
- `PRODUCT_SCENE_RUNTIME_PYTHON` đã được image API đặt sẵn (runtime `usd-core` nhỏ, không cần GPU) để API tự dựng
  gói USD lai.
- (tuỳ chọn) hình khối asset thư viện: chạy `scripts/scene/build_asset_previews.py` lúc deploy và trỏ
  `PRODUCT_ASSET_PREVIEW_DIR` tới thư mục kết quả; không có thì Studio vẽ hộp.

API và worker ở hai máy đã dùng chung được (2026-10-01): yêu cầu "chạy lại tách theo vật / dùng hộp" nằm trong DB,
và mọi chỗ kiểm "artifact đã có chưa" đều tìm cả trên kho file. Đã kiểm bằng test hai máy giả lập (chung DB + kho
file, khác đĩa); **chưa chạy trên Railway + R2 thật**.

Giới hạn còn lại của cách C:

- Kho checkpoint train nằm trên đĩa worker: destroy instance là mất, retry chạy lại từ đầu.
- Xác nhận hệ mét và dựng gói USD chạy trong tiến trình API và phải tải 3DGS gốc (hàng trăm MB) về máy API: cần
  đĩa + RAM tương ứng trên Railway.

### Tự bật/tắt GPU theo hàng đợi

`scripts/cloud/gpu_autoscaler.py` chạy thường trực cạnh API (cùng `DATABASE_URL` + `ARTIFACT_S3_*`), đếm việc đang
chờ GPU và bật/tắt worker trên vast.ai. Job đang chờ **người dùng** xác nhận hệ mét không giữ GPU bật.

| `VAST_MODE` | Cách hoạt động | Hợp khi |
| --- | --- | --- |
| `instance` (mặc định) | Bạn thuê sẵn 1 instance, đặt `VAST_INSTANCE_ID`; autoscaler chỉ start/stop | Dùng thường xuyên: bật lại nhanh, giữ checkpoint; nhưng lúc stop vẫn tính tiền đĩa, và có thể không bật lại được ngay nếu GPU đang có người khác thuê |
| `rent` | Mỗi lần cần: tìm offer rẻ nhất ≥ `VAST_MIN_GPU_RAM_GB` trong giá trần `VAST_MAX_DPH`, thuê với `VAST_IMAGE`, rảnh thì destroy | Dùng thưa: không tốn gì lúc rảnh; mỗi lần bật mất vài phút kéo image |

```bash
export VAST_API_KEY=...            # tạo ở vast.ai → Account → API keys; chỉ đặt qua biến môi trường
export VAST_MODE=instance VAST_INSTANCE_ID=<id>      # hoặc: VAST_MODE=rent VAST_IMAGE=<user>/real2sim-gpu:v2
python -m scripts.cloud.gpu_autoscaler --once --dry-run   # xem quyết định, chưa bật/tắt gì
python -m scripts.cloud.gpu_autoscaler                    # chạy thật (rảnh 10 phút thì tắt: GPU_IDLE_MINUTES)
```

Chưa gọi API vast.ai thật (chưa có tài khoản): logic và dạng request đã test bằng transport giả theo tài liệu
vast.ai. Lần đầu hãy chạy `--once --dry-run`, rồi `--once`, và theo dõi trang Instances của vast.ai. Ở mode `rent`
secret DB/kho file được gửi vào biến môi trường của instance thuê — dùng key quyền vừa đủ, đặt hạn mức nạp tiền.

## 5. Chi phí tham khảo

Chưa đo trên máy thuê. Ước lượng trong ADR 0003 (INFERENCE): GPU khoảng 0,1 USD/job trên RTX 4090 nếu một job
15–20 phút; R2 miễn phí trong 10 GB; Supabase gói miễn phí; Railway 5–10 USD/tháng.
