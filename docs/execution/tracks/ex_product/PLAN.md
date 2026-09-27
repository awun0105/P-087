# EX-PRODUCT — Kế hoạch thực hiện theo milestone

**Track Owner:** Cường.
**Cập nhật lần cuối:** 26/09/2026.

File này ghi thứ tự thực hiện và trạng thái từng task của `EX-PRODUCT` theo
milestone. Nguồn milestone: [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md)
Chương 11. Định nghĩa task: [`TRACK.md`](./TRACK.md), chi tiết từng task nằm
trong [`tasks/`](./tasks/).

File này **không thay thế** task file và không định nghĩa contract mới.

---

## 1. Trạng thái hiện tại — 26/09/2026

| Hạng mục | Trạng thái thực tế |
|---|---|
| `PRODUCT-01` | `IN_PROGRESS` — API mock-first + privacy gate xong; ô DoD "swap sang worker thật" chờ PRODUCT-03 |
| `PRODUCT-02` | `DONE` — state machine + persistence + attempt history |
| `PRODUCT-05` | **`DONE`** — shell xong, build xanh, **browser smoke thật đã chạy 25/09** |
| `PRODUCT-06` | `IN_PROGRESS` — viewer fixture + edit revision + browser smoke xong; ô DoD "3DGS thật" cố ý để trống: AC-11 chờ `REC-04`, mốc M3 |
| `PRODUCT-03`/`04`/`07`/`07A`/`08`/`09`/`10`/`11`/`12` | `TODO` |
| [`src/api/routes.py`](../../../../src/api/routes.py) | Đã include `product_router` — 16 endpoint product dưới `/api/v1` |
| `frontend/` | **Đã tồn tại** — Next.js 16 + React 19 + Tailwind 4, 8 route, 54 test |
| [`src/services/orchestration/artifacts/`](../../../../src/services/orchestration/artifacts/) | Đã có `ArtifactResolver`, `FilesystemArtifactStore`, SHA-256, atomic publish |
| [`src/services/orchestration/jobs/`](../../../../src/services/orchestration/jobs/) | Đã có `JobLifecycle`, `JobArtifactStore`, bảng chuyển trạng thái |
| [`src/services/orchestration/scene/`](../../../../src/services/orchestration/scene/) | Đã có `SceneEditor` — **phục hồi revision từ đĩa sau restart (26/09)**, edit, publish revision |
| `src/services/orchestration/release/` | Package rỗng, chưa có code |
| [`fixtures/`](../../../../fixtures/) | Đã có đủ: `mock_job/`, `artifact_store/jobs/job-fixture-001/`, `candidate/`, `validation_report/`, `scene_ir/`, `invalid/` |

Nguồn Foundation đã khóa tại M0 (commit `49f2456`).

**Trạng thái kiểm chứng (26/09):**

```
pytest tests/            → 297 passed in 3.41s
ruff check + format      → sạch (104 file đã format)
npm test (frontend)      → 54 passed, 5 file   (25/09)
npm run typecheck        → sạch                (25/09)
npm run lint             → sạch                (25/09)
npm run build            → exit 0, 8 route     (25/09)
```

**Sửa lỗi restart `SceneEditor` (26/09).** Sau khi backend restart,
`GET /scene` từng trả revision cũ và `POST /scene/edits` trả **500**. Đã sửa:
`current()` phục hồi revision cao nhất đã publish trên đĩa, và route map
`ArtifactStoreError` → 409. Kiểm trên server thật: `GET /scene` → `rev-004`
(khớp đĩa), `POST` edit → **201** `rev-005`, revision cũ vẫn **409**, object lạ vẫn
**422**. 9 test mới; 8 trong đó fail trên code chưa sửa.

**Browser smoke thật (25/09)** — Chrome headless trỏ vào backend + frontend đang
chạy: proxy `rewrites` → 200, 6/6 route → 200, `<canvas data-engine="three.js
r180">` (Three.js khởi tạo WebGL context thật, `webgl-unavailable` vắng mặt),
trình duyệt tự tải PLY thật qua `/artifacts/content` → 200, sửa revision
`rev-003 → rev-004` (201) và revision cũ → 409, 4 ca âm giữ đúng mã. Chi tiết ở
[PRODUCT-05 §12](tasks/PRODUCT-05.md) và [PRODUCT-06 §12](tasks/PRODUCT-06.md).

