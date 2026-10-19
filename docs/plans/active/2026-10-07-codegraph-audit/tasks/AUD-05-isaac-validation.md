# AUD-05 — Production Isaac validation từ queue đến review

## Metadata và goal

- IN PROGRESS; P0; EX-SIM runtime/report, EX-PRODUCT queue/API/UI.
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
**Exit (local implementation):** [x] durable request, replay, lease recovery,
worker fencing, candidate-staleness, ownership and exact-run selection regression
tests pass; [x] server-owned config/profile contracts bind immutable checksummed
runtime identity to a validation attempt.

**Deployment gate:** [ ] a concrete supported Isaac runtime/config profile is
published and qualified. The current checkout has no Isaac Sim/Isaac Lab install
or server validation config/profile, so this gate is **UNVERIFIED**. A test-only
manifest is not qualification evidence; do not claim AUD-05.S2 runtime acceptance.

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

## Sprint AUD-05.S3 — Report và execution-evidence publication

**Input:** observations/logs S2.
**Output:** checksum-valid report + available execution-evidence refs + completed trusted run.
**Contract:** required check/pair set đúng config; report checksum và byte refs
đúng; no missing-file ref; evidence publish xong mới complete run.

Implement: report serializer theo normative schema. Publish runtime manifest,
execution log và structured Isaac observations trước report; worker chỉ complete
run sau khi repository resolve mọi ref cùng job và kiểm checksum/readability.
Consumer hiện dùng checks/path results và evidence refs; không có UI media field,
configured capture camera hay consumer cho viewport/FFmpeg artifact. Vì vậy S3
không tạo thêm video/screenshot subsystem; có thể mở task riêng khi có use case,
camera contract và UI consumer.
Tests: roundtrip/checksum, wrong candidate/config, duplicate/missing checks hoặc
pairs, tamper/missing refs, resource wait, stale candidate và publication failure.
**Exit local:** [x] report refs verified; [x] no missing-file refs; [x] trusted run
chỉ complete sau execution evidence publication. **Runtime gate:** [ ] real Isaac
run/log/report; media capture không thuộc output S3 sau consumer audit.

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

**Local implementation:** typed Studio submit/poll/cancel/retry, CAS selection of
the exact completed candidate/config run, refresh of review state after selection,
and authenticated download of the named report/runtime manifest/log/observations
artifacts. API resolves downloads from persisted refs and verifies artifact
checksums; the UI does not accept artifact paths from payloads. Historical runs
remain visible, while mutation actions are limited to the current candidate.

**Deployment/browser gate:** UI browser interactions, live worker progress,
failure/retry on Isaac, edit-during-run, release sealing and comparison with the
released ZIP remain unverified until a logged-in Studio and qualified Isaac
deployment are available. A fake child process only proves the local protocol.
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

### AUD-05.S1 — Durable validation request and report selection

Implemented the persisted `r2s_validation_operations` queue (schema v16),
checksummed request/run/operation identities, idempotent submit/replay, immutable
candidate/config/profile binding, worker claim leases with fencing, heartbeat,
resource wait/requeue, stale-candidate cancellation, retryability checks, cancel
acknowledgement, expired-lease recovery, and owner-guarded Studio list/read/submit/
cancel/retry APIs. Server-owned settings load the policy and runtime profile; API
requests cannot provide or override them. Existing validation selection continues
to bind a completed trusted run to its exact candidate/config.

An initial focused run found that `_request_fingerprint` prepended `sha256:` to a
digest that already included the prefix, causing new submissions to fail model
validation. The helper now returns the canonical digest unchanged. Two migration
tests also still expected schema v15 and were advanced to v16.

Verification:

- `.venv/bin/pytest tests/test_orchestration/test_validation_queue.py tests/test_api/test_validation_routes.py tests/test_orchestration/test_validation_runs.py tests/test_orchestration/test_review_workflow.py tests/test_orchestration/test_runtime_migrations.py tests/test_contracts/test_validation_run.py tests/test_api/test_review_routes.py -q -rs --tb=short` — 52 passed, 4 skipped; all skips require `R2S_TEST_POSTGRES_URL`.
- `.venv/bin/pytest tests/test_api -q --tb=short` — 166 passed.
- `ruff check src/ tests/` — passed.
- `ruff format --check src/ tests/` — passed (493 files already formatted).
- CodeGraph index — 801 files, 15,382 nodes, 44,628 edges; up to date before docs-only edits.
- Environment probe — `isaaclab` and `isaacsim` modules absent; server validation config/profile not configured. Runtime qualification is therefore UNVERIFIED and is a deployment/S2 gate.

Changed files: `src/services/orchestration/jobs/database.py`,
`src/services/orchestration/review/validation_queue.py`,
`src/services/orchestration/review/validation_runs.py`,
`src/api/studio/review.py`, `src/config.py`,
`src/models/contracts/validation_run.py`, `src/models/contracts/__init__.py`,
`tests/test_orchestration/test_runtime_migrations.py`,
`tests/test_orchestration/test_validation_queue.py`,
`tests/test_api/test_validation_routes.py`, and this task/plan documentation.

