# SIM-04 — Deterministic Preflight

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2` |

## 2. Goal

Run deterministic static rules before CandidatePackage build and publish PreflightReport.

## 3. Why This Task Exists

Avoid expensive Isaac runs and prevent review when metric, geometry, collider, transform, spawn or candidate prerequisites fail.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-03 physics SceneIR.
- Normative PreflightReport/ruleset contract.
- Normative rule ID `OBJECT_CONFIRMATION_INCOMPLETE` cho unresolved object candidates.

## 5. Input Contract

- Physics-enriched SceneIR, ruleset version and product path configuration.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- PreflightReport with per-rule evidence/remediation and blocking_result.
- Candidate-build allow/block decision.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/preflight/`
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` deterministic rules; LLM may explain but cannot change results.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Metric/collider/transform/bounds/artifact/spawn/candidate rule unit tests.
- ERROR/FAIL cannot become PASS negative tests.
- Fixture pass/fail report contract smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] All applicable P0 static rules execute deterministically.
- [ ] Candidate build blocked whenever blocking_result is not PASS.
- [ ] Object-candidate rule cannot be confused with final CandidatePackage review.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Pass/fail PreflightReports.
- Ruleset/config version.
- Representative remediation/error.
