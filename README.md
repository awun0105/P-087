# Real2Sim Studio — Warehouse / Indoor AMR MVP

> Chuyển dữ liệu RGB/LiDAR của kho trong nhà thành scene 3D có thể chỉnh sửa, kiểm định trong NVIDIA Isaac Sim và phát hành có truy vết.

**Team:** P-087 — VinUni AI20K Build Phase, Cohort 4

**Trạng thái (2026-09-29):** Studio MVP chạy được luồng video → 3DGS: upload video,
EX-REC chạy thật (kiểm video → xác nhận dữ liệu → tách frame → COLMAP → Brush → SOG),
xem/chỉnh scene trong editor SuperSplat (WebGPU) hoặc viewer WebGL2. Đã chạy thật
trên GPU local (Quadro T2000); editor WebGPU chưa kiểm trên browser có GPU; EX-SCENE,
EX-SIM và Isaac Sim chưa nối vào luồng. Chi tiết: [plan MVP](docs/plans/active/2026-09-29-mvp-studio-demo.md).

**Phạm vi P0:** Warehouse / Indoor AMR, primary RGB workflow, NVIDIA Isaac Sim

## Vấn đề (Problem)

Kỹ sư mô phỏng thường nhận video hoặc dữ liệu LiDAR của nhà kho, nhưng không thể đưa thẳng chúng vào Isaac Sim. Họ phải dùng nhiều công cụ để dựng mô hình 3D, chỉnh đúng kích thước, tách vật thể và tạo vùng va chạm. Công việc này tốn nhiều thời gian và dễ phát sinh lỗi.

Một mô hình 3D nhìn giống cảnh thật chưa chắc robot sử dụng được: kích thước có thể chưa theo đơn vị mét, vật thể chưa tách riêng hoặc chưa có vùng va chạm. Real2Sim Studio hướng tới giảm các bước thủ công này. Trong tuần đầu, nhóm sẽ đo thời gian của quy trình hiện tại làm mốc so sánh, sau đó mới đặt mục tiêu cải thiện cụ thể.

## Giải pháp (Solution)

Real2Sim Studio tổ chức một workflow thống nhất:

- Tái tạo Visual và Geometry từ moving-camera RGB; Registered LiDAR là geometry input tùy chọn.
- Tạo candidate object, cho phép con người xác nhận và tạo `SceneIR` có thể chỉnh sửa.
- Sinh collider/OpenUSD, chạy validation trong Isaac Sim, sau đó Reviewer approve hoặc reject.
- Lưu artifact, checksum và provenance để phát hành đúng candidate đã được kiểm tra.

**Hướng pipeline v2 (30/09/2026, [ADR 0007](./docs/decisions/0007-object-centric-hybrid-usd-pipeline.md)):**
video → scene 3D **theo vật** chỉnh sửa được (thêm/xoá/sửa vật, nền vá sẵn chỗ vật che, nhãn và
khối lượng) → xuất **USD lai** cho Isaac Sim: Gaussian để hiển thị, collider để va chạm. Đang ở pha
chạy thử; xem [plan pipeline v2](./docs/plans/active/2026-09-30-pipeline-v2.md).


## Target User

- **Primary:** Simulation / Real2Sim Engineer chuẩn bị scene cho robot và simulator.
- **Secondary:** AMR Integration Engineer và Reviewer/Tech Lead kiểm tra collision, path và release.

## Tech Stack

| Layer | Technology | Trạng thái |
|---|---|---|
| Contracts | Pydantic 2 | Foundation baseline với synthetic fixture/integration proof |
| Backend | FastAPI, Python 3.12, SQLite runtime DB | API product + Studio (upload, scene, tiến trình, thông số, video mẫu); queue worker ngoài HTTP |
| Agent scaffold | LangGraph, LangChain, multi-provider LLM | Có sẵn, chưa phải Real2Sim pipeline |
| Reconstruction | FFmpeg, COLMAP (Docker), Brush 0.3.0, splat-transform 3.6.6 (SOG nén bằng WebGPU) | Chạy thật local cho luồng video → 3DGS; Open3D chỉ dùng trong offline tooling; OpenMVS chưa tích hợp |
| Scene/Object | SAM2, Open3D, NumPy | Planned integration |
| Simulation | Trimesh, Scipy, OpenUSD, NVIDIA Isaac Sim, IsaacLab | Preflight rules & Collider generator (SIM-02/04) đã hoàn thành; Isaac Sim runtime đang phát triển |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4, SuperSplat 3.4.2 (vendored), PlayCanvas + supersplat-viewer | Studio chạy đủ luồng video → scene → gói mô phỏng → duyệt/phát hành (validation Isaac thật chưa có); UI P0 cũ đã xoá 02/10/2026 |
| DevOps | Docker, Docker Compose, GitHub Actions | Scaffold backend và CI config; chưa chứng minh full product deployment |

