# PRODUCT-10 — Review Lifecycle And Authorization

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | Cường |
| Target milestone | `M2/M4` |

## 2. Goal

Implement submit/review/approve/reject lifecycle and ApprovalRecord bound to exact candidate/validation.

## 3. Why This Task Exists

Automation/editor cannot self-approve; review must see evidence before release.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- CandidatePackage, PreflightReport, ValidationReport and conditional EvaluationReport.
- Reviewer/editor identity and permission authority.
- Accepted review state machine.

## 5. Input Contract

- READY_FOR_REVIEW revision, exact candidate/reports and authenticated actor.
- Published replay/screenshots/log refs của validation run khi có; nếu thiếu,
  nhận diagnostic riêng, không đổi kết quả `ValidationReport`.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- ApprovalRecord or rejection record/reason.
- Audit entries and valid state transition.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/review/`
- `src/api/` review endpoints
- `frontend/src/features/review/`
- validation evidence UI trong `frontend/src/features/validation/`
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` PRD lifecycle and authorization; LLM cannot approve or alter validation.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

**Files đã tạo/sửa:**

| File | Vai trò |
|---|---|
| [`frontend/src/features/review/ReviewLifecycle.tsx`](../../../../../frontend/src/features/review/ReviewLifecycle.tsx) | State machine PENDING → APPROVE/REJECT + approve/reject buttons |
| [`frontend/src/app/jobs/[jobId]/review/page.tsx`](../../../../../frontend/src/app/jobs/[jobId]/review/page.tsx) | Layout review: lifecycle panel + checksum cross-reference + warnings |
| [`tests/review-lifecycle.test.tsx`](../../../../../tests/review-lifecycle.test.tsx) | Kiểm tra payload approve/reject + reason validation |
| [`src/api/routes_product.py`](../../../../../src/api/routes_product.py) | Fake endpoints `POST /review/{submit,approve,reject}` |

**API flow:**

| Method | Path | Payload |
|---|---|---|
| `POST` | `/jobs/{job_id}/review/approve` | reviewer_id, candidate_checksum, validation_report_checksum, accepted_warning_ids |
| `POST` | `/jobs/{job_id}/review/reject` | reviewer_id, reason (required), candidate_checksum, validation_report_checksum |

**State ownership:** ApprovalRecord thuộc backend; UI chỉ gửi action và refresh canonical state.

**Failure handling:** reject yêu cầu reason; checksum mismatch do validation report cũ hơn approval sẽ hiện cảnh báo trên UI.

## 10. Tests

- State/permission/checksum/warning/rejection unit/API tests.
- Editor approve, mismatch, missing reason and rejected-release negative tests.
- Review UI evidence-bundle integration.
- Media fixture và real-run review: scene + report + replay + screenshots +
  warning/error cùng candidate; thiếu/sai checksum media phải hiện rõ.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [ ] Only Reviewer can approve/reject after required evidence.
- [x] Decision binds candidate and validation checksums; warnings reference evidence IDs.
- [ ] Any post-validation edit creates DRAFT revision and invalidates old decision.
- [ ] Reviewer mở được replay/screenshots/logs đã publish của đúng candidate,
  hoặc thấy media-unavailable warning mà không bị báo validation FAIL giả.
- [ ] Fixture UI proof và ít nhất một real candidate report/media handoff được
  phân biệt rõ; Primary Demo E2E acceptance thuộc PRODUCT-12, không dùng để
  block implementation độc lập của review UI.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

> Ghi chú: authorization là mock (`reviewer-mock-001`); real reviewer identity/permission sẽ được thay bằng PRODUCT-10 backend authority. DoD #1 và #3 chưa đạt vì authorization chưa có và backend chưa persist lifecycle hay auto-invalidate decision. Chưa có backend/API tests cho review endpoint.

## 12. Result / Evidence

**Ngày:** 2026-09-26 · **Nhánh:** `feat/product`

**Test:** `npm test` 66 passed; `tests/review-lifecycle.test.tsx` 3 passed.

**State machine UI:** PENDING → APPROVED/REJECTED với mũi tên và active highlight.

**Payload approve gửi đúng checksum binding:**

```ts
POST /api/v1/jobs/job-fixture-001/review/approve
body: {
  reviewer_id: "reviewer-mock-001",
  candidate_checksum: "sha256:...",
  validation_report_checksum: "sha256:...",
  accepted_warning_ids: []
}
```

**Payload reject yêu cầu reason:**

```ts
POST /api/v1/jobs/job-fixture-001/review/reject
body: { reason: "sai vị trí pallet", ... }
```

**Cảnh báo checksum mismatch:** trang review hiện banner khi `approval.validation_report_checksum !== validation.data.report.report_checksum`.

**Limitations**

- Reviewer authorization là synthetic (`synthetic_authorization=true`).
- Backend fake stub chỉ cập nhật decision/reviewer_id/timestamp trong approval record copy, chưa persist real lifecycle.
- Chưa tự động invalidate old decision khi scene edit sau validation (cần backend PRODUCT-10).
- Chưa có browser smoke.

Expected evidence:

- Approval/rejection/audit records.
- Authorization negative tests.
- Review UI recording.
- Real candidate/report/media lineage; fixture playback được ghi riêng với
  Isaac runtime acceptance.
