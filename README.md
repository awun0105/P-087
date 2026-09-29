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
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4, SuperSplat 3.4.2 (vendored), PlayCanvas + supersplat-viewer | Studio MVP chạy; UI P0 đầy đủ (review/release, HITL edit) giữ code, ẩn sau `LEGACY_UI=1` |
| DevOps | Docker, Docker Compose, GitHub Actions | Scaffold backend và CI config; chưa chứng minh full product deployment |

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/AI20K-Build-Phase-Cohort-4/P-087.git
cd P-087

# 2. Setup Python 3.12 và dependencies từ lockfiles
make setup
source .venv/bin/activate

# 3. make setup tạo .env nếu chưa có; chọn LLM_PROVIDER và điền API key
# tương ứng (Settings bắt buộc key của provider đang chọn khi khởi động)

# 4. Chạy backend
make run
```

Swagger UI: <http://localhost:8000/docs>

Chạy cả Studio (API + queue worker + Next.js) với tool xử lý thật: xem runbook
[`scripts/gpu/README.md`](scripts/gpu/README.md) (`scripts/gpu/run_stack.sh`).

Kiến trúc cloud đã chốt nhưng chưa triển khai ([ADR 0003](docs/decisions/0003-cloud-architecture-roles-and-browser-budget.md),
[plan](docs/plans/active/2026-09-29-cloud-studio.md)): Web UI trên Vercel, API + Postgres
trên Railway, kho file Cloudflare R2, GPU Vast.ai (dự phòng RunPod) tự bật/tắt; hai role Editor/Reviewer,
khách chỉ dùng video mẫu.

Chạy kiểm tra:

```bash
make lint
make test
# Chạy bộ unit tests của EX-SIM (preflight & colliders):
pytest tests/test_simulation/ -v
```

Chạy bằng Docker:

```bash
docker compose up --build
```

## Environment Variables

Không commit `.env`. Các biến chính:

| Nhóm | Biến |
|---|---|
| LLM | `LLM_PROVIDER`, API key và model của provider được chọn |
| App | `APP_ENV`, `APP_HOST`, `APP_PORT`, `CORS_ORIGINS`, `LOG_LEVEL` |
| Artifacts | `ARTIFACT_ROOT` (runtime resolve thành absolute path; contract chỉ lưu logical URI) |
| Organizer scaffold | `DATABASE_URL`, `CHROMA_PERSIST_DIR` (chưa phải product database/vector-store decision) |
| AI logs | `AI_LOG_SERVER`, `AI_LOG_API_KEY`, `AI_LOG_DIR` |

Chỉ API key của `LLM_PROVIDER` đang chọn là bắt buộc để chạy backend scaffold.

## Project Structure

Bản đồ nhanh (kiểm theo checkout 2026-09-29). Placement/ownership chính thức:
[`ARCHITECTURE.md`](./ARCHITECTURE.md).

| Đường dẫn | Nội dung | Nguồn |
|---|---|---|
| `src/models/contracts/` | Shared typed contracts giữa các track | Nhóm |
| `src/services/reconstruction/` | EX-REC: `rgb/{preflight,frames,pose,splat,geometry,canonical}` theo stage, `adapters/` (COLMAP/Brush/splat-transform), `lidar/`, `alignment/`, CLI `prepare_cli`/`preview_cli` | Nhóm |
| `src/services/orchestration/` | EX-PRODUCT: `jobs/` (lifecycle, `runner`, `worker_cli`), `projects/`, `uploads/`, `processing/` (thông số xử lý), `samples/` (video mẫu), `artifacts/`, `scene/` (SceneIR revision) | Nhóm |
| `src/services/scene/`, `src/services/simulation/` | EX-SCENE, EX-SIM (nhiều package còn là placeholder) | Nhóm |
| `src/api/` | `routes.py` (gốc), `routes_product.py`, `studio/` (route Studio MVP) | Scaffold + nhóm |
| `src/agents/`, `src/llm/`, `src/models/schemas.py` | Chat agent scaffold, chưa thuộc pipeline Real2Sim | Ban tổ chức |
| `frontend/src/app/(studio)/`, `features/studio/` | Studio MVP (Scenes, Scene mới + video mẫu, trang scene/editor) | Nhóm |
| `frontend/src/app/(legacy)/`, `features/{jobs,review,scene,viewer}` | UI P0 đầy đủ, giữ để dùng lại; ẩn khi không đặt `LEGACY_UI=1` | Nhóm |
| `frontend/vendor/supersplat/` | SuperSplat editor (MIT), build ra `public/editor` | Bên thứ ba |
| `configs/product/` | File cấu hình chung: thông số xử lý, profile chất lượng upload | Nhóm |
| `scripts/torwic/` | Offline dataset tooling (`migrations/` = script chạy một lần) | Nhóm |
| `scripts/gpu/`, `scripts/demo/` | Chạy stack trên máy GPU; export bundle video mẫu | Nhóm |
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
