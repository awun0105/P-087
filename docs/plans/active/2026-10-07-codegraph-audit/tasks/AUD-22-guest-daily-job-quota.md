# AUD-22 — Quota Guest 3 lượt mỗi ngày, atomic và idempotent

## Metadata và goal

- IN PROGRESS — S1 contract and S2 enforcement are implemented; shared-PostgreSQL concurrency evidence remains pending because `R2S_TEST_POSTGRES_URL` is unset. S3 UX/operations is next. Owner confirmed objectify is excluded from Guest's 3/day quota on 2026-10-08. P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. S1 thêm pure calendar/DTO contract và tests; chưa bật quota route hoặc sửa tài khoản. Ngày 08/10/2026, owner xác nhận objectify không trừ quota 3 lượt/ngày của Guest.
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
fixed daily calendar ledger; Reviewer remains unlimited. At the audit baseline,
Guest had no calendar ledger. S1 added the calendar helper/DTO contract. AUD-22.S2
now enforces the ledger on the three accepted run paths and exposes Guest quota
state in `/auth/me`; S3 owns quota display and operations UX.

## Input / output / data contract

Owner chốt: Guest 3 accepted manual run intents/ngày, bao gồm tạo job và Retry
thủ công; objectify/tách vật không trừ vào 3 lượt này; reset 00:00 Asia/Ho_Chi_Minh. Persist UTC window [start,end) từ calendar
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
An explicitly requested `request_objectify` is excluded from the Guest daily count,
even when accepted by the durable queue. It remains subject to worker/resource
admission. Existing Editor rolling-24-hour quota behavior is unchanged. Duplicate
submissions and worker resume do not create a Guest quota unit. Other non-job
operations stay excluded.
`GuestQuotaSummary`: `policy_id`, fixed `limit`, `used`, `remaining`, UTC
`window_start_utc`/`resets_at_utc`, and `timezone`. HTTP 429 uses stable code
`guest_daily_job_quota_exceeded` with the summary; clients do not parse message
text. Guest run requests require `Idempotency-Key`, scoped to actor+operation and
bound to a canonical request fingerprint; the same key with a different payload
conflicts, while an identical duplicate returns the original immutable accepted
job manifest.

### Quota transaction design selected in S1

- Add an additive `RuntimeDatabase` migration for `r2s_guest_quota_windows` with
  `(actor_user_id, policy_id, window_start_utc)` unique key, persisted reset time,
  policy limit and used count. DB checks enforce `0 <= used_count <= policy_limit`;
  FK actor to `r2s_users`. `policy_id` is versioned so later policy changes do not
  rewrite historical windows.
- Add `r2s_quota_intents` as accepted-intent/idempotency ledger, unique on
  `(actor_user_id, operation_kind, idempotency_key)` across windows/role changes. Persist request
  fingerprint, original UTC window, accepted timestamp, result kind/id and the
  immutable manifest reference needed to replay the exact acceptance. This
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
RuntimeDatabase/job transitions. S3 builds on the S2 quota summary and errors; it
does not need GPU proof. Shared-PostgreSQL concurrency qualification remains a
deployment gate separate from worker runtime acceptance.

## Sprint AUD-22.S1 — Quota policy và window contract

**Input:** Owner policy + current quota/retry code.
**Output:** Implemented calendar helper/DTO, DB constraints and reservation design.
**Contract:** Guest calendar day khác Editor rolling24h.

Implement: `guest_quota_window()` uses server UTC clock + `ZoneInfo`, injected aware clock in tests, and outputs half-open Vietnam calendar windows as UTC. Add typed `GuestQuotaWindow`, `GuestQuotaSummary` and `GuestQuotaExceededDetail`; keep `/auth/me`/429 consumers for S2/S3. Record DB constraints, actor/idempotency semantics, accepted queue transaction boundary, concurrent PostgreSQL/SQLite behavior, no-side-effect denial and retry eligibility ordering above. Audit remains diagnostic for Guest.
Tests: Vietnam midnight UTC conversion, exact boundary/previous day, aware-vs-naive clock, stable typed summary/error and invalid model values. Later S2/S3 tests cover manual vs auto retry, operator role and duplicate fingerprint.
**Exit:** [x] policy/window/DTO/DB contract clear; preserve Editor policy. Owner decision (2026-10-08): Guest objectify does not consume the daily quota; worker/resource admission still applies.

## Sprint AUD-22.S2 — Atomic admission và durable job intent

**Input:** S1 contracts + permission-checked run requests.
**Output:** Migration v14 and an authoritative Guest ledger on job creation,
scene-from-upload and manual Retry. Guest receives no more than 3 accepted run
intents per Vietnam calendar day; objectify remains excluded.
**Contract:** Quota acceptance and queued job/project/upload linkage or Retry CAS
commit in one database transaction. Same actor/operation/key/fingerprint replays
the original immutable accepted manifest; conflicting payload returns 409.

