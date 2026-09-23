# PRODUCT-05 — Web Studio Shell

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
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

`SELF-CODE` on Next.js primitives; do not create alternate backend state in frontend.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Route/state/API-client unit tests.
- Unavailable/error/loading state negative tests.
- Browser shell smoke through fixture API.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] All minimum screens/routes are reachable.
- [ ] UI reflects backend state and explicit errors.
- [ ] No persisted business truth exists only in React state.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Build/test output.
- Screen captures/navigation recording.
- API error-state evidence.