## Quick Start (Khởi chạy hệ thống End-to-End)

Bạn có hai cách để khởi động toàn bộ WebApp (API, UI, Worker) tùy thuộc vào hệ điều hành và nhu cầu:

### Lựa chọn 1: Chạy bằng Docker Compose (Đa nền tảng: Windows, macOS, Linux - Đề xuất cho Teammate)
Đây là cách tiêu chuẩn để chạy hệ thống trên mọi hệ điều hành nếu bạn được nhận gói phân phối dữ liệu từ đồng đội.

**Chuẩn bị:**
1. Clone repository hoặc giải nén gói source code (`real2sim-studio-source.zip`).
2. Cần cài đặt Docker + Docker Compose. Trên Windows/macOS dùng Docker Desktop (Windows chạy Linux containers).
3. **Quan trọng:** Bạn cần có file dữ liệu `r2s-studio-data.zip` (do đồng đội đóng gói) đặt tại thư mục gốc của project (cùng cấp với `docker-compose.yml`).
4. Copy file cấu hình môi trường:
   ```bash
   cp .env.studio.example .env.studio
   # Trên Windows PowerShell: Copy-Item .env.studio.example .env.studio
   ```

**Cấu hình (`.env.studio`):**
- Mặc định, file đã cấu hình khởi chạy cả Worker GPU. Nếu máy của bạn (hoặc Mac) không có NVIDIA GPU, hãy mở `.env.studio`, comment dòng `# COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` và mở comment dòng `COMPOSE_FILE=docker-compose.yml`.
- Nếu bị lỗi DNS lúc build trên Linux, đổi `STUDIO_BUILD_NETWORK=host`. Windows/macOS giữ nguyên `default`.

**Khởi chạy:**
```bash
docker compose --env-file .env.studio up --build -d --wait
```
Docker sẽ tự build, giải nén/khôi phục dữ liệu từ `r2s-studio-data.zip` (nếu chưa có sẵn database) và khởi động API + Web. Dữ liệu sau đó được lưu tại thư mục `./data`. Mở http://localhost:3010 để sử dụng.

### Lựa chọn 2: Chạy Native (Chuyên sâu cho Linux + NVIDIA GPU)
Cách này tối ưu hiệu năng để chạy worker dựng hình 3DGS trực tiếp trên máy chủ Linux như máy trạm hiện tại. Yêu cầu đã cài sẵn `python3.12`, `nodejs`, `ffmpeg`, và Docker (cho COLMAP).

```bash
# 1. Clone và chuẩn bị thư mục
git clone https://github.com/AI20K-Build-Phase-Cohort-4/P-087.git
cd P-087

# 2. Cài đặt Python & Node.js dependencies
make setup
source .venv/bin/activate
cd frontend && npm ci && cd ..

# 3. Sinh file cấu hình môi trường Studio
make -f Makefile.studio env

# 4. Khởi động toàn bộ Stack (API + Worker + Web UI)
make -f Makefile.studio up
```

---

**Sau khi hệ thống khởi động (bằng bất kỳ cách nào), bạn có thể truy cập:**
- **Web Studio (Giao diện chính):** http://localhost:3010
- **API Swagger Docs:** http://localhost:8010/docs

Kiến trúc cloud đã chốt nhưng chưa triển khai ([ADR 0003](docs/decisions/0003-cloud-architecture-roles-and-browser-budget.md),
[plan](docs/plans/active/2026-09-29-cloud-studio.md)): Web UI trên Vercel, API trên Railway,
PostgreSQL trên Supabase, kho file Cloudflare R2, GPU Vast.ai (dự phòng RunPod) tự bật/tắt; hai role Editor/Reviewer,
khách chỉ dùng video mẫu.

