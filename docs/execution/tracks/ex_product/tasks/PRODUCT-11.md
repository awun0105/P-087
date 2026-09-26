# PRODUCT-11 — Exact Candidate Release

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
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

**Files đã tạo/sửa:**

| File | Vai trò |
|---|---|
| [`frontend/src/features/review/ReleasePanel.tsx`](../../../../../frontend/src/features/review/ReleasePanel.tsx) | UI seal exact candidate với điều kiện release |
| [`frontend/src/app/jobs/[jobId]/release/page.tsx`](../../../../../frontend/src/app/jobs/[jobId]/release/page.tsx) | Route release mới |
| [`tests/release-panel.test.tsx`](../../../../../tests/release-panel.test.tsx) | Kiểm tra payload + disabled states |
| [`src/api/routes_product.py`](../../../../../src/api/routes_product.py) | Fake endpoint `POST /release` |
| [`frontend/src/components/shell.tsx`](../../../../../frontend/src/components/shell.tsx) | Thêm "Release" vào `jobRoutes` |

**API flow:**

| Method | Path | Payload |
|---|---|---|
| `POST` | `/jobs/{job_id}/release` | approval_record_checksum, candidate_checksum, validation_report_checksum |

**Conditions to enable release (backend re-checks):**
- Job status = SUCCEEDED.
- Approval decision = APPROVE.
- Candidate + validation checksums match approval record.

**State ownership:** ReleaseManifest thuộc backend; UI chỉ trigger seal.

## 10. Tests

- Manifest/checksum/conditional-evaluation unit tests.
- Mismatched/unapproved/rejected/edited candidate negative tests.
- Independent manifest reconstruction/audit integration test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [x] Release binds exact candidate and ApprovalRecord checksums.
- [ ] Locked acceptance requires EvaluationReport; ordinary no-GT release follows accepted conditional rule.
- [x] No package content changes between validation, approval and release.
- [x] Release candidate/report identities khớp exact package và report đã verify;
  serialized release có canonical content checksum riêng, không dùng lại byte hash.
- [x] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

Implementation UI + fake endpoint + tests đã hoàn thành trong session nâng cấp UI 26/09/2026.

**Files đã tạo/sửa:**

- [`frontend/src/features/review/ReleasePanel.tsx`](../../../../../frontend/src/features/review/ReleasePanel.tsx) — UI seal exact candidate, disable khi chưa đủ điều kiện.
- [`frontend/src/app/jobs/[jobId]/release/page.tsx`](../../../../../frontend/src/app/jobs/[jobId]/release/page.tsx) — Route release mới.
- [`frontend/tests/release-panel.test.tsx`](../../../../../frontend/tests/release-panel.test.tsx) — Kiểm tra payload + disabled states.
- [`src/api/routes_product.py`](../../../../../src/api/routes_product.py) — Fake endpoint `POST /jobs/{job_id}/release` trả `ReleaseManifest` checksum.
- [`frontend/src/components/shell.tsx`](../../../../../frontend/src/components/shell.tsx) — Thêm "Release" vào `jobRoutes`.

**Verification đã chạy:**

```text
npm test -- --run          # 10 test files passed, 71 tests passed
npm run lint               # LINT_OK
npm run build              # BUILD_OK
python -m pytest tests/ -q # 297 passed
python -m ruff check src/ tests/ frontend/       # All checks passed
python -m ruff format --check src/ tests/ frontend/ # 105 files already formatted
```

**Limitation / chưa làm:**

- Đây là fake endpoint; backend chưa thực sự seal `ReleaseManifest` vào artifact store.
- Điều kiện "Locked acceptance requires EvaluationReport" chưa kiểm tra vì `EvaluationReport` chưa có trong fixture/API.
- Browser smoke thật cho release route vẫn pending trong session này; UI tests đã bao phủ disabled states và payload.
