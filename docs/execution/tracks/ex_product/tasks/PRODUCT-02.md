# PRODUCT-02 — Job State Machine And Persistence

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Implement QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED transitions and persisted attempt history.

## 3. Why This Task Exists

Long-running stages cannot be modeled as one HTTP request or fake success.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-01 job API.
- JobManifest and stage artifact lifecycle contract.

## 5. Input Contract

- Validated job creation/transition commands and JobManifest.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Persisted job/current-stage/attempt records.
- Validated transition/error responses.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/jobs/`
- `src/api/` routes
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` deterministic state machine; storage choice follows existing architecture/accepted config.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Allowed transition and persistence unit tests.
- Invalid transition, failed-stage-as-success and overwrite-attempt negative tests.
- Create→run→complete/fail API integration tests.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Only legal transitions persist.
- [ ] SUCCEEDED requires required artifacts/checksums resolvable.
- [ ] Retry appends attempt/history and does not overwrite prior provenance.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Transition table/test output.
- Persisted JobManifest examples.
- Failure/retry sequence.

