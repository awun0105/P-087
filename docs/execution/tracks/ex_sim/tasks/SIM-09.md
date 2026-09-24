# SIM-09 — Simulation And Evaluation Worker Entrypoints

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2/M3` |

## 2. Goal

Expose separate stable simulation-worker and evaluation-runner interfaces.

## 3. Why This Task Exists

Evaluation-only access must not leak into generic Isaac validation or PRODUCT prediction path.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-06/07 product validation path.
- SIM-08 evaluator path.
- Job/artifact lifecycle contracts.

## 5. Input Contract

- `simulation-worker validate <scene-ir|candidate>` product inputs.
- `evaluation-runner run <prediction> <protocol>` controlled evaluator inputs.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Published candidate/validation artifacts and separate evaluation report/stage records.
- Stable dispatch contracts for PRODUCT-08.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/`
- `eval/` entrypoints
- `tests/test_simulation/`

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` wrappers preserving process/data boundary and distinct permissions.

**Architecture Reference (Audit #3):**
- Candidate reference: [`zst1406217/VR-Robo`](https://github.com/zst1406217/VR-Robo) (xem chi tiết tại [`docs/execution/audits/03_vr_robo.md`](../../../audits/03_vr_robo.md)).
- Pattern tham khảo (**`ADAPT`**): Tách biệt môi trường thực thi (process isolation) giữa IsaacLab simulation worker và Gaussian renderer worker, chạy trên các container độc lập để tránh dependency/driver conflicts.

## 9. Implementation Plan

1. Thiết kế CLI wrapper riêng biệt cho `simulation-worker` (validation) và `evaluation-runner` (benchmark).
2. Áp dụng quy tắc ranh giới tiến trình (process boundary), đảm bảo worker thực thi độc lập và giao tiếp qua file artifacts/status JSON.
3. Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- CLI/config/status/error unit tests.
- Validator denied evaluation-only refs negative test.
- Worker smoke and PRODUCT dispatch contract tests.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Two entrypoints are operationally and permission-wise separate.
- [ ] Stage success requires valid outputs/checksums; retries preserve attempt provenance.
- [ ] PRODUCT can dispatch validation without evaluator credentials/data.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- Example commands/logs.
- Access-boundary negative proof.
- JobManifest stage records and PRODUCT handoff.

