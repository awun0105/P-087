# PRODUCT-02 — Job State Machine And Persistence

## 1. Metadata

| Field | Value |
|---|---|
| Track | `EX-PRODUCT` |
| Priority | `P0` |
| Status | `IN_PROGRESS` |
| Owner | Cường |
| Target milestone | `M1/M2` |

## 2. Goal

Implement QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED transitions and persisted attempt history.

## 3. Why This Task Exists

Long-running stages cannot be modeled as one HTTP request or fake success.

Source anchors: [Track Guide](../../../TRACK_IMPLEMENTATION_GUIDE.md), [Contract](../../../TEAM_EXECUTION_CONTRACT.md), [PRD](../../../../PRD.md), [Integration Playbook](../../../INTEGRATION_PLAYBOOK.md), [Wireframe](../../../../WIREFRAME_AND_UI_FLOW.md), [Architecture](../../../../../ARCHITECTURE.md).

## 4. Dependencies

- PRODUCT-01 job API.
- JobManifest and stage artifact lifecycle contract.

## 5. Input Contract

- Validated job creation/transition commands and JobManifest.

Frontend/API không được bypass privacy, artifact, revision hoặc authorization boundaries.

## 6. Output Contract

- Persisted job/current-stage/attempt records.
- Validated transition/error responses.

Persisted state phải nằm ở backend/shared artifacts; UI-local state không phải source of truth.

## 7. Code Ownership

Create/modify trong:

- `src/services/orchestration/jobs/`
- `src/api/` routes
- `tests/test_orchestration/`

Không sửa track internals. Shared contract change cần producer + consumer review; không rename/move organizer scaffold.

## 8. Tool / Repository Strategy

`SELF-CODE` deterministic state machine; storage choice follows existing architecture/accepted config.

P0 không tự mở rộng sang advanced scheduler, multi-tenant platform hoặc public deployment hardening.

## 9. Implementation Plan

Audit/implementation 2026-09-28: historical DONE chưa chứng minh recovery, vì
registry vẫn giữ pointer/history trong RAM. Đang nối SQLite/PostgreSQL repository
vào API factory, immutable UUID revisions + atomic pointer/event transaction,
CAS stale writers, fixture opt-in và explicit execution profile. Không đổi shared
JobManifest. Owner yêu cầu không chạy lại tests; regression đã thêm nhưng chưa
thực thi, vì vậy chưa chốt DONE hoặc restart/cloud acceptance.

**Files**

| File | Vai trò |
|---|---|
| [`src/services/orchestration/jobs/transitions.py`](../../../../../src/services/orchestration/jobs/transitions.py) | Bảng chuyển trạng thái thuần, không I/O: `ALLOWED_TRANSITIONS`, `TERMINAL_STATUSES`, `CLOSING_STATUSES`, `require_transition()` |
| [`src/services/orchestration/jobs/models.py`](../../../../../src/services/orchestration/jobs/models.py) | `TransitionRequest` (target status, current stage tùy chọn) |
| [`src/services/orchestration/jobs/service.py`](../../../../../src/services/orchestration/jobs/service.py) | `JobLifecycle`: kiểm luật, dựng revision kế tiếp, chặn `SUCCEEDED` giả |
| [`src/services/orchestration/jobs/store.py`](../../../../../src/services/orchestration/jobs/store.py) | `JobArtifactStore`: publish/đọc revision bất biến |
| [`src/services/orchestration/jobs/errors.py`](../../../../../src/services/orchestration/jobs/errors.py) | `InvalidTransitionError`, `JobNotResolvableError` |

**Bảng chuyển trạng thái**

| Từ | Sang |
|---|---|
| `QUEUED` | `RUNNING`, `CANCELLED` |
| `RUNNING` | `SUCCEEDED`, `FAILED`, `CANCELLED` |
| `SUCCEEDED` | — (kết thúc) |
| `FAILED` | `QUEUED` — **cạnh retry duy nhất** |
| `CANCELLED` | — (kết thúc) |

**API flow (sau `/api/v1`)**

| Method | Path | State ownership |
|---|---|---|
| `POST` | `/jobs/{job_id}/transitions` | `JobLifecycle.apply()` — publish revision mới, `422` nếu cạnh không hợp lệ |
| `POST` | `/jobs/{job_id}/retry` | Nối attempt mới vào `attempts[]`, giữ nguyên attempt cũ |
| `GET` | `/jobs/{job_id}/attempts` | Đọc lịch sử attempt |

State nằm ở backend: mỗi lần chuyển publish một `JobManifest` revision bất biến ở
URI riêng (`artifact://jobs/<job_id>/manifests/job_manifest.<NNN>.json`), dưới
runtime root đã gitignore. `FilesystemArtifactStore.publish` từ chối ghi đè path
đã tồn tại, nên revision cũ không thể bị sửa.

**Failure handling**

| Tình huống | Kết quả |
|---|---|
| Cạnh chuyển không có trong bảng | `422`, `detail` nêu rõ các đích được phép |
| `SUCCEEDED` khi job chưa publish artifact nào | `409` — `JobNotResolvableError` |
| `SUCCEEDED` khi checksum artifact không resolve được | `409` — fail closed, không hạ cấp thành cảnh báo |
| `retry` trên job không ở `FAILED` | `422` — lỗi sinh ra từ chính bảng chuyển, không phải một nhánh riêng |
| Job không tồn tại | `404` |

## 10. Tests

