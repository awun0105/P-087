# PRODUCT-07 — Object And Human Confirmation Actions

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M2/M3` |

## 2. Goal

Expose P0 candidate/object actions through UI/application commands without duplicating Scene Core logic.

## 3. Why This Task Exists

Users must confirm/correct candidates and edit SceneObjects in the product workflow.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-06 viewer selection.
- SCENE-05 Human Confirmation and SCENE-08 edit command contracts.

## 5. Input Contract

- Selected candidate/object, current scene revision and allowed command schema.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Rename/confirm/ignore/merge/create/reassign and move/rotate/hide/delete requests.
- Updated revision/audit feedback.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/features/scene/`
- shared object controls trong `frontend/src/components/`
- `src/api/` command endpoints
- `tests/test_orchestration/` and browser tests

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` UI/application layer consuming Scene Core operations; no local-only mutation.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Command authorization/payload unit/API tests.
- Stale revision, invalid operation and hidden local mutation negative tests.
- Candidate correction and object edit browser integration.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] All P0 actions invoke backend domain operations.
- [ ] Stale/conflicting edits return actionable errors.
- [ ] UI reload shows canonical revision/audit result.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Before/after UI and SceneIR.
- Correction/edit API logs.
- Conflict/error case.
