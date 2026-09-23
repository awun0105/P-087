# PRODUCT-07A — Added Asset And Collider Controls

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M2/M4` |

## 2. Goal

Support add/delete obstacle, explicit primitive/asset sizing and collider type/dimensions/local-transform controls.

## 3. Why This Task Exists

AC-12 requires layout-changing obstacle edits that affect path/collision validation.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-06/07 viewer/action flow.
- SCENE-08A add-object and SIM-02A collider-edit contracts.

## 5. Input Contract

- Supported asset/primitive catalog, current revision and collider schemas.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Backend commands for user-added object/collider edits.
- Updated scene revision and validation errors.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `frontend/src/features/scene/`
- collider/viewer controls trong `frontend/src/features/viewer/`
- `src/api/` command endpoints
- browser/e2e tests

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` controls; no generic scale until propagation semantics are accepted/tested.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Control serialization and validation display unit tests.
- Unsupported scale, invalid dimensions and stale revision negative tests.
- Add→move→validate→delete→revalidate browser/E2E flow.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Added object has valid explicit size and collider controls.
- [ ] All changes persist as new backend revision and invalidate stale reports.
- [ ] Path/collision flow observes current revision.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- AC-12 interaction recording.
- SceneIR/report lineage before/after.
- Invalid collider UI evidence.
