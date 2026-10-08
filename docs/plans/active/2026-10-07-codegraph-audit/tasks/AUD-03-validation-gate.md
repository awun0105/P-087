# AUD-03 — Review/release gate dựa trên validation được tin cậy

## Metadata và goal

- IN PROGRESS; P0; EX-PRODUCT + EX-SIM producer handoff.
- Canonical SIM-07/09, PRODUCT-10/11. SELF-CODE policy/record using current contracts.
- Goal: report PASS tự khai báo hoặc fixture không thể seal ORDINARY release.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0013](../../../../decisions/0013-validation-evidence-and-release-identity.md).

## Baseline và scope

CodeGraph: `review_state`, `record_validation_report`, `has_isaac_runtime_proof`,
`decide`, `seal_release`. Current eligibility chỉ overall_result PASS. Repro
UNVERIFIED + paths/evidence rỗng vẫn RELEASED. Check arrays khác rỗng chưa đủ proof.

Owned: src/services/orchestration/review/{workflow,lifecycle}.py,
minimal runtime records/migration trong orchestration/jobs/database.py,
src/services/simulation/validation/, src/api/studio/review.py,
frontend/src/features/studio/ReviewPanel.tsx và typed API/contracts/tests.
Không đổi auth role/quota; không thêm public arbitrary-report ingestion.

## Input / output / data contract

Input: CandidatePackage, immutable ValidationReport, public validation config,
backend-owned ValidationRunRecord/evidence. Output: truthful ReviewState với
blockers/required warnings và exact candidate/report/approval bindings.

Proposed ValidationRunRecord tối thiểu: version, run_id, attempt, job_id,
scene_revision, candidate_checksum, validation_config_checksum, worker identity,
lease/fencing token, status, timestamps, runtime fingerprint, report_ref và
execution_log_ref sau completion. Record do trusted worker/backend commit;
report body hoặc client claim không tự tạo trusted status.

Config có version, required_check_ids, warning_check_ids và public path pairs
với pair_id/required. ID catalog giữ theo public profile; AUD-05 chốt catalog
production cùng validator. Normative
ValidationReport vẫn dùng checks/path_results và content checksum hiện có.
Không yêu cầu 5 paths cho mọi ORDINARY run; configured pairs có thể rỗng khi
profile công khai cho phép, nhưng phải có ít nhất một required check. Tất cả
required checks phải xuất hiện đúng một lần và PASS; duplicate/unknown check
hoặc pair block. Required path phải có kết quả; required BLOCKED, mọi ERROR và
overall FAIL/ERROR block. Optional BLOCKED là warning có thể được chấp nhận từng
pair; acknowledgment không thể vượt qua FAIL/ERROR check. Optional path chưa trả
kết quả không tự block.

Report refs theo run_id để retry cùng candidate không overwrite first report.
Selection record trỏ đúng một completed worker run/report/config cho candidate;
đổi policy thay active selection bằng CAS nhưng giữ attempt history. Legacy report
chỉ đọc được nhưng thiếu proof thì không eligible. Package import từ nguồn ngoài
không được nâng completed worker row thành trusted proof khi chưa có authenticated
receipt (AUD-05). Capture issue không sửa physics result.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Review/release eligibility dựa trusted run.
Cần sửa đồng bộ: ValidationRun producer, report DTO/verifier, workflow eligibility, review/release endpoints/UI, sealing và stale-revision invalidation.
Acceptance xuyên consumer: Thiếu/stale/synthetic proof không release; producer thật và report/candidate/config cùng identity.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S2 dùng persisted worker-shaped fixture để kiểm positive gate, nhưng fixture
không phải acceptance Isaac. Synthetic-origin run không thể được chọn. Real run
producer/authentication là AUD-05. Seal atomicity ở AUD-04, nhưng seal entrypoint
phải dùng cùng gate ngay khi AUD-03 hoàn thành.

## Sprint AUD-03.S1 — Chốt execution proof/config contract

**Input:** current report/release schemas và positive/negative audit fixtures.
**Output:** typed operational records/config, migration/consumer fixtures và
explicit trusted vs synthetic distinction.
**Contract:** all checksums bind candidate/config/run/report; runtime fingerprint
không lấy từ arbitrary UI input; old report checksum giữ nguyên.

Implement: inspect producer/consumer; choose minimal DB record + refs; keep
check IDs profile-owned and checksum-bound; add run-specific URI/selection
protocol for retries. Current code has no production Isaac report producer, so
do not freeze a guessed global check-ID enum; AUD-05 must finalize the production
catalog with its validator. Use a backend test port, no production bypass flag.
Tests: roundtrip/version/old report; wrong candidate/config/report/worker; missing
log ref, corrupt checksum; two attempts/report selection; migration preserves history.
**Exit:** [x] producer/consumer schema review (no production producer exists yet);
[x] backend-owned record/selection boundary tested; live worker authentication remains AUD-05.

## Sprint AUD-03.S2 — One shared eligibility gate