Limitations: these tests prove the durable queue/API contract only. They do not
prove that Isaac Sim starts, executes physics checks, publishes a real report, or
passes browser/GPU/release acceptance. No real `run_id`, report checksum, runtime
fingerprint or evidence artifact exists yet; capture these in S2/S3 rather than
inventing values here.

### AUD-05.S2 — Headless Isaac thin path and observed checks (local prerequisite)

Base commit: `bccf27d` (`AUD-12.S4`). CodeGraph traced
`generate_scene_usda` through candidate building and simulation-package caching;
its 11 direct callers are the legacy builder/package service and USD tests. The
legacy USD entrypoint previously omitted `/World/PhysicsScene`, while the hybrid
builder already creates one. Added the PhysicsScene to legacy candidates, bumped
the legacy simulation-package builder identity from v4 to v5 so cached packages
are rebuilt, updated the generated README, and added an assertion to the USD
syntax test.

Verification:

- `.venv/bin/pytest tests/test_simulation/test_usd.py tests/test_orchestration/test_simulation_package.py -q --tb=short` — 30 passed.
- The configured USD scene runtime opened the generated legacy stage and verified `/World/PhysicsScene` is a `UsdPhysics.Scene`; this is OpenUSD evidence, not Isaac Sim execution.
- `.venv/bin/ruff check src/ tests/` — passed.
- `.venv/bin/ruff format --check src/ tests/` — passed; 561 files formatted.
- `codegraph status` — 899 files, 18,117 nodes, 53,879 edges; index up to date.
- `graphify update .` and a focused `graphify query` — completed; 21,200 nodes, 63,055 edges, 712 communities. Generated graph files remain untracked.
- Environment probe — `isaacsim`, `isaaclab`, `isaac-sim`, and server validation config/profile are absent.

The S2 local implementation now adds an injectable host process adapter and a
std-library-only `scripts/isaac/validate_candidate.py` entrypoint. The host
verifies the queued run/config/profile/runtime identities and exact candidate
inventory, extracts the immutable simulation-package archive under member-count
and byte limits, rejects traversal/symlinks, checks packaged USD/dependency
bytes against the candidate refs, and validates child output identity/check and
path sets. The child creates a separate headless `SimulationApp`, opens the
candidate, checks stage composition/default prim/PhysicsScene/metric units/up
axis, resolves the configured robot and measures its bounds, then observes
spawn and straight-line fixed-orientation footprint overlaps through PhysX scene
queries. Timeout and cancellation use the existing process-group terminator.
Only protocol tests use a fake executable; those tests are not simulator proof.

Contract check IDs are mapped to their observed semantics, including
`ISAAC_LOAD_ERROR`, `ROBOT_SPAWN_INVALID`, `PATH_VALIDATION_ERROR`, and
`REQUIRED_ROUTE_BLOCKED`. Required-route aggregation considers required pairs
only. `PENETRATION_DEPTH` is deliberately `ERROR` with no measured value:
PhysX overlap queries report intersections but not penetration depth. Contact
reports are an available API path ([Omni Physics contact reports](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/latest/extensions/runtime/source/omni.physx/docs/dev_guide/contact_reports.html)); implementing and qualifying a stable depth observation remains engineering work, not a technology impossibility. Until then the worker must not infer zero penetration.

Local verification on 2026-10-09:

- `.venv/bin/pytest tests/test_simulation/test_isaac_process.py tests/test_simulation/test_usd.py tests/test_orchestration/test_simulation_package.py -q --tb=short` — 52 passed. The Isaac process tests exercise a fake child and validate host-side identity, archive, timeout and cancellation behavior; they do not prove Isaac Sim executed.
- `.venv/bin/ruff check src/ tests/` — passed.
- `.venv/bin/ruff format --check src/ tests/` — passed; 587 files already formatted.
- `git diff --check` — passed.
- CodeGraph — 938 files, 19,357 nodes, 58,687 edges; index current.
- Graphify — updated to 22,081 nodes, 67,816 edges and 710 communities; focused query completed.
- Environment/deployment acceptance — **UNVERIFIED**: no Isaac Sim/Isaac Lab runtime or configured worker command is available in this checkout, and no deployed CLEAR/BLOCKED smoke was run.

The host adapter is now dispatched by the durable validation worker added in
AUD-05.S3. That worker persists execution observations, a runtime manifest, a
log, and a schema-valid report before completing the exact fenced run; the
repository verifies reference ownership and artifact checksums on completion
and read. Queue integration does not qualify the Isaac runtime: S2 remains **IN
PROGRESS** until a deployed runtime produces real CLEAR/BLOCKED observations.
The fake child and protocol worker tests are local contract evidence only.

