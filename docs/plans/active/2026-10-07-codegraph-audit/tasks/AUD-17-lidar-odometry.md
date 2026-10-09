# AUD-17 — Opt-in LiDAR odometry cho raw scan sequence

## Metadata và goal

- IN PROGRESS — S1/S2, S3a và S3b1 đã triển khai; S3b2 có local lease-guarded product stage và source evidence nhưng chưa có world/floor confirmation hoặc canonical LiDAR ingest/alignment. R5 runtime qualification và quality evidence còn mở. P2 extension theo yêu cầu owner; EX-REC + EX-PRODUCT.
- Canonical REC-08/06, PRODUCT-02/08/09; bổ sung task-local scope, không đổi crosswalk.
- ADAPT qualified process-isolated KISS-ICP adapter; REUSE LiDAR ingest/metric/
  alignment contracts và durable admission. Technically feasible, không loại trừ
  chỉ vì old MVP không làm SLAM.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0018](../../../../decisions/0018-opt-in-lidar-odometry.md).

## Baseline và scope

detect._detect_lidar_package yêu cầu trajectory/calibration/timestamps; chưa có
odometry producer. Legacy supplied-trajectory APIs giữ behavior. Estimate mode là
explicit resolved config cho ordered timestamped raw scans; AUD-24 có thể tự chọn
recipe này và hiển thị trước Run, không bắt user chọn mode ở màn hình riêng.

CodeGraph: _detect_lidar_package, LiDAR package/models/fusion/ingest,
camera_priors/coordinate_bridge, metric/world_alignment, input kinds và job dispatch.
Owned: REC worker adapter, typed derived trajectory/package binding, input routing,
PRODUCT durable operation/config/API diagnostics và tests/eval protocol.
Initial scope local odometry; global loop closure/map optimization/localization
stack là future scope. FAST-LIO cần qualified IMU/sensor/timing inputs, không gắn
vào scan-only pipeline. Odometry không giải blind camera↔LiDAR calibration.

## Input / output / data contract

Input: safe scan package, unit/frame convention, ordered scan indices/timestamps,
explicit estimate profile. RGB fusion còn cần calibration, camera timing/offset
và intrinsics đúng contract; scan-only estimation không tự tạo chúng.
Output proposed EstimatedTrajectoryArtifact + diagnostics, optional fused cloud
qua existing ingest và metric/alignment proposal cho user confirm.

Trajectory contract: schema/provider/runtime version, exact assembly/revision/recipe
checksums, timestamp-file checksum, per-scan source file ID/checksum and timestamp
in seconds, ordered `map_from_sensor` SE(3) poses in meters, origin=estimated,
coverage/gap and optional convergence/degeneracy diagnostics. Absolute drift is
`not_measured` unless a separate reference evaluator proves it. `world_from_map` is
optional and must be confirmed before canonical world/Z-up ingestion. S1 stores
this derived artifact contract without claiming that a producer is installed.
Never tag ground_truth, create identity poses on failure hoặc modify original ZIP.
Missing ground truth nghĩa absolute drift unknown, không là zero.

Odometry map khởi tạo ở sensor pose không tự là canonical world/Z-up. Integration
phải có declared/confirmed world_from_map từ supported sensor up/floor prior hoặc
qualified floor evidence. Persist transform/provenance; thiếu up/floor support thì
trajectory vẫn có diagnostics nhưng metric/canonical fusion bị block. Không truyền
arbitrary first-scan frame vào estimate_floor vốn giả định Z-up; không rotate lại
existing SceneIR để hợp thức hóa output. AUD-14.S1 có thể cung cấp fitted-plane evidence.

