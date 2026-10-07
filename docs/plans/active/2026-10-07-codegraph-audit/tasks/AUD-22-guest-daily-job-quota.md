# AUD-22 — Quota Guest 3 lượt mỗi ngày, atomic và idempotent

## Metadata và goal

- PLANNED; P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. Chỉ lập kế hoạch; chưa sửa source hoặc tài khoản.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Current enforce_gpu_quota dùng audit count rolling 24h; Reviewer unlimited,
Editor daily_job_quota default10 configurable. Retry quota check và record_gpu_run
ở steps riêng, không đủ atomic concurrency cho Guest. Giữ Editor policy hiện tại;
Guest cần authoritative DB reservation, không dựa vào frontend hoặc audit count.

CodeGraph đã đọc auth/models.py, auth/service.py, api/auth.py, auth/cli.py,
product/jobs.py, product/projects.py, AuthForms.tsx, ScenesHome.tsx và frontend
API/auth.ts. Trước implementation đi tiếp callers của symbols được sửa, inventory
Studio/legacy mutation routes, runtime services, packaging/bootstrap và tests.
Không lấy việc ẩn button làm access control.

## Input / output / data contract

Owner chốt: Guest 3 accepted manual run intents/ngày, bao gồm tạo job và Retry
thủ công; reset 00:00 Asia/Ho_Chi_Minh. Persist UTC window [start,end) từ calendar
Vietnam. Automatic worker retries, duplicate idempotent requests, admission waits
không tính thêm. Accepted durable queue intent tính một lượt dù sau đó fail/cancel;
validation/permission/commit failure trước accepted intent không tính.
Charged actor là người bấm run; Editor/Reviewer chạy job Guest dùng chính policy
của operator, không trừ Guest hoặc đổi ownership. Editor rolling24h configurable
hiện có và Reviewer unlimited giữ nguyên. Guest cap cố định3, admin không override
bằng daily_job_quota; role promotion/demotion đọc current role, reservations cũ giữ.
New Preview hoặc final reconstruction job là run mới; không tính UI viewing,
sample playback, edit/delete/cancel hoặc worker resume cùng intent. Inventory all
job-producing paths; heavy non-job operations không tự biến thành một lượt job.
Proposed QuotaSummary: limit/used/remaining, window_start/end UTC, timezone,
policy_id và role; 429 reason guest_daily_job_quota_exceeded + resets_at và retry
metadata, không bắt frontend parse text. Idempotency key scoped actor+operation,
request fingerprint; same key khác payload conflict, duplicate original result.

## Logic change và dependent updates

Risk: **Rất cao** khi chỉ sửa một phần. Logic delta: Atomic Guest calendar quota và accepted intent.
Cần sửa đồng bộ: create_scene_from_upload/retry_job/request_objectify policy inventory, auth helpers, UserRecord/Me quota projection, DB reservations/CAS queue, manual/auto retry và UI.
Acceptance xuyên consumer: 3 accepted run intents across replicas; duplicate/manual/auto retry và midnight Vietnam đúng; giữ owner khác charged actor, Editor rolling24h/Reviewer unlimited theo role người chạy.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 dùng AUD-21.S1 identity/action matrix; S2 dùng AUD-21.S2/S3 guards và current
RuntimeDatabase/job transitions. S3 dùng S2, không cần GPU để verify quota; actual
accepted-run/browser proof separate from worker runtime acceptance.

## Sprint AUD-22.S1 — Quota policy và window contract

**Input:** Owner policy + current quota/retry code.
**Output:** Calendar helper/DTO, DB constraints và reservation design.
**Contract:** Guest calendar day khác Editor rolling24h.

Implement: Define server-clock ZoneInfo windows, actor/idempotency semantics và accepted queue transaction boundary. Select durable per-day counter/reservation unique key; audit remains diagnostic. Specify concurrent PostgreSQL/SQLite behavior, zero side effect on denied run, preview/final producers and retry eligibility ordering.
Tests: Vietnam midnight UTC conversion, exact boundary, previous day, manual vs auto retry, operator role, invalid input and duplicate fingerprint.
**Exit:** [ ] policy/DB contract rõ và preserve Editor fixtures.

## Sprint AUD-22.S2 — Atomic admission và durable job intent

**Input:** S1 contracts + permission-checked run requests.
**Output:** At most3 accepted Guest runs across API replicas.
**Contract:** Quota reservation và queued job/CAS cùng transaction hoặc recoverable atomic DB intent.

Implement: Use locked counter or conditional update with unique reservation. Bind accepted job/attempt and idempotent response; move expensive dispatch after commit. Failed retry eligibility trước charge; duplicate never recharges. Crash rollback/replay does not leak count or leave uncharged runnable jobs. Enforce all job-producing APIs; quota không thay resource admission.
Tests: Concurrent 4 requests: exactly3 accepted, fourth429; same key across workers one charge; queue/CAS failure rollback, crash before/after commit, manual Retry, auto attempts and Editor/Reviewer regression on real DB.
**Exit:** [ ] multi-process DB tests chứng minh cap/idempotency và recovery.

## Sprint AUD-22.S3 — Quota UX, operations và end-to-end

**Input:** S2 authoritative summary/errors.
**Output:** Remaining/reset UI và complete role/quota acceptance.
**Contract:** Exhaustion chỉ block new run, own edit/cancel/delete vẫn allowed.

Implement: Render 3/day remaining and Vietnam reset, refresh after run, handle stale multi-tab429, no localStorage authority. Show manual Retry cost before accepted run; maintain queue waiting config. Add minimal usage diagnostics without secrets; apply forward schema migration and update docs.
Tests: Browser fourth run blocked, own editing at cap, midnight new window, operator rerun Guest, duplicate network retry, promotion/demotion, frozen clock APIs và persistent restart.
**Exit:** [ ] quota đúng sau restart/multiple tabs và browser evidence.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_api/test_auth_routes.py tests/test_orchestration/test_auth_service.py tests/test_api/test_studio_routes.py tests/integration/test_studio_processing_job.py -q
```

Thêm tests mới theo sprint rồi bổ sung command. Chạy ruff; frontend lint/typecheck,
focused tests/build khi sửa UI. DONE cần real DB concurrency/API và browser evidence;
mock hoặc source review không chứng minh feature đã chạy.

## Result / Evidence

Pending — schema/migration, command outputs, permission matrix, browser/API traces,
legacy compatibility và failure/recovery evidence.
