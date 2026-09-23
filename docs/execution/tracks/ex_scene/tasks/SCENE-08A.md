# SCENE-08A — Add Primitive Or Asset

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M2/M4` |

## 2. Goal

Create user-added SceneObject from supported primitive dimensions or asset_ref with explicit size parameters.

## 3. Why This Task Exists

AC-12 requires adding, moving and deleting an obstacle whose geometry/collider affects validation.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-07 SceneObject model.
- Approved primitive/asset catalog and size-parameter semantics.
- SIM-02A consumes collider edits; PRODUCT-07A provides UI.

## 5. Input Contract

- Scene revision and validated primitive/asset creation command.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- New SceneIR revision containing `origin=user_added` SceneObject with geometry/asset provenance.
- Primitive path khai báo `primitive_dimensions_xyz_m` dương/hữu hạn; asset path
  giữ `asset_ref` và asset-specific sizing theo catalog của task.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/editing/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE`; do not expose generic scale until propagation to visual/geometry/collider is defined and tested.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Primitive dimensions and asset-specific parameter unit tests.
- Missing dimensions/asset, unsupported scale and invalid placement negative tests.
- Add/save/reload/delete integration test.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] User-added object has valid geometry or asset reference and explicit sizing.
- [ ] Revision/audit/provenance rules apply.
- [ ] Output is consumable by collider generation and Product UI.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Added-object SceneIR diff.
- Dimension/provenance tests.
- Invalid generic-scale response.