Scan-native trajectory khác poses tại RGB frame_times. Consumer mapping cần explicit
clock offset, interpolation method/bounds, available interval và provenance.
Nếu supported: translation interpolation + quaternion SLERP với bounded gap,
no unconstrained extrapolation; persist derived RGB pose mapping separately.
Không claim point-cloud deskew nếu sensor package thiếu per-point time/capability.
New estimated or user-supplied trajectory tạo new identity; downstream QA/alignment/
collision phải invalidate evidence cũ và confirm lại theo existing workflow.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Estimated trajectory mode khác supplied trajectory.
Cần sửa đồng bộ: input detection/routing, safe scan ingest, odometry worker/provider/version, trajectory/frame bindings, RGB priors/metric/alignment và QA consumers.
Acceptance xuyên consumer: Explicit supplied/estimated modes, unsupported/drift diagnostics và timestamps giữ identity; estimated trajectory không tự tạo calibration PASS.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập để qualify adapter/input contract. S2 dùng AUD-07 admission/lease pattern.
AUD-24.S1 cung cấp grouped assembly/recipe port; reuse trong unified path, không
đợi whole AUD-24 để implement odometry. Legacy missing-trajectory request khác
valid assembly có accepted estimated recipe; không auto estimate từ file ambiguous.
Contract port: `sensor_trajectory` khác `camera_trajectory`; each supplied or
estimated scan pose binds exact scan refs/timestamps and uses `world_from_sensor`
in a declared world frame, metres, quaternion `xyzw`. Estimated output retains
source scan refs and `estimated` provenance; it is never inserted as a supplied
TUM upload. The existing TUM parser checks row ordering/pose shape but does not
establish RGB clock synchronization.
S3 dùng AUD-13 calibration/timing QA cho RGB integration; AUD-14.S1 khi cần fit
floor/up normalization; AUD-12 cho collision selection, không auto-enable LiDAR
collision từ trajectory vừa estimate.

## Sprint AUD-17.S1 — Input mode và runtime qualification

**Input:** current package detector/schema + timestamped scan fixtures/real sensor sample.
**Output:** explicit supplied/estimate modes, derived trajectory contract, neutral timestamp role/unit declarations and a pinned adapter candidate envelope.
**Contract:** supplied mode unchanged; ZIP/header/path/count checks preserved;
unsupported sensor/timestamps báo reason; estimated output không là upload/ground truth.

Implement: preserve supplied trajectory behavior; classify one-column numeric time
rows as role-ambiguous until the user assigns RGB or LiDAR; keep separate timestamp
units while reading legacy shared `timestamp_unit`. An explicit R5 estimate candidate
requires one ordered scan timestamp per scan, matching row count, declared time unit,
declared scan order, metric unit and sensor frame. Bind the exact scan/time refs and
checksum them in `EstimatedTrajectoryArtifact`; incomplete inputs stay `NEEDS_INPUT`
and wired-unqualified runtime stays pending. Normalize derived pose translations to
meters; do not treat the local odometry map as canonical world.

Adapter candidate: pin `kiss-icp==1.3.0` in the future isolated worker image and use
its Python `KissICP.register_frame` API. Upstream release is MIT. The API consumes
per-point relative timestamps for deskew; the sidecar accepted here contains per-scan
timestamps only and must never be passed off as per-point timing. S2 must disable
deskew or reject inputs without verified per-point timing, then test this behavior.
The provider package is not installed in the Studio runtime; the transitive license
inventory, worker image, supported point attributes, real-sensor sample, and memory/
performance envelope remain unqualified. R5 stays `WIRED_UNQUALIFIED`.

Tests: legacy shared-unit payload/checksum compatibility; ambiguous timestamp probe;
explicit R5 binding, scan-count mismatch, invalid ordering, artifact pose/frame/lineage
invariants; UI requires explicit role selection, preserves distinct RGB/LiDAR units,
and clears stale bindings when the selected input changes. Keep unsafe ZIP/header
checks and supplied trajectory paths unchanged.
**Exit:** [x] mode/schema/runtime candidate envelope agreed; [x] validation not weakened;
[ ] isolated provider/dependency license qualification; [ ] supported sensor sample,
memory/performance and per-point timing behavior qualified.

## Sprint AUD-17.S2 — Durable odometry worker và trajectory publication

**Input:** validated scan refs/config + admitted operation/lease.
**Output:** immutable estimated trajectory/diagnostics and verified ingest binding.
**Contract:** subprocess isolated/cancellable; lease fences publication; finite
SE(3)/monotonic time/coverage checked; degeneracy not fabricated success.

Implement: decode supported scans, run pinned adapter, classify input/runtime failures,
validate output and publish through resolver. Build scan-native mapping only; preserve
scan identities and timestamp rows without RGB interpolation. Use bounded point counts,
actual resource measurement and retry policy; failed attempt files/logs remain available
for diagnosis and are never consumed as complete trajectories. S3 owns RGB-time mapping.
Tests: known-motion and static sequences, sparse/over-budget scans, invalid SE(3),
timestamp unit/count/gap handling, same-attempt immutability, cancel/timeout, stale
lease and corrupt output. KISS-ICP exposes no qualified convergence/degeneracy signal;
low-overlap quality classification stays in S3, and S2 must not invent confidence.
**Exit:** [x] valid estimated producer path for the pinned synthetic fixture; [x] failed/cancelled results remain truthful. This is not R5 product acceptance or real-sensor qualification.

