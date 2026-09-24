# EX-PRODUCT — Kế hoạch thực hiện theo milestone

**Track Owner:** Cường.
**Cập nhật lần cuối:** 24/09/2026.

File này ghi thứ tự thực hiện và trạng thái từng task của `EX-PRODUCT` theo
milestone. Nguồn milestone: [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md)
Chương 11. Định nghĩa task: [`TRACK.md`](./TRACK.md), chi tiết từng task nằm
trong [`tasks/`](./tasks/).

File này **không thay thế** task file và không định nghĩa contract mới.

---

## 1. Trạng thái hiện tại — 24/09/2026

| Hạng mục | Trạng thái thực tế |
|---|---|
| `PRODUCT-01` | `IN_PROGRESS` — API mock-first + privacy gate xong; ô DoD "swap sang worker thật" chờ PRODUCT-03 |
| `PRODUCT-02` | `DONE` — state machine + persistence + attempt history |
| `PRODUCT-05` | `IN_PROGRESS` — shell xong, build xanh; **chưa chạy browser smoke** |
| `PRODUCT-06` | `IN_PROGRESS` — viewer fixture + edit revision xong; AC-11 (3DGS thật) chờ `REC-04`, mốc M3 |
| `PRODUCT-03`/`04`/`07`/`07A`/`08`/`09`/`10`/`11`/`12` | `TODO` |
| [`src/api/routes.py`](../../../../src/api/routes.py) | Đã include `product_router` — 16 endpoint product dưới `/api/v1` |
| `frontend/` | **Đã tồn tại** — Next.js 16 + React 19 + Tailwind 4, 8 route, 54 test |
| [`src/services/orchestration/artifacts/`](../../../../src/services/orchestration/artifacts/) | Đã có `ArtifactResolver`, `FilesystemArtifactStore`, SHA-256, atomic publish |
| [`src/services/orchestration/jobs/`](../../../../src/services/orchestration/jobs/) | Đã có `JobLifecycle`, `JobArtifactStore`, bảng chuyển trạng thái |
| [`src/services/orchestration/scene/`](../../../../src/services/orchestration/scene/) | Đã có `SceneEditor` — seed fixture, edit, publish revision |
| `src/services/orchestration/release/` | Package rỗng, chưa có code |
| [`fixtures/`](../../../../fixtures/) | Đã có đủ: `mock_job/`, `artifact_store/jobs/job-fixture-001/`, `candidate/`, `validation_report/`, `scene_ir/`, `invalid/` |

Nguồn Foundation đã khóa tại M0 (commit `49f2456`).

**Trạng thái kiểm chứng (24/09):**

```
pytest tests/            → 288 passed
ruff check + format      → sạch
npm test (frontend)      → 54 passed, 5 file
npm run typecheck        → sạch (next typegen && tsc --noEmit)
npm run lint             → sạch
npm run build            → exit 0, 8 route
```

Đây là **fixture/API/unit proof**. Chưa có bằng chứng browser, chưa có worker thật,
chưa có 3DGS thật.

---

## 2. Thứ tự thực hiện

`PRODUCT-01` là nền: response shape của nó được `PRODUCT-02`, `PRODUCT-04`,
`PRODUCT-05` và `PRODUCT-08` tiêu thụ. Định nghĩa shape sai ở đây thì các task
sau phải sửa theo — nên làm trước và làm chắc.

```text
PRODUCT-01 (mock API + privacy gate)
    ├── PRODUCT-02 (job state machine)     → PRODUCT-03 (dispatch) → PRODUCT-08 (real orchestration)
    ├── PRODUCT-04 (artifact resolver)
    └── PRODUCT-05 (web shell)             → PRODUCT-06 (viewer)
                                                ├── PRODUCT-07  (object actions)
                                                └── PRODUCT-07A (asset/collider)
                                                        ↓
                              PRODUCT-09 (progress/error/retry)
                              PRODUCT-10 (review lifecycle)
                              PRODUCT-11 (exact-candidate release)
                                                        ↓
                              PRODUCT-12 (stable demo route)
```

---

## 3. Checklist theo milestone

### M1 — 28/09/2026

Điều kiện gate: 4 subsystem chạy độc lập. EX-PRODUCT phải demo
`mock project → mock job → browser viewer → mock review`.

