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
git checkout feat/pipeline-v2                # hoặc develop sau khi PR của nhánh này được merge
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

Runtime tách scene theo vật (pipeline v2, ADR 0007 — SAM2, gsplat, CoACD, usd-core, LaMa):

```bash
sudo apt install python3.12-dev               # header để gsplat biên dịch kernel CUDA (cần nvcc)
scripts/gpu/setup_scene_runtime.sh /opt/real2sim/scene_runtime
# in ra 3 biến PRODUCT_SCENE_RUNTIME_PYTHON / PRODUCT_SAM2_CHECKPOINT / PRODUCT_LAMA_CHECKPOINT
```

Thiếu runtime này job vẫn chạy: bước tách vật lùi về hộp ứng viên (ADR 0006) hoặc tách hình học.

Copy `scripts/gpu/studio.env.example` → `scripts/gpu/studio.env`, sửa đường dẫn.
Giá trị JSON giữ nháy đơn. Sinh runtime manifest **trên chính máy này**:

```bash
set -a; source scripts/gpu/studio.env; set +a
.venv/bin/python -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"
```

### Cấu hình khi chạy trên máy teammate

Phân phối ZIP và chạy API/web qua Docker Compose đa nền tảng: xem
[`docs/guide/studio-distribution.md`](../../docs/guide/studio-distribution.md).
Phần dưới mô tả cấu hình native trên Linux cho stack GPU hiện tại.

Chạy `make -f Makefile.studio env` **từ root repo** để sinh `scripts/gpu/studio.env`
với đường dẫn của checkout trên máy đó. Data khôi phục cần nằm tại
`data/studio_local/runtime.db`, `data/studio_local/artifacts/` và `data/demo/library/`;
asset preview và bản ghi Rerun dùng các thư mục mặc định trong `data/`.
Có thể chọn thư viện mẫu khác bằng `make -f Makefile.studio env DEMO_DIR=/duong/dan/library`.

Lệnh giữ nguyên env đã tồn tại. Với env copy từ máy khác, cập nhật đường dẫn trong
file đó; nếu muốn dùng lại baseline mặc định, sao lưu cấu hình riêng trước rồi chạy
`make -f Makefile.studio env FORCE_ENV=1`. File được sinh chỉ cấu hình đường dẫn,
không cài runtime hoặc chứng minh máy mới đã chạy GPU thành công. Khi cài runtime
tách vật thể, thêm các biến mà `setup_scene_runtime.sh` in ra vào env này.

`make setup` cài Python dependencies từ lockfile; `npm ci` trong `frontend/` cài
frontend dependencies. Docker trong stack local này dùng cho COLMAP qua launcher;
Brush và splat-transform cần cài riêng theo mục 2 khi chạy native. Compose ở root
khởi động API/web; thêm `docker-compose.gpu.yml` để cài runtime trong image GPU
và khởi động worker NVIDIA cùng stack.

## 3. Thông số xử lý

Mọi thông số (lấy mẫu frame, COLMAP, Brush) nằm trong **một file chung**
`configs/product/processing_presets_v1.json`: nhãn, giới hạn min/max, preset
"tối thiểu cho chất lượng tốt" và "tối đa", giá trị cố định và hệ số ước lượng
VRAM/RAM/đĩa. Worker tự đo máy (GPU, VRAM, CPU, RAM, ổ trống) mỗi 5 phút; UI dùng
số đo đó để đề xuất "tối đa cho máy này" và tô đỏ thông số có thể gây crash.
Thông số người dùng chọn được lưu thành `config/processing.json` của job.

## 4. Chạy stack

```bash
scripts/gpu/run_stack.sh scripts/gpu/studio.env
# API :8000, worker (queue), Studio :3000
```

Truy cập từ máy mình qua SSH tunnel: `ssh -L 3000:localhost:3000 <gpu-host>` rồi
mở http://localhost:3000.

### Chạy trên laptop: bảo vệ nhiệt

Laptop có thể tự tắt vì quá nhiệt khi train 3DGS (đã xảy ra 2026-10-01 trên ThinkPad P1/T2000 khi
chạy hai việc nặng cùng lúc). Chạy stack dưới systemd với trần CPU và bật watchdog nhiệt; watchdog
đóng băng stack khi nóng và thả ra khi nguội, job không mất tiến độ. Chỉ chạy một việc nặng một lúc.

```bash
systemd-run --user --unit r2s-stack -p CPUQuota=250% --working-directory="$PWD" make -f Makefile.studio up
systemd-run --user --unit r2s-thermal --working-directory="$PWD" scripts/gpu/thermal_guard.sh r2s-stack
journalctl --user -u r2s-thermal -f      # xem các lần đóng băng/chạy tiếp
```

Ngưỡng mặc định: đóng băng khi CPU ≥ 90°C hoặc GPU ≥ 82°C, chạy tiếp khi CPU ≤ 80°C và GPU ≤ 68°C
(ngưỡng chạy tiếp phải cao hơn nhiệt nền lúc máy rảnh, nếu không stack sẽ bị giữ đóng băng)
(đổi bằng `HOT_CPU`, `HOT_GPU`, `COOL_CPU`, `COOL_GPU`). Máy thuê trong datacenter không cần bước này.

### Đứt giữa chừng: checkpoint và chạy tiếp

Trong lúc train 3DGS, Brush xuất checkpoint định kỳ vào `PRODUCT_WORKER_ROOT/<job_id>/resume/` (mặc định khoảng
2.500 bước một lần; đổi bằng `REC04_BRUSH_CHECKPOINT_EVERY`, đặt `0` để tắt). Job `FAILED` vì máy tắt/worker chết
thì bấm **Thử lại** (hoặc `POST /api/v1/jobs/<job_id>/retry`): attempt mới dùng lại kết quả COLMAP và train tiếp
từ checkpoint mới nhất. Kho này chỉ nằm trên máy worker; đổi máy thì chạy lại từ đầu.

Không có Docker (Kaggle, GPU thuê dạng container): xem `scripts/kaggle/README.md`.

## 5. Xử lý Aisle_CW và export demo

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
.venv/bin/python -m scripts.demo.export_demo_bundle --out /opt/real2sim/state/demo/library/aisle-cw \
  --note "GPU <model>, Brush 30k bước" job --job-id <job_id>
tar -C /opt/real2sim/state/demo/library -czf aisle_cw_demo.tgz aisle-cw
```

Mang `aisle_cw_demo.tgz` về máy demo, giải nén vào thư mục thư viện
(`PRODUCT_DEMO_DIR`, mặc định `data/demo/library`). Mỗi thư mục con là một video
mẫu (id = tên thư mục) hiện ở bước "Tải video lên" của Scene mới. Bundle tự kiểm
checksum từng file khi phục vụ.

## 6. Kiểm tra nhanh

- `curl localhost:8000/api/v1/samples` liệt kê video mẫu, `origin: "pipeline_job"`.
- Studio › Scene mới › chọn video mẫu chạy đủ các bước; bước cuối mở editor.
- Editor SuperSplat cần WebGPU (Chrome/Edge mới); trình duyệt không có WebGPU sẽ
  tự chuyển sang viewer WebGL2 chỉ xem.

## Đã kiểm trên máy local (2026-09-29)

Quadro T2000 4 GB, cấu hình local cũ (trước file chung): video 200 frame → 50
frame sau stride; kiểm tra 10 s, tách frame 5 s, COLMAP 53 s, Brush 3000 bước 89 s; SOG
~1 MB render được trong Chrome (WebGL2). Chưa chạy cấu hình GPU 30k bước.
