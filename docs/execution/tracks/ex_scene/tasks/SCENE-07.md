# SCENE-07 — SceneObject Model

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M1/M2` |

## 2. Goal

Represent reconstructed and user-added SceneObjects with one canonical transform and linked visual/geometry/asset/collider refs.

## 3. Why This Task Exists

Frontend and simulator must share one object identity and transform truth.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-06 decomposition.
- Authority gate: final SceneIR/SceneObject fields must be synchronized in normative Contract.

## 5. Input Contract

- Environment/object bindings and scene/revision metadata.
- Normative SceneIR/ColliderSpec contracts.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Validated SceneObject records ready for SceneIR publication.
- Transform/ref/state invariants: unique IDs per revision, collider offset
  parented to object local frame, and sized primitive or asset for `user_added`.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/`
- `src/models/contracts/scene.py` only with EX-SIM/PRODUCT review
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` from project contract; no competing scene model.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Canonical transform/ref/origin/active unit tests.
- Missing geometry, invalid user-added asset/primitive and duplicate-ID negative tests.
- Roundtrip with current shared model.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] One canonical transform controls all representations.
- [ ] Required rename/provenance/revision semantics are contract-backed, not fixture-inferred.
- [ ] Objects validate for both reconstructed and allowed user-added origins.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- SceneObject examples.
- Invariant/roundtrip tests.
- Invalid representation failure.