| | Task | Trạng thái 24/09 |
|---|---|---|
| [x] | **PRODUCT-01** — Mock-first project/job/artifact API + source-rights attestation + privacy gating | Xong ở mức fixture/API |
| [x] | **PRODUCT-02** — Job state machine tối thiểu (`QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`) | Xong |
| [ ] | **PRODUCT-05** — Web shell tối thiểu, có màn hình mock review | Code + build xong; **chưa chạy browser smoke** |
| [ ] | **PRODUCT-06** — Viewer tối thiểu: orbit/pan/zoom, select, hide/show, transform edit cơ bản | Code xong; **chưa chạy browser smoke**; 3DGS thật là AC-11 mốc M3 |
| [ ] | Metric baseline tuần 1 ([`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md) §5.4.1): Human Active Time, Manual Step Count, Time to Simulation-ready Scene | Chưa làm |

#### Kế hoạch từng ngày còn lại của M1

Kế hoạch nằm ở đây, **không** nằm trong `WORKLOG.md`: worklog chỉ ghi việc đã thực
sự xảy ra kèm bằng chứng, nên không được điền trước ngày.

| Ngày | Việc |
|---|---|
| 25/09 | Chạy browser smoke thật: `make run` + `npm run dev`, đi hết `project → job → viewer → review`, chụp màn hình. Sửa lỗi proxy `rewrites` nếu có. Đóng ô `PRODUCT-05`/`PRODUCT-06`. |
| 26/09 | Metric baseline tuần 1 §5.4.1 — đo Human Active Time / Manual Step Count / Time to Simulation-ready Scene trên chính luồng vừa chạy; ghi phương pháp đo, không ước đoán. |
| 27/09 | Đóng gói evidence M1: ảnh/recording, output test, request/response mẫu; rà lại `§11 DoD` từng task; chuẩn bị demo script cho gate. |
| 28/09 | Gate M1 — demo `mock project → mock job → browser viewer → mock review`. |

Việc còn nợ lại ngoài M1: browser smoke cho cả 5 màn hình, test component cho
`projects/[projectId]`, `jobs/[jobId]`, `validation`, `review`.

### M2 — 05/10/2026

Điều kiện gate: Integration #1 thật giữa các track.

- [ ] **PRODUCT-02/03/04/05/06** hoàn thiện đầy đủ Definition of Done
- [ ] **PRODUCT-03** — Worker dispatch abstraction, mock ↔ real dùng chung một contract
- [ ] **PRODUCT-04** — Artifact registry/resolver, resolve bằng URI + checksum
- [ ] **PRODUCT-06** — Render real Brush 3DGS `VisualArtifact`, chuyển view Geometry/Point Cloud/Collider
- [ ] **PRODUCT-08** — Orchestrate REC→SCENE→SIM, dừng downstream khi thiếu artifact
- [ ] Integration #1: nhận `ValidationReport` thật từ EX-SIM và hiển thị trực tiếp

### M3 — 09/10/2026

Điều kiện gate: Product E2E Alpha qua Web/API trên cùng candidate lineage.

- [ ] **PRODUCT-07** — Object/human confirmation actions, mọi thao tác qua backend command
- [ ] **PRODUCT-09** — Progress/error/retry, hiện đúng stage lỗi, không fake percentage
- [ ] **PRODUCT-11** — Bắt đầu exact-candidate release

### M4 — 12/10/2026

Điều kiện gate: Feature complete + AC-08/SM-04/AC-12/authorization.

- [ ] **PRODUCT-07A** — Added asset/collider controls, edit persist thành revision mới
- [ ] **PRODUCT-09** — Retry preserve input và attempt cũ
- [ ] **PRODUCT-10** — Review lifecycle + authorization (chỉ Reviewer được approve/reject)
- [ ] **PRODUCT-11** — Seal exact candidate, không rebuild sau approval

### M5 — 14/10/2026

- [ ] **PRODUCT-12** — Stable demo route, có real 3DGS, artifact/checksum inventory

### M6 — 19/10/2026

- [ ] Demo rehearsal + fallback path, evidence bundle đầy đủ

---

## 4. Phụ thuộc ngoài track

Cần chốt với các track khác trước khi làm `PRODUCT-03` và `PRODUCT-08`:

- worker command interface của EX-REC / EX-SCENE / EX-SIM;
- artifact paths thực tế mỗi worker publish;
- stable entrypoints `REC-11`, `SCENE-10`, `SIM-09`;
- `REC-04` publish real Brush `VisualArtifact` — điều kiện để `PRODUCT-06` đạt AC-11.

Giao tiếp giữa các track **chỉ qua artifacts**, không import code của nhau.

---

## 5. Quy tắc bất biến

- Chỉ sửa `src/api/`, `src/services/orchestration/`, `frontend/`, `tests/test_orchestration/`, `tests/e2e/`. Không sửa track internals.
- Persisted state nằm ở backend/shared artifacts; React state không phải source of truth.
- Response API chỉ mang `artifact://jobs/<job_id>/<path>` + checksum, không lộ local path.
- Raw `ground_truth` / `evaluation_only` không được đi qua product boundary.
- Release bind đúng candidate đã validation và approval.
- Không nâng fixture/mock proof thành runtime acceptance trong evidence.
