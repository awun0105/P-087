# PRODUCT-09 — Progress Error And Retry

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | Cường |
| Target milestone | `M2/M4` |

## 2. Goal

Expose truthful stage status/errors and retry without overwriting prior attempts/releases.

## 3. Why This Task Exists

AC-09 requires recoverable known failures; fake percentage undermines observability.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-02 job state and PRODUCT-08 orchestration.
- Worker stage error contract.

## 5. Input Contract

- Worker/job status/events/errors and retry command.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- User-visible progress/error/retry state.
- New attempt records preserving original inputs and history.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/jobs/`
- `src/api/` status/retry endpoints
- `frontend/src/features/jobs/`
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE`; use discrete stage/status unless backend emits real measured progress.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

**Files đã tạo/sửa:**

| File | Vai trò |
|---|---|
| [`frontend/src/features/jobs/StageTimeline.tsx`](../../../../../frontend/src/features/jobs/StageTimeline.tsx) | Timeline REC→SCENE→SIM hiển thị trạng thái thật từng stage |
| [`frontend/src/app/jobs/[jobId]/page.tsx`](../../../../../frontend/src/app/jobs/[jobId]/page.tsx) | Tích hợp timeline + attempt table + artifact list |
| [`src/services/orchestration/jobs/...`](../../../../../src/services/orchestration/jobs) | Không thay đổi: sử dụng JobManifest + attempt có sẵn |

**UI flow:** Job detail page hiện:
1. Status card: trạng thái, stage hiện tại, timestamps.
2. Provenance checksums.
3. Lifecycle controls (đã có từ PRODUCT-02).
4. Stage timeline: REC → SCENE → SIM, mỗi bước có dot/status/error/artifact URI/timestamp.
5. Attempt history table: retryable flag, error code, manifest checksum.
6. Artifact list.

**State ownership:** mọi trạng thái thực tế đến từ `JobManifest` và `JobAttemptRecord`; UI không synthesize percentage.

## 10. Tests

- Status/error/retry and event-order unit/API tests.
- Fake success, invalid retry and overwritten history negative tests.
- Injected failure→UI→retry integration test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance.

## 11. Definition of Done

- [x] Exact failed stage/human message/retryability are visible.
- [ ] Retry preserves input and prior attempt/release.
- [x] No fabricated percentage is shown as measured progress.
- [ ] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

> Ghi chú: StageTimeline hiển thị trạng thái từ JobManifest nhưng retry/preservation thật cần PRODUCT-08 worker events. DoD #2 và #4 chưa đạt.

## 12. Result / Evidence

**Ngày:** 2026-09-26 · **Nhánh:** `feat/product`

**Test:** `npm test` 66 passed; `npm run build` exit 0.

**Job detail page hiện StageTimeline:** pipeline `ST-INPUT-VALIDATE → ST-PRIVACY-GATE → ST-REC-DISPATCH → ST-REC-WAIT → ST-SCENE-DISPATCH → ST-SCENE-WAIT → ST-SIM-DISPATCH → ST-SIM-WAIT → ST-CANDIDATE-SEAL → ST-VALIDATION → ST-REVIEW-READY`.

Mỗi node hiển thị:
- Dot màu theo status (OK/running/failed/pending).
- `current` label trên stage đang active.
- Error message + `(có thể retry)` nếu `retryable=true`.
- Artifact URI và timestamp (nếu có).

**Attempt table:** hiện `error_code`, `human_message` gọn, flag `retryable`, manifest checksum. Retry tạo attempt mới (PRODUCT-02) — bảng không bị ghi đè.

**Không có progress bar %:** timeline chỉ dùng trạng thái rồi rạc, không ước tính.

**Limitations**

- Stage status vẫn là mock do chưa có real worker events (PRODUCT-08).
- Chưa có auto-refresh khi worker thật chạy; user cần reload hoặc chờ polling (tương lai).
- Chưa có browser smoke cho job page ngoài `npm run build`.

Expected evidence:

- Injected failure/retry recording.
- Job attempt history/checksums.
- Error response/UI screenshots.
