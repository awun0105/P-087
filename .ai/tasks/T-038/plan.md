# T-038: Một công thức cài cho mọi máy GPU (`install.sh` + `doctor`), image Docker gọi chính nó

## Goal
Máy GPU nào (laptop, máy SSH thuê, image Docker) cũng dựng runtime bằng **cùng một lệnh**, ra cùng bố cục thư mục và
cùng file `runtime.env`. Hết cảnh mỗi nơi một công thức: `Dockerfile.gpu`, `docs/RUNPOD_GUIDE.md` (COLMAP 3.9.1 từ apt,
sai bản ghim) và `Makefile.studio` đang tự cài theo ba cách.

## Context
- Hiện trạng cài từng công cụ:

| Công cụ | `Dockerfile.gpu` | Laptop | `RUNPOD_GUIDE.md` |
| --- | --- | --- | --- |
| COLMAP 4.x ghim digest `b8498ebe…` | chép binary + thư viện từ image ở stage `colmap` (dòng 13–19, 43–59) | `docker run` qua `colmap-launcher.sh` | **apt 3.9.1: sai** |
| Brush 0.3.0 (sha `4f0f9a87…`) | `RUN curl` (dòng 63–71) | giải nén tay | tải tay |
| Node v22.20.0 + splat-transform 3.6.6 | `RUN curl` + `npm install` | `npm install` tay | tải tay |
| venv app | `uv pip sync requirements.lock.txt` | `.venv` | `uv` |
| KISS-ICP | venv + `requirements-lidar-odometry.lock.txt` | `make lidar-runtime` | không có |
| SAM2/gsplat/CoACD/LaMa/MoGe | `setup_scene_runtime.sh` | `setup_scene_runtime.sh` | `setup_scene_runtime.sh` |
| ObjectGS | không có | dựng tay | không có |

- `scripts/gpu/docker_entrypoint.sh` dòng 40–80 đặt mặc định cho ~25 biến runtime bằng đường dẫn trong image. Đây là
  chỗ trùng lặp thứ tư.
- Kiểm máy: `scripts/kaggle/preflight.py` (entrypoint chế độ `preflight`).
- T-036 đặt tên thư mục trên laptop `data/{reconstruction,lidar_odometry,scene,objectgs}_runtime` và biến `R2S_*`.
  T-037 có `setup_objectgs_runtime.sh`.

## Thiết kế

### Bố cục chung (laptop: `<gốc>=data`; image: `<gốc>=/opt/real2sim`)
```
<gốc>/colmap/                    bin/colmap + lib/ (COLMAP 4.x đúng digest) và wrapper bin/colmap-run
<gốc>/reconstruction_runtime/    brush/brush_app, node/, node_modules/@playcanvas/splat-transform
<gốc>/lidar_odometry_runtime/    venv KISS-ICP
<gốc>/scene_runtime/             setup_scene_runtime.sh
<gốc>/objectgs_runtime/          setup_objectgs_runtime.sh
<gốc>/runtime.env                sinh ra; chỉ đường dẫn và identity, không secret
```
Laptop: COLMAP hiện chạy qua Docker; **giữ được** bằng tuỳ chọn `--colmap=docker` (xem dưới), mặc định trên laptop là
`docker` để không đổi hành vi đang đo.

### `scripts/gpu/install.sh <gốc> [--only a,b] [--skip a,b] [--colmap=binary|docker] [--objectgs-wheels <dir>] [--skip-gpu-check]`
- Mỗi công cụ là một hàm `install_<tên>` trong `scripts/gpu/install.d/<tên>.sh` (source vào): `colmap`, `brush`,
  `splat`, `lidar_odometry`, `scene` (gọi `setup_scene_runtime.sh`), `objectgs` (gọi `setup_objectgs_runtime.sh`).
- Mỗi hàm idempotent: có file `.r2s-installed` ghi phiên bản công thức; khớp thì bỏ qua.
- Phiên bản ghim ở **một file**: `configs/runtime/pins.env` (BRUSH_VERSION, BRUSH_SHA, NODE_VERSION, NODE_SHA,
  SPLAT_TRANSFORM_VERSION, COLMAP_IMAGE digest, COLMAP_TARBALL_URL, COLMAP_TARBALL_SHA, MICROMAMBA...). `Dockerfile.gpu`,
  `install.d/*` đều đọc từ đây; xoá các ARG trùng trong Dockerfile.
