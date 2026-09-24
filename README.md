# Real2Sim Studio — Warehouse / Indoor AMR MVP

> Chuyển dữ liệu RGB/LiDAR của kho trong nhà thành scene 3D có thể chỉnh sửa, kiểm định trong NVIDIA Isaac Sim và phát hành có truy vết.

**Team:** P-087 — VinUni AI20K Build Phase, Cohort 4

**Trạng thái:** Foundation Baseline M0 (contracts/fixtures synthetic); MVP P0 đang phát triển. Chưa có real reconstruction, browser 3DGS hoặc Isaac acceptance.

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
| Backend | FastAPI, Python 3.12 | Organizer scaffold |
| Agent scaffold | LangGraph, LangChain, multi-provider LLM | Có sẵn, chưa phải Real2Sim pipeline |
| Reconstruction | FFmpeg, COLMAP, Brush, OpenMVS, Open3D | Planned integration |
| Scene/Object | SAM2, Open3D, NumPy | Planned integration |
| Simulation | OpenUSD, NVIDIA Isaac Sim, IsaacLab | Planned integration |
| Frontend | Next.js, React, TypeScript, Three.js | Planned; chưa scaffold |
| DevOps | Docker, Docker Compose, GitHub Actions | Scaffold backend và CI config; chưa chứng minh full product deployment |

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/AI20K-Build-Phase-Cohort-4/P-087.git
cd P-087

# 2. Setup Python 3.12 và dependencies từ lockfiles
make setup
source .venv/bin/activate

# 3. make setup tạo .env nếu chưa có; chọn LLM_PROVIDER và
# điền API key tương ứng để chạy backend chat scaffold hiện tại

# 4. Chạy backend hiện tại
make run
```

Swagger UI: <http://localhost:8000/docs>

Chạy kiểm tra:

```bash
make lint
make test
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

- `src/models/contracts/`: shared typed handoff contracts; `fixtures/` và
  `tests/` chứa synthetic proof cho phát triển song song.
- `src/services/reconstruction/`, `scene/`, `simulation/`, `orchestration/`:
  lần lượt thuộc EX-REC, EX-SCENE, EX-SIM, EX-PRODUCT.
- `src/api/`: backend FastAPI của EX-PRODUCT; các route hiện có vẫn chủ yếu là
  organizer chat scaffold.
- `frontend/`: Next.js Web Studio do EX-PRODUCT tạo trong `PRODUCT-05`; hiện
  chưa được scaffold. Viewer đặt tại `frontend/src/features/viewer/`.
- `scripts/torwic/`: offline dataset tooling; `eval/`: evaluation protocols.

Placement và ownership đầy đủ chỉ khóa tại [`ARCHITECTURE.md`](./ARCHITECTURE.md),
không suy trạng thái triển khai từ sơ đồ thư mục mục tiêu.

## API Endpoints

Các endpoint dưới đây thuộc organizer scaffold hiện tại; Real2Sim APIs sẽ được bổ sung theo execution contract.

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/health` | Kiểm tra backend và environment |
| `GET` | `/api/v1/status` | Kiểm tra LangGraph agent scaffold |
| `POST` | `/api/v1/chat` | Gửi message tới agent scaffold |

Request mẫu:

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

- **Screenshot/GIF:** chưa có vì frontend chưa được scaffold.
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
- [ ] Weekly Journal (`JOURNAL.md` đang là template)
- [ ] Worklog (`WORKLOG.md` đang là template)
- [ ] Evaluation Evidence (`eval/results/`)

## Team

| Thành viên | Track | Student ID |
|---|---|---|
| Lâm Quang Anh Quân | `EX-REC` — Reconstruction | 2A202602467 |
| Đức (tên đầy đủ TBD) | `EX-SCENE` — Scene/Object | Chưa cung cấp |
| Đạt (tên đầy đủ TBD) | `EX-SIM` — Simulation/Evaluation | Chưa cung cấp |
| Lê Mạnh Cường | `EX-PRODUCT` — Product/Orchestration | 2A202602604 |

Track owners đã khóa tại Execution Plan; tên đầy đủ, Student ID và GitHub handles
còn thiếu của ba thành viên sẽ được cập nhật khi họ cung cấp, không suy đoán từ
Git author.

## License

MIT
