# SCENE-05 — Human Confirmation Operations

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M2` |

## 2. Goal

Implement rename, confirm, ignore, merge, create-missing and reassign as auditable domain operations.

## 3. Why This Task Exists

PRD P0 requires minimal correction before candidates become SceneObjects.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-04 candidate model.
- PRODUCT UI is a consumer, not a prerequisite for domain implementation.

## 5. Input Contract

- Candidate records and selected mask/geometry regions.
- Actor/command metadata and scene revision.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Confirmed/corrected candidates and operation audit trail.
- New revision/invalidations where required by contract.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/candidates/`
- `src/services/scene/editing/` if shared command pattern applies
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` PRD operations; UI remains EX-PRODUCT.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Rename/confirm/ignore/merge/create/reassign unit tests.
- Invalid source/target and duplicate ownership negative tests.
- Before/after correction smoke with persisted revision.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Every required operation has deterministic validation and audit metadata.
- [ ] At least one missing/grouping correction case completes.
- [ ] PRODUCT can invoke operations without importing scene internals.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Before/after candidates.
- Operation/audit records.
- Invalid operation errors.