Implement: migration v14 adds `r2s_guest_quota_windows` and `r2s_quota_intents`.
The locked calendar counter, accepted intent, job row/event, and scene upload
linkage share one write transaction; Retry quota and status CAS share one write
transaction. The intent keeps the immutable manifest reference for replay. Validate
worker profile/input before scene mutation; return 503 before mutation if the
shared persistent runtime DB is unavailable. Apply Guest quota only to
`scene.create`, `job.create`, and `job.retry`; objectify remains outside the daily
counter and continues through durable worker/resource admission. Keep Editor's
rolling 24-hour quota and Reviewer unlimited. Expose `GuestQuotaSummary` in
`/auth/me`, stable 429 code and 409 idempotency conflict. Dispatch/recovery after
acceptance reuses the same intent; do not charge worker retries or duplicate
requests.

Tests: concurrent four create requests accept exactly three and reject the
fourth; same key replays the same manifest; conflicting fingerprint does not
charge; transaction rollback and Vietnam midnight are tested at the ledger/API
boundary; manual Retry consumes one run and exact replay returns its original
QUEUED manifest even after worker progress; quota exhaustion does not block
objectify; missing persistent runtime DB fails closed with 503. SQLite shared-file
concurrency is covered. PostgreSQL variants are present but require
`R2S_TEST_POSTGRES_URL`; without it, multi-process/shared-database qualification is
pending. Editor/Reviewer behavior is covered by API regression.
**Exit:** [x] implementation and local SQLite/API acceptance complete; [ ]
shared-PostgreSQL concurrency/restart proof and deployment qualification.

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
  audit stays diagnostic. The earlier source-based assumption that manual objectify
  consumes a Guest run was superseded by the owner's explicit 2026-10-08 decision:
  Guest objectify is excluded from the 3/day counter; Editor quota behavior is
  unchanged. Atomic queue + quota transaction and migration are S2.
- **Verification:** `.venv/bin/pytest tests/test_orchestration/test_guest_quota_policy.py -q`
  — 6 passed; targeted `ruff check` PASS; `ruff format --check` PASS;
  `codegraph sync` up-to-date; `codegraph status` up-to-date (759 files,
  13,751 nodes, 39,470 edges); `git diff --check` PASS; relative Markdown links PASS.
- **Gate report:** CodeGraph PASS; minimum scope PASS (window contract only); source
  checks PASS; browser N/A (no UI changes); API behavior is not enabled.
- **Pending at S1:** no DB schema migration, reservation or route enforcement had
  been implemented yet. AUD-22.S2 added them; shared-PostgreSQL proof remains
  pending, and browser quota UX is S3.

### AUD-22.S2 — atomic Guest admission and durable run intent

- **Base:** AUD-22.S1 and AUD-21.S3 commits in the active branch.
- **Files:** migration v14, quota ledger/service, Guest `/auth/me` summary,
  scene/job creation and Retry API, runtime transaction/persistence/registry,
  frontend run idempotency headers and quota type, API/orchestration tests, task
  and ADR 0022.
- **CodeGraph evidence:** inspected callers for `create_job`,
  `create_scene_from_upload`, `retry_job`, `request_objectify`, registry
  persistence/CAS and frontend run-intent calls before edits. `codegraph sync`
  completed; status is up to date at 764 files, 13,951 nodes and 40,192 edges.
- **Contract implemented:** only accepted Guest reconstruction-job intents from
  scene creation, project job creation and manual Retry count. Guest objectify is
  excluded and remains under worker/resource admission. Retry and duplicate
  semantics follow the owner decisions; Editor rolling-24-hour behavior and
  Reviewer unlimited behavior are preserved. Run routes fail closed with 503 if
  the persistent runtime DB required for atomic Guest quota is unavailable.
- **Verification:** `.venv/bin/pytest tests/test_api -q` — 142 passed;
  `.venv/bin/pytest tests/test_orchestration -q` — 583 passed, 25 skipped;
  `.venv/bin/pytest tests/integration/test_studio_processing_job.py tests/integration/test_upload_to_prepared_job.py -q`
  — 9 passed; quota-specific ledger/migration matrix — 15 passed, 9 skipped;
  frontend full Vitest — 279 passed in 42 files; frontend typecheck and changed-file
  ESLint passed; backend `ruff check src/ tests/`,
  `ruff format --check src/ tests/`, and `git diff --check` passed.
- **Gate report:** CodeGraph PASS; minimal scope PASS; backend/API/integration and
  frontend checks PASS; browser visual gate N/A because no rendered UI changed
  (request headers are covered by Vitest). PostgreSQL variants skipped because
  `R2S_TEST_POSTGRES_URL` is unset; no shared-database race/restart or deployment
  qualification is claimed.
- **Pending:** shared PostgreSQL concurrency/restart verification and AUD-22.S3
  remaining/reset UX plus browser acceptance.
