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
với pair_id/required. S1 khóa concrete IDs/schema cùng SIM producer. Normative
ValidationReport vẫn dùng checks/path_results và content checksum hiện có.
Không yêu cầu 5 paths cho mọi ORDINARY run; configured pairs có thể rỗng khi
profile công khai cho phép. Required path BLOCKED/ERROR block; optional BLOCKED
chỉ là observed result. Missing/duplicate/unknown checks/pairs phải được policy
xử lý xác định; không tự ignore malformed IDs.

Report refs theo run_id để retry cùng candidate không overwrite first report.
Selection record trỏ một completed trusted run/report; legacy report chỉ đọc
được nhưng thiếu proof thì không eligible. Capture issue không sửa physics result.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Review/release eligibility dựa trusted run.
Cần sửa đồng bộ: ValidationRun producer, report DTO/verifier, workflow eligibility, review/release endpoints/UI, sealing và stale-revision invalidation.
Acceptance xuyên consumer: Thiếu/stale/synthetic proof không release; producer thật và report/candidate/config cùng identity.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1/S2 có thể dùng persisted trusted-run fixture với nhãn synthetic rõ ràng;
không cần Isaac worker để kiểm gate. Real run producer là AUD-05. Seal atomicity
ở AUD-04, nhưng seal entrypoint phải dùng cùng gate ngay khi AUD-03 hoàn thành.

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
**Exit:** [ ] original repro blocked; [ ] valid trusted exact candidate can approve;
[ ] direct seal cannot skip gate.

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
**Exit:** [ ] gate applied everywhere; [ ] consumer/permissions tests pass;
[ ] real Isaac proof chỉ được tick sau AUD-05.

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