**Input:** candidate/report/run/config S1, current revision.
**Output:** READY_FOR_REVIEW chỉ khi đủ eligibility; clear blockers otherwise.
**Contract:** required checks/pairs đầy đủ; no FAIL/ERROR bypass by acknowledgment;
stale report/candidate không dùng được; synthetic cannot ORDINARY seal.

Implement: eligibility helper dùng chung review_state/decide/seal, recheck tại
commit. Verify logical report checksum và byte refs qua resolver. Runtime proof
là validated run binding, không string version regex. Giữ warning acceptance
itemized; không biến all optional warnings thành unconditional blockers.
Tests: UNVERIFIED fixture; forged version; no run; wrong candidate; missing
required check; optional BLOCKED vs required BLOCKED; ERROR; configured zero
pairs; media capture warning; stale revision after validation.
**Exit:** [x] original repro blocked; [x] valid exact candidate/config worker-shaped
record can approve; [x] direct seal cannot skip gate. S3 still owns API/UI projection
and stale-command regression.

## Sprint AUD-03.S3 — API/UI projections và release regression

**Input:** gate outcome, reviewer action và stale screen.
**Output:** blockers/eligible state đúng trên Studio; rejected command status;
release regression và old fixture labels.
**Contract:** API authority quyết định; frontend disable là projection; 409 stale
identity, validation data errors dùng existing typed error convention.

