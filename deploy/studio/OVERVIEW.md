# Real2Sim Studio — tổng quan production

Trang này trả lời ba câu: hệ thống gồm những gì, cấu hình đặt ở đâu, và deploy theo thứ tự nào. Chi tiết từng
nhà cung cấp nằm ở [README.md](README.md).

## Thành phần

```text
Người dùng (trình duyệt)
   │
   ├─► Landing ─────────────── Cloudflare Pages          landing/
   │
   └─► Giao diện Studio ────── Vercel (Next.js)           frontend/
            │  chuyển tiếp /api/v1/*, giữ cookie đăng nhập
            ▼
        API điều khiển ─────── Railway (FastAPI)          Dockerfile
            │        │
            │        └─► PostgreSQL ── Supabase
            │                  ▲
            ▼                  │ nhận job, ghi tiến trình
        Kho file ── Cloudflare R2 ◄──► GPU worker ── Vast.ai / RunPod    Dockerfile.gpu
```

| Thành phần | Nhà cung cấp | Vai trò |
|---|---|---|
| Landing | Cloudflare Pages | Trang giới thiệu |
| Giao diện Studio | Vercel | Form tạo scene, timeline, viewer, màn duyệt |
| API | Railway | Đăng nhập, quota, tạo job, tiến trình, cấp link tải file |
| PostgreSQL | Supabase | Job, người dùng, hàng đợi, số đo tài nguyên |
| Kho file | Cloudflare R2 | Video upload, frame, kết quả 3DGS, manifest |
| GPU worker | Vast.ai, dự phòng RunPod | Toàn bộ pipeline dựng 3D |

API và GPU worker không gọi nhau. Chúng chỉ gặp nhau qua PostgreSQL và R2, nên worker có thể bật tắt hay đổi pod
mà API không cần biết. Worker tự công bố runtime phần mềm của nó vào PostgreSQL, API gắn job mới vào runtime đó.

## Cấu hình: một file gốc

[`production.env.example`](production.env.example) là nguồn duy nhất, chia bốn phần:

| Phần | Đi vào file | Chứa |
|---|---|---|
| `[shared]` | `api.env` và `worker.env` | PostgreSQL, R2, đăng nhập, chế độ privacy, COLMAP GPU, bắt buộc che, khóa LLM |
| `[api]` | `api.env` | Đường dẫn trên volume Railway, CORS, cờ "worker ở máy khác", cờ lấy runtime từ worker |
| `[worker]` | `worker.env` | Đường dẫn trong image GPU, trọng số EgoBlur, số worker |
| `[web]` | `web.env` | `REAL2SIM_API_URL` |

```bash
cp deploy/studio/production.env.example /secure/production.env     # điền giá trị, không commit
python -m scripts.studio.deploy_env check  --source /secure/production.env
python -m scripts.studio.deploy_env render --source /secure/production.env --out-dir /secure/out
```

`check` thoát mã 1 khi có cấu hình làm production không chạy; `render` từ chối sinh file khi còn lỗi và từ chối
ghi vào trong repo. Ba file `api.env.example`, `worker.env.example`, `web.env.example` được sinh bằng
`render --examples`; một test giữ chúng khớp với file gốc.

## Thứ tự deploy

1. **Supabase và R2.** Tạo database và bucket; đặt CORS của R2 cho đúng origin của Studio (`GET`, `HEAD`, `PUT`,
   expose `ETag`). Điền `[shared]`.
2. **Chạy `check`.** Sửa hết lỗi trước khi làm tiếp.
3. **GPU worker.** Build `Dockerfile.gpu`, khởi động pod với `worker.env`, chạy chế độ `preflight` của entrypoint.
   Entrypoint tự sinh `/data/runtime_manifest.json` ở lần chạy đầu.
4. **API trên Railway.** Gắn volume vào `/app/data`, nạp `api.env` (có `PRODUCT_RUNTIME_FROM_WORKERS=true`), deploy,
   gọi `/health`. Không chép runtime manifest của worker lên API: khi GPU worker lên và công bố runtime, job mới chạy
   được ngay, không cần khởi động lại API.
5. **Tạo tài khoản Reviewer đầu tiên** (lệnh trong README, mục import).
6. **Studio trên Vercel.** Đặt `REAL2SIM_API_URL` từ `web.env`, build bằng `npm run build:editor && npm run build`.
7. **Chạy thử một job** từ upload tới viewer.

## Nâng cấp từ bản trước T-040

