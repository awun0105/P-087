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
mà API không cần biết, miễn là runtime manifest còn khớp (xem bước 4).

## Cấu hình: một file gốc

[`production.env.example`](production.env.example) là nguồn duy nhất, chia bốn phần:

| Phần | Đi vào file | Chứa |
|---|---|---|
| `[shared]` | `api.env` và `worker.env` | PostgreSQL, R2, đăng nhập, chế độ privacy, COLMAP GPU, bắt buộc che, khóa LLM |
| `[api]` | `api.env` | Đường dẫn trên volume Railway, CORS, cờ "worker ở máy khác", runtime manifest |
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
4. **Chép runtime manifest của pod lên volume của API**, vào đường dẫn `PRODUCT_RUNTIME_MANIFEST` trong `[api]`.
   Kiểm lại bằng `check --api-manifest ... --worker-manifest ...`.
5. **API trên Railway.** Gắn volume vào `/app/data`, nạp `api.env`, deploy, gọi `/health`.
6. **Tạo tài khoản Reviewer đầu tiên** (lệnh trong README, mục import).
7. **Studio trên Vercel.** Đặt `REAL2SIM_API_URL` từ `web.env`, build bằng `npm run build:editor && npm run build`.
8. **Chạy thử một job** từ upload tới viewer.

## Những chỗ dễ vấp

- **Runtime manifest gắn với từng máy.** File ghi model GPU và phiên bản driver. Job mang checksum của manifest
  trên API, và worker từ chối job có checksum khác manifest của nó. Đổi pod sang GPU hoặc driver khác thì phải
  chép manifest mới lên API và khởi động lại API. Hai pod khác loại GPU không dùng chung một API được.
- **Chế độ privacy là quyết định của owner và không có mặc định trong file gốc.** Với `qa_verified`, mọi yêu cầu
  tạo scene từ video bị từ chối (409) vì chưa có luồng QA nào để đi qua cổng; `self_attested` là chế độ duy nhất
  hiện tạo được scene. `check` báo lỗi khi để trống hoặc đặt `qa_verified`.
- **`PRODUCT_COLMAP_USE_GPU` do API quyết định.** API ghi giá trị vào cấu hình job, worker chỉ thực thi. Nó nằm ở
  `[shared]` vì đặt ở mỗi worker thì COLMAP vẫn chạy CPU.
- **API thiếu `PRODUCT_PROCESSING_CONFIG` hoặc `PRODUCT_RUNTIME_MANIFEST`** thì từ chối tạo scene với thông báo
  "Chưa cấu hình worker".
- **Bộ che khuôn mặt/biển số cần hai nơi.** Worker cần `PRODUCT_EGOBLUR_WEIGHTS` trỏ tới hai file `.jit`; API cần
  `PRODUCT_ANONYMIZE_REMOTE_WORKER=true` thì form mới hiện ô chọn. Image GPU không có sẵn trọng số (Meta yêu cầu
  đồng ý giấy phép khi tải), và entrypoint chưa tự tải chúng.
- **Worker đo RAM và CPU theo giới hạn của container** (AUD-26.S4). Chưa kiểm trên pod thật.
- **Image GPU chưa từng được build trọn vẹn** (ghi chú trong `Dockerfile.gpu`). Lần build đầu chạy `preflight`.

## Chưa có trong đóng gói

- Entrypoint của image GPU chưa tự tải và kiểm checksum trọng số EgoBlur.
- Preflight chưa kiểm sự có mặt của trọng số EgoBlur (đã kiểm COLMAP chạy GPU khi bật).
- Không có bước tự động chép runtime manifest từ pod lên API; đang là thao tác tay ở bước 4.
- `docker-compose.gpu.yml` là cấu hình chạy cục bộ (`APP_ENV: development`, SQLite), không phải production.
