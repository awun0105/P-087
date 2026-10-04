# PRODUCT-05 — Web Studio Shell

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `DONE` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Create minimal project, job, viewer, validation and review navigation shell.

## 3. Why This Task Exists

P0 is a Web product; the UI cannot be deferred until all CLI stages finish.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-01 fixture API.
- Root `frontend/` boundary đã được khóa trong `ARCHITECTURE.md` và thuộc EX-PRODUCT.
- Wireframe/product flow.

## 5. Input Contract

- Mock/real API schemas and product user flows.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Runnable Web shell and typed API client boundary.
- Screens for project/job/scene/validation/review states.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/app/`
- `frontend/src/components/`
- `frontend/src/lib/api/` và `frontend/src/lib/contracts/`
- `frontend/tests/`
- `src/api/` only for required typed endpoints
- product/e2e tests in canonical locations

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` Real2Sim workflow + selective `ADAPT` generic Web UI từ
[`Kiranism/next-shadcn-dashboard-starter`](https://github.com/Kiranism/next-shadcn-dashboard-starter)
(MIT): inspect shell/sidebar, navigation, table/list/detail, React Query/URL
state, forms và loading/error states. Chỉ mang component/pattern thực sự cần
cho project/job/artifact screens vào `frontend/`; không clone toàn repo làm
source of truth. [`arhamkhnz/next-shadcn-admin-dashboard`](https://github.com/arhamkhnz/next-shadcn-admin-dashboard)
là layout reference; [`shadcndashboard/next-shadcn-dashboard`](https://github.com/shadcndashboard/next-shadcn-dashboard)
là form/table/file-dropzone UI reference, không phải upload validation backend.

Không mang Clerk, SaaS organizations/billing, demo domain, Next.js business API
routes hoặc starter authorization/persistence vào Real2Sim. FastAPI và shared
contracts vẫn sở hữu business state, quyền và artifact validation. Trước khi
copy code, kiểm tra license/notice của exact revision và dependency versions;
không thêm dependency chỉ vì starter có sẵn.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

**Stack:** Next.js 16.3.6 (App Router, Turbopack) + React 19 + TypeScript + Tailwind 4.
Không dùng shadcn/Clerk hay starter dashboard nào: shell ở đây nhỏ, và §8 cấm mang
authorization/persistence của starter vào Real2Sim.

**Files**

| File | Vai trò |
|---|---|
| [`frontend/src/app/layout.tsx`](../../../../../frontend/src/app/layout.tsx) | Root layout, dùng `AppShell`; không `next/font/google` để build không phụ thuộc mạng |
| [`frontend/src/components/shell.tsx`](../../../../../frontend/src/components/shell.tsx) | `AppShell`, `PageHeader`, `JobTabs`, `NAV_SECTIONS`, `jobRoutes` |
| [`frontend/src/components/states.tsx`](../../../../../frontend/src/components/states.tsx) | `ErrorState`, `EmptyState`, `LoadingState`, `JobStatusBadge`, `PrivacyBadge`, `Checksum` |
| [`frontend/src/components/create-job.tsx`](../../../../../frontend/src/components/create-job.tsx) | Tạo job qua backend, hiện lỗi nguyên văn |
| [`frontend/src/components/job-lifecycle.tsx`](../../../../../frontend/src/components/job-lifecycle.tsx) | Nút chuyển trạng thái, gọi transitions/retry |
| [`frontend/src/lib/contracts/api.ts`](../../../../../frontend/src/lib/contracts/api.ts) | Bản mirror TypeScript của shared contract |
| [`frontend/src/lib/api/client.ts`](../../../../../frontend/src/lib/api/client.ts) | `fetchApi` không ném, `ApiError` giữ `status` + `detail` nguyên văn |
| [`frontend/src/lib/api/endpoints.ts`](../../../../../frontend/src/lib/api/endpoints.ts) | Endpoint có type |
| [`frontend/next.config.ts`](../../../../../frontend/next.config.ts) | `rewrites` proxy `/api/v1/*` sang backend |

**Routes**

| Route | Màn hình |
|---|---|
| `/` | Điểm vào, trạng thái M1 |
| `/projects` | Danh sách project + tạo project kèm attestation |
| `/projects/[projectId]` | Chi tiết project + privacy state + danh sách job |
| `/jobs/[jobId]` | Job manifest, stage artifact, attempt |
| `/jobs/[jobId]/viewer` | Viewer (PRODUCT-06) |
| `/jobs/[jobId]/validation` | Validation report, nói rõ chưa có runtime proof |
| `/jobs/[jobId]/review` | Mock review, gắn nhãn synthetic authorization |

**State ownership**

Server component đọc dữ liệu canonical; client component chỉ giữ **view preference**
(view mode, ẩn/hiện layer, đang chọn gì). Không có business truth nào sống chỉ
trong React state: sau mọi lệnh ghi, client gọi `router.refresh()` để đọc lại từ
backend.

**Proxy thay vì CORS**

[`src/config.py`](../../../../../src/config.py) (`cors_origins` mặc định `[]`) và
[`src/main.py`](../../../../../src/main.py) đều **ngoài ownership** của track, nên
không bật CORS ở đó. `frontend/next.config.ts` proxy `/api/v1/*` sang backend bằng
`rewrites`, biến mọi lời gọi thành same-origin.

**Failure handling**

| Tình huống | Kết quả |
|---|---|
| Backend trả 4xx/5xx | `ApiError` giữ `status` + `detail`, `ErrorState` hiện nguyên văn |
| Backend không chạy | `status: 0`, thông điệp "không gọi được backend" — không ném, không màn hình trắng |
| Body lỗi không phải JSON | Dùng nguyên văn body làm `detail` |
| Danh sách rỗng | `EmptyState` có chữ, không phải khoảng trắng |

## 10. Tests

`vitest` + `@testing-library/react` (jsdom), 54 test / 5 file:

- [`frontend/tests/api-client.test.ts`](../../../../../frontend/tests/api-client.test.ts) — 6 test: 200 giữ dữ liệu, envelope lỗi FastAPI giữ nguyên `status` + `detail`, `detail` dạng list gộp thành chuỗi, backend chết → `status: 0`, body không phải JSON, 5xx không bị coi là lỗi client.
- [`frontend/tests/states.test.tsx`](../../../../../frontend/tests/states.test.tsx) — 8 test: `ErrorState`/`EmptyState`/`LoadingState` đều render ra chữ; `JobStatusBadge` và `PrivacyBadge` phủ **mọi** giá trị trong contract.
- [`frontend/tests/layers.test.ts`](../../../../../frontend/tests/layers.test.ts) — 20 test (thuộc PRODUCT-06).
- [`frontend/tests/ply.test.ts`](../../../../../frontend/tests/ply.test.ts) — 10 test (thuộc PRODUCT-06).
- [`frontend/tests/viewer-panel.test.tsx`](../../../../../frontend/tests/viewer-panel.test.tsx) — 10 test (thuộc PRODUCT-06).

Cổng kiểm tra: `npm run typecheck` (`next typegen && tsc --noEmit`), `npm run lint`
(eslint), `npm test`, `npm run build`.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [x] All minimum screens/routes are reachable.
- [x] UI reflects backend state and explicit errors.
- [x] No persisted business truth exists only in React state.
- [x] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

**Ngày:** 2026-09-24 (build/test) và 2026-09-25 (browser smoke) · **Nhánh:** `feat/product`

**Build — `npm run build` (exit 0):**

```
▲ Next.js 16.3.6 (Turbopack)
✓ Compiled successfully in 627ms
✓ Generating static pages (5/5) in 2.2s

Route (app)
┌ ƒ /
├ ○ /_not-found
├ ƒ /jobs/[jobId]
├ ƒ /jobs/[jobId]/review
├ ƒ /jobs/[jobId]/validation
├ ƒ /jobs/[jobId]/viewer
├ ƒ /projects
└ ƒ /projects/[projectId]
```

Mọi route là `ƒ (Dynamic)` — đúng, vì tất cả đều đọc từ backend lúc request.
`_not-found` là `○ (Static)`.

**Test — `npm test`:**

```
✓ tests/api-client.test.ts   (6 tests)
✓ tests/layers.test.ts       (20 tests)
✓ tests/ply.test.ts          (10 tests)
✓ tests/states.test.tsx      (8 tests)
✓ tests/viewer-panel.test.tsx (10 tests)
Test Files  5 passed (5)
     Tests  54 passed (54)
```

**Typecheck / lint:**

```
npm run typecheck → ✓ Types generated successfully  (không còn lỗi tsc)
npm run lint      → không có cảnh báo
```

**Bằng chứng UI phản ánh lỗi backend nguyên văn**
(`frontend/tests/api-client.test.ts`):

```ts
// backend trả 409 {"detail": "không thể tạo job: privacy gate chặn"}
expect(result.error.status).toBe(409);
expect(result.error.detail).toBe("không thể tạo job: privacy gate chặn");
```

**Browser smoke thật — ngày 2026-09-25, Chrome headless trỏ vào backend đang chạy:**

Đây là phần §12 trước đó ghi là "chưa làm". Đã chạy được, nên `Status` chuyển
`IN_PROGRESS` → `DONE`.

Môi trường: backend `uvicorn src.main:app --host 127.0.0.1 --port 8000`, frontend
`npm run dev` (Next.js 16.3.6 Turbopack, `http://localhost:3000`), trình duyệt
`chrome.exe --headless --dump-dom` / `--screenshot`.

**1. Proxy `rewrites` chạy thật — không phải CORS, không phải mock:**

```
GET http://localhost:3000/api/v1/projects   →  200
{"projects":[{"project_id":"project-fixture-001","name":"Fixture warehouse project",
 "source_type":"dataset", ... "privacy_report":{"result":"VERIFIED_ANONYMIZED", ...}}]}
```

Request đi qua Next rồi tới FastAPI thật; backend log ghi nhận đúng từng lượt gọi
từ trình duyệt (`GET /api/v1/jobs/job-fixture-001/scene HTTP/1.1" 200` ×8, v.v.).

**2. Cả 6 route dựng được và trả 200 trong trình duyệt thật:**

| Route | `data-testid` quan sát được trong DOM |
|---|---|
| `/projects` | `privacy-badge` (giá trị `VERIFIED_ANONYMIZED · cho phép dispatch`) |
| `/projects/[projectId]` | `privacy-badge`, `job-status` |
| `/jobs/[jobId]` | `job-status`, `job-tabs`, `lifecycle` |
| `/jobs/[jobId]/viewer` | `scene-canvas`, `scene-revision` (`rev-001`), `brush-proof-absent`, `job-tabs` |
| `/jobs/[jobId]/validation` | `no-runtime-proof`, `job-tabs` |
| `/jobs/[jobId]/review` | `synthetic-authorization`, `job-tabs` |

Dữ liệu trong DOM là dữ liệu fixture thật (`Fixture warehouse project`,
`sha256:afe1bbad091…`), không phải chữ hardcode trong JSX.

**3. Trạng thái lỗi/thiếu bằng chứng hiện đúng trên trình duyệt, không bị "trang
trí" thành thành công:** `brush-proof-absent` (viewer), `no-runtime-proof` +
`UNVERIFIED` (validation), `synthetic-authorization` + "không phải uỷ quyền của
Reviewer thật (PRODUCT-10)" (review). Đây chính là các nhãn mà §11 đòi để một
fixture không bị đọc nhầm thành acceptance.

**4. Ảnh chụp** (`.smoke/shots/`, 6 file `01-projects.png` … `06-review.png`):
`04-viewer.png` (375 KB) là ảnh render 3D thật — sàn và rack của warehouse hiện
lên trong canvas, panel layer có dữ liệu, banner thiếu bằng chứng Brush hiện rõ.

**Limitations**

- Browser smoke chạy trên **Chrome headless**, không phải Chrome có giao diện và
  không phải một bộ E2E test tự động (`playwright` không có trong repo). Đã kiểm
  DOM thật, ảnh chụp thật và request thật tới backend, nhưng **chưa** kiểm
  tương tác người dùng (click, orbit, gõ phím) bằng test tự động. Việc đó thuộc
  PRODUCT-07/07A.
- Chưa có test cho các trang `projects/[projectId]`, `jobs/[jobId]`,
  `validation`, `review` ở tầng component — chúng được `next build` kiểm tra kiểu
  và được browser smoke render thật, nhưng chưa có test tự động trong `vitest`.
- React state chỉ giữ view preference là **ràng buộc trong thiết kế**, kiểm bằng
  review code chứ chưa bằng test tự động.
- `.smoke/` là thư mục tạm của lần smoke, không nằm trong git; evidence được dẫn
  lại bằng chữ ở đây chứ không commit ảnh vào repo.