### AUD-05.S3 — Durable worker dispatch and report/evidence publication

The validation queue is now a worker capability in `worker_cli`, sharing the
existing `ResourceAdmission` reservation and heartbeat lifecycle. It loads only
the checksummed config/profile/runtime and the current immutable candidate;
stale or absent candidates are cancelled before admission. If no resource
profile is configured, the attempt returns to `WAITING_RESOURCES`; if no
launcher is configured, it fails visibly rather than reporting a simulated
success. The process adapter receives cancellation, while the lease and
reservation heartbeat stay active through evidence publication. A lost lease,
cancel request, invalid child result, timeout, or publication failure cannot
complete the run. Failed attempt scratch remains available for diagnosis.

Successful local protocol runs publish a per-run runtime manifest, raw execution
log, checksummed structured observations, and report. Report checks and paths
reference the raw observations and log. Completion validates all referenced
bytes and same-job ownership; later reads verify the referenced checksums too.
Optional blocked paths remain observations without failing the whole report;
required blocked paths fail, and missing penetration depth remains ERROR rather
than being inferred from overlap. Report publication is idempotent only when an
existing immutable URI contains identical bytes.

The task draft requested viewport screenshots/video. Source and consumer review
found the Studio review card consumes structured check/path results and evidence
refs, with no configured capture camera or report-media consumer. This sprint
therefore publishes execution evidence only. A media subsystem would need a
defined camera, retention, report contract and UI consumer before implementation.

Verification on 2026-10-09:

- `.venv/bin/pytest tests/test_orchestration/test_isaac_validation_worker.py tests/test_orchestration/test_validation_queue.py tests/test_orchestration/test_validation_runs.py tests/test_orchestration/test_review_workflow.py tests/test_simulation/test_isaac_process.py tests/test_simulation/test_usd.py tests/test_orchestration/test_simulation_package.py tests/test_api/test_review_routes.py tests/test_api/test_validation_routes.py tests/test_packaging/test_deploy_env.py -q --tb=short` — 116 passed.
- `.venv/bin/ruff check src/ tests/` — passed; `.venv/bin/ruff format --check src/ tests/` — passed (589 files formatted).
- `.venv/bin/pytest -q --tb=short` — 2,541 passed, 28 skipped, 15 deprecation warnings. The first full run exposed an unrelated test isolation bug: `tests/conftest.py` loads `.env`, while the symlink guard test retained managed-path variables. Test isolation was fixed separately in commit `21adc736`; production entrypoint behavior was unchanged.
- `git diff --check` — passed; CodeGraph current at 940 files, 19,436 nodes, 58,955 edges.
- `graphify update .` and a focused `graphify query` — completed; 22,132 nodes, 68,135 edges and 760 communities.
- Runtime boundary — **UNVERIFIED**: no Isaac runtime, measured resource profile, or deployment is configured; no real simulator/device log or CLEAR/BLOCKED smoke evidence exists.

Changed files: `src/config.py`,
`src/services/orchestration/jobs/worker_cli.py`,
`src/services/orchestration/review/validation_queue.py`,
`src/services/orchestration/review/validation_runs.py`,
`src/services/orchestration/review/validation_worker.py`,
`tests/test_orchestration/test_isaac_validation_worker.py`,
`deploy/studio/production.env.example`, regenerated deployment examples,
`deploy/studio/README.md`, and this task record.

### AUD-05.S4 — Studio queue controls and evidence access (local implementation)

Added the exact-run selection API with candidate/config binding and compare-and-
swap against the current selection. Added named artifact downloads for the
persisted report, runtime manifest, execution log and observations; each download
is owner-authorized and resolved through the checksum-verifying artifact store.
The Studio review tab now submits and polls validation runs, shows persisted
status/error/resource-wait states, allows cancel and retry when the server marks
the run retryable, and selects completed reports. The UI refreshes ReviewState
after selection and uses the current candidate-wide selection ID for CAS, so a
completed run from the new policy can replace the prior policy's selection.

Local verification on 2026-10-09:

- `.venv/bin/pytest -q --tb=short` — 2,544 passed, 28 skipped, 15 warnings.
- `cd frontend && npm test` — 440 passed across 56 files.
- `cd frontend && npm run typecheck` — passed; changed-file ESLint — passed.
- `.venv/bin/ruff check src/ tests/` and `.venv/bin/ruff format --check src/ tests/` — passed.
- `python scripts/check_contract_mirror.py` and `git diff --check` — passed.
- CodeGraph sync/status — 942 files, 19,498 nodes, 59,161 edges; current.
- `graphify update .` and focused query — 22,163 nodes, 68,263 edges, 722 communities.
- DevTools browser evidence is **UNVERIFIED**: no Studio process listened on
  ports 3010/8010 and the browser tab showed a connection error.
- Isaac runtime, browser interaction, release sealing and deployed end-to-end
  acceptance remain **UNVERIFIED**. This is not a task DONE claim.
