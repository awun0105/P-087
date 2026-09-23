# SIM-07 — Structured ValidationReport

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2/M4` |

## 2. Goal

Serialize candidate-bound runtime checks and per-path observations into ValidationReport consumed directly by PRODUCT.

## 3. Why This Task Exists

A single opaque result cannot prove required load/collision/spawn/path behavior.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-06 observed validation evidence.
- Normative structured `checks[]`, observed `path_results[]`, environment versions and overall result are locked.

## 5. Input Contract

- SIM-06 observed evidence and environment/validator versions.
- Candidate checksum and validation config checksum.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Structured ValidationReport with checks, path_results, overall_result and report checksum.
- Published report ref.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/validation/`
- `src/models/contracts/validation.py` and fixture with PRODUCT review
- `tests/test_contracts/` and `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` against accepted shared contract; no ad-hoc result blob.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Report roundtrip/checksum/per-pair unit tests.
- Wrong candidate, missing required check and ERROR-as-PASS negative tests.
- PRODUCT direct-consumer contract test.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Report binds exact candidate and validator/environment/config versions.
- [ ] Required checks and every configured path are structured and evidenced.
- [ ] No hidden expected label is read or serialized by ValidationReport.
- [ ] PRODUCT reads report without manual conversion.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- ValidationReport/checksum.
- Contract/consumer test output.
- Malformed/mismatched report rejection.
