# AUD-05 — Production Isaac validation từ queue đến review

## Metadata và goal

- PLANNED; P0; EX-SIM runtime/report, EX-PRODUCT queue/API/UI.
- Canonical SIM-01/06/07/09, PRODUCT-08/10/12. ADAPT Isaac process-isolation
  patterns; REUSE qualified Isaac runtime và existing artifact/DB ports.
- Goal: exact candidate được chạy Isaac thật, report/evidence publish, rồi đi
  qua review/release gate; lỗi và cancellation có persisted trạng thái.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0013](../../../../decisions/0013-validation-evidence-and-release-identity.md),
  [ADR 0014](../../../../decisions/0014-durable-heavy-operations.md).

## Baseline và scope

CodeGraph: `record_validation_report` callers, `create_simulation_package`,
`ReviewPanel`, `ResourceAdmission`. Isaac/validation packages chưa có runtime
producer; report ingestion chỉ được tests gọi. Review/release framework đã tồn tại.

Owned runtime: src/services/simulation/{isaac,validation}/ và tests/test_simulation/.
Owned orchestration: minimal validation queue dưới orchestration/review/,
worker_cli dispatch, runtime DB migration, src/api/studio/ simulation/review
boundary, typed frontend clients/ReviewPanel. Shared report changes cần producer/
consumer review. Không load Isaac trong FastAPI process, không đọc benchmark
hidden expected labels, không đổi release run_type để bỏ required checks.

## Input / output / data contract

Input: immutable CandidatePackage/inventory, package refs/checksums, versioned
public validation config, trusted ValidationRunRecord AUD-03, admission AUD-07.
Output: observed ValidationReport, runtime log/evidence refs, completed run record
bind candidate/config/report; API có truthful progress và review eligibility.

Public config phải khóa: robot asset ref/footprint, spawn pose, units, timestep,
timeouts, penetration/collision thresholds và Start–Goal pairs/pair IDs/required.
Giá trị runtime phụ thuộc qualification; không tự chọn một robot/threshold để
đánh dấu acceptance. S1 phải ghi concrete config/profile trước S2. Candidate
inventory verify trước load; không dùng latest mutable scene để rebuild trong validator.

Checks IDs/config từ AUD-03: tối thiểu USD load, metric/axes, robot spawn,
collision/penetration và các configured path observations. Result PASS/FAIL/ERROR
phản ánh observation; runtime exception/timeout/missing artifacts không là PASS.
PathResult không chứa expected label. Required BLOCKED block; optional BLOCKED
được report trung thực. Video capture failures dùng operational diagnostics,
không thay physics report hoặc tạo ref tới file không tồn tại.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Durable Isaac run và evidence lifecycle.
Cần sửa đồng bộ: candidate inventory/config, operation queue/admission, Isaac adapter/report publication, audit/status/ReviewPanel và AUD-03 gate.
Acceptance xuyên consumer: Queue/restart/cancel/stale lease và report identity pass; real Isaac proof được phân biệt local fake-run.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

- S1 cần contract AUD-03.S1, admission AUD-07.S1; local fake-run tests có thể làm trước GPU.
- S2 cần AUD-01/AUD-02 supported candidate và qualified SIM-01 runtime/config.
- S3 cần S2 observations; S4 cần AUD-03 gate và AUD-04 sealing.
- Thiếu GPU/runtime/config: phần local có thể hoàn thành; runtime sprint phải
  ghi BLOCKED/UNVERIFIED cụ thể, không đánh dấu task DONE bằng fixture.

## Sprint AUD-05.S1 — Durable validation request và report selection

**Input:** current candidate + public config + editor authorization.
**Output:** queued run ID, persisted input identity, status/read API và worker claim.
**Contract:** one operation identity per request/attempt; lease/fencing; exact
candidate/config; multiple run reports không overwrite; current selection chỉ
trỏ completed trusted run của exact candidate.