Chạy kiểm tra:

```bash
make lint
make test
# Chạy bộ unit tests của EX-SIM (preflight & colliders):
pytest tests/test_simulation/ -v
```

CI (`.github/workflows/ci.yml`) có job Python (ruff, pytest, foundation/contract
mirror check) và job frontend (lint, typecheck, vitest, build). Runner GitHub Actions
do ban tổ chức quản lý đang bị chặn billing từ 26/09/2026 nên job không khởi động;
nhóm chạy cùng các bước ở local trước mỗi lần merge và ghi kết quả trong PR.

## Environment Variables

Không commit `.env`. Các biến chính:

| Nhóm | Biến |
|---|---|
| LLM | `LLM_PROVIDER`, API key và model của provider được chọn |
| App | `APP_ENV`, `APP_HOST`, `APP_PORT`, `CORS_ORIGINS`, `LOG_LEVEL` |
| Artifacts | `ARTIFACT_ROOT` (cache cục bộ; contract chỉ lưu logical URI) |
| Kho file (ADR 0003) | `ARTIFACT_S3_BUCKET`, `ARTIFACT_S3_ENDPOINT`, `ARTIFACT_S3_REGION`, `ARTIFACT_S3_ACCESS_KEY_ID`, `ARTIFACT_S3_SECRET_ACCESS_KEY`, `ARTIFACT_S3_PREFIX`, `ARTIFACT_PRESIGN_SECONDS` — để trống bucket = chỉ filesystem |
| Đăng nhập (ADR 0003) | `AUTH_REQUIRED` (mặc định `false`), `AUTH_SESSION_DAYS`, `AUTH_INVITE_DAYS`, `AUTH_COOKIE_SECURE` |
| Benchmark | `BENCHMARK_GPU_HOURLY_USD`, `BENCHMARK_LABEL` |
| Database | `DATABASE_URL` — SQLite local, PostgreSQL (Supabase) khi deploy; migration tự chạy khi khởi động |
| Organizer scaffold | `CHROMA_PERSIST_DIR` (chưa phải vector-store decision) |
| AI logs | `AI_LOG_SERVER`, `AI_LOG_API_KEY`, `AI_LOG_DIR` |

Chỉ API key của `LLM_PROVIDER` đang chọn là bắt buộc để chạy backend scaffold.

## Bản đồ thư mục gốc

Thư mục gốc giữ nguyên khung do ban tổ chức (BTC) cung cấp — không đổi tên, dời hay xoá
([`ARCHITECTURE.md`](./ARCHITECTURE.md)). Bảng dưới nói rõ từng file dùng để làm gì.

**Đọc trước**

| File | Vai trò | Nguồn |
|---|---|---|
| `README.md` | README của dự án (file này) | BTC, nhóm viết lại |
| `AGENTS.md` | Quy tắc làm việc cho coding agent và bảng authority (tài liệu nào quyết định việc gì) | Nhóm |
| `ARCHITECTURE.md` | Vị trí chuẩn của từng loại code và ownership theo track | BTC, nhóm viết lại |
| `docs/` | Mọi tài liệu khác; bắt đầu từ [`docs/README.md`](./docs/README.md) | Nhóm + guide của BTC |

**Nhật ký nộp bài (deliverable Demo Day)**

| File | Vai trò | Nguồn |
|---|---|---|
| `WORKLOG.md` | Việc đã làm theo ngày, chia theo 4 track | Khung BTC, nhóm ghi |
| `JOURNAL.md` | Kết quả, quyết định và bài học theo tuần | Khung BTC, nhóm ghi |

**Khung mẫu của BTC (không dùng để chạy dự án)**

| File | Vai trò |
|---|---|
| `README_starter.md` | Hướng dẫn dùng template AI20K (cấu trúc mẫu, danh sách deliverable) |
| `README_boilerplate.md` | Khung README mẫu để đội điền; README thật là `README.md` |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `LICENSE` | Quy định chung của chương trình |

**Build và phụ thuộc**

