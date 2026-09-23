# Real2Sim Studio — Warehouse / Indoor AMR MVP

> Chuyển dữ liệu RGB/LiDAR của kho trong nhà thành scene 3D có thể chỉnh sửa, kiểm định trong NVIDIA Isaac Sim và phát hành có truy vết.

**Team:** P-087 — VinUni AI20K Build Phase, Cohort 4

**Trạng thái:** Foundation Scaffold — đang phát triển MVP P0

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
| Contracts | Pydantic 2 | Foundation scaffold |
| Backend | FastAPI, Python 3.11 | Organizer scaffold |
| Agent scaffold | LangGraph, LangChain, multi-provider LLM | Có sẵn, chưa phải Real2Sim pipeline |
| Reconstruction | FFmpeg, COLMAP, Brush, OpenMVS, Open3D | Planned integration |
| Scene/Object | SAM2, Open3D, NumPy | Planned integration |
| Simulation | OpenUSD, NVIDIA Isaac Sim, IsaacLab | Planned integration |
| Frontend | Next.js, React, TypeScript, Three.js | Planned; chưa scaffold |
| DevOps | Docker, Docker Compose, GitHub Actions | Có sẵn |

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/AI20K-Build-Phase-Cohort-4/P-087.git
cd P-087

# 2. Tạo môi trường Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Tạo file cấu hình local
cp .env.example .env
# Chọn LLM_PROVIDER và điền API key tương ứng trong .env

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
| Storage | `DATABASE_URL`, `CHROMA_PERSIST_DIR` |
| AI logs | `AI_LOG_SERVER`, `AI_LOG_API_KEY`, `AI_LOG_DIR` |

Chỉ API key của `LLM_PROVIDER` đang chọn là bắt buộc để chạy backend scaffold.

## Project Structure

```text
src/
├── api/                              # Organizer scaffold; EX-PRODUCT
├── agents/                           # Organizer scaffold; giữ nguyên
├── llm/                              # Organizer scaffold; giữ nguyên
├── models/
│   ├── schemas.py                    # Organizer scaffold; giữ nguyên
│   └── contracts/                    # Shared artifact contracts
│       ├── artifacts.py
│       ├── manifests.py
│       ├── reconstruction.py
│       ├── scene.py
│       ├── validation.py
│       └── release.py
└── services/
    ├── reconstruction/               # EX-REC
    │   ├── adapters/
    │   ├── rgb/
    │   ├── lidar/
    │   └── alignment/
    ├── scene/                        # EX-SCENE
    │   ├── extraction/
    │   ├── association/
    │   ├── candidates/
    │   ├── decomposition/
    │   └── editing/
    ├── simulation/                   # EX-SIM
    │   ├── colliders/
    │   ├── preflight/
    │   ├── usd/
    │   ├── isaac/
    │   └── validation/
    └── orchestration/                # EX-PRODUCT
        ├── jobs/
        ├── artifacts/
        ├── review/
        └── release/

scripts/torwic/                       # EX-REC; offline dataset preparation only
fixtures/                             # Shared contract-shaped development fixtures
├── reconstruction_bundle/
├── scene_ir/
├── validation_report/
└── mock_job/

tests/                                # Existing tests remain; track suites are additive
├── test_contracts/
├── test_reconstruction/
├── test_scene/
├── test_simulation/
├── test_orchestration/
├── integration/
└── e2e/

eval/                                 # Top-level name is stable
├── visual/
├── geometry/
├── pose/
├── object/
├── path/
├── protocols/
└── results/report.md                 # Existing acceptance report; giữ nguyên
```

Xem cấu trúc và ownership đầy đủ tại [`ARCHITECTURE.md`](./ARCHITECTURE.md).

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
  "message": "Kiểm tra trạng thái dự án"
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
- [Integration Playbook](./docs/execution/INTEGRATION_PLAYBOOK.md)
- [Team Execution Contract](./docs/execution/TEAM_EXECUTION_CONTRACT.md)
- [Track Implementation Guide](./docs/execution/TRACK_IMPLEMENTATION_GUIDE.md)

## Demo và triển khai

- **Screenshot/GIF:** chưa có vì frontend chưa được scaffold.
- **Live URL:** chưa triển khai.
- **Video demo:** chưa thực hiện.

## Deliverables Checklist

- [x] Repository và Foundation Scaffold
- [x] README.md
- [ ] Architecture Diagram đồng bộ với Real2Sim
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
| Chưa cập nhật | `EX-SCENE` — Scene/Object | Chưa cập n |
| Chưa cập nhật | `EX-SIM` — Simulation/Evaluation | Chưa cập nhật |
| Chưa cập nhật | `EX-PRODUCT` — Product/Orchestration | Chưa cập nhật |

Tên và Student ID sẽ được cập nhật sau khi team khóa ownership; không suy đoán từ Git author.

## License

MIT