- Nâng cấp từ bản trước T-040 khi còn job RUNNING: đưa job đó về FAILED retryable bằng tay trước khi bật worker mới.
  Bản trước không có lease nên worker mới không tự phục hồi job đó.
- Migration 22 và 23 chạy tự động khi API hoặc worker khởi động. Worker mới công bố runtime vào `r2s_worker_runtimes`
  ngay nhịp heartbeat đầu tiên; API không cần khởi động lại để thấy runtime đó.

## Những chỗ dễ vấp

- **Runtime gắn với phiên bản công cụ, không gắn với GPU.** Khoá ghép job với worker là checksum của runtime
  manifest sau khi bỏ `gpu_model`, `vram` và `nvidia_driver`. Đổi pod sang GPU hoặc driver khác không làm job lệch
  worker. Đổi phiên bản công cụ (image mới) thì job chưa có stage được gắn lại sang máy mới; job đã có stage và
  runtime cũ không còn máy nào chạy thì UI báo "đang chờ GPU" và job cần chạy lại từ đầu. Máy dev có thể ghim
  `PRODUCT_RUNTIME_MANIFEST` thay cho chế độ worker.
- **Chế độ privacy mặc định là `self_attested`** (chạy được khi pod chưa có bộ che). `self_attested`: người upload
  tự cam kết, che là lựa chọn theo từng job. `qa_verified`: mọi video bị che tự động, và job có frame bị che
  dừng chờ người upload xác nhận rồi mới dựng 3D; chế độ này cần bộ che ở worker, thiếu thì `check` báo lỗi.
- **`PRODUCT_COLMAP_USE_GPU` do API quyết định.** API ghi giá trị vào cấu hình job, worker chỉ thực thi. Nó nằm ở
  `[shared]` vì đặt ở mỗi worker thì COLMAP vẫn chạy CPU.
- **API không có runtime nào để gắn job** (chưa có GPU worker nào công bố và không ghim manifest) thì từ chối tạo
  scene với thông báo "Chưa có runtime cho job". `check` báo lỗi nếu API vừa không có `PRODUCT_RUNTIME_MANIFEST`
  vừa không bật `PRODUCT_RUNTIME_FROM_WORKERS`.
- **Bộ che khuôn mặt/biển số cần hai nơi.** Worker cần `PRODUCT_EGOBLUR_WEIGHTS`; API cần
  `PRODUCT_ANONYMIZE_REMOTE_WORKER=true` thì form mới hiện ô chọn. Image GPU không chứa trọng số (Meta yêu cầu
  đồng ý giấy phép khi tải): chạy `python -m scripts.gpu.egoblur_weights upload --from <thư mục>` một lần để đưa
  hai file lên R2, sau đó pod nào có biến trên cũng tự tải và kiểm sha256 lúc khởi động. Đổi pod không cần
  chép tay.
- **Giới hạn thời gian công cụ** (T-043): công cụ treo bị dừng theo tiến độ log (`R2S_<CÔNG CỤ>_STALL_SECONDS`),
  scene đã có số đo thì có hạn tự tính, còn giới hạn cứng chỉ là lưới cuối (COLMAP 14400 s, Brush 21600 s). Trần giờ GPU
  mỗi scene đặt bằng `PRODUCT_JOB_GPU_HOURS_MAX`, mặc định tắt. Chi tiết trong `scripts/gpu/README.md`.
- **Worker đo RAM và CPU theo giới hạn của container** (AUD-26.S4). Chưa kiểm trên pod thật.
- **Image GPU chưa từng được build trọn vẹn.** Image dựng bằng `scripts/gpu/install.sh` (cùng công thức với laptop, ghi `/opt/real2sim/runtime.env`), nhưng T-038 chưa build image: lần build thật là T-039 và chạy `preflight` trong container.

## Chưa có trong đóng gói

Demo tương tác có runbook riêng tại [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md): code bundle,
thư viện mẫu có checksum, bootstrap API từ R2, schema PostgreSQL/output R2 riêng từng
phiên, ownership và janitor giữa các host. Image/GPU/cloud vẫn cần bằng chứng chạy
thật; việc có code và bundle không thay thế acceptance đó.

- `PRODUCT_INPUT_RUNTIME_REGISTRY` vẫn là file chép tay từ pod lên volume của API (ngoài phạm vi chuyển sang
  worker-công-bố; cần task riêng để bỏ).
- `docker-compose.gpu.yml` là cấu hình chạy cục bộ (`APP_ENV: development`, SQLite), không phải production.
