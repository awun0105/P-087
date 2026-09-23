# SIM-05 — Candidate OpenUSD Build

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-SIM` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Đạt |
| Target milestone | `M2/M3` |

## 2. Goal

Translate exact physics SceneIR revision into immutable CandidatePackage with OpenUSD entrypoint, inventory and package checksum.

## 3. Why This Task Exists

Validation/review/release must bind the exact candidate tested, not a rebuilt file.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Dataset Playbook](../../../../DATASET_PLAYBOOK.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- SIM-04 PreflightReport PASS.
- Canonical coordinate/runtime package policy locked.

## 5. Input Contract

- Physics SceneIR checksum, PASS preflight report, JobManifest and build config.

Evaluation-only references chỉ được đọc trong evaluator theo protocol.

## 6. Output Contract

- Immutable CandidatePackage and candidate manifest/checksum.
- SceneIR→USD transform/asset/collider provenance.
- CandidateManifest mang shared canonical `CoordinateSystem`; exporter convert
  convention native tại adapter boundary, không ghi free-form unit/up-axis.

Artifacts/reports phải bind đúng subject/candidate checksum, version và evidence refs.

## 7. Code Ownership

Create/modify trong:

- `src/services/simulation/usd/`
- `tests/test_simulation/`
- shared candidate contract with PRODUCT review

Không sửa scene/product/reconstruction internals. Shared contract change cần producer + consumers review.

## 8. Tool / Repository Strategy

`SELF-CODE` adapter using OpenUSD APIs; do not mutate package after checksum.

Research systems chỉ là references trừ khi change control chấp nhận runtime dependency.

## 9. Implementation Plan

Assignee điền files, runtime command, failure handling và proof sau inspect. Không tự khóa policy còn mở.

## 10. Tests

- Hierarchy/unit/up-axis/transform/inventory/checksum unit tests.
- Preflight-not-PASS and unresolved asset negative tests.
- Fixture SceneIR→CandidatePackage smoke.

Ghi rõ local/mock proof khác real Isaac/GPU/locked-acceptance proof.

## 11. Definition of Done

- [ ] Package preserves units, hierarchy, transforms, geometry, colliders and assets.
- [ ] Checksum covers canonical package inventory/content without self-reference.
- [ ] `artifact_checksums[]` khớp đúng ordered package refs; từng byte ref resolve
  và SHA-256 match trước khi công bố `candidate_checksum` theo Contract 3.1.1.
- [ ] Exact package is consumable by SIM-06 and immutable through review.
- [ ] Focused tests, required real-runtime/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- CandidatePackage/checksum.
- USD inspection/load-precheck.
- Blocked-build failure.
