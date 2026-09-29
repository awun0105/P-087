# Chạy Studio MVP trên máy GPU (SSH) và tạo demo bundle

Runbook cho máy GPU thuê (Vast.ai hoặc tương đương): dựng runtime, chạy pipeline
thật trên video TorWIC `Aisle_CW`, export demo bundle rồi mang về máy demo.
Kết quả demo **phải** đến từ chính pipeline này (không vẽ tay, không dùng
`evaluation_only`).

## 1. Yêu cầu máy

- Ubuntu 22.04/24.04, GPU NVIDIA ≥ 12 GB VRAM, driver có Vulkan
  (`/usr/share/vulkan/icd.d/nvidia_icd.json`), Docker (COLMAP chạy trong container).
- Python 3.12, Node 20+, `ffmpeg`, `git`.

## 2. Chuẩn bị

```bash
git clone <repo> /opt/real2sim/app && cd /opt/real2sim/app
git checkout feat/product-rec
make setup                                   # .venv + dependencies từ lockfile
(cd frontend && npm ci && npm run build:editor)

# Runtime EX-REC (cùng version với máy local, xem data/rec04_runtime/):
mkdir -p /opt/real2sim/runtime && cd /opt/real2sim/runtime
#  - Brush 0.3.0 linux archive (sha256 4f0f9a87…): giải nén brush_app vào ./brush/
#  - splat-transform 3.6.6:   npm install @playcanvas/splat-transform@3.6.6
#  - COLMAP image pin digest: docker pull colmap/colmap@sha256:b8498ebe…f40954
#  - colmap-launcher.sh: copy từ data/rec04_runtime/colmap-launcher.sh; trên GPU có
#    thể thêm `--gpus all` nếu bật use_gpu trong processing config.
```

Copy `scripts/gpu/studio.env.example` → `scripts/gpu/studio.env`, sửa đường dẫn.
Giá trị JSON giữ nháy đơn. Sinh runtime manifest **trên chính máy này**:

```bash
set -a; source scripts/gpu/studio.env; set +a
.venv/bin/python -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"
```

## 3. Chạy stack

```bash
scripts/gpu/run_stack.sh scripts/gpu/studio.env
# API :8000, worker (queue), Studio :3000
```

Truy cập từ máy mình qua SSH tunnel: `ssh -L 3000:localhost:3000 <gpu-host>` rồi
mở http://localhost:3000.

## 4. Xử lý Aisle_CW và export demo

```bash
# Video từ frame chuẩn hóa (đúng FPS theo timestamps.csv, 1092 frame ≈ 109 s)
.venv/bin/python -m scripts.demo.make_torwic_video \
  --sequence-dir data/torwic_slam/normalized/aisle_cw --out /opt/real2sim/state/aisle_cw.mp4
```

Upload qua Studio (Scene mới → tải video → chọn → Bắt đầu xử lý), hoặc bằng API:

```bash
curl -X POST "localhost:8000/api/v1/uploads?filename=aisle_cw.mp4" \
  -H "Content-Type: video/mp4" --data-binary @/opt/real2sim/state/aisle_cw.mp4
curl -X POST localhost:8000/api/v1/scenes/from-upload -H "Content-Type: application/json" -d '{
  "upload_id": "<upload_id>", "name": "Kho TorWIC · Aisle CW",
  "attestation": {"data_origin": "public_or_synthetic", "declared_owner": "P-087",
    "declared_purpose": "Demo Real2Sim Studio", "rights_to_use_confirmed": true,
    "anonymization_confirmed": true, "retention_acknowledged": true}}'
curl localhost:8000/api/v1/jobs/<job_id>/progress      # chờ preview_ready=true
```

Export bundle từ job vừa chạy (thời lượng stage lấy từ journal thật):

```bash
set -a; source scripts/gpu/studio.env; set +a
.venv/bin/python -m scripts.demo.export_demo_bundle --out /opt/real2sim/state/demo/aisle_cw \
  --note "GPU <model>, Brush 30k bước" job --job-id <job_id>
tar -C /opt/real2sim/state/demo -czf aisle_cw_demo.tgz aisle_cw
```

Mang `aisle_cw_demo.tgz` về máy demo, giải nén và đặt
`PRODUCT_DEMO_DIR=<thư mục aisle_cw>`. Bundle tự kiểm checksum từng file khi phục vụ.

## 5. Kiểm tra nhanh

- `curl localhost:8000/api/v1/demo` trả manifest `origin: "pipeline_job"`.
- Studio › Kịch bản demo chạy đủ 4 bước; bước cuối mở editor.
- Editor SuperSplat cần WebGPU (Chrome/Edge mới); trình duyệt không có WebGPU sẽ
  tự chuyển sang viewer WebGL2 chỉ xem.

## Đã kiểm trên máy local (2026-09-29)

Quadro T2000 4 GB, `processing_local_v1.json`: video 200 frame → 50 frame sau
stride; kiểm tra 10 s, tách frame 5 s, COLMAP 53 s, Brush 3000 bước 89 s; SOG
~1 MB render được trong Chrome (WebGL2). Chưa chạy cấu hình GPU 30k bước.
