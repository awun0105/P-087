# SIM-03 — Physics Enrichment

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2` |

## 2. Goal

Attach ColliderSpec/physics metadata to a new revision of the same SceneIR schema.

## 3. Why This Task Exists

Cross-track architecture forbids a competing PhysicsScene format.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-02 generated colliders; SIM-02A edit semantics.
- SCENE-09 SceneIR contract.

## 5. Input Contract

- SceneIR and generated/validated collider records.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Physics-enriched SceneIR revision with checksum/provenance.
- Revision invalidation record.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/`
- `src/models/contracts/scene.py` only with EX-SCENE/PRODUCT review
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE`; enrich the shared SceneIR schema, do not create `PhysicsScene.json`.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Enrichment/roundtrip/ref unit tests.
- Missing object/geometry and duplicate collider negative tests.
- EX-PRODUCT/Preflight direct consumer contract test.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Physics revision validates same SceneIR schema.
- [ ] All active required entities have traceable physics refs where policy requires.
- [ ] Old candidate/reports are invalidated.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Input/output SceneIR checksums.
- Enrichment contract tests.
- Invalid binding failure.

