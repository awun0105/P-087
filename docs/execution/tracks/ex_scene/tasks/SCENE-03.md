# SCENE-03 — Multi-View Object Association

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M1/M2` |

## 2. Goal

Associate masks across views with camera poses and canonical geometry to create stable candidate identities.

## 3. Why This Task Exists

SAM2 masks per frame do not establish cross-view object identity.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-01 poses/canonical geometry.
- SCENE-02 mask artifacts.

## 5. Input Contract

- Masks with metadata, normalized camera poses and canonical geometry.
- Deterministic association config.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Candidate identity groups with source mask/geometry refs and provenance.
- Association confidence/diagnostics.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/association/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` deterministic baseline; Gaussian Grouping/ObjectGS/SegAnyGaussians/R2G are `REFERENCE`, not runtime dependencies by default.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Deterministic grouping and stable-ID unit tests.
- Conflicting/unprojectable mask negative tests.
- Fixture masks+poses+geometry smoke.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Repeated run on same fixture produces same grouping/IDs.
- [ ] Each group traces to masks, poses and geometry selections.
- [ ] Baseline produces input accepted by SCENE-04.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Grouping visualization/table.
- Config/seed/checksum.
- Failure/ambiguity sample.