- Cuối cùng ghi `<gốc>/runtime.env` (ghi file tạm rồi `mv`), gồm các biến `R2S_*` và `PRODUCT_*` về đường dẫn runtime
  mà `docker_entrypoint.sh` dòng 40–80 đang đặt, cộng `PRODUCT_OBJECTGS_*`. Không ghi DATABASE_URL, khoá hay đường dẫn
  dữ liệu.
- Kiểm hệ thống trước khi cài: `install.sh --check-system` in gói apt còn thiếu (danh sách lấy từ `Dockerfile.gpu`
  dòng 37–42, chuyển vào `configs/runtime/apt-packages.txt`). Có quyền root và thêm `--apt` thì tự `apt-get install`.

### COLMAP không cần Docker (`--colmap=binary`)
Pod SSH thường không chạy được Docker. Tạo **gói nhị phân** một lần:
- `scripts/gpu/export_colmap_binary.sh <out.tar.zst>`: trên máy có Docker, `docker create` từ `COLMAP_IMAGE` ghim, chép
  đúng các file mà stage `colmap` của `Dockerfile.gpu` đang chép (dòng 16–19), nén, in sha256.
- File nén đưa lên **GitHub Release** của repo (chủ dự án làm, vì cần quyền), URL + sha256 ghi vào `pins.env`.
- `install_colmap --colmap=binary` tải, kiểm sha256, giải nén vào `<gốc>/colmap`, tạo wrapper như `Dockerfile.gpu`
  dòng 54–59, chạy hai lệnh kiểm `colmap help | grep "^COLMAP 4\."` và `pose_prior_mapper -h`.
- Identity giữ `colmap-image-sha256:<digest>` vì byte của binary là của đúng image đó.

### `doctor`
- `scripts/gpu/doctor.sh <gốc>`: `source <gốc>/runtime.env` rồi `python -m scripts.kaggle.preflight`. Exit khác 0 khi
  thiếu mục bắt buộc. `install.sh` gọi doctor ở cuối.

### Image Docker
`Dockerfile.gpu` sau task:
```
FROM ${COLMAP_IMAGE} AS colmap      # giữ stage này, tránh tải gói nhị phân trong lúc build
FROM nvidia/cuda:12.6.3-devel-ubuntu24.04
COPY configs/runtime/ scripts/gpu/ ...      # chỉ những gì install.sh cần, để cache lớp tốt
RUN apt-get install $(cat configs/runtime/apt-packages.txt) ...
COPY --from=colmap /export /opt/real2sim/colmap
RUN scripts/gpu/install.sh /opt/real2sim --skip colmap --skip-gpu-check
COPY . .
```
- `install_colmap` khi thấy `<gốc>/colmap/bin/colmap` có sẵn (đã COPY) chỉ tạo wrapper và kiểm.
- `docker_entrypoint.sh`: thay khối mặc định dòng 40–80 bằng `set -a; source /opt/real2sim/runtime.env; set +a`, giữ
  quy tắc "biến người vận hành đã cấp thì không ghi đè" (source vào biến tạm rồi chỉ export biến chưa có).
- Đường dẫn trong container đổi theo bố cục chung: `/opt/real2sim/runtime` → `/opt/real2sim/reconstruction_runtime`,
  `/opt/real2sim/lidar_runtime` → `/opt/real2sim/lidar_odometry_runtime`. Cập nhật `docker-compose.gpu.yml`,
  `deploy/studio/production.env.example` và chạy `python -m scripts.studio.deploy_env render --examples` để sinh lại
  ba file `*.env.example` (có test giữ chúng khớp). Đổi tên biến trong các file này sang `R2S_*` (T-036 để lại).
- Mặc định `src/services/reconstruction/lidar/odometry.py:173` đổi theo đường dẫn mới.

