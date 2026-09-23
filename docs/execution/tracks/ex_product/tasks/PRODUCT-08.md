# PRODUCT-08 — Real Worker Orchestration

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M2/M3` |

## 2. Goal

Orchestrate REC→SCENE→SIM using published artifacts and stop downstream when required output is absent/invalid.

## 3. Why This Task Exists

Product E2E is not proven by independent CLIs; it needs one upload/job/candidate lineage.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-03 dispatch and PRODUCT-04 resolver.
- REC-11, SCENE-10 and SIM-09 stable entrypoints.
- Shared contract/golden fixtures.

## 5. Input Contract

- InputManifest/JobManifest, worker configs and artifact registry.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Stage execution records and real ReconstructionBundle/SceneIR/Candidate/reports lineage.
- Final ready-for-review state or exact failed stage.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/jobs/`
- `src/services/orchestration/artifacts/`
- `src/api/` status endpoints
- `tests/integration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` control flow over worker interfaces; no cross-track internal imports or manual conversion.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Stage order/handoff/checksum unit/integration tests.
- Missing/invalid artifact prevents downstream negative tests.
- Real REC→SCENE→SIM Integration #1.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Each consumer reads producer artifact directly.
- [ ] Status only advances after schema/checksum/resolver proof.
- [ ] Same candidate lineage reaches validation/review UI.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Integration JobManifest/artifact graph.
- M2 handoff test output.
- Controlled upstream-failure trace.

