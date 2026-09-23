# PRODUCT-10 — Review Lifecycle And Authorization

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M2/M4` |

## 2. Goal

Implement submit/review/approve/reject lifecycle and ApprovalRecord bound to exact candidate/validation.

## 3. Why This Task Exists

Automation/editor cannot self-approve; review must see evidence before release.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- CandidatePackage, PreflightReport, ValidationReport and conditional EvaluationReport.
- Reviewer/editor identity and permission authority.
- Accepted review state machine.

## 5. Input Contract

- READY_FOR_REVIEW revision, exact candidate/reports and authenticated actor.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- ApprovalRecord or rejection record/reason.
- Audit entries and valid state transition.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/review/`
- `src/api/` review endpoints
- `frontend/src/features/review/`
- validation evidence UI trong `frontend/src/features/validation/`
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` PRD lifecycle and authorization; LLM cannot approve or alter validation.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- State/permission/checksum/warning/rejection unit/API tests.
- Editor approve, mismatch, missing reason and rejected-release negative tests.
- Review UI evidence-bundle integration.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Only Reviewer can approve/reject after required evidence.
- [ ] Decision binds candidate and validation checksums; warnings reference evidence IDs.
- [ ] Any post-validation edit creates DRAFT revision and invalidates old decision.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Approval/rejection/audit records.
- Authorization negative tests.
- Review UI recording.
