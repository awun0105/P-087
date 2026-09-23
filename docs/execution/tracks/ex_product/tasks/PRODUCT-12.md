# PRODUCT-12 — Stable Product Demo Route

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M3/M5` |

## 2. Goal

Provide a short reproducible Web/API demo covering real scene inspection/edit, validation, review and release on one lineage.

## 3. Why This Task Exists

Pitch proof must demonstrate Product E2E, not isolated mocks or backend benchmark success.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-05 through PRODUCT-11.
- Primary Demo Scene, locked environment and fallback plan.

## 5. Input Contract

- Primary Demo Scene/job/artifacts and accepted demo choreography.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Live/precomputed demo route and backup recording.
- E2E evidence bundle with exact versions/checksums.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `tests/e2e/`
- demo navigation trong `frontend/src/app/`
- browser/component support trong `frontend/tests/`
- existing product/orchestration modules only for bounded stability fixes
- evidence location accepted in Foundation Lock

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` deterministic demo path; no fake results or rebuild-after-approval.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Full Web/API E2E on one candidate lineage.
- Failure/fallback rehearsal and authorization checks.
- AC-08/AC-12/review/release evidence verification.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Upload/job→REC→SCENE→SIM→Web review→release runs on one lineage.
- [ ] Demo can show Visual/Geometry/Collider, edit/path response and review decision.
- [ ] Live, precomputed and backup paths are clearly labeled and evidence-backed.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Full E2E screen recording.
- Artifact/checksum/version inventory.
- Fallback rehearsal result and known limitations.
