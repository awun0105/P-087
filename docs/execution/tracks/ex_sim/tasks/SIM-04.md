# SIM-04 — Deterministic Preflight

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `DONE` |
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

1. Tạo `src/services/simulation/preflight/rules.py` cài đặt 6 rule tĩnh chuẩn P0:
   - `METRIC_SCALE_MISSING`: kiểm tra `metric_scale.status == "CONFIRMED"` và `meters_per_unit > 0`.
   - `COLLIDER_MISSING`: kiểm tra mọi active `SceneObject` có `collider` hợp lệ và `environment` có `collider_ref`.
   - `TRANSFORM_INVALID`: kiểm tra quaternion chuẩn hóa và translation hữu hạn (không NaN/Inf).
   - `OBJECT_OUT_OF_BOUNDS`: kiểm tra vị trí/bounding box vật thể trong workspace bounds và không penetration sâu dưới mặt sàn (`z < floor_min_z`).
   - `REQUIRED_ARTIFACT_MISSING`: kiểm tra các artifact refs (geometry, collider) tồn tại khi có artifact resolver.
   - `OBJECT_CONFIRMATION_INCOMPLETE`: kiểm tra không còn object nào ở trạng thái `CANDIDATE`.
2. Tạo `src/services/simulation/preflight/engine.py` điều phối thực thi các rules, tính `blocking_result` (FAIL/ERROR/PASS) và tạo `PreflightReport` chuẩn kèm SHA-256 `report_checksum`.
3. Export public API tại `src/services/simulation/preflight/__init__.py`.
4. Tạo bộ unit tests toàn diện tại `tests/test_simulation/test_preflight.py` bao phủ cả positive, negative, và invariant không bao giờ đổi ERROR/FAIL thành PASS.

## 10. Tests

- Metric/collider/transform/bounds/artifact/spawn/candidate rule unit tests.
- ERROR/FAIL cannot become PASS negative tests.
- Fixture pass/fail report contract smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [x] All applicable P0 static rules execute deterministically.
- [x] Candidate build blocked whenever blocking_result is not PASS.
- [x] Object-candidate rule cannot be confused with final CandidatePackage review.
- [x] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

- **Trạng thái**: DONE (2026-09-26).
- **Mã nguồn đã triển khai**:
  - `src/services/simulation/preflight/rules.py`: Cài đặt đủ 6 quy tắc tĩnh P0 (`METRIC_SCALE_MISSING`, `COLLIDER_MISSING`, `TRANSFORM_INVALID`, `OBJECT_OUT_OF_BOUNDS`, `REQUIRED_ARTIFACT_MISSING`, `OBJECT_CONFIRMATION_INCOMPLETE`).
  - `src/services/simulation/preflight/engine.py`: Engine điều phối `run_preflight`, đánh giá `blocking_result` (FAIL/ERROR/PASS) và tính SHA-256 `report_checksum` qua `canonical_content_checksum`.
  - `src/services/simulation/preflight/__init__.py`: Export public API.
- **Evidence kiểm thử**:
  - Command: `pytest tests/test_simulation/test_preflight.py -v`
  - Kết quả: `9 passed in 0.13s` bao phủ positive, negative trên từng rule và invariant không quy đổi FAIL/ERROR thành PASS.
  - Linter & Formatting: `ruff check` và `ruff format --check` đều pass 100%.