## Files
- Tạo: `scripts/gpu/install.sh`, `scripts/gpu/install.d/{colmap,brush,splat,lidar_odometry,scene,objectgs}.sh`,
  `scripts/gpu/doctor.sh`, `scripts/gpu/export_colmap_binary.sh`, `configs/runtime/pins.env`,
  `configs/runtime/apt-packages.txt`, `tests/test_gpu/test_install_scripts.py`.
- Sửa: `Dockerfile.gpu`, `scripts/gpu/docker_entrypoint.sh`, `docker-compose.gpu.yml`, `deploy/studio/*.env.example`,
  `src/services/reconstruction/lidar/odometry.py` (mặc định), `Makefile.studio` (target `gpu-setup`, `doctor`; các target
  cũ `lidar-runtime`, `objectgs-runtime` gọi `install.sh --only`), `docs/RUNPOD_GUIDE.md` (viết lại mục cài),
  `scripts/gpu/README.md`, `deploy/studio/OVERVIEW.md`, test đóng gói liên quan.

## Steps
1. `pins.env` + `apt-packages.txt` + `install.d/*.sh` + `install.sh` + `doctor.sh`. Test tĩnh: `bash -n` mọi script;
   mọi `curl` có kiểm sha256; không còn số phiên bản nào chép tay ngoài `pins.env` (quét `Dockerfile.gpu`, `install.d`,
   `Makefile.studio`); `runtime.env` sinh ra từ một gốc giả chỉ có biến trong danh sách cho phép. Commit.
2. `export_colmap_binary.sh` + nhánh `--colmap=binary`. Chạy thật trên laptop (có Docker): tạo gói, giải nén vào thư mục
   tạm, chạy hai lệnh kiểm COLMAP. Ghi sha256 vào report; **không tự đưa lên GitHub Release**, báo chủ dự án làm, rồi điền
   URL vào `pins.env` (để trống kèm chú thích nếu chưa có). Commit.
3. Laptop: `make -f Makefile.studio gpu-setup` trên `data/` phải nhận ra mọi runtime đã có (không cài lại gì) và sinh
   `data/runtime.env`; `doctor` PASS. So các biến trong `data/runtime.env` với `scripts/gpu/studio.env` (chỉ phần đường
   dẫn runtime): phải trỏ cùng chỗ. Commit phần Makefile.
4. `Dockerfile.gpu` + `docker_entrypoint.sh` + compose + deploy examples. Test đóng gói hiện có
   (`tests/test_packaging/`) xanh, sửa test theo đường dẫn mới. **Không build image** (laptop thiếu ổ; T-039 làm).
   Thêm vào cuối `Dockerfile.gpu` ghi chú "build thật ở T-039". Commit.
5. Tài liệu: `RUNPOD_GUIDE.md` mục cài còn: thuê pod → `git clone` → `sudo scripts/gpu/install.sh /opt/real2sim --apt
   --colmap=binary` → `doctor`; và cách dùng image (T-039). Bỏ hướng dẫn COLMAP apt. Commit.

## Acceptance criteria
1. Một lệnh `install.sh <gốc>` dựng đủ runtime; chạy lại không cài lại.
2. Phiên bản Brush, Node, splat-transform, COLMAP, micromamba chỉ có ở `configs/runtime/pins.env`. Ngoại lệ được giữ:
   ghim riêng trong `setup_scene_runtime.sh` (SAM2, LaMa, MoGe) và commit ObjectGS trong `objectgs.py`.
3. `Dockerfile.gpu` và `docker_entrypoint.sh` không còn tự cài hay tự đặt đường dẫn công cụ ngoài `install.sh`/`runtime.env`.
4. COLMAP cài được không cần Docker, đúng bản 4.x và có `pose_prior_mapper`.
5. Laptop: `gpu-setup` không phá runtime đang chạy; `doctor` PASS; stack không cần khởi động lại.
6. `RUNPOD_GUIDE.md` không còn COLMAP apt.

## Tests required
```
.venv/bin/python -m pytest tests/test_gpu tests/test_packaging tests/test_kaggle -q
for f in scripts/gpu/install.sh scripts/gpu/install.d/*.sh scripts/gpu/doctor.sh scripts/gpu/export_colmap_binary.sh; do bash -n "$f"; done
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
Cần T-036 và T-037 accepted trước.
