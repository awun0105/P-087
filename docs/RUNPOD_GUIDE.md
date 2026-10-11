# Hướng Dẫn Triển Khai & Vận Hành Real2Sim Studio Trên RunPod

> **Mục tiêu:** Hướng dẫn từng bước dành cho các thành viên trong nhóm để triển khai hệ thống Real2Sim Studio trên Cloud GPU (RunPod), kết nối bằng VS Code Remote - SSH, nạp dữ liệu hoàn chỉnh (`r2s-studio-data.zip`) và trình diễn Web Studio trực tiếp trên trình duyệt laptop mà không gây nóng máy hoặc tốn dung lượng ổ cứng.

---

## Mục lục
1. [Tại sao dùng RunPod thay vì chạy trên máy cá nhân?](#1-tại-sao-dùng-runpod)
2. [Chuẩn bị trước khi deploy](#2-chuẩn-bị-trước-khi-deploy)
3. [Bước 1: Khởi tạo Pod trên RunPod](#bước-1-khởi-tạo-pod-trên-runpod)
4. [Bước 2: Cấu hình VS Code Remote - SSH](#bước-2-cấu-hình-vs-code-remote---ssh)
5. [Bước 3: Thiết lập môi trường sạch trên Pod](#bước-3-thiết-lập-môi-trường-sạch-trên-pod)
6. [Bước 4: Nạp dữ liệu hoàn chỉnh (r2s-studio-data.zip)](#bước-4-nạp-dữ-liệu-hoàn-chỉnh-r2s-studio-datazip)
7. [Bước 5: Khởi động Backend & Frontend](#bước-5-khởi-động-backend--frontend)
8. [Bước 6: Truy cập Web Studio từ Laptop (Port Forwarding)](#bước-6-truy-cập-web-studio-từ-laptop)
9. [Xử lý sự cố thường gặp (Troubleshooting)](#xử-lý-sự-cố-thường-gặp)

---

## 1. Tại sao dùng RunPod?

- **Không tốn tài nguyên laptop:** Các tác vụ 3D Gaussian Splatting (3DGS), COLMAP và xử lý dữ liệu point cloud yêu cầu GPU rời và VRAM lớn (tối thiểu 16–24 GB).
- **Mạng Datacenter siêu nhanh (10 Gbps):** File dữ liệu lớn như `r2s-studio-data.zip` (gần 3 GB) tải trên RunPod chỉ mất **20–30 giây**, không tốn băng thông gia đình.
- **Chi phí thấp:** Thuê **RTX 3090** (24GB VRAM) chỉ khoảng **$0.30 – $0.40 / giờ**. Chạy cả buổi làm việc chỉ tốn khoảng $1 – $2.

---

## 2. Chuẩn bị trước khi deploy

1. **Tài khoản RunPod:** Đăng ký tại [runpod.io](https://www.runpod.io) và nạp trước $5 – $10.
2. **SSH Key trên máy tính của bạn:**
   - Mở Terminal / PowerShell trên máy tính cá nhân và chạy:
     ```bash
     ssh-keygen -t ed25519 -C "my-runpod-key"
     ```
     *(Bấm `Enter` 3 lần để lưu mặc định tại `~/.ssh/id_ed25519` và không đặt mật khẩu).*
   - In Public Key ra màn hình:
     - Trên Windows (PowerShell): `Get-Content ~/.ssh/id_ed25519.pub`
     - Trên macOS / Linux: `cat ~/.ssh/id_ed25519.pub`
   - Đăng nhập RunPod -> Bấm vào Avatar góc trên bên phải -> **Settings** -> **SSH Public Keys** -> Bấm **Add SSH Key** -> Dán nội dung key vào.
3. **GitHub Personal Access Token (PAT):**
   - Repo dự án là private. Để clone được trên RunPod, vào GitHub -> **Settings** -> **Developer settings** -> **Personal access tokens** -> **Tokens (classic)**.
   - Bấm **Generate new token (classic)**, tích chọn quyền **`repo`** và copy chuỗi token (`ghp_...`).
4. **Cài đặt VS Code Extension:** Cài extension **Remote - SSH** (`ms-vscode-remote.remote-ssh`) trên VS Code của máy bạn.

---

## 3. Bước 1: Khởi tạo Pod trên RunPod

1. Vào tab **Pods** -> Bấm **Deploy**:
   - **GPU:** Chọn **1x RTX 3090** (hoặc **RTX 4090**) — có **24 GB VRAM**.
     > ⚠️ **Lưu ý quan trọng:** Không chọn card dòng máy chủ như **NVIDIA L4** vì driver máy chủ chỉ có CUDA, thiếu thư viện đồ họa Vulkan cần thiết cho Brush 3DGS.
2. **Template:** Chọn template chính thức **RunPod PyTorch 2.4.0** (`runpod/pytorch:2.4.0-py311-cuda12.4.1-devel-ubuntu22.04`).
3. **Ổ đĩa (Storage):**
   - **Container Disk:** `20 GB`
   - **Volume Disk:** `60 GB` (Dùng **Volume Disk / Local NVMe** thông thường, **KHÔNG** dùng Global / Network Volume để đảm bảo tốc độ đọc ghi cao nhất).
4. **Biến môi trường (Bắt buộc):**
   - Bấm **Edit Template / Environment Variables**:
   - Thêm biến môi trường:
     - Key: `NVIDIA_DRIVER_CAPABILITIES`
     - Value: `all`
5. Bấm **Deploy On-Demand**.

---

## 4. Bước 2: Cấu hình VS Code Remote - SSH

Khi Pod chuyển sang trạng thái **Running**:
1. Bấm nút **Connect** trên thẻ Pod -> Chọn tab **SSH over exposed TCP**:
   - RunPod sẽ hiển thị thông số kết nối, ví dụ:
     `ssh root@194.26.196.45 -p 12345 -i ~/.ssh/id_ed25519`
   - Hãy lưu lại **IP** (`194.26.196.45`) và **Port** (`12345`).

2. Mở file cấu hình SSH trên máy tính của bạn:
   - File nằm tại: `C:\Users\<username>\.ssh\config` (Windows) hoặc `~/.ssh/config` (macOS/Linux).
   - Thêm vào cuối file đoạn sau:
     ```ssh
     Host runpod-real2sim
         HostName 194.26.196.45
         User root
         Port 12345
         IdentityFile ~/.ssh/id_ed25519
         ServerAliveInterval 60
     ```
     *(Thay IP và Port bằng số thật của bạn).*

3. **Mở kết nối từ VS Code:**
   - Trong VS Code, bấm `Ctrl + Shift + P` (hoặc `Cmd + Shift + P` trên Mac) -> gõ `Remote-SSH: Connect to Host...` -> Chọn `runpod-real2sim`.
   - Chọn hệ điều hành: **Linux**.
   - Cửa sổ VS Code mới sẽ kết nối vào RunPod.
   - Chọn menu **File -> Open Folder...** -> Điền `/workspace` và bấm OK.

---

## 5. Bước 3: Thiết lập môi trường sạch trên Pod

Mở Terminal trong VS Code (`Ctrl + \``) và chạy các lệnh dưới đây:

### 5.1. Kiểm tra phần cứng & Vulkan
```bash
nvidia-smi
vulkaninfo --summary | grep -E "deviceName|deviceType"
```
*(RTX 3090 sẽ in ra `NVIDIA GeForce RTX 3090 / DISCRETE_GPU` ngay lập tức).*

### 5.2. Cài đặt các gói công cụ hệ điều hành
```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y colmap ffmpeg libvulkan1 vulkan-tools xz-utils curl git
```
> ⚠️ **Lưu ý:** Không chạy `apt-get install libnvidia-gl-*` vì RunPod đã mount sẵn driver từ máy chủ vật lý.

### 5.3. Clone Source Code
```bash
cd /workspace
git clone https://<GITHUB_PAT>@github.com/AI20K-Build-Phase-Cohort-4/P-087.git real2sim
cd /workspace/real2sim
git checkout feat/sim    # Hoặc nhánh bạn đang làm việc
```
*(Thay `<GITHUB_PAT>` bằng Personal Access Token bạn đã tạo ở Bước 2).*

### 5.4. Cài đặt Python 3.12 & Thư viện dự án qua `uv`
```bash
pip install uv
mkdir -p /workspace/r2s/runtime

# Tạo virtual environment và đồng bộ lockfile
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements.lock.txt
```

### 5.5. Cài đặt Brush 0.3.0 & Node.js + splat-transform
```bash
# 1. Cài đặt Brush 0.3.0 (3DGS Trainer)
mkdir -p /workspace/r2s/runtime/brush
curl -L -o /workspace/r2s/runtime/brush.tar.xz https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/brush-app-x86_64-unknown-linux-gnu.tar.xz
tar --no-same-owner -xJf /workspace/r2s/runtime/brush.tar.xz -C /workspace/r2s/runtime/brush --strip-components=1
rm /workspace/r2s/runtime/brush.tar.xz
chmod +x /workspace/r2s/runtime/brush/brush_app

# Kiểm tra Brush
/workspace/r2s/runtime/brush/brush_app --version

# 2. Cài đặt Node.js v22 + splat-transform
mkdir -p /workspace/r2s/runtime/node
curl -L -o /workspace/r2s/runtime/node.tar.xz https://nodejs.org/dist/v22.20.0/node-v22.20.0-linux-x64.tar.xz
tar --no-same-owner -xJf /workspace/r2s/runtime/node.tar.xz -C /workspace/r2s/runtime/node --strip-components=1
rm /workspace/r2s/runtime/node.tar.xz

export PATH="/workspace/r2s/runtime/node/bin:$PATH"
cd /workspace/r2s/runtime
npm install --silent @playcanvas/splat-transform@3.6.6
cd /workspace/real2sim
```

### 5.6. Cài đặt dependencies cho Frontend
```bash
cd /workspace/real2sim/frontend
npm ci
cd /workspace/real2sim
```

### 5.7. Cài đặt Scene Runtime cho SAM2, SAMPro3D & LaMa (Tùy chọn — để tách vật thể nâng cao)
> 💡 **Lưu ý:** Nếu không cài bước này, hệ thống sẽ tự động dùng **Fallback hình học** (`geometric_voxel_components_v1`) tạo hộp bounding box cho vật thể mà không bị lỗi. Nếu bạn muốn chạy phân đoạn AI thật bằng **SAM2 + SAMPro3D** và vá nền bằng **LaMa** (ADR 0006 & 0007), hãy chạy lệnh cài đặt:

```bash
# Cài đặt header Python 3.12 và build tools (gsplat cần để biên dịch kernel CUDA)
apt-get install -y python3.12-dev build-essential ninja-build

# Chạy script tự động thiết lập venv riêng data/scene_runtime và tải sẵn các model SAM2 + LaMa + MoGe:
bash scripts/gpu/setup_scene_runtime.sh /workspace/r2s/runtime/scene_runtime
```
*Script sẽ tự động cài `sam-2`, `gsplat`, `coacd`, `lpips`, và tải 3 file checkpoint (`sam2.1_hiera_tiny.pt`, `big-lama.pt`, `moge-2-vitb-normal.pt`) vào `/workspace/r2s/runtime/scene_runtime`.*

---

## 6. Bước 4: Nạp dữ liệu hoàn chỉnh (`r2s-studio-data.zip`)

Thư mục `r2s-studio-data.zip` chứa 5 scene kho hoàn chỉnh, 2 demo bundles, 34 asset previews và database SQLite `runtime.db`. 

### 6.1. Tải file ZIP từ Google Drive vào Pod
Tại thư mục `/workspace/real2sim`:
```bash
pip install gdown

# Tải file r2s-studio-data.zip trực tiếp về thư mục gốc
# (Thay link bên dưới bằng link Drive hoặc ID file)
gdown "https://drive.google.com/drive/folders/1NqZmn3iJO6UuA4YCPq295jwMNMXDdr-f" --folder -O /workspace/real2sim/
```

### 6.2. Bung dữ liệu bằng Python (KHÔNG dùng Docker Compose)
> 💡 **Khác biệt quan trọng:** Trong container RunPod **không có Docker daemon**, nên không chạy `docker compose up`. Script `scripts/studio/data_package.py` được viết hoàn toàn bằng thư viện chuẩn Python, bung dữ liệu trực tiếp trong 5 giây:

```bash
cd /workspace/real2sim
python scripts/studio/data_package.py --root . unpack real2sim-team-data/r2s-studio-data.zip --force
```
Lệnh này sẽ tự động giải nén toàn bộ 1.421 files payload, tạo thư mục `data/studio_local/runtime.db` và các artifacts sẵn sàng 100%.

---

### 7.1. Cấu hình file `.env`
Tạo file `.env` tại `/workspace/real2sim/.env` chứa đầy đủ cấu hình Web Studio và Worker GPU:
```bash
cat > /workspace/real2sim/.env << 'EOF'
APP_ENV=development
AUTH_REQUIRED=true
AUTH_COOKIE_SECURE=false
OPENAI_API_KEY=not-used-by-studio
DATABASE_URL=sqlite:///./data/studio_local/runtime.db
ARTIFACT_ROOT=./data/studio_local/artifacts
PRODUCT_WORKER_ROOT=./data/studio_local/workers
PRODUCT_DEMO_DIR=./data/demo/library
PRODUCT_ASSET_PREVIEW_DIR=./data/asset_previews
PRODUCT_RERUN_RECORDING_DIR=./data/rerun_recordings
PRODUCT_TRASH_ROOT=./data/studio_local/trash
CHROMA_PERSIST_DIR=./data/studio_local/chroma

# Cấu hình xử lý và Runtime Manifest
PRODUCT_PROCESSING_CONFIG=/workspace/real2sim/configs/product/processing_presets_v1.json
PRODUCT_RUNTIME_MANIFEST=/workspace/r2s/runtime_manifest.json
PRODUCT_GEOMETRY_CONFIG=/workspace/real2sim/configs/product/geometry_v1.json

# COLMAP (apt native)
REC03_COLMAP_COMMAND='["colmap"]'
REC03_COLMAP_RUNTIME_IDENTITY=colmap-apt-3.9.1
REC03_COLMAP_TIMEOUT_SECONDS=7200

# Brush 3DGS Trainer
REC04_BRUSH_COMMAND='["/workspace/r2s/runtime/brush/brush_app"]'
REC04_BRUSH_EXPECTED_VERSION=0.3.0
REC04_BRUSH_RUNTIME_IDENTITY=brush-v0.3.0-linux-archive-sha256:4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20
REC04_BRUSH_ENVIRONMENT='{"RUST_LOG":"info,wgpu_core=warn","VK_ICD_FILENAMES":"/usr/share/vulkan/icd.d/nvidia_icd.json"}'
REC04_BRUSH_TIMEOUT_SECONDS=14400

# Splat-transform & Voxel
REC04_SPLAT_MODULE_PATH=/workspace/r2s/runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs
REC05_VOXEL_CLI=/workspace/r2s/runtime/node_modules/@playcanvas/splat-transform/bin/cli.mjs
REC05_VOXEL_MODULE_PATH=/workspace/r2s/runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs

# Scene Runtime cho tách vật thể AI (SAM2, SAMPro3D, LaMa, MoGe)
PRODUCT_SCENE_RUNTIME_PYTHON=/workspace/r2s/runtime/scene_runtime/bin/python
PRODUCT_SAM2_CHECKPOINT=/workspace/r2s/runtime/scene_runtime/checkpoints/sam2.1_hiera_tiny.pt
PRODUCT_LAMA_CHECKPOINT=/workspace/r2s/runtime/scene_runtime/weights/big-lama.pt
REC06_MOGE_PYTHON=/workspace/r2s/runtime/scene_runtime/bin/python
REC06_MOGE_MODEL=/workspace/r2s/runtime/scene_runtime/weights/moge-2-vitb-normal.pt
REC04_BRUSH_LPIPS_PYTHON=/workspace/r2s/runtime/scene_runtime/bin/python
EOF

# Nạp Node.js vào PATH và sinh Runtime Manifest chứng nhận môi trường máy
export PATH="/workspace/r2s/runtime/node/bin:$PATH"
source .venv/bin/activate
set -a; source .env; set +a
python -m scripts.gpu.make_runtime_manifest --out /workspace/r2s/runtime_manifest.json
```

### 7.2. Chạy Backend (FastAPI)
Trong Terminal 1 của VS Code:
```bash
cd /workspace/real2sim
source .venv/bin/activate
set -a; source .env; set +a
uvicorn src.main:app --host 0.0.0.0 --port 8000
```
Backend sẽ báo: `Application startup complete` trên port `8000`.

### 7.3. Chạy Frontend (Next.js)
Mở Terminal 2 trong VS Code:
```bash
cd /workspace/real2sim/frontend
export PATH="/workspace/r2s/runtime/node/bin:$PATH"

# Cách 1 (Khuyên dùng khi chia sẻ tunnel): Chạy chế độ Production (nhẹ, nhanh, không bị lỗi dev WebSocket/HMR)
npm run build
npm run start -- -p 3000

# Cách 2: Chạy chế độ Dev (chỉ dùng khi đang sửa code giao diện)
# npm run dev -- -p 3000
```
Frontend sẽ báo: `Ready in ... http://localhost:3000`.

### 7.4. Chạy GPU Reconstruction Worker (Tùy chọn — nếu cần xử lý video mới)
Nếu bạn tạo dự án mới từ video thô (như dataset TorWIC) cần chạy COLMAP và huấn luyện Brush 3DGS:
Mở Terminal 3 trong VS Code:
```bash
cd /workspace/real2sim
source .venv/bin/activate
set -a; source .env; set +a
python -m scripts.gpu.run_workers
```

---

## 8. Bước 6: Truy cập & Chia sẻ Web Studio cho Cả Nhóm

Web Studio chạy Frontend trên port `3000` (Next.js) và tự động chuyển tiếp toàn bộ API sang Backend (port `8000`).

### 8.1. Cách 1: Truy cập cá nhân qua VS Code Port Forwarding (Bảo mật, nội bộ)
1. Trong giao diện VS Code (Remote - SSH), nhìn xuống thanh trạng thái bên dưới, mở tab **PORTS** (cạnh Terminal):
2. Bấm **Forward a Port**:
   - Thêm port: **`3000`** (Frontend)
   - Thêm port: **`8000`** (Backend API)
3. Mở trình duyệt trên máy của bạn và truy cập: **`http://localhost:3000`**

### 8.2. Cách 2: Tạo link công khai (Public HTTPS) chia sẻ cho nhóm (Cloudflare Tunnel)
Để teammate hoặc người khác mở trực tiếp từ xa mà không cần SSH hay cài phần mềm:

Mở một Terminal trên RunPod và chạy:
```bash
# Tải cloudflared (chỉ cần chạy lần đầu)
curl -L -o /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared

# Tạo đường hầm công khai (LƯU Ý cờ --http-host-header để tránh lỗi Unauthorized Host/HMR)
cloudflared tunnel --http-host-header localhost:3000 --url http://localhost:3000
```
Terminal sẽ in ra một đường link công khai dạng:
```text
Your quick Tunnel has been created! Visit it at:
https://random-subdomain.trycloudflare.com
```
> 💡 Gửi link `https://...trycloudflare.com` cho nhóm, bất kỳ ai cũng có thể vào dùng ngay lập tức từ trình duyệt trên điện thoại hoặc máy tính cá nhân.

*(Tùy chọn khác không cần tải thêm file: `export PATH="/workspace/r2s/runtime/node/bin:$PATH" && npx localtunnel --port 3000`)*

### 8.3. Tài khoản đăng nhập & Đổi mật khẩu
Đăng nhập vào Web Studio bằng tài khoản seed:
- **Tài khoản Reviewer:** `reviewer@real2sim.com` (hoặc `reviewer@real2sim.dev`) / Mật khẩu: `password12345`
- **Tài khoản Editor:** `editor@real2sim.com` (hoặc `editor@real2sim.dev`) / Mật khẩu: `password12345`

*Nếu muốn đặt lại mật khẩu cho tất cả tài khoản về `password12345`, chạy script sau tại `/workspace/real2sim`:*
```bash
source .venv/bin/activate
python -c "
import sqlite3, json
from src.services.orchestration.auth.passwords import hash_password
conn = sqlite3.connect('data/studio_local/runtime.db')
h = hash_password('password12345')
for uid, em, p in conn.execute('SELECT user_id, email, payload FROM r2s_users').fetchall():
    d = json.loads(p); d['password_hash'] = h; d['active'] = True
    conn.execute('UPDATE r2s_users SET payload = ? WHERE user_id = ?', (json.dumps(d), uid))
conn.commit(); conn.close()
print('Đã đổi mật khẩu tất cả tài khoản về: password12345')
"
```

---

## 9. Bước 7: Quy trình Tái dựng End-to-End từ Video Thô & Đóng gói Demo

Khi upload video mới (ví dụ TorWIC Aisle CW 546 frames) qua Web Studio:

### 9.1. Tự động xác nhận tỉ lệ Mét (Bỏ qua lỗi thiếu WebGL2 trên trình duyệt remote)
Khi pipeline chạy xong COLMAP & Brush 3DGS, hệ thống sẽ chờ ở bước **Xác nhận tỉ lệ mét** (REC-06). Nếu trình duyệt qua remote SSH không có WebGL2/WebGPU để click chọn điểm trên canvas, bạn có thể xác nhận tự động bằng Python:
```bash
python -c "
from src.services.orchestration.projects.registry import get_project_registry
from src.services.orchestration.jobs.metric import MetricConfirmationService
from src.services.reconstruction.metric_port import UserMetricInput
from src.models.contracts.manifests import StageId

registry = get_project_registry()
svc = MetricConfirmationService(registry)
job_id = '<JOB_ID>' # Thay bằng Job ID của bạn, ví dụ job-ed9cf7739a70

with registry.persistence.database.transaction() as tx:
    for row in tx.execute('SELECT job_id, current_stage, payload FROM r2s_jobs WHERE job_id = ?', (job_id,)):
        import json
        job_data = json.loads(row[2])
        for att in reversed(job_data.get('attempts', [])):
            for stage in att.get('stages', []):
                if stage.get('stage_id') == StageId.METRIC_CANONICALIZE and stage.get('stage_status') == 'WAITING_CONFIRMATION':
                    prev = stage.get('preview', {})
                    scale = prev.get('recommended_scale_m_per_unit', 1.0)
                    floor_z = prev.get('recommended_floor_z', 0.0)
                    ref = svc.confirm(job_id, prev.get('preview_checksum'), UserMetricInput(scale, floor_z))
                    print('==> XÁC NHẬN THÀNH CÔNG! Ref:', ref.artifact_uri)
"
```

### 9.2. Chạy bước Hoàn tất (Hình học, Voxel & Bundle)
```bash
set -a; source .env; set +a
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.services.orchestration.projects.registry import get_project_registry
from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.runner import run_finalize_job

registry = get_project_registry()
job_id = '<JOB_ID>'
registry.transition_job(job_id, TransitionRequest(target_status=JobStatus.QUEUED))
completed = run_finalize_job(job_id)
print('==> KẾT QUẢ JOB STATUS:', completed.status)
"
```

### 9.3. Xuất Demo Bundle & Đóng gói ZIP dữ liệu cho cả nhóm
```bash
# 1. Export sang thư viện demo
python -m scripts.demo.export_demo_bundle \
  --out data/demo/library/torwic_scene_01 \
  --title "TorWIC Warehouse Scene 1" \
  --dataset "TorWIC" \
  --sequence "01_LoiDi_Kho_Thuan_Aisle_CW" \
  job --job-id <JOB_ID>

# 2. Đóng gói file ZIP hoàn chỉnh (database, 3DGS, collision meshes, demo)
python scripts/studio/data_package.py --root . pack --out /workspace/r2s-torwic-complete.zip --keep-seed-accounts

# 3. Upload lên GoFile (miễn phí, siêu tốc 1-2 phút có link chia sẻ ngay)
curl -F "file=@/workspace/r2s-torwic-complete.zip" https://upload.gofile.io/contents/uploadfile
```

Sau khi upload xong, bạn có thể **Stop Pod ngay lập tức** để tiết kiệm chi phí! Teammate chỉ cần tải file `.zip` về và chạy lệnh `python scripts/studio/data_package.py --root . unpack r2s-torwic-complete.zip --force` là có đầy đủ toàn bộ scene 60 FPS trên máy local.

### 9.4. Tách lại vật thể bằng SAM2 & LaMa (Re-objectify) cho Scene đã có sẵn
Nếu trước đó bạn đã dựng xong 3DGS & collision mesh nhưng chỉ ở chế độ fallback hình học (`note: chưa cấu hình runtime SAM2; dùng tách hình học`), sau khi đã cài Mục 5.7 bạn có thể **chạy lại bước tách vật thể bằng SAM2 & LaMa** mà **KHÔNG CẦN train lại 3DGS hay chạy lại COLMAP** (chỉ mất khoảng 2–3 phút):

```bash
set -a; source .env; set +a
python scripts/scene/reobjectify.py <JOB_ID>
```
Lệnh này sẽ đọc `ReconstructionBundle` có sẵn, dùng SAM2 + SAMPro3D phân đoạn 3D point cloud, dùng LaMa vá nền, và xuất phiên bản SceneIR mới (`rev-002`) với từng Gaussian gán riêng cho từng vật thể và tạo collider phân rã lồi CoACD!

---

## 10. Xử lý sự cố thường gặp (Troubleshooting)

| Lỗi | Nguyên nhân | Cách khắc phục |
|---|---|---|
| `fatal: Authentication failed for 'https://github.com/...'` | GitHub không cho dùng password thông thường qua HTTPS | Dùng GitHub Personal Access Token (`https://<TOKEN>@github.com/...`) hoặc cấu hình SSH Key trên RunPod. |
| `Cannot connect to the Docker daemon` | Chạy lệnh `docker compose` bên trong RunPod | Không dùng Docker Compose trên RunPod. Chạy trực tiếp `python scripts/studio/data_package.py --root . unpack r2s-studio-data.zip`. |
| `ERROR_INCOMPATIBLE_DRIVER` khi gọi `vulkaninfo` | Chọn GPU máy chủ (như L4) hoặc thiếu biến quyền đồ họa | Phải chọn GPU **RTX 3090 / 4090 / RTX 4000 Ada** và đặt biến môi trường `NVIDIA_DRIVER_CAPABILITIES=all` lúc tạo Pod. |
| `tar: Cannot change ownership to uid 1001, gid 1001: Operation not permitted` | Phân vùng `/workspace` là network mount không cho phép lệnh `tar` chạy quyền root đổi ownership gốc trong archive | Thêm cờ `--no-same-owner` vào lệnh `tar` (ví dụ `tar --no-same-owner -xJf ...`). |
| `Missing API key for LLM provider: openai` | `Settings` yêu cầu key LLM khi khởi tạo | Thêm `OPENAI_API_KEY=not-used-by-studio` vào file `.env`. |
| `VISUAL_TIMEOUT` trong quá trình Brush 3DGS | Scene nhiều frame (ví dụ > 500 frames) vượt ngưỡng timeout 1800s | Đặt `REC04_BRUSH_TIMEOUT_SECONDS=14400` trong file `.env`. |
| `Voxel mutation requires X blocks, exceeding 32-bit mutable-grid limit` | 3DGS sinh các hạt floater khổng lồ làm phình bounding box | Đã fix: đặt `max_gaussian_scale_log=1.0` trong `configs/product/geometry_v1.json` để loại bỏ các hạt scale > 2.7m. |
| `note: chưa cấu hình runtime SAM2; dùng tách hình học` | Chưa cài Mục 5.7 hoặc thiếu biến `PRODUCT_SAM2_CHECKPOINT` | Đây là fallback an toàn, không hỏng job. Để chạy SAM2 thật, làm theo Mục 5.7 rồi chạy `python scripts/scene/reobjectify.py <JOB_ID>`. |
| `Field required: expected_version, runtime_identity` | Worker không đọc được biến môi trường từ `.env` | Chạy `set -a; source .env; set +a` trước khi chạy script Python worker. |
| Quên tắt Pod tốn tiền | Pod vẫn tính phí khi đang chạy | Sau khi upload file zip lên GoFile/GDrive, vào console RunPod bấm **Stop Pod** (hoặc **Terminate Pod**). |
