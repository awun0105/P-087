# SCENE-06 — Scene Decomposition

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M2` |

## 2. Goal

Decompose global reconstruction into Environment and independent object bindings.

## 3. Why This Task Exists

Global reconstruction is not an editable scene; confirmed objects must be independently transformable/removable.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-05 confirmed candidates.
- Canonical geometry and representation refs.

## 5. Input Contract

- Confirmed candidates, global visual/geometry and canonical coordinate metadata.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Environment representation and object-level visual/geometry bindings.
- Decomposition provenance.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/decomposition/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` with R2G/gs-real2sim/DISCOVERSE as `REFERENCE`; do not make full research systems runtime dependencies.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Environment/object partition and ref-binding unit tests.
- Overlap/missing geometry/duplicate ownership negative tests.
- Candidate-to-decomposition fixture smoke.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Environment and independent object bindings exist.
- [ ] Confirmed reconstructed object can be removed from active geometry/physics path.
- [ ] Bindings preserve source provenance and feed SCENE-07/09.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Decomposition sample/visualization.
- Object-to-source mapping.
- Ambiguous binding failure.

