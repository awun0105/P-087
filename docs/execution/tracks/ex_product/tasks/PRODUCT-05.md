# PRODUCT-05 — Web Studio Shell

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
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

**Ngày:** 2026-09-24 · **Nhánh:** `feat/product`

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

**Limitations**

- **Chưa chạy browser smoke.** Đây là khoảng trống lớn nhất: §10 yêu cầu "browser
  shell smoke through fixture API" và M1 yêu cầu demo được trên browser, nhưng
  trong phiên này chỉ chạy được `vitest` (jsdom) + `next build`. Chưa có lần nào
  mở trình duyệt thật, trỏ vào backend đang chạy, đi hết
  `project → job → viewer → review`. Vì vậy `Status` để `IN_PROGRESS`, **không**
  phải `DONE`.
- Điều *được* chứng minh: shell build được, mọi route dựng được, contract biên dịch
  khớp backend, và các trạng thái lỗi/rỗng render ra chữ. Điều *chưa* được chứng
  minh: luồng điều hướng thật trong browser và proxy `rewrites` sang backend thật.
- Chưa có test cho các trang `projects/[projectId]`, `jobs/[jobId]`,
  `validation`, `review` ở tầng component — chúng mới chỉ được `next build` kiểm
  tra kiểu, chưa được render trong test.
- React state chỉ giữ view preference là **ràng buộc trong thiết kế**, kiểm bằng
  review code chứ chưa bằng test tự động.
