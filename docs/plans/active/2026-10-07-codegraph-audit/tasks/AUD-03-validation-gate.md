# AUD-03 — Review/release gate dựa trên validation được tin cậy

## Metadata và goal

- PLANNED; P0; EX-PRODUCT + EX-SIM producer handoff.
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

Implement: inspect producer/consumer; choose minimal DB record + refs; stable
check policy IDs; run-specific URI/selection protocol cho retries. Làm fixture
trusted bằng backend test port, không thêm production bypass flag để tests pass.
Tests: roundtrip/version/old report; wrong candidate/config/report/worker; missing
log ref, corrupt checksum; two attempts/report selection; migration preserves history.
**Exit:** [ ] producer/consumer schema review; [ ] backend-owned trust boundary tested.

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

Pending — lưu required-check config/version, rejected cases và trusted-run fixture refs.