- [`tests/test_orchestration/test_job_transitions.py`](../../../../../tests/test_orchestration/test_job_transitions.py) — bảng chuyển, 11 test: bảng phủ đủ mọi `JobStatus`, đối chiếu từng cạnh được/không được phép, trạng thái kết thúc không có lối ra, retry là lối ra duy nhất từ `FAILED`, `SUCCEEDED` không thể hoàn tác.
- [`tests/test_orchestration/test_job_lifecycle.py`](../../../../../tests/test_orchestration/test_job_lifecycle.py) — persistence + âm, 15 test.
- [`tests/test_api/test_product_routes.py`](../../../../../tests/test_api/test_product_routes.py) — HTTP thật qua `ASGITransport`, 24 test.

Tách fixture/mock/API/browser proof khỏi real-worker Product E2E acceptance. Toàn bộ
test ở đây là **API/fixture proof**: chúng chứng minh state machine và persistence,
không chứng minh một worker thật đã chạy.

## 11. Definition of Done

- [x] Only legal transitions persist.
- [x] SUCCEEDED requires required artifacts/checksums resolvable.
- [x] Retry appends attempt/history and does not overwrite prior provenance.
- [x] Focused tests, applicable browser/E2E/handoff proof và evidence/limitations được ghi.

## 12. Result / Evidence

**Ngày:** 2026-09-24 · **Nhánh:** `feat/product`

**Test — transition table:**

```
tests/test_orchestration/test_job_transitions.py  11 passed
tests/test_orchestration/test_job_lifecycle.py    15 passed
```

**Test — HTTP (`tests/test_api/test_product_routes.py`), các ca chính:**

```
test_create_job_then_run_then_fail              PASS  QUEUED→RUNNING→FAILED qua HTTP
test_illegal_transition_rejected_422            PASS  QUEUED→SUCCEEDED bị từ chối (422, nêu đích được phép)
test_succeeded_cannot_be_faked_over_http        PASS  RUNNING→SUCCEEDED khi chưa có artifact → 409
test_retry_appends_attempt_over_http            PASS  attempt mới, attempt cũ còn nguyên
test_retry_on_non_failed_job_rejected           PASS
test_unknown_target_status_422                  PASS  status ngoài enum bị chặn ở tầng schema
test_attempt_response_has_no_filesystem_paths   PASS  response không lộ path
```

**Chuỗi fail → retry** (chạy lại thật qua proxy Next ngày 25/09, backend log xác nhận
từng request; `attempts` khớp đúng bảng dưới):

```jsonc
// POST /api/v1/jobs/<id>/transitions  {"target_status": "FAILED"}
{ "status": "FAILED", ... }        // JobManifest KHÔNG chứa attempts[]

// POST /api/v1/jobs/<id>/retry   →  200, status về QUEUED, attempt mới được nối
{ "status": "QUEUED", ... }

// GET /api/v1/jobs/<id>/attempts  →  lịch sử nằm ở endpoint riêng
{ "job_id": "<id>",
  "attempts": [
    { "attempt": 1, "status": "QUEUED",  "job_manifest_uri": ".../job_manifest.001.json" },
    { "attempt": 1, "status": "RUNNING", "job_manifest_uri": ".../job_manifest.002.json" },
    { "attempt": 1, "status": "FAILED",  "job_manifest_uri": ".../job_manifest.003.json" },
    { "attempt": 2, "status": "QUEUED",  "job_manifest_uri": ".../job_manifest.004.json" }
  ] }

// POST /api/v1/jobs/<id>/retry trên job đang QUEUED  →  422
// Thông điệp do chính bảng chuyển sinh ra: QUEUED không có cạnh nào tới QUEUED.
{ "detail": "không thể chuyển job từ QUEUED sang QUEUED; chỉ cho phép: CANCELLED, RUNNING" }

// POST /api/v1/jobs/<id>/transitions  {"target_status": "SUCCEEDED"} khi chưa có artifact → 409
{ "detail": "job <id> chưa có artifact nào được publish; không thể ghi SUCCEEDED" }
```

Mỗi lần chuyển trạng thái publish một `job_manifest.<NNN>.json` **riêng**, và
`attempts[]` là lịch sử chỉ đọc ở endpoint riêng — không phải field của `JobManifest`.
Đây là điểm tôi từng ghi sai trong bản evidence 24/09 và đã sửa sau khi chạy thật.

**Bằng chứng revision bất biến** (`test_revision_paths_are_distinct_per_transition`,
`test_started_at_is_never_overwritten`): mỗi lần chuyển ghi một
`job_manifest.<NNN>.json` riêng; `started_at` không bị ghi đè qua các revision.

**Limitations**

- Chuyển trạng thái hiện **do API gọi**, chưa do worker thật báo tiến độ: route
  transitions được viết như một affordance *mock-worker*, client đóng vai người
  báo tiến độ. Worker thật (PRODUCT-08) sẽ gọi cùng đường đó. Việc tự động chuyển
  theo stage là PRODUCT-03 (dispatch). Cho tới lúc đó, "job chạy" chưa được chứng
  minh — chỉ có state machine và persistence được chứng minh.
- Registry giữ **chỉ mục job** trong bộ nhớ, mất khi restart. Bản thân các revision
  `JobManifest` đã publish thì nằm trên đĩa dưới runtime root đã gitignore, nên
  không mất — nhưng sau restart registry chưa tự dựng lại chỉ mục từ chúng.
- `attempts[]` của job mẫu `job-fixture-001` là dữ liệu **seed từ fixture**, không
  phải một lần retry thật đã xảy ra.
- Chưa có test kiểm hai tiến trình ghi cùng lúc (không có khoá liên tiến trình);
  `FilesystemArtifactStore` chỉ chống ghi đè ở mức một tiến trình.