| File | Vai trò | Nguồn |
|---|---|---|
| `requirements.in` → `requirements.lock.txt` | Phụ thuộc runtime của API/worker. `Dockerfile`, `Dockerfile.gpu`, CI và `scripts/setup.sh` cài từ file lock | BTC + nhóm |
| `requirements-dev.in` → `requirements-dev.lock.txt` | Công cụ dev/test (ruff, pytest…); CI và `scripts/setup.sh` cài từ file lock | Nhóm |
| `requirements-offline.in` → `requirements-offline.lock.txt` | Tooling dataset offline cho `scripts/torwic/` (open3d), tách khỏi runtime | Nhóm |
| `Makefile` | Lệnh dev của template: `run`, `test`, `lint`, `setup`, `lock`, `doctor`, `smoke` | BTC |
| `Makefile.studio` | Chạy cả stack Studio cục bộ (API + worker + web): `make -f Makefile.studio up` | Nhóm |
| `Dockerfile` | Image API Studio (CPU), có restore/auth entrypoint, USD, ffmpeg và splat-transform | Nhóm |
| `Dockerfile.gpu` | Image GPU worker (COLMAP, Brush, runtime tách vật thể) | Nhóm |
| `frontend/Dockerfile` | Image Next.js và editor | Nhóm |
| `docker-compose.yml` | Stack Studio mặc định: restore data, API, web | Nhóm |
| `docker-compose.gpu.yml` | Override thêm worker NVIDIA và runtime preflight | Nhóm |
| `ruff.toml`, `.python-version`, `.env.example`, `.gitignore`, `.dockerignore` | Cấu hình công cụ và mẫu biến môi trường | BTC + nhóm |
| `THIRD_PARTY_NOTICES.md` | Nguồn và giấy phép của code, mô hình, asset bên thứ ba (backend và frontend) | Nhóm |

Sinh lại ba file lock bằng `make lock` (`scripts/lock_dependencies.sh`).
Chỉnh dependency trong `.in`; cài từ lock tương ứng. Offline LiDAR dùng
Open3D 0.19.0 và Pydantic/settings trong môi trường riêng. Các file requirements
template cũ và khai báo LiDAR riêng đã được hợp nhất vào các cặp canonical.

## Bản đồ thư mục `data/`

`data/` không nằm trong git: dữ liệu, môi trường cài sẵn và kết quả chạy. Tên các thư mục có ghi "cấu hình trỏ tới" được
`scripts/gpu/studio.env`, `Makefile.studio` hoặc giá trị mặc định trong code dùng theo đường dẫn — đổi tên thì phải sửa
cấu hình tương ứng.

| Thư mục | Nội dung | Tạo lại bằng |
|---|---|---|
| `data/studio_local/` | Stack Studio cục bộ (cấu hình trỏ tới): `runtime.db`, `artifacts/` (kho artifact của các scene), `workers/` (thư mục làm việc của worker — xoá được khi không có job đang chạy), `trash/` (scene đã gỡ bằng `projects/delete_cli`, khôi phục được tới khi `purge`), `backups/`, `qa/` (script và ảnh kiểm thử trình duyệt), `seed-accounts/` | `make -f Makefile.studio up` |
| `data/demo/library/` | Thư viện video mẫu đã xử lý sẵn (`PRODUCT_DEMO_DIR`) | `scripts/demo/export_demo_bundle.py` |
| `data/asset_previews/` | GLB xem trước của asset danh mục | `scripts/scene/build_asset_previews.py` |
| `data/rerun_recordings/` | Bản ghi Rerun của quá trình train (`<job_id>.rrd`) | `eval/visual/brush_quality.py --rerun-save` |
| `data/rec04_runtime/` | Công cụ dựng hình (cấu hình trỏ tới): launcher COLMAP, Brush, splat-transform | [`scripts/gpu/README.md`](./scripts/gpu/README.md) |
| `data/scene_runtime/` | Môi trường Python tách vật thể (cấu hình trỏ tới): PyTorch, SAM2, gsplat, LaMa, CoACD, usd-core và trọng số | `scripts/gpu/setup_scene_runtime.sh` |
| `data/rec07_runtime/` | Môi trường Python cho tooling LiDAR offline (Open3D); test REC-07 tự bỏ qua khi thiếu | `requirements-offline.lock.txt` |
| `data/tools/rerun-0.24.1/` | Viewer Rerun đúng phiên bản Brush nhúng | [`eval/visual/README.md`](./eval/visual/README.md) |
| `data/torwic_slam/` | Dataset TorWIC: `raw/` (gốc, bất biến), `normalized/`, `derived/`, `evaluation_only/`. Ảnh RGB nằm ở `normalized/`. Trên máy của owner, `raw/…/image_left` và `raw/…/lidar` là symlink tới ổ ngoài (`/media/usb/AI20K/TorWIC SLAM Dataset/Aisle_CW`), nên tooling dataset và validator cần cắm ổ; máy giữ cả bản raw thì gộp ảnh trùng bằng hardlink | `scripts/torwic/`; gộp ảnh trùng: `scripts/torwic/dedupe_rgb_frames.py` |
| `data/evidence/` | Bằng chứng chạy thử theo task (REC-05/06/07, sweep chất lượng). Task file cũ ghi đường dẫn không có `evidence/` | — |
| `data/artifacts/` | Kho artifact mặc định khi chạy không có `studio.env`. Test không được ghi vào đây (guard ở `tests/conftest.py`) | tự tạo |

