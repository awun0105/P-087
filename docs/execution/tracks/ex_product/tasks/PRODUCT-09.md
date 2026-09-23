# PRODUCT-09 — Progress Error And Retry

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M2/M4` |

## 2. Goal

Expose truthful stage status/errors and retry without overwriting prior attempts/releases.

## 3. Why This Task Exists

AC-09 requires recoverable known failures; fake percentage undermines observability.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-02 job state and PRODUCT-08 orchestration.
- Worker stage error contract.

## 5. Input Contract

- Worker/job status/events/errors and retry command.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- User-visible progress/error/retry state.
- New attempt records preserving original inputs and history.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/jobs/`
- `src/api/` status/retry endpoints
- `frontend/src/features/jobs/`
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE`; use discrete stage/status unless backend emits real measured progress.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Status/error/retry and event-order unit/API tests.
- Fake success, invalid retry and overwritten history negative tests.
- Injected failure→UI→retry integration test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Exact failed stage/human message/retryability are visible.
- [ ] Retry preserves input and prior attempt/release.
- [ ] No fabricated percentage is shown as measured progress.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Injected failure/retry recording.
- Job attempt history/checksums.
- Error response/UI screenshots.
