# PRODUCT-03 — Worker Dispatch Abstraction

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Define dispatch interface that can switch from mock workers to real track entrypoints without changing product lifecycle.

## 3. Why This Task Exists

PRODUCT must orchestrate track boundaries and avoid importing internal implementations.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-02 job lifecycle.
- Stable/mock worker contracts; real REC-11/SCENE-10/SIM-09 later.

## 5. Input Contract

- Job/stage request, artifact refs and versioned worker config.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Dispatch handle/status/result/error normalized to JobManifest.
- Mock and real adapter implementations.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/jobs/`
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` interface + basic queue/CLI integration; no advanced scheduler in P0.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Mock dispatch/result/error/timeout unit tests.
- Unknown worker and malformed result negative tests.
- Contract test against each stable track entrypoint.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] PRODUCT imports no track internals.
- [ ] Mock and real workers share one dispatch/result contract.
- [ ] Worker failures map to exact stage and retryability.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Interface examples.
- Mock/real contract tests.
- Timeout/failure record.

