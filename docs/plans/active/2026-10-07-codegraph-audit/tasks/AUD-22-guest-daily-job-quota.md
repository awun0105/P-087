# AUD-22 — Quota Guest 3 lượt mỗi ngày, atomic và idempotent

## Metadata và goal

- IN PROGRESS — S1 calendar contract implemented; charge-unit edge classification pending. P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. S1 thêm pure calendar/DTO contract và tests; chưa bật quota route hoặc sửa tài khoản.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Current `enforce_gpu_quota` counts `gpu.run` audit rows in rolling 24h; Reviewer is
unlimited and Editor's `daily_job_quota` defaults to configurable 10. CodeGraph
finds quota check + audit write in separate steps on scene creation, retry and
objectify; retry checks eligibility before quota, but accepted transition and audit
are separate commits. `POST /projects/{project_id}/jobs` creates a queued job
without quota enforcement. Scene-from-upload checks quota before validating worker,
upload and processing config, then writes project/upload links/job in separate
operations and records usage after job creation. Audit count is therefore neither
atomic nor idempotent for Guest.

CodeGraph callers were refreshed for quota helper, `MeResponse`, `AuthService`
audit/count, scene creation, retry, objectify and `RuntimeDatabase` migrations.
Current role policy must remain split: Editor rolling 24h stays as-is; Guest uses
fixed daily calendar ledger; Reviewer remains unlimited. This S1 adds the calendar
helper/DTO contract only; enforcement and quota API projection begin later.

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
S1 applies the same fixed Guest unit to an explicitly requested `request_objectify`
accepted by the durable queue. This is an inference from current source: Editors
already pay the GPU quota for this manual operation, and excluding it would leave
Guest able to enqueue unlimited GPU work. Duplicate submissions and worker resume
remain the same intent and do not add units. Other non-job operations stay excluded.
`GuestQuotaSummary`: `policy_id`, fixed `limit`, `used`, `remaining`, UTC
`window_start_utc`/`resets_at_utc`, and `timezone`. HTTP 429 uses stable code
`guest_daily_job_quota_exceeded` with the summary; clients do not parse message
text. `Idempotency-Key` is scoped to actor+operation and binds a canonical request
fingerprint; same key with different payload conflicts, identical duplicate returns
the original accepted intent.

### Quota transaction design selected in S1

- Add an additive `RuntimeDatabase` migration for `r2s_guest_quota_windows` with
  `(actor_user_id, policy_id, window_start_utc)` unique key, persisted reset time,
  policy limit and used count. DB checks enforce `0 <= used_count <= policy_limit`;
  FK actor to `r2s_users`. `policy_id` is versioned so later policy changes do not
  rewrite historical windows.
- Add `r2s_quota_intents` as accepted-intent/idempotency ledger, unique on
  `(actor_user_id, operation_kind, idempotency_key)` across windows/role changes. Persist request
  fingerprint, original UTC window, accepted timestamp, and result kind/id. This
  ledger, not audit rows or UI state, is Guest quota authority.
- In PostgreSQL, upsert the window row then `SELECT ... FOR UPDATE`; in SQLite,
  rely on existing `BEGIN IMMEDIATE` writer serialization. Lock order is quota
  window → idempotency key → target rows sorted by kind/ID → job row/event. Check
  identical idempotency before counting; same key/different fingerprint returns 409. If full, rollback without
  an intent, counter increment, project/job link, queued job or dispatch.
- Insert accepted intent, increment used count, write queued job/attempt (or manual
  retry CAS) and any project/upload linkage in the same DB transaction. For
  scene-from-upload, validate profile/input/config before mutation, then commit
  project + links + initial queued job + quota unit atomically. Published immutable
  artifacts must remain unreachable without a committed DB pointer; failed commit
  must never leave a runnable uncharged job. Dispatch is after commit; restart/poll
  recovers accepted work without another quota unit.
- Retry status, latest attempt retryability, owner and expected checksum are checked
  before charge and revalidated with CAS in the transaction. Worker recovery,
  resource-admission wait and automatic continuation reuse the accepted intent.
  Audit remains diagnostic and may be written in the acceptance transaction, but
  `count_actions` is not Guest authority.
- Cross-replica atomic guarantee requires a shared PostgreSQL database. SQLite
  serializes writers sharing one DB file; independent per-host SQLite files cannot
  coordinate quota and are not a supported multi-replica deployment.

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
**Output:** Implemented calendar helper/DTO, DB constraints and reservation design.
**Contract:** Guest calendar day khác Editor rolling24h.

Implement: `guest_quota_window()` uses server UTC clock + `ZoneInfo`, injected aware clock in tests, and outputs half-open Vietnam calendar windows as UTC. Add typed `GuestQuotaWindow`, `GuestQuotaSummary` and `GuestQuotaExceededDetail`; keep `/auth/me`/429 consumers for S2/S3. Record DB constraints, actor/idempotency semantics, accepted queue transaction boundary, concurrent PostgreSQL/SQLite behavior, no-side-effect denial and retry eligibility ordering above. Audit remains diagnostic for Guest.
Tests: Vietnam midnight UTC conversion, exact boundary/previous day, aware-vs-naive clock, stable typed summary/error and invalid model values. Later S2/S3 tests cover manual vs auto retry, operator role and duplicate fingerprint.
**Exit:** [x] policy/window/DTO/DB contract clear; preserve Editor policy. Guest objectify charge is a source-based inference: one unit per accepted manual queue request; auto-resume is free.

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

### AUD-22.S1 — quota policy và window contract

- **Base:** `31ffac2` (`AUD-21.S1`).
- **Files:** `src/services/orchestration/auth/quota.py`,
  `tests/test_orchestration/test_guest_quota_policy.py`, task AUD-22; ADR 0022 and
  master README are updated in this sprint commit.
- **CodeGraph evidence:** current quota callsites are scene creation, manual Retry
  and objectify; `/projects/{project_id}/jobs` is an uncovered job-creation path.
  Retry eligibility precedes quota, while `record_gpu_run` follows job CAS in a
  separate transaction. `AuthService.count_actions` counts audit rows in rolling
  24h. CodeGraph re-indexed and found the new window/summary/error contract.
- **Decision:** Guest windows are half-open local calendar days in
  Asia/Ho_Chi_Minh, stored/serialized in UTC. Added immutable typed window/summary/
  429 contracts. Selected per-actor day counter + idempotent accepted-intent ledger;
  audit stays diagnostic. One manual objectify request is counted as a source-based
  inference because current Editor quota already charges it; automatic resume is
  free. Atomic queue + quota transaction and migration are S2.
- **Verification:** `.venv/bin/pytest tests/test_orchestration/test_guest_quota_policy.py -q`
  — 6 passed; targeted `ruff check` PASS; `ruff format --check` PASS;
  `codegraph sync` up-to-date; `codegraph status` up-to-date (759 files,
  13,751 nodes, 39,470 edges); `git diff --check` PASS; relative Markdown links PASS.
- **Gate report:** CodeGraph PASS; minimum scope PASS (window contract only); source
  checks PASS; browser N/A (no UI changes); API behavior is not enabled.
- **Pending:** no DB schema migration, reservation, auth role or route behavior has
  been implemented in S1. Multi-process DB/API and browser proof remain S2/S3.
