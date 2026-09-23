# SCENE-09 — Publish SceneIR

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M1/M2` |

## 2. Goal

Build, version, serialize/deserialize, validate and publish SceneIR for EX-SIM/EX-PRODUCT.

## 3. Why This Task Exists

SceneIR is the shared editable-scene contract and cross-track handoff.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-06 environment and SCENE-07 objects.
- SCENE-08/08A behavior must remain compatible.
- Normative SceneIR contract resolved before final handoff.

## 5. Input Contract

- Environment, SceneObjects, coordinate/metric/revision/provenance content.
- Workflow review state không thuộc SceneIR input/content checksum.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Versioned, checksummed SceneIR with resolvable refs.
- Publication/handoff record.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/`
- `src/models/contracts/scene.py` and `fixtures/scene_ir/` with consumer review
- `tests/test_contracts/` and `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` exactly one project schema; no PhysicsScene or frontend-specific duplicate.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- SceneIR roundtrip/version/checksum/ref unit tests.
- Duplicate ID, invalid transform, unresolved ref negative tests.
- EX-SIM direct consumer contract test.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] SceneIR validates normative schema and refs resolve.
- [ ] Revision/provenance follow accepted contract; review state is stored separately.
- [ ] EX-SIM consumes fixture and real SceneIR without manual edit.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Published SceneIR/checksum.
- Roundtrip/consumer tests.
- Representative schema failure.
