# PRODUCT-11 — Exact Candidate Release

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `TODO` |
| Owner | Cường |
| Target milestone | `M3/M4` |

## 2. Goal

Seal the exact validated/approved CandidatePackage into ReleaseManifest without rebuilding it.

## 3. Why This Task Exists

Release lineage and reproducibility depend on candidate immutability.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-10 valid APPROVE ApprovalRecord.
- Candidate/validation/evaluation conditionality accepted in ReleaseManifest contract.

## 5. Input Contract

- ApprovalRecord, exact candidate/preflight/validation and required EvaluationReport by run type.
- Input/job/config/software/artifact inventory.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Checksummed ReleaseManifest and sealed release reference.
- Release audit/timestamp.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/release/`
- `src/api/` release endpoint
- `src/models/contracts/release.py` only with shared review
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` release sealing; never rerun USD builder after approval.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Assignee điền files, API/UI flow, state ownership, failure handling và proof sau inspect. Không đổi scope.

## 10. Tests

- Manifest/checksum/conditional-evaluation unit tests.
- Mismatched/unapproved/rejected/edited candidate negative tests.
- Independent manifest reconstruction/audit integration test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Release binds exact candidate and ApprovalRecord checksums.
- [ ] Locked acceptance requires EvaluationReport; ordinary no-GT release follows accepted conditional rule.
- [ ] No package content changes between validation, approval and release.
- [ ] Release candidate/report identities khớp exact package và report đã verify;
  serialized release có canonical content checksum riêng, không dùng lại byte hash.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Pending implementation.

Expected evidence:

- ReleaseManifest/package checksums.
- Lineage audit test.
- Mismatch/rebuild rejection.