Đây là **fixture/API/unit proof + browser proof trên dữ liệu fixture**. Vẫn chưa
có worker thật và **chưa có 3DGS thật** — AC-11 là mốc M3, chờ `REC-04`.

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

| | Task | Trạng thái 26/09 |
|---|---|---|
| [x] | **PRODUCT-01** — Mock-first project/job/artifact API + source-rights attestation + privacy gating | Xong ở mức fixture/API |
| [x] | **PRODUCT-02** — Job state machine tối thiểu (`QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`) | Xong |
| [x] | **PRODUCT-05** — Web shell tối thiểu, có màn hình mock review | **`DONE`** — browser smoke thật đã chạy 25/09 |
| [ ] | **PRODUCT-06** — Viewer tối thiểu: orbit/pan/zoom, select, hide/show, transform edit cơ bản | Browser smoke 25/09 xong (Three.js `r180` render thật); **ô DoD đầu cố ý để trống** vì 3DGS thật là AC-11, mốc M3 |
| [~] | Metric baseline tuần 1 ([`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md) §5.4.1): Human Active Time, Manual Step Count, Time to Simulation-ready Scene | **26/09** — protocol + baseline phía tool-assisted xong ([`METRIC_BASELINE.md`](./METRIC_BASELINE.md)); 3 ô cần người/simulator **để trống có chủ đích** |

#### Kế hoạch từng ngày còn lại của M1

Kế hoạch nằm ở đây, **không** nằm trong `WORKLOG.md`: worklog chỉ ghi việc đã thực
sự xảy ra kèm bằng chứng, nên không được điền trước ngày.

| Ngày | Việc | Trạng thái |
|---|---|---|
| 25/09 | Chạy browser smoke thật: backend + `npm run dev`, đi hết `project → job → viewer → review`, chụp màn hình. | ✅ Xong — [PRODUCT-05 §12](tasks/PRODUCT-05.md), [PRODUCT-06 §12](tasks/PRODUCT-06.md) |
| 26/09 | Metric baseline tuần 1 §5.4.1 — đo Human Active Time / Manual Step Count / Time to Simulation-ready Scene trên chính luồng vừa chạy; ghi phương pháp đo, không ước đoán. | ✅ Xong phần máy đo được — [`METRIC_BASELINE.md`](./METRIC_BASELINE.md). 3 ô cần người/simulator để trống có chủ đích. Kèm sửa lỗi restart `SceneEditor` (lộ ra khi chuẩn bị đo) |
| 27/09 | Đóng gói evidence M1: ảnh/recording, output test, request/response mẫu; rà lại `§11 DoD` từng task; chuẩn bị demo script cho gate. | Chưa làm |
| 28/09 | Gate M1 — demo `mock project → mock job → browser viewer → mock review`. | Chưa làm |

**Ghi chú 25/09 — kết quả rà repo mẫu.** File authority là
[`INTEGRATION_PLAYBOOK.md`](../../INTEGRATION_PLAYBOOK.md) Ch.7 §7.1 (đối chiếu
`PRODUCT-05 §8`, `PRODUCT-06 §8`, `TRACK.md`). Trạng thái tận dụng thật, kiểm từ
`frontend/package.json`:

| Repo mẫu | Vai trò | Đã dùng? |
|---|---|---|
| three.js (docs + examples) | P0 library | ✅ `three ^0.180.0` — `SceneCanvas` dùng thật |
| pmndrs/react-three-fiber | candidate | ✅ `@react-three/fiber ^9.8` + `drei ^10.7` |
| Kiranism/next-shadcn-dashboard-starter | P0 selective ADAPT | ❌ Không — shell viết tay; §8 cấm starter authorization/persistence |
| sparkjsdev/spark | P0 renderer candidate | ❌ Chưa — chỉ adopt sau khi có real Brush output (`REC-04` còn `TODO`) |
| potree/potree | REFERENCE (point-cloud LOD) | ❌ Không — không phải P0 dependency |
| spark-react-nextjs, arhamkhnz, shadcndashboard | REFERENCE | ❌ Không — chỉ tham khảo |

Việc còn nợ lại ngoài M1: test component cho `projects/[projectId]`,
`jobs/[jobId]`, `validation`, `review`; E2E tương tác tự động (PRODUCT-07/07A).

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
