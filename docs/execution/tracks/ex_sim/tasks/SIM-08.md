# SIM-08 — EvaluationRunner

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2/M4` |

## 2. Goal

Run visual, pose, geometry, object and path protocols in a subsystem separate from product validation.

## 3. Why This Task Exists

Acceptance/benchmark metrics require controlled ground truth without leaking it into prediction/runtime.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- Locked Evaluation Set, protocol ID and reference checksums.
- Prediction artifact frozen before evaluator reads references.
- SIM-06 observed path results for EV-PATH.

## 5. Input Contract

- Frozen prediction subject/checksum.
- Protocol-selected held-out RGB, traj_gt, geometry, annotations and locked path references.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.
`ArtifactRef.data_class` phải khai báo `ground_truth`/`evaluation_only` cho raw
reference tương ứng; URI folder không phải access policy. GT-assisted derived
artifact giữ provenance riêng, không được claim independent benchmark.

## 6. Output Contract

- EvaluationReport bound to reconstruction/scene_revision/candidate_package as protocol requires.
- Metric evidence and preprocessing dependency disclosure.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `eval/visual/`, `eval/pose/`, `eval/geometry/`, `eval/object/`, `eval/path/`, `eval/protocols/`
- `src/services/simulation/` evaluator orchestration
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` from Dataset Playbook; ground truth is evaluator-only and methodology claims must disclose dependencies.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Metric math/protocol binding unit tests.
- Reference-before-prediction, wrong subject and independence-claim negative tests.
- Locked-protocol smoke producing EvaluationReport.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Visual/pose/geometry/object/path metrics run only when protocol/reference supports them.
- [ ] EV-PATH compares observed vs expected and records unsafe false-clear.
- [ ] Locked acceptance produces valid report; ordinary upload can remain N/A.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- EvaluationReport/metric tables.
- Protocol/reference/preprocessing checksums.
- Separate product-validation vs benchmark results.