## Project Structure

Bản đồ nhanh (kiểm theo checkout 2026-09-29). Placement/ownership chính thức:
[`ARCHITECTURE.md`](./ARCHITECTURE.md).

| Đường dẫn | Nội dung | Nguồn |
|---|---|---|
| `src/models/contracts/` | Shared typed contracts giữa các track | Nhóm |
| `src/services/reconstruction/` | EX-REC: `rgb/{preflight,frames,pose,splat,geometry,canonical}` theo stage, `adapters/` (COLMAP/Brush/splat-transform), `lidar/`, `alignment/`, CLI `prepare_cli`/`preview_cli` | Nhóm |
| `src/services/orchestration/` | EX-PRODUCT: `jobs/` (lifecycle, migration, `runner`, `worker_cli`), `projects/`, `uploads/` (+ upload thẳng), `processing/` (thông số xử lý), `samples/` (video mẫu), `artifacts/` (+ kho file S3), `auth/` (2 role), `scene/` (SceneIR revision, tách theo vật), `review/` (duyệt/phát hành, gói mô phỏng); gốc chỉ còn `storage.py`, `benchmark.py`, `environment.py` | Nhóm |
| `src/services/scene/`, `src/services/simulation/` | EX-SCENE, EX-SIM (nhiều package còn là placeholder) | Nhóm |
| `src/api/` | `routes.py` (điểm vào), `auth.py` (đăng nhập, quyền), `schemas.py`, `product/` (hợp đồng UI P0: project, job, artifact, scene, review), `studio/` (route của Studio) | Scaffold + nhóm |
| `src/agents/`, `src/llm/`, `src/models/schemas.py` | Chat agent scaffold, chưa thuộc pipeline Real2Sim | Ban tổ chức |
| `frontend/src/app/(studio)/`, `features/studio/` | Studio MVP (Scenes, Scene mới + video mẫu, trang scene/editor) | Nhóm |
| `frontend/src/features/viewer/`, `features/shell/`, `components/{shadcn,studio}` | Engine 3D dùng chung (PlayCanvas, lớp phủ vật thể), khung app, bộ component nền và primitives của Studio | Nhóm + donor |
| `frontend/vendor/supersplat/` | SuperSplat editor (MIT), build ra `public/editor` | Bên thứ ba |
| `configs/product/` | File cấu hình chung: thông số xử lý, profile chất lượng upload | Nhóm |
| `scripts/torwic/` | Offline dataset tooling (`migrations/` = script chạy một lần) | Nhóm |
| `scripts/gpu/`, `scripts/demo/` | Chạy stack trên máy GPU; export bundle video mẫu | Nhóm |
| `scripts/benchmark/`, `scripts/cloud/` | Tổng hợp benchmark; cấu hình bucket kho file | Nhóm |
| `eval/protocols/BENCHMARKS.md` | Mục lục các loại benchmark (mã, chỉ số, nơi lưu kết quả) | Nhóm |
| `scripts/log_*`, `scripts/setup*` | AI log + setup | Ban tổ chức |
| `tests/` | Theo track; `tests/test_reconstruction/{support,smoke}` = fixture và smoke chạy tay | Nhóm |
| `docs/guide/` | Sách hướng dẫn | Ban tổ chức |
| `docs/execution/`, `docs/plans/`, `docs/decisions/` | Contract, task theo track, plan, ADR | Nhóm |