## Sprint AUD-17.S3 — Integration, drift QA và product diagnostics

**Input:** derived trajectory + calibration/timing/metric evidence and real traversals.
**Output:** ingest/alignment consumers, selectable fallback và qualified quality report/UI.
**Contract:** user sees estimated provenance/uncertainty; no automatic GT status;
supplied replacement or timing/calib change invalidates dependent evidence.

Implement: connect existing ingest/fusion/metric ports; add bounded RGB pose mapping
only when timestamp/clock evidence supports it; display actionable quality diagnostics
and allow explicit supplied trajectory fallback with new identity.
Evaluate supported sensor conditions over separate traversals; independent reference
trajectory chỉ dùng evaluator, không leak vào product solver. Record relative/absolute
pose error where reference exists, degeneracy/coverage and downstream obstacle retention.
Confirm source-map→world transform trước canonical ingest; giữ original scan poses.
Tests: supplied/estimated consumer parity, stale calibration/trajectory binding,
clock mismatch, tilted first-scan frame/up normalization, missing floor support,
UI mode/failure/fallback, real odometry benchmark và held-out quality.
**Exit:** [ ] supported envelope/drift measured; [ ] integrations and fallback verified.

S3 execution is split into separately reviewable commits:

### Sprint AUD-17.S3a — Independent-reference drift evaluator

**Input:** immutable estimated trajectory plus evaluation-only reference trajectory, explicit frame, units, clock relation and offset.
**Output:** JSON report bound to exact trajectory/reference checksums with reference coverage, first-pose rigid-aligned ATE and adjacent-scan RPE.
**Contract:** reference data is consumed only by the evaluator; no scale fit, product artifact mutation, solver input or qualification verdict.

Tests cover equivalent trajectories under a global map change, accumulated translation drift, declared clock offset, unit conversion, frame mismatch, interpolation limits, no extrapolation and insufficient adjacent matches. The report must keep real-sensor qualification pending.

### Sprint AUD-17.S3b1 — Consumer-readiness guard for diagnostic pose mapping

**Input:** an estimated scan trajectory, selected RGB source timestamps, optional
camera/LiDAR calibration, explicit clock evidence and an optional confirmed world
bridge.
**Output:** diagnostic RGB pose mappings plus complete blocker codes and an explicit
consumer-readiness boolean.
**Contract:** diagnostic poses may be calculated for inspection, but they are
`complete_for_consumer` only when the runtime is qualified, the world bridge is
confirmed, calibration/time evidence is valid and every selected frame maps within
the configured interpolation bound. A wired-unqualified runtime must never appear
consumer-ready, even when a fixture supplies a world bridge.

Implement/test this guard before adding durable product consumers. Preserve usable
diagnostic poses and their provenance; report runtime qualification alongside missing
calibration, clock, world-frame and per-frame mapping blockers. Do not enable R5 or
canonical ingest in this sprint.

### Sprint AUD-17.S3b2 — Durable estimated-trajectory consumer integration

**Input:** accepted R6 assembly, exact scan/time/calibration bindings and a verified derived trajectory.
**Output:** lease-guarded odometry stage, explicit world/floor confirmation and source-bound LiDAR ingest/alignment evidence.
**Contract:** no estimated poses enter canonical ingest until the world bridge, calibration and time evidence are confirmed; stale bindings invalidate dependent QA; supplied trajectory remains a separate new recipe identity.

### Sprint AUD-17.S3c — Product diagnostics and fallback UX

**Input:** persisted odometry, mapping, calibration and ingest diagnostics.
**Output:** actionable coverage/gap/qualification state and explicit supplied-trajectory fallback in the Studio assembly flow.
**Contract:** never label unqualified odometry as PASS or ground truth; fallback creates a distinct recipe and reruns downstream evidence.

Held-out traversal measurement and supported-envelope acceptance remain external gates after S3b2/S3c; synthetic tests do not close them.

## Verification và DoD