Implement: wire required proof/blockers to UI and typed clients; update old tests
asserting display-only proof. Giữ fixture/demo previews usable, không tạo ordinary
release. Kiểm reviewer roles, warning IDs và direct API calls.
Tests: API/auth/stale POST, frontend render/pending/error; trusted fixture happy
path; synthetic bypass negative; browser review screen theo GUIDE.
**Exit:** [x] API gate remains authoritative and Studio fails closed on missing,
stale or mismatched proof; [x] API/auth/stale and UI consumer tests pass;
[x] GUIDE DevTools MCP review-screen gate (application screen inspected in an authenticated Reviewer session);
[ ] real Isaac proof, deferred to AUD-05.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_review_workflow.py tests/test_api/test_review_routes.py tests/test_contracts/test_validation.py tests/test_contracts/test_release.py -q
```

Frontend: tests/review-panel.test.tsx, tests/validation-report-card.test.tsx.
DONE khi backend gate có full negative matrix và current candidate happy path;
record/result phải nói fixture proof, chưa thay cho real-runtime acceptance.

## Result / Evidence

### AUD-03.S1 — execution proof/config contract

- Base: `1f34976` (`AUD-02.S3`). Current code has no non-test caller of
  `record_validation_report` and no production Isaac report producer. Existing
  report fixtures expose `ISAAC_LOAD`, `ROBOT_SPAWN`, and `fixture-pair-001`; the
  current review tests also use local-only IDs. S1 therefore keeps IDs as
  checksum-bound public profile values; AUD-05 owns the production ID catalog.
- Added `ValidationConfig`, `ValidationRunRecord`, and
  `ValidationRunSelection` contracts. `ValidationReport` fields and canonical
  checksum are unchanged. Config, report, runtime manifest, and log refs carry
  exact byte checksums; report/run/selection carry logical checksums and bind
  candidate, config, attempt, worker lease, and report identity.
- Added run-specific immutable report/runtime/log URIs, append-only RuntimeDatabase
  migration v9, one row per attempt, unique candidate/config/attempt identity,
  immutable run transitions, and CAS selection generations. Synthetic records
  persist with an explicit fixture ID and cannot be selected for review.
- Updated Studio data packages and cloud package import to retain validation
  history, verify payload/checksum/ref identity, preserve FK insertion order, and
  refuse packages with queued/running/malformed validation state. Existing
  project/job history survives v8→v9 migration.
- Source changes: `database.py`, `validation_run.py`, contracts `__init__.py`,
  `validation_runs.py`, `data_package.py`, `package_publish.py`.
  Regression/contract changes: `test_validation_run.py`,
  `test_validation_runs.py`, `test_runtime_migrations.py`,
  `test_data_package.py`, `test_package_publish.py`.
- CodeGraph was synced after implementation: 746 files, 13,292 nodes,
  37,543 edges; index reports up to date. The final focused suite across
  contracts, run repository, migration, review API/workflow, release contracts,
  and Studio/cloud package handoff reports 70 passed, 4 skipped. Skips are the
  existing optional PostgreSQL migration cases; SQLite v8→v9 and package import
  were exercised locally. `ruff check src/ tests/` passes and
  `ruff format --check src/ tests/` reports 462 files already formatted.
- Limits: this commits the durable contract and internal repository, not a live
  Isaac producer or worker-authentication path. The legacy report workflow still
  exists until S2/S3 replace eligibility consumers. Fixtures validate storage and
  identity logic; they are not Isaac runtime acceptance.
- Next: AUD-03.S2 must route review/approve/seal through one eligibility gate,
  validate policy completeness and exact current revision, and block synthetic
  or legacy reports from ORDINARY release.

### AUD-03.S2 — one shared eligibility gate

- CodeGraph traced `review_state → evaluate_validation_eligibility →
  get_selection_for_candidate`; both `decide` and `seal_release` re-enter
  `review_state`, so they consume the same backend gate.
- Added one active CAS selection per job/candidate, including policy switches;
  policy changes replace the active pointer and preserve immutable run attempts.
  Eligibility binds the current scene revision/checksum, candidate, config,
  selected run/report, byte/logical checksums, worker origin, and structured
  `isaac_sim=VERIFIED` runtime component.
- Required checks and required path pairs must be complete. Duplicate/unknown
  checks or pairs, any check FAIL/ERROR, any path ERROR, required BLOCKED, or
  report overall FAIL/ERROR block review. Optional BLOCKED paths become
  itemized warnings; zero configured paths remains valid when required checks
  pass. Legacy reports stay visible for diagnostics but never enable approval.
- Direct release sealing now rechecks the same gate; persisted approval/release
  checksums and candidate/report identities are validated before showing a
  released state. Package publication rejects completed WORKER-origin rows until
  AUD-05 supplies an authenticated receipt, while failed run history remains
  transferable.
- Related consumers updated together: workflow service, reviewer API tests,
  repository selection CAS, cloud package publisher, contracts, and regression
  tests. No frontend shape changed in S2; API/UI messaging is S3.
- Verification: combined contracts/run/migration/review/API/package regression
  reports 81 passed, 4 skipped. Skips are the optional PostgreSQL migration
  cases; SQLite migrations were exercised. `ruff check src/ tests/` passed and
  `ruff format --check src/ tests/` reports 463 files formatted. CodeGraph synced
  and reports
  747 files, 13,330 nodes, 37,732 edges, up to date.
- Limits: test evidence uses a worker-shaped fixture, not a real Isaac run.
  Repository rows are not authenticated worker output until AUD-05; package
  imports therefore cannot carry completed worker proof. Seal idempotency and
  atomic crash recovery remain AUD-04. Browser review remains AUD-03.S3.
- Completed in AUD-03.S3: typed API/UI blockers and proof projection, stale/direct
  request regressions and role checks. Browser MCP was unavailable during the code
  implementation; its later application-screen verification is recorded in the S3
  result below.

### AUD-03.S3 — API/UI projections and release regression

- Base commit: `e16d47b` (`AUD-03.S2`). CodeGraph explored `ReviewPanel`,
  `ValidationReportCard`, and `ReviewStateView` before editing; affected Studio
  caller is `ReviewTab` (three render sites), with focused tests for the panel
  and report card. Index is up to date at 747 files, 13,333 nodes, 37,750 edges.
- Before: UI treated a PASS report as review-ready without requiring the trusted
  worker proof and exact candidate/report identities; no-report blockers were
  hidden, optional path warnings had no matching evidence row, and legacy API
  reports that named an Isaac version needed an explicit regression.
- After: review actions and progress steps require backend proof, PASS, matching
  candidate/report checksums and no blockers; all blockers render even without a
  report. Optional `path:<pair_id>` warnings show the corresponding message and
  evidence on both review controls and the report card. Retry-seal is hidden
  while blockers remain. Typed API comments document that environment version
  strings do not establish trust. No DB/schema or API field change.
- Added API regressions proving a legacy report with `isaac_sim=4.2.0` but no
  selected worker run remains `CANDIDATE_READY` and returns 409 on direct review;
  stale candidate identity also returns 409. Existing API tests cover anonymous
  401, editor 403, and reviewer success. UI regressions cover missing blockers,
  untrusted READY state, exact checksums, warning acknowledgement, editor
  read-only behavior, stale revision, loading state, and read-error retry.
- Files changed: `frontend/src/features/studio/ReviewPanel.tsx`,
  `frontend/src/features/studio/ValidationReportCard.tsx`,
  `frontend/src/lib/api/studio.ts`, `frontend/tests/review-panel.test.tsx`,
  `frontend/tests/validation-report-card.test.tsx`,
  `tests/test_api/test_review_routes.py`.
- Verification: focused backend tests **33 passed**; focused frontend tests
  **18 passed**; `ruff check src/ tests/` passed; `ruff format --check src/ tests/`
  reported 463 files already formatted; frontend typecheck and lint passed;
  `npm run build -- --webpack` passed; `git diff --check` passed.
- Browser evidence: on 2026-10-09 Chrome DevTools MCP opened the application
  review tab for an existing job in the authenticated Reviewer session. The
  screen showed “Chưa đủ điều kiện duyệt”, “Chưa thể phát hành”, and the explicit
  blocker that this revision has no simulation package. `GET .../review-state`
  returned 200 with that blocker; the disclosure explaining revision-bound
  package/report/approval was readable. No package or approval command was
  created. Console had no errors or warnings. This verifies the real application
  screen's fail-closed no-package projection; a package without trusted worker
  proof was unavailable for browser observation, while API/UI regression tests
  cover that state.
- Limits: synthetic/worker-shaped evidence is not real Isaac execution.
  Authenticated worker receipt and real Isaac acceptance remain AUD-05; release
  seal atomic crash recovery remains AUD-04. The checks establish local API and
  component behavior only, not deployment/cloud acceptance.
- Next: authenticated worker receipt and real Isaac acceptance remain with AUD-05;
  AUD-04 owns release-seal atomicity and crash-safe publication.
