# SCENE-02 — Object Extraction With SAM2

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SCENE` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đức |
| Target milestone | `M1/M2` |

## 2. Goal

Run SAM2 through an adapter to produce mask artifacts with frame, bbox, confidence and provenance metadata.

## 3. Why This Task Exists

P0 requires automatic candidate generation before manual correction.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SCENE-01 validated RGB frame refs.
- Locked SAM2/runtime/checkpoint source and license.

## 5. Input Contract

- RGB frame refs/visual evidence from ReconstructionBundle.
- Versioned SAM2 config/checkpoint.

Manual evaluation annotations không được feed vào prediction/object creation.

## 6. Output Contract

- Mask artifacts plus frame_id, mask_id, bbox, confidence and provenance.
- Extraction stats/errors.

Published artifacts phải có version/checksum/provenance và resolvable refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/scene/extraction/`
- `tests/test_scene/`

Không sửa reconstruction, simulation hoặc product implementation. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`REUSE` SAM2 predictor/propagation; team owns adapter and artifact metadata, not a new foundation model.

Giữ research repos ở mức reference/adapter đã được phê duyệt; không thay project architecture.

## 9. Implementation Plan

Assignee điền files/sequence/failure handling sau khi inspect repository. Không đổi task scope hoặc authority gate.

## 10. Tests

- Mask metadata/serialization unit tests.
- Missing frame/checkpoint and empty-result negative tests.
- Few-frame SAM2 GPU smoke.

Tách mock/fixture proof khỏi real model/artifact handoff proof.

## 11. Definition of Done

- [ ] Masks are not stored as untracked image files only.
- [ ] Every mask binds source frame/config/model provenance.
- [ ] Output can feed SCENE-03 deterministically.
- [ ] Focused tests, applicable handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Mask samples/metadata.
- Model/runtime config and smoke log.
- Extraction stats/failure.