## API Endpoints

Đầy đủ tại Swagger (`/docs`). Nhóm chính:

| Nhóm | Path | Mô tả |
|---|---|---|
| Health | `GET /health` | Kiểm tra backend và environment |
| Studio | `POST/GET /api/v1/uploads` | Upload video (stream raw body) và liệt kê |
| Studio | `POST /api/v1/scenes/from-upload`, `GET /api/v1/scenes` | Tạo scene + xếp job, danh sách scene |
| Studio | `GET /api/v1/jobs/{id}/progress` | Tiến trình từng stage |
| Studio | `GET /api/v1/processing/options`, `POST /api/v1/processing/evaluate` | Bảng thông số, ước lượng tài nguyên |
| Studio | `GET /api/v1/samples[/{id}[/files/{name}]]` | Video mẫu đã xử lý sẵn |
| Product | `/api/v1/projects…`, `/api/v1/jobs/{id}/…` | Project/job/artifact, preview, scene, validation, review |
| Scaffold | `GET /api/v1/status`, `POST /api/v1/chat` | LangGraph agent scaffold |

Request mẫu cho `/api/v1/chat`:

```json
{
  "message": "Xin chào"
}
```

Response mẫu:

```json
{
  "response": "...",
  "analysis": "..."
}
```

## Tài liệu chính

- [Product Brief](./docs/BRIEF.md)
- [PRD](./docs/PRD.md)
- [Dataset Playbook](./docs/DATASET_PLAYBOOK.md)
- [Architecture](./ARCHITECTURE.md)
- [Agent Harness](./AGENTS.md) và [Repository Workflow](./docs/WORKFLOW.md)
- [Integration Playbook](./docs/execution/INTEGRATION_PLAYBOOK.md)
- [Team Execution Contract](./docs/execution/TEAM_EXECUTION_CONTRACT.md)
- [Team Execution Plan](./docs/execution/TEAM_EXECUTION_PLAN.md)
- [Track Implementation Guide](./docs/execution/TRACK_IMPLEMENTATION_GUIDE.md)
- [Execution Tracks](./docs/execution/tracks/README.md)
- [Quyết định kiến trúc/sản phẩm (ADR)](./docs/decisions/README.md)
- [Đặc tả UX Web Studio](./docs/STUDIO_UX_SPEC.md): IA, màn hình, trạng thái UI và các quyết định Q/D-xx. PRD quyết định
  phạm vi và acceptance; đặc tả UX không override PRD
- [Onboarding cho coding agent](./docs/CONTEXT.md): tổng quan định hướng, không phải source of truth

## Demo và triển khai

- **Screenshot/GIF:** chưa có.
- **Live URL:** chưa triển khai.
- **Video demo:** chưa thực hiện.

## Deliverables Checklist

- [x] Repository và Foundation Baseline M0 (synthetic proof)
- [x] README.md
- [x] Architecture Diagram và pipeline glossary đồng bộ trong `ARCHITECTURE.md` (logical design, không phải runtime proof)
- [x] AI Logs (auto-collected)
- [ ] Live URL / Deploy
- [ ] Video Demo
- [ ] Pitch Deck (`presentation/`)
- [ ] Weekly Journal (`JOURNAL.md` đang cập nhật theo tuần)
- [x] Worklog ([`WORKLOG.md`](WORKLOG.md) — cập nhật thường xuyên theo lịch sử commit của team)
- [ ] Evaluation Evidence (`eval/results/`)

## Team

| Thành viên | Track | Student ID |
|---|---|---|
| Lâm Quang Anh Quân | `EX-REC` — Reconstruction | 2A202602467 |
| Đức (tên đầy đủ TBD) | `EX-SCENE` — Scene/Object | Chưa cung cấp |
| Nguyễn Thọ Đạt | `EX-SIM` — Simulation/Evaluation | 2A202602484 |
| Lê Mạnh Cường | `EX-PRODUCT` — Product/Orchestration | 2A202602604 |

Track owners đã khóa tại Execution Plan; tên đầy đủ, Student ID và GitHub handles
còn thiếu của ba thành viên sẽ được cập nhật khi họ cung cấp, không suy đoán từ
Git author.

## License

MIT