Implement: thin Studio submit/status/cancel/retry boundary; reuse RuntimeDatabase
queue/claim patterns; use AUD-07 admission adapter. Claim work theo capability;
wait/cancel khi unavailable. Publish result selection bằng CAS; scene mới không
attach report cũ, nhưng giữ run history/artifacts.
Tests: request permissions, duplicate submit, same candidate new attempt, restart,
two workers, stale lease/candidate; fake executable chỉ là local queue proof.
**Exit:** [ ] durable request/selection tests pass; [ ] config profile cụ thể được ghi.

## Sprint AUD-05.S2 — Headless Isaac thin path và observed checks

**Input:** exact candidate, qualified runtime/config S1, resource reservation.
**Output:** real load/spawn/collision/penetration observations và path outcomes.
**Contract:** process-local typed request/result hoặc artifact IPC; không pickle
network/RPyC; runtime fingerprint và candidate/config identity kiểm chứng được.

Implement: isolated headless subprocess, verify inventory rồi load USD; spawn
configured robot; measure checks bằng simulator APIs. Chạy từng configured pair,
timeout/collision/path exceptions thành ERROR diagnostics. Heartbeat/cancel kill
process group và reap trước release resources. Không thêm teleoperation/streaming.
Tests: unit mappings + real GPU smoke một CLEAR và một BLOCKED; wrong units,
invalid USD, bad spawn, collision/contact, timeout và process cancellation.
**Exit:** [ ] real logs/runtime/device; [ ] observed results có exact bindings;
[ ] không dùng fixture để chứng minh simulator chạy.

## Sprint AUD-05.S3 — Report và media/log publication

**Input:** observations/logs S2 và capture output.
**Output:** checksum-valid report + available evidence refs + completed trusted run.
**Contract:** required check/pair set đúng config; report checksum và byte refs
đúng; no missing-file ref; capture issue không thay observed physics result.

Implement: report serializer theo normative schema; native capture trong locked
runtime, fallback frame/FFmpeg chỉ khi native fail và ghi reason/version. Publish
evidence trước report/selection; publish partial có recovery. Consumer resolve
logs/screenshots/video và verify checksum/readability. Không nhúng machine paths.
Tests: roundtrip, wrong candidate/config, duplicate/missing pairs, capture fail,
corrupt media, remote publish fail/retry; real MP4 readability và report consumer.
**Exit:** [ ] report refs verified; [ ] capture diagnostics tách kết quả vật lý;
[ ] trusted run chỉ complete sau required execution evidence publication.

## Sprint AUD-05.S4 — Studio → Isaac → review → release acceptance

**Input:** worker S1–S3, gate AUD-03, sealing AUD-04, real supported candidate.
**Output:** user-observable status/evidence và one verified released artifact.
**Contract:** VALIDATING là projection của real run; approval exact report;
edit tạo DRAFT/candidate mới; stale completion không restore eligibility.

Implement: typed UI submit/poll/cancel/retry, current-run selection, blocked/error
messages và evidence download. Chạy happy path và edit-during-run/failure retry;
compare candidate loaded với release ZIP. Không fabricate progress percentage.
Tests: API/consumer/Vitest + browser interactions + real GPU release journey;
required BLOCKED, ERROR, insufficient resources, stale poll/worker, two attempts.
**Exit:** [ ] end-to-end evidence đủ; [ ] video/log/report/release cùng candidate;
[ ] CPU, browser, GPU và provider coverage được ghi riêng.

## Verification và DoD

Existing suites: tests/test_contracts/test_validation.py,
tests/test_orchestration/test_review_workflow.py, tests/test_api/test_review_routes.py.
Planned: tests/test_simulation/test_validation_report.py,
test_isaac_worker.py, tests/test_orchestration/test_validation_queue.py.
Chạy focused pytest sau khi tạo files; frontend tests/review-panel.test.tsx,
tests/validation-report-card.test.tsx, tests/ux-scene-flow.test.tsx.

S1 phải ghi exact runtime CLI đã qualification, config checksum, GPU/runtime
versions và smoke command. Không cung cấp command giả để tick S2. DONE cần
real Isaac observations + artifact publication + Studio review/release handoff.

## Result / Evidence

Pending — từng sprint lưu run_id, attempt, candidate/config/report checksums,
runtime fingerprint, commands, evidence refs và coverage/limitations.
