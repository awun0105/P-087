# SCENE-08 — Scene Edit Semantics

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M2/M4` |

## 2. Goal

Implement move, rotate, hide/show, rename and delete/disable as backend scene-revision operations.

## 3. Why This Task Exists

PRD requires synchronized editable objects and invalidation after validated-scene edits.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-07 SceneObject model.
- Revision invalidation/review rules from Contract.

## 5. Input Contract

- SceneIR revision, object ID and validated edit command.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- New SceneIR revision with synchronized transform/active/ref behavior.
- Audit event and invalidation of stale candidate/reports when applicable.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/editing/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE`; persisted state is backend SceneIR, not frontend local state.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Move/rotate/hide/rename/delete unit tests.
- Edit-after-validation invalidation and missing-object negative tests.
- Save/reload transform consistency integration test.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Visual/geometry/collider share canonical transform after save/reload.
- [ ] Delete removes geometry/collider from active simulation and handles visual limitation explicitly.
- [ ] Edit never inherits old approval/validation.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Before/after SceneIR/checksums.
- Transform consistency results.
- Delete/path-consumer evidence when integrated.

