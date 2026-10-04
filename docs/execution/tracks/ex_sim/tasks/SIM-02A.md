# SIM-02A — Collider Edit And Resize Validation

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2/M4` |

## 2. Goal

Validate collider type, dimensions, local transform and parameters after user edit and force a new SceneIR revision.

## 3. Why This Task Exists

P0 allows collider inspection/editing; invalid edits must not reach candidate build.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-02 ColliderSpec outputs.
- Scene revision invalidation rules.
- PRODUCT-07A is UI consumer.

## 5. Input Contract

- Existing ColliderSpec, edit command and SceneIR revision.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Validated edited ColliderSpec in new SceneIR revision or deterministic validation error.
- Invalidation event for stale candidate/reports.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/colliders/`
- `src/services/simulation/validation/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` against ColliderSpec and revision contracts.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Type/dimensions/local-transform/parameter unit tests.
- Negative/zero/non-finite/unsupported edit negative tests.
- Edit→revision→preflight integration test.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Only allowed collider types/parameters persist.
- [ ] Every accepted edit creates new revision and invalidates stale validation/approval.
- [ ] PRODUCT can display actionable errors without duplicating validation logic.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Before/after ColliderSpec/SceneIR.
- Validation/invalidation tests.
- Invalid edit examples.