Focused verification command is recorded below with the sprint result. S2 adds the
odometry producer tests; opt-in API/UI tests remain for S3 integration.
DONE cần actual adapter runs/quality envelope/integration, không chỉ mocked poses;
không claim drift-free SLAM. Primary: [KISS-ICP](https://github.com/PRBonn/kiss-icp),
[FAST-LIO](https://github.com/hku-mars/FAST_LIO).

## Result / Evidence

Partial — S1 code implements neutral timestamp roles and separate units, exact ordered
scan/time bindings, resolver prerequisites, and immutable estimated-pose lineage. It
also rejects non-finite pose/map translations; the existing raw-sequence resolver gate
requires at least two scans. R5 remains `WIRED_UNQUALIFIED`; no estimated trajectory
is dispatchable.

Verification before commit:
- Backend focused regression command (input detection/package/fusion/ingest/metric,
  resolver/contracts, upload API paths): 153 passed. Resolver rejects a timestamp
  file bound to both RGB and LiDAR roles.
- `.venv/bin/ruff check src/ tests/` and `.venv/bin/ruff format --check src/ tests/`:
  passed; 537 files already formatted.
- Frontend `unified-input-flow` and `studio-inspection` tests: 21 passed; TypeScript
  typecheck and focused ESLint: passed.
- Chrome DevTools Reviewer session: `/new` and `/api/v1/auth/me` returned 200 with no
  console warnings/errors; mocked upload interaction covered explicit timestamp-role
  selection, separate units, duplicate-role prevention and clearing stale selections.
  No upload/job was created. The separate QA stage URL was also inspected: its old job
  is RUNNING at metric confirmation and has no `ST-LIDAR-CALIBRATION-QA` stage, so the
  page correctly shows the incomplete-stage state. This does not verify rendering a
  completed QA report.

At S1 close, runtime execution, dependency inventory, real-sensor resource/quality
evidence, worker publication and S3 consumer QA were still pending. S2 updates that
state below; real-sensor qualification and S3 integration remain open.

S2 implementation:
- Added the isolated `kiss-icp==1.3.0` CPU runtime lock and GPU-worker interpreter path;
  the API and scene runtimes do not acquire the provider dependency. PCD input is
  limited to bounded ASCII/uncompressed-binary scans with finite XYZ coordinates;
  default point budgets are 5M per scan and 25M across the sequence.
- The worker binds each scan ID/checksum to exactly one timestamp row, converts the
  declared unit to seconds, preserves scan-native poses, measures adapter-process/provider
  elapsed time, provider CPU time and peak RSS, and publishes a separate byte-checksummed
  artifact plus logical trajectory checksum. Read-back verification creates a typed
  ingest binding that remains pending world-frame confirmation.
- KISS-ICP's per-point deskew is explicitly disabled and an empty relative-point-time
  array is passed; the per-scan clock sidecar is never used as fabricated point timing.
  The worker checks cancellation and lease currency while the subprocess runs and before
  and after immutable publication. A lease loss in the narrow publication race may
  leave an attempt-scoped orphan artifact, but no ingest binding is returned and no
  JobManifest pointer is committed. S3 must perform the durable lease-guarded commit.
- The provider API does not expose a qualified per-scan convergence/degeneracy or drift
  estimate. Those fields remain absent, absolute drift remains `not_measured`, and every
  result stays `wired_unqualified`; no output from this sprint is dispatchable through
  R5. Synthetic known-motion and static runs validate adapter direction and truthful
  uncertainty reporting, not warehouse sensor accuracy. A world-frame bridge and
  real-sensor envelope remain pending. The isolated lock was installed from the exact
  generated lockfile and exercised successfully; the full GPU image was not built.
- A metadata scan covered all 19 pinned distributions. KISS-ICP declares the MIT
  license; `tqdm` and `python-dotenv` provide no license expression/classifier in their
  installed metadata. Complete transitive license review remains open before image
  release.

S2 verification:
- Focused regression command:

  ```bash
  REC17_LIDAR_ODOMETRY_PYTHON=/tmp/r2s-lidar-locked-runtime/bin/python .venv/bin/pytest \
    tests/test_reconstruction/test_lidar_odometry.py \
    tests/test_contracts/test_reconstruction.py \
    tests/test_contracts/test_input_assembly.py \
    tests/test_reconstruction/test_input_detection.py \
    tests/test_reconstruction/test_lidar_package.py \
    tests/test_reconstruction/test_lidar_fusion.py \
    tests/test_reconstruction/test_rec08_lidar_ingest.py \
    tests/test_reconstruction/test_rec06_lidar_metric.py \
    tests/test_reconstruction/test_lidar_world_alignment.py \
    tests/test_orchestration/test_upload_input_kinds.py -q
  ```

  Result: 121 passed. The opt-in case exercises known-motion and static scans through
  the complete worker with the exact lock-installed KISS-ICP 1.3.0 runtime.
- `.venv/bin/ruff check src/ tests/ scripts/gpu/lidar_odometry_runner.py` and
  `.venv/bin/ruff format --check src/ tests/ scripts/gpu/lidar_odometry_runner.py`:
  passed; 541 files formatted.
- The expected +0.10 m sensor displacement is recovered within 0.04 m tolerance; the
  static sequence remains explicitly unqualified with convergence and degeneracy absent.
- Cancellation, timeout and stale-lease tests verify the process group is killed and
  reaped. Invalid SE(3), sparse scans, timestamp row-count mismatch and corrupted output
  are rejected before publishing a consumable trajectory. Retry policy is limited to
  runtime-unavailable, timeout and OS out-of-memory errors; deterministic,
  incompatible-runtime, cancelled and stale-lease failures remain non-retryable.
- Chrome DevTools was not a mandatory S2 gate because no UI code changed. An optional
  check with the existing Reviewer session confirmed that the QA route renders its
  incomplete-stage state for the current job. No completed calibration artifact/report
  was available; the browser console had no runtime errors. This does not verify a
  completed QA report.

S3 implementation progress — not complete:
- Added a diagnostic-only mapping function from verified RGB output/source-frame PTS
  to interpolated LiDAR odometry poses. It requires a camera-to-sensor transform with
  matching frame identity and a known clock relation; known offsets follow the AUD-13
  residual sign convention. If `world_from_map` is absent, it still returns poses in
  the local odometry frame but marks the mapping incomplete and leaves
  `world_from_camera` unset. When present, the world transform must match the odometry
  frame. Translation is interpolated linearly and rotation with quaternion SLERP; the
  mapper rejects contradictory same-clock offsets, never extrapolates, and reports
  frames outside the trajectory or beyond the configured scan-gap limit. Every result
  remains `diagnostic_only`; partial or map-local mappings cannot be consumed as
  canonical results.
- This utility is not wired into `ProjectRegistry`, `LidarPackageIngest`, `camera_priors`,
  or an alignment consumer. It does not create an estimated `LidarPackageRecord`,
  canonical floor/world bridge, calibration QA, drift/coverage quality report, UI,
  or supplied-trajectory fallback. R5 dispatch remains disabled. Those S3 requirements
  and real held-out traversals remain open; synthetic transform tests prove only the
  mapping behavior and frame/clock guards.
- The module deliberately does not infer `world_from_map` from the first scan or assume
  Z-up. S2 trajectories remain in their local odometry frame until a separate, evidenced
  map-to-world and floor/up-axis decision exists.
- Chrome DevTools read-only inspection of the current QA route returned HTTP 200. Its
  progress API reported a RUNNING attempt waiting for metric confirmation, and the stage
  list contained no `ST-LIDAR-CALIBRATION-QA`; the page correctly rendered its incomplete
  stage state. No browser console errors appeared. This verifies only the incomplete
  state, not a completed QA report, and no job was created or changed.

Focused S3 mapping verification:
- `REC17_LIDAR_ODOMETRY_PYTHON=/tmp/r2s-lidar-locked-runtime/bin/python .venv/bin/pytest tests/test_reconstruction/test_lidar_odometry.py -q`: 21 passed.
- Mapping tests cover a nonzero clock offset, translation interpolation, quaternion
  SLERP, exact frame lineage, required calibration/clock evidence, map-local output
  without a world bridge, frame-mismatched world transforms, contradictory clock
  declarations, no extrapolation, and maximum-gap rejection.
- Implementation base: `71d338c` (`AUD-17.S2`). Changed files: the new
  `src/services/reconstruction/lidar/trajectory_mapping.py`,
  `tests/test_reconstruction/test_lidar_odometry.py`, this task record, and the active
  plan checklist in `README.md`. No persisted schema/artifact changed; no artifact was
  published. Synthetic consumer proof is limited to the mapping function's returned
  camera transforms and blocker diagnostics.
- Gate report: CodeGraph explore/callers completed; minimal change adds one isolated
  mapper and focused negative/positive tests. Focused regression: 125 passed; repository
  Ruff check/format: passed, 541 files formatted; `git diff --check`: passed. Graphify
  updated after source changes. Browser evidence above covers only the existing
  incomplete-stage state. The sprint remains open for actual consumer wiring, drift QA,
  fallback, UI, and held-out traversal qualification.
- CodeGraph explored `EstimatedTrajectoryArtifact`, `LidarPackageIngest`, `camera_priors`
  and `compose_transforms`; its caller list confirms the new mapper has tests only and
  no product consumer yet. Index status: 879 files, 17,484 nodes and 51,601 edges,
  up to date. `graphify update .` rebuilt the graph to 20,732 nodes and 60,708 edges.
- Related-code impact: no shared consumer contract changed; legacy ingest, camera-prior
  callers, and R5 dispatch remain unchanged. Remaining S3 work must add and test the
  consumer path before this sprint can be marked complete.

AUD-17.S3a implementation:
- Added the evaluation-only `eval.pose.lidar_odometry_error` CLI and
  `eval/protocols/lidar_odometry.md`. It validates the estimated artifact checksum,
  explicit reference frame/units/clock, bounded reference interpolation, and exact
  reference-file checksum.
- ATE uses only a rigid alignment from the first matched pose; it never fits scale or
  aligns the complete path. RPE uses adjacent estimated scan poses only. The report
  includes matched coverage, unpaired scans, metrics, runtime qualification state, and
  `product_solver_used_reference=false`.
- The evaluator leaves the product trajectory unchanged and cannot qualify R5. No
  real sensor reference was available in this run; supported-envelope and held-out
  acceptance remain pending.
- Verification: `.venv/bin/pytest tests/test_reconstruction/test_lidar_odometry_evaluation.py
  tests/test_reconstruction/test_lidar_odometry.py tests/test_reconstruction/test_reference_evaluators.py -q` —
  35 passed, 1 skipped. `.venv/bin/ruff check src/ tests/ eval/pose/lidar_odometry_error.py` —
  passed. `.venv/bin/ruff format --check src/ tests/ eval/pose/lidar_odometry_error.py` —
  576 files formatted. `git diff --check` — passed.
- Gate report: CodeGraph read `trajectory_errors`, `EstimatedTrajectoryArtifact`,
  `parse_trajectory`, `timestamps_in_seconds`, `verify_content_checksum`, and
  `rotation_matrix`; impact is evaluation-only with no product callers. The evaluator
  reuses existing parsers, unit conversion and checksum validation. `understand-anything`
  CLI is unavailable; AUD-17 and ADR 0018 provided the business context. No UI changed,
  so DevTools is not applicable. S3b1–S3b2/S3c and real-sensor acceptance remain open.

AUD-17.S3b1 implementation:
- A diagnostic mapper could previously report `complete_for_consumer=true` when a
  test supplied `world_from_map`, despite the producer being `wired_unqualified`.
  The readiness gate now also requires `runtime_qualification_status == "qualified"`.
- Diagnostic poses remain available for inspection. Mapping reports
  `ODOMETRY_RUNTIME_NOT_QUALIFIED` with any missing calibration, clock, world-bridge
  or frame-coverage blockers; blocked global mappings retain all applicable reasons.
- This sprint does not change product consumers, R5 dispatch or canonical ingest.
  The live producer remains wired-unqualified, so no current trajectory is consumer-ready.
- Verification: focused odometry/evaluator tests — 28 passed, 1 skipped;
  `.venv/bin/ruff check src/ tests/` passed; `.venv/bin/ruff format --check src/ tests/`
  passed (575 files); `git diff --check` passed.
- Gate report: CodeGraph traced the mapper and its direct reconstruction tests;
  Graphify located the AUD-17 mapping and consumer-readiness context. The change is
  limited to the mapper contract/tests and AUD-17 plan/progress. No UI changed, so
  DevTools is not applicable. CodeGraph reports 918 files, 18,692 nodes and 55,906
  edges with the index up to date; `codegraph sync .` could not acquire the database
  lock held by the live MCP server (PID 14310). `graphify update .` rebuilt 21,586
  nodes and 64,895 edges. `understand-anything` availability remains unverified.

Before the S3b2 integration patch, dispatch stopped at the resolver and there was no
durable product stage. The remaining S3b2 and qualification gates are recorded below.

AUD-17.S3b2 implementation progress — partial, sprint remains open:
- Added an opt-in worker path for accepted R5 estimated-trajectory and R6
  sensor-guided recipes. It enters `ST-LIDAR-ODOMETRY`, uses the existing isolated
  KISS-ICP worker, checks the current job/stage/manifest lease before publication,
  and resumes only from evidence bound to the exact accepted recipe.
- The worker copies the accepted assembly, resolution, runtime registry and recipe
  from project scope into the current job attempt. The reducer checks artifact type,
  schema, checksum, exact copied bytes, project-source provenance, attempt URI,
  recipe identity, ordered scan IDs/checksums, archive-member checksums, timestamp,
  calibration and RGB-frame-time bindings before its compare-and-swap commit.
- Fixed R5/R6 upload persistence: raw scan ZIPs remain staged-assembly sources and
  are linked through the input-assembly store. They are no longer incorrectly
  expected in the legacy product-upload table. RGB video and R4 supplied-trajectory
  linkage remain covered by existing route regressions.
- The v1.0 `EstimatedTrajectoryConsumerEvidence` and `ST-LIDAR-ODOMETRY` stage report
  runtime qualification plus explicit pending world-frame, floor/up-axis and
  RGB-alignment states. Estimated poses do not enter canonical geometry or collision
  selection. This patch does not implement a world/floor confirmation command or
  source-bound `LidarPackageRecord`/alignment consumer, so S3b2 is not complete.
- R6 without server-verified prepared-to-source frame mapping remains rejected with
  `VERIFIED_RGB_FRAME_MAP_REQUIRED`. The R5 product runtime remains
  `WIRED_UNQUALIFIED`; qualified records in the route test are synthetic and do not
  qualify a deployed runtime. Real traversal drift/coverage and held-out quality are
  still external acceptance gates. These are missing implementation/evidence, not
  technology impossibilities.
- Consumer proof: the API test invokes `_execute_lidar_odometry` with a fake provider
  process, persists the stage through `ProjectRegistry.record_lidar_odometry`, checks
  the job-scoped evidence and confirms the world/floor/alignment blockers. The R4
  supplied-trajectory regression passes. This does not execute the pinned provider
  or prove sensor accuracy.
- Browser check: authenticated Reviewer DevTools opened
  `/scenes/job-6bc02e5de4ed/stages/ST-LIDAR-ODOMETRY`; HTML and progress API returned
  200, the current job had no odometry stage, and the page correctly showed its
  incomplete-stage state. Console had no runtime error. No completed odometry artifact
  was available, so the artifact panel was not verified in the browser.
- Schema delta: add `StageId.LIDAR_ODOMETRY` and `EstimatedTrajectoryConsumerEvidence`
  v1.0; no database migration and no legacy artifact rewrite. No production artifact
  was created; test artifacts were isolated to pytest temporary directories.
- Base: `08768020`. Changed implementation files: `frontend/src/features/studio/inspection/StageInspectionPage.tsx`, `frontend/src/features/studio/inspection/LidarOdometryStage.tsx`, `frontend/src/features/studio/stages.ts`, `frontend/src/lib/contracts/api.ts`, `frontend/tests/studio-inspection.test.tsx`, `src/api/studio/assemblies.py`, `src/models/contracts/manifests.py`, `src/models/contracts/reconstruction.py`, `src/services/orchestration/inputs/assembly.py`, `src/services/orchestration/jobs/runner.py`, `src/services/orchestration/projects/persistence.py`, `src/services/orchestration/projects/registry.py`, `src/services/reconstruction/lidar/odometry.py`, `tests/test_api/test_studio_routes.py` and `tests/test_reconstruction/test_lidar_odometry.py`.
- Verification: affected backend suites — 99 passed, 1 skipped; `.venv/bin/ruff check
  src/ tests/` and `.venv/bin/ruff format --check src/ tests/` — passed, 582 files
  already formatted. `npm test -- tests/studio-inspection.test.tsx
  tests/unified-input-flow.test.tsx` — 23 passed; `npm run typecheck` — passed;
  changed-file ESLint — passed; full `npm run lint` — 0 errors and 2 warnings in
  unchanged `LidarCalibrationQAStage.tsx`. `npm run build -- --webpack` in an isolated
  frontend mirror with repository fixtures — compiled, typechecked and generated all
  17 static pages and dynamic routes. The first isolated copy omitted the repository
  fixture directory; the corrected mirror passed. `git diff --check` — passed.
  `codegraph status` — 931 files, 19,038 nodes, 57,185 edges, up to date;
  `graphify update .` rebuilt 21,855 nodes and 66,383 edges. `understand-anything` is
  unavailable in this environment; task guide, integration map and caller paths were
  read directly.
- Pre-flight gate: CodeGraph traced `_execute_lidar_odometry`, the worker, the reducer,
  assembly routing and stage inspection. The static caller command did not resolve
  the registry method dispatch, but the on-disk worker call and reducer integration
  test verify that path. Minimal change reuses `ArtifactResolver`,
  `FilesystemArtifactStore`, the existing admission/lease lifecycle and R4 route.
  DevTools verified only the incomplete state; completed artifact rendering remains
  unverified. Next: implement evidenced world/floor confirmation and LiDAR ingest/
  alignment consumers before closing S3b2; preserve R5/R6 and held-out gates.

- Follow-up S3b2 progress: the worker fuses its already verified cached scans with
  the estimated poses and publishes a deterministic `EstimatedTrajectoryMapCloud`
  in the local odometry frame. `EstimatedTrajectoryProductEvidence` binds that PLY
  and its fusion profile/counts to the exact trajectory, accepted recipe, timestamps
  and ordered scans. The registry streams checksum and finite-point validation for
  the PLY before committing the composite stage receipt; it also reads legacy
  `EstimatedTrajectoryConsumerEvidence` receipts. Stage inspection displays the
  local map status and count while world, floor and RGB alignment remain pending.
- Verification for this increment: `tests/test_reconstruction/test_lidar_odometry.py`
  and `tests/test_api/test_studio_routes.py` — 45 passed, 1 skipped; full repository
  Ruff check passed and format check reported 582 files formatted. Focused
  `studio-inspection.test.tsx` — 19 passed; `npx tsc --noEmit` and changed-file ESLint
  passed. Route regression confirms a tampered fused PLY is rejected before a second
  manifest commit. `git diff --check` passed.
- DevTools follow-up: authenticated Reviewer session returned HTTP 200 for the
  odometry stage route and its progress request; console contained only React
  DevTools/HMR informational messages. That job has no completed odometry artifact,
  so the new product-evidence panel remains **UNVERIFIED** in the browser.
- This follow-up does not confirm `world_from_map`, floor/up-axis evidence, create a
  canonical `LidarPackageRecord`, or register the map against RGB. S3b2 remains open;
  R5/R6 runtime qualification, real traversal quality and held-out acceptance remain
  separate gates.

S3c supplied-trajectory fallback UX regression:
- `UnifiedInputFlow` already renders runtime status and resolver diagnostics for each
  candidate, and only renders Run for the recommended READY candidate. A READY R4
  supplied-trajectory candidate can therefore remain usable while estimated R6 is
  pending; the UI does not silently dispatch or switch to R6.
- Added a frontend regression that presents R6 as `wired_unqualified`, keeps its
  diagnostic visible, and submits only the selected R4 candidate. This verifies the
  existing fallback behavior; it does not provide persisted odometry QA or close
  S3b2/S3c quality-report work.
- Verification: `npm exec vitest run -- tests/unified-input-flow.test.tsx` — 5 passed;
  `npm run typecheck` — passed; `npm exec eslint -- tests/unified-input-flow.test.tsx`
  — passed; `git diff --check` — passed. No rendered component changed, so the
  browser UI change gate is not applicable.
- Gate report: CodeGraph traced `UnifiedInputFlow`, its candidate submit gate and
  the focused regression; Graphify located the unified-input/R4–R6 relationship.

R6 estimated-map consumer follow-up (AUD-17.S3b2, 2026-10-09):
- Added a distinct `estimated_trajectory_map` registration input. Preparation
  selects only a successful attempt-scoped R6 `EstimatedTrajectoryProductEvidence`
  and its exact PLY map ref, then rechecks the accepted assembly, ordered raw-scan
  binding/checksums, project recipe lineage, parsed map header, local map frame and
  runtime status before sealing a registration request.
- The registration request and copied `RegistrationSourceCloudManifest` preserve
  the ordered scan IDs/checksums and both odometry refs. The evidence/map refs must
  share the same attempt ID. Raw scan sequences remain blocked as direct ICP input;
  a mismatched or wired-unqualified odometry runtime remains preflight-blocked.
- This opens a provisional geometric-registration consumer for R6 without claiming
  same-place truth from the user declaration. It does not confirm world-from-map,
  floor/up axis, calibration/time quality, canonical `LidarPackageRecord`, or an
  `AlignmentRecord`; it does not enable current R5/R6 runtime dispatch. AUD-17.S3b2
  and real-sensor qualification therefore remain open.
- Verification: focused registration, odometry and Studio API suites — 115 passed,
  1 skipped; frontend registration API and stage-inspection tests — 26 passed;
  `.venv/bin/ruff check src/ tests/`, `.venv/bin/ruff format --check src/ tests/`,
  frontend typecheck and changed-file ESLint passed. The UI flow is **UNVERIFIED**
  in DevTools because the current CUA session exposes no browser. Tests prove the
  contract and local code path only, not production runtime qualification or
  physical alignment accuracy.
- Changed scope: registration source/request contracts, accepted R6 preparation
  and verification, worker source-manifest publication, frontend registration
  parsing, stage diagnostics, API/contract/worker/frontend regressions, and this
  task evidence. Graph indexes are refreshed after the implementation checks.
  S3b2's lack of a production adapter remains the controlling product limitation.
