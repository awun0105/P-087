# AUD-19 — Automatic RGB–LiDAR map registration bằng floor, BEV và ICP

## Metadata và goal

- IN PROGRESS; P1; EX-REC registration/geometry; EX-PRODUCT operation/API/UX;
  SCENE/SIM consumers. Owner đồng ý bổ sung hướng cải tiến ngày 07/10/2026.
- Canonical REC-06/08/09, PRODUCT-04/08/09; bổ sung task-local scope, không đổi crosswalk.
- REUSE trajectory camera-center fitting, REC-06 scale/floor proposal, REC-09
  alignment service/resolver và admission; ADAPT bounded BEV search/robust ICP.
- Goal: automatic alignment là thao tác mặc định, manual landmarks là fallback;
  hỗ trợ registered static map độc lập khi không có trajectory/camera extrinsic.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0020](../../../../decisions/0020-automatic-rgb-lidar-map-registration.md).

## Baseline và scope

propose_metric_from_lidar đã fit camera centers, đề xuất scale/floor không cần user
chọn điểm. FinalizeWorker._lidar_alignment tạo confirmed alignment sau metric
confirmation từ trajectory. Fit và proposal hiện có phải reuse, không viết lại
chỉ để đổi tên algorithm. Lần source review 07/10/2026 chạy 19 focused tests pass
ở rec06_lidar_metric/lidar_world_alignment/rec06_auto_scale; đây không là proof
BEV/ICP hoặc browser/real-data acceptance.

MoGe relative_uncertainty chỉ là dispersion giữa frames, không gồm systematic
bias. RGB propose_floor có RANSAC; LiDAR package estimate_floor hiện tìm height
band và giả định Z-up. Hai implementation này không là exact floor/metric guarantee.

CodeGraph: propose_metric_from_lidar, _fit, fit_world_from_lidar_map,
FinalizeWorker._lidar_alignment, propose_metric/align_scale/propose_floor,
LidarPackageIngest/estimate_floor, LiDARIngestService, RgbLidarAlignmentService,
AlignmentRequest/AlignmentRecord và Studio metric/inspection consumers.
Owned: reconstruction/alignment/ registration producer, lidar input adapter,
orchestration operation/confirmation glue, API/frontend alignment flow,
eval/geometry/ protocol và focused tests. No heavy ICP dependency in API process.

Input modes rõ ràng: sensor package có trajectory/calibration dùng đường hiện có;
registered static cloud + reconstructed RGB geometry dùng map registration;
raw scan sequence thiếu trajectory đi qua AUD-17 trước khi thành registered map.
New static-map mode không bỏ validation của existing sensor-package mode.
Map registration không tự tìm camera↔LiDAR rig extrinsic hoặc per-frame time sync.
AUD-24 bổ sung one-dropzone assembly: một static scan có thể dùng map registration
nếu đủ overlap/units/frame evidence; không gọi scan đó là registered whole map.
Raw scans có supplied trajectory nhưng thiếu rig calibration/timing có thể fusion
qua map adapter rồi vào mode này; không fake sensor package để thỏa schema cũ.

## Input / output / data contract

Input: exact RGB source/geometry/metric/floor refs, LiDAR registered-cloud ref,
declared units/source frame, selected profile/ROI, same-scene/capture-context
evidence, optional trusted trajectory/correspondence prior và expected target revision.
Active target là reconstructed RGB source/geometry. Imported PLY/SOG target và
source-space proxy của AUD-25 đã Deferred; không implement hoặc đợi adapter đó.
Static-map mode không bắt user fabricate calibration/timestamps; geometry overlap,
units và scale/floor evidence vẫn phải đủ. Unknown layout changes/coverage báo uncertainty.

Output proposed RegistrationProposalArtifact + RegistrationQAReport, candidate
overlay refs; sau confirmation mới publish checksum-bound AlignmentRecord/bundle.
Operation mutable state/lease tách khỏi immutable proposals và reports.

Proposal: schema/method/version, source/target refs và byte checksums, processing
profile/tool checksum, floor/metric refs, frame conventions, candidate transforms/
scores, scale estimate+uncertainty nếu cần, selected candidate ID và evidence refs.
QA: exact candidate/source/config identity, observed overlap/coverage, robust
residual distributions per region, floor consistency, observability/rank,
multi-candidate ambiguity và PASS/FAIL/INCONCLUSIVE with reasons. GT pose error
chỉ ghi khi evaluator có independent reference; ICP RMSE không là absolute accuracy.

Rigid Transform không chứa scale. Floor-normalized metric maps dùng SE(2) yaw/x/y
với known floor offset; nếu scale chưa chắc thì proposal search thêm scale, không
scale LiDAR metric cloud để ép khớp RGB. Chốt/correct RGB scale qua new REC-06
confirmation/canonical artifacts trước khi tạo final SE(3) world_from_lidar_map.
Không đưa Sim(3) scale vào quaternion hoặc rewrite old metric/SceneIR checksum.
Small roll/pitch/height refinement chỉ khi profile cho phép và bound theo floor evidence.

Current alignment service chỉ nhận same-job geometry/evidence. Independent upload
phải qua authorized ingest/binding vào target job bằng derived ref có original
asset lineage, hoặc reviewed compatible contract extension trong S1; không chỉ
sửa job_id/disable checksum hoặc cross-project authorization checks. Source bytes giữ nguyên.
Target geometry/revision đổi thì proposal/QA/confirmation cũ stale; reprocessing
metric tạo artifacts/revision mới và invalidate candidate/validation/approval cũ.
Initial scale-changing path trước user object edits, hoặc explicit new reconstruction
run; không tự rescale scene đã chỉnh sửa khi registration hoàn tất ngầm.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Static-map registration mode và metric/floor correction.
Cần sửa đồng bộ: input mode/ingest binding, trajectory fit/BEV/ICP, proposal/QA/confirmation, canonical scale/alignment record, CAS scene update và collision selection.
Acceptance xuyên consumer: Final rigid transform đúng units/frame; scale correction creates new artifacts; ambiguity/stale target không auto publish và không rescale edited scene ngầm.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập; reuse current flat-floor/trajectory contract fixtures. AUD-24.S1 cung cấp
assembly/recipe ports khi bind loose files; review adapter/from-assembly lineage
cùng task đó. Port contract tách `registered_lidar_map`, `static_lidar_cloud` và
`lidar_scan`; registration consumes exact checksummed map/cloud refs with declared
units/frame/same-scene evidence. A registered map is not thereby RGB-aligned, and
map registration does not require camera extrinsics. Existing direct map request giữ supported compatibility. S2 dùng
AUD-14.S1 khi cần adaptive floor evidence và AUD-12.S1 quality/coverage protocol.
AUD-25 Deferred; không có dependency hoặc imported-source work từ task đó trong
active S1–S4. RGB/LiDAR registration tiếp tục với existing target contracts.
S3 không đợi toàn bộ AUD-12/13: static-map registration có QA riêng, sensor package
có AUD-13 calibration/timing QA; thiếu rig metadata không tự block map-registration mode.
S4 dùng AUD-07.S1 admission, AUD-10.S2 khi publish scene revision và AUD-03 gate.
AUD-12 source consumer dùng S1 report contract trước; optional static-map source
chỉ qualified sau S3/S4. Không tạo cycle giữa hai whole epics.

## Sprint AUD-19.S1 — Input modes, scale/floor và proposal/QA contract

**Input:** existing REC-06/08/09 contracts + full package/independent-map fixtures.
**Output:** typed mode/profile/request/proposal/report contract, binding và state matrix.
**Contract:** independent maps khác blind sensor calibration; old package path giữ
validation; metric uncertainty không tự thành accuracy; pure rigid final Transform.
`RegistrationSourceBinding` distinguishes sensor package, registered map, one static
cloud and raw scan sequence. Map inputs bind an exact input-assembly ID/revision/
checksum, role and file IDs. Independent map files are PCD/PLY with parsed-header
checksum, explicit m/cm/mm units, source frame and observed point count; one map file
is selected per request. The source frame must be distinct from canonical `world`.
Point count must be nonzero and at most 20,000,000 before downsampling. Missing
format/header/units/frame/count/same-scene context and a
negative same-scene declaration remain `INSUFFICIENT`; malformed units/roles are
rejected. Raw scan sequences preserve their ordered file IDs but remain blocked for
AUD-17 trajectory estimation. Sensor-package requests bind a same-job
`LidarPackageRecord` and meter units, leaving the existing calibration/trajectory
alignment service unchanged. S1 only records and validates source units; the S2
ingester must convert cm/mm to canonical meters before publishing any
`LiDARGeometryArtifact`.

The request binds canonical same-job `RgbGeometry`, target scene revision, metric
confirmation, supported floor-fit evidence, source binding and optional world-frame ROI.
For schema-1.0 wire compatibility, floor evidence refs remain serialized in
`floor_model_refs`; new map requests must place one `FloorFitEvidence` ref there.
Legacy bare `FloorModel` refs remain readable but map preflight rejects them.
Independent maps require an ROI in meters; each dimension is bounded by the profile
(default 100 m). Default search budgets are 180 yaw hypotheses, 2,500 translation
hypotheses, top-8 candidates, 50 ICP iterations, 300 s, 20M source points and 250k
points/map. Profile maxima are bounded at 720 yaw hypotheses, 100k translations,
32 candidates, 200 iterations, 3,600 s and 1M points/map. Known confirmed scale is
the default policy. A bounded RGB scale hypothesis may produce a proposal while
metric scale is unknown, but cannot pass QA or become final geometry; REC-06 must
confirm and republish canonical geometry first. Final transform remains rigid SE(3).

QA reports source/target coverage, overlap, bidirectional p95 residual, floor
difference, observable degrees of freedom, candidate margin and per-region residuals.
Provisional defaults require 10% source/target coverage, 20% overlap, <=0.10 m
bidirectional p95 residual, <=0.10 m floor difference, 3 observable DOF and 0.05
candidate margin. These are a frozen proposal profile, not production qualification:
`PASS` requires a profile with an exact server-owned qualification record, confirmed
metric scale, supported floor, exact proposal/source/target evidence and the selected
unambiguous candidate. It also requires at least one unique, measured region; each
region must have nonzero correspondences, at least 10% source/target coverage and
P95 residual at or below the profile limit. Qualification remains held-out-data work in S3. Independent
map requests also require server-resolved same-scene context from the exact assembly;
the boolean in a request is not authorization or proof by itself. The API must
authorize the actor/project, verify assembly ownership/checksum/bindings and resolve
source bytes before worker admission.

Implement: typed source/profile/request/proposal/QA contracts; exact package/map
mode bindings; preflight findings; checksum-sealed request/proposal/report; immutable
state transition guard. Reuse existing same-job `AlignmentRequest`/
`AlignmentRecord`; independent map source must be re-ingested into the target job
with original input lineage. No legacy alignment model or checksum is changed. No
solver, durable operation, API or UI is enabled in S1.

Tests: old REC-09 artifacts/checksums and focused alignment consumers; missing/invalid
units, formats and headers; input-role separation; cross-job/project bindings;
unknown scale; unsupported/uncertain floor; empty/over-budget cloud; stale scene
revision; qualification/evidence guards; and terminal/invalid state transitions.
**Exit:** [x] typed schema and state/binding rules exist; [x] supported input and
qualification limits are explicit; [ ] independent-map runtime is implemented or qualified.

## Sprint AUD-19.S2 — Trajectory prior hoặc BEV multi-candidate initialization

**Input:** verified geometry/floor/scale/ROI + optional trusted trajectory prior.
**Output:** ranked coarse transform candidates và degeneracy/search diagnostics.
**Contract:** paired trajectory evidence reused when applicable; observed cells khác
unobserved; no single forced solution for repetitive/symmetric geometry.

Implement: strengthen existing camera-center fit with bounded robust outlier/
rank checks and reported prior assumptions. For independent maps, construct
multi-height structural BEV from supported surface geometry, floor-normalize and
downsample with unit-aware resolution. Search yaw/translation coarse→fine; evaluate
top-K candidates, masked overlap and optional bounded RGB scale hypotheses.
FFT phase correlation có thể estimate translation at tested yaw; không assume
one FFT solves arbitrary rotation/partial overlap. Keep floor/coverage provenance;
Gaussian centers alone không là verified surfaces. Freeze seed/profile/search limits.
Tests: known yaw/translation, scale perturbation, partial overlap, repetitive racks,
180° symmetry, straight corridor, floor-only clouds, noisy/ghosted RGB and trajectory outliers.
**Exit:** [x] supported synthetic ground-truth candidate retained in bounded search;
[x] ambiguous/degenerate synthetic scenes do not receive a unique proposal. Real map
coverage, qualification and producer integration remain open for S3/S4.

## Sprint AUD-19.S3 — Constrained robust ICP và alignment qualification

**Input:** S2 coarse candidates + LiDAR map points already in meters + RGB collision
surface points/normals + frozen quality profile.
**Output:** refined proposals, per-region QA and measured supported failure envelope.
**Contract:** floor/scale constraints maintained; enough independent structure;
low residual alone không PASS, no universal cm/mm guarantee.

Implement: trimmed/robust multi-resolution point-to-plane refinement on supported
surfaces; correspondences bounded, normals validated, nonoverlap/outliers excluded
with recorded criteria. Parameterize yaw/x/y or bounded floor corrections; standard
6-DoF ICP không silently unlock fixed axes. Handle scale through S1 REC-06 path.
Evaluate overlap, retained structures, bidirectional/per-region residuals,
candidate score gap/observability; never use ground-truth labels in product solver.
Freeze thresholds on tuning split then qualify independent warehouse traversals/
registered maps with reference transforms where available and explicit no-reference metrics.
Tests: poor initialization/local wrong minima, sparse/thin obstacles, floor-only
point-to-plane ambiguity, density differences, drift/nonrigid mismatch, incorrect
scale, missing normals, held-out transform errors and false-auto-accept cases.
**Exit:** [ ] frozen acceptance and ambiguity rejection measured on held-out warehouse data;
[x] proposal confidence separated from absolute pose/geometry accuracy. Qualification remains
open because this checkout has summary benchmark JSONL and fixture PLYs, but no paired
held-out source/target maps with reference transforms. This is missing qualification
evidence, not a technology limitation.

## Sprint AUD-19.S4 — Durable operation, Studio confirmation và consumers

**Input:** qualified S1–S3 producer + current target refs/revision + authorized user.
**Output:** automatic registration command, overlay/QA UI, fallback và committed alignment.
**Contract:** automatic proposal không silently rewrite source/scene or grant release;
confirmation binds exact selected candidate/source/report; stale lease/revision rejects commit.

Implement: default action runs applicable trajectory/geometry path through admission,
lease/retry/cancel and artifact resolver. User inspects overlay/status; supported
proposal cần confirmation hiện có, ambiguous case offer more capture/ROI/landmarks.
Manual correspondence fit reuse similarity math, validate nondegenerate pairs and
rerun same QA; không force exactly three points or bypass evidence on manual choice.
Publish through alignment verifier with source/QA/confirmation identity; update bundle/
overlay/source selection using AUD-12.S1 contract. Stage scene publication qua CAS;
metric correction follows explicit new canonicalization/run, preserving prior outputs.
Tests: UI default/no-point happy path, ambiguous/manual fallback, permission/input
binding, two workers, duplicate confirm, change source/metric during run, cancel/restart,
stale polling/revision, aligned-cloud/SceneIR consumer and real browser/registered-map flow.
**Exit:** [ ] no manual landmarks on qualified automatic case; [ ] fallback/recovery verified;
[ ] exact source/report/transform survives consumer publication.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_contracts/test_rgb_lidar_registration.py tests/test_reconstruction/test_bev_registration.py tests/test_reconstruction/test_constrained_icp.py tests/test_reconstruction/test_rec06_lidar_metric.py tests/test_reconstruction/test_lidar_world_alignment.py tests/test_reconstruction/test_rec06_auto_scale.py tests/test_reconstruction/test_lidar_package.py tests/test_reconstruction/test_rec09_alignment.py tests/test_reconstruction/test_rec09_guards.py tests/test_reconstruction/test_rec10_bundle.py tests/test_reconstruction/test_lidar_overlay.py tests/test_reconstruction/test_finalize_lidar_binding.py -q
```

The synthetic BEV and constrained ICP solver tests are implemented. The planned
`tests/test_reconstruction/test_registration_qa.py` and operation/API/frontend tests
remain for S4.
DONE cần supported independent-map runs + held-out QA + browser/consumer evidence;
19 baseline tests hoặc synthetic transform recovery không thay real acceptance.
Collision/Isaac safety còn nghiệm thu qua AUD-12.S4/AUD-05; no registration-score safety claim.

## Result / Evidence

AUD-19.S1 delivered checksum-sealed Python contracts in
`src/models/contracts/rgb_lidar_registration.py`, exported through the shared
contracts package, with 29 new contract test cases. Source bindings preserve the four
input modes, exact package/assembly/file lineage, explicit units/frame/parsed header,
point limits and scene context. Requests/proposals/reports bind exact job, project,
source, target revision, profile, metric/floor evidence and selected candidate;
unknown scale can only propose under bounded search, and `PASS` requires a qualified
profile plus exact QA evidence. The old REC-09 alignment contract/service remains
unchanged.

Verification: `.venv/bin/ruff check src/ tests/` PASS; `.venv/bin/ruff format --check
src/ tests/` PASS (517 files); focused registration plus existing REC-06/08/09 tests
PASS (85 tests); `scripts/check_contract_mirror.py` PASS (5 enums, 5 models);
CodeGraph current (847 files, 16,607 nodes, 48,652 edges). These were local contract
and compatibility checks only at S1 delivery.

AUD-19.S2 now implements the bounded coarse-to-fine search slice in
`src/services/reconstruction/alignment/bev_search.py`: floor-normalized multi-height
BEV support, meter-aware cells, explicit source units/floor checksums, deterministic
sampling, FFT translation correlation at tested yaw hypotheses, bounded local yaw/
translation refinement, bounded scale search, top-K transform candidates, and
coverage/search diagnostics with explicit ambiguous or insufficient outcomes. The
profile checksum binds cell size, height bands, seed and refinement budgets. Empty
cells are treated as unknown; the target parameter is
limited to supported collision-surface points, not Gaussian centers. The existing
camera-center fit now uses deterministic bounded consensus with rank/outlier
diagnostics, and finalize evidence records its actual thresholds, seed, support,
rejections and prior assumptions.

Verification: focused registration/BEV/trajectory/finalize/REC-06/REC-09 tests PASS
(97 tests); cases cover known yaw/translation including a source map cropped at yaw
zero but supported after rotation, partial overlap with added RGB ghost points,
bounded scale, repeating/180-degree symmetry, a straight corridor, floor-only maps,
unit conversion and trajectory outliers beyond/within the bound. Profile checksum
tests bind BEV resolution/height/search seed/refinement budgets. These are synthetic algorithm tests.
The coarse solver still requires S3/S4 artifact loading, worker integration and
S4 artifact loading and worker integration; S2 synthetic results alone do not establish
held-out warehouse qualification, production accuracy, browser acceptance, or collision
safety.

AUD-19.S3 adds `src/services/reconstruction/alignment/constrained_icp.py`. It refines
bounded BEV candidates with deterministic multi-resolution point-to-plane ICP, a
Huber-weighted trimmed solve, bounded correspondence/step/iteration/point budgets and
floor-local yaw/x/y updates. It rejects invalid normals and insufficient Jacobian rank,
keeps ambiguous candidates unresolved, and reports bidirectional Euclidean p95/max,
point-to-plane p95, coverage, rejected support, convergence and up to four floor regions. RGB
scale candidates are applied about the verified floor origin; ICP does not estimate
scale. All ICP schedules and thresholds are included in the sealed profile checksum.
QA `PASS` requires a qualified profile, convergence, regional/global coverage, residual
limits and an unambiguous candidate decision. The default provisional profile can never PASS.

S3 synthetic coverage: 11 tests exercise yaw/translation recovery, a tilted floor with
fixed floor height and pitch/roll, floor-only unobservability, duplicate-density changes,
bounded scale and wrong-scale rejection, outlier residual accounting, ambiguous and
truncated candidate sets, sparse support, invalid normals and source-frame mismatch.
The complete focused verification command above PASSed (110 tests). Ruff check on the five
changed Python files, `.venv/bin/ruff format --check src/ tests/` (529 files), and
`.venv/bin/python -m scripts.check_contract_mirror` PASSed (5 enums, 6 models mirrored).
The repository-wide `.venv/bin/ruff check src/ tests/` is currently blocked by an unrelated
worktree edit in `src/services/reconstruction/adapters/colmap_runtime.py` (`I001` import order);
that file is outside S3 and remains unstaged.

The repository's `eval/results` JSONL files provide aggregate measurements, and the
tracked PLY artifacts are fixtures; neither provides a held-out registration point-cloud
pair with independent reference transforms. S3's real-data threshold freeze and
qualification exit therefore remain unchecked. No profile was promoted to qualified,
and synthetic recovery does not establish a supported warehouse failure envelope.

### AUD-19.S4 progress — source-bound QA report producer

`src/services/reconstruction/alignment/registration_qa.py` now builds and seals a
`RegistrationQAReport` from one exact request, proposal artifact reference, selected
ICP candidate, measured profile metrics, floor comparison and server-resolved
same-scene evidence. It rejects stale/mismatched candidate bindings, carries the exact
proposal/source/target/metric/floor/qualification refs, and validates the finished report
with `validate_registration_qa_binding`. A qualified profile is still insufficient by
itself: the caller must affirm that the server resolved and verified its exact
qualification record; this gate defaults closed. Missing same-scene, floor or
qualification evidence remains `INCONCLUSIVE`; measured threshold violations under a
qualified profile are `FAIL`.

`tests/test_reconstruction/test_registration_qa.py` covers provisional profiles,
untrusted client qualification claims, missing same-scene context, measured residual/
overlap failure, exact-evidence PASS construction and candidate-binding rejection.
Focused verification passed 50 tests across registration QA, registration contracts
and constrained ICP. At that commit, this was only the QA producer slice. Worker-integrated
admission/reservation and dispatch, source ingestion, API, Studio proposal/status/overlay,
confirmation CAS, consumer publication and browser/registered-map flow remained open. The
real held-out qualification evidence described above is also still missing; no live
alignment is enabled by this slice.

### AUD-19.S4a — Durable operation envelope and lease persistence

**Input:** checksum-sealed `RegistrationRequest` after a future API caller has
authorized the user, project, source assembly and expected target revision.
**Output:** idempotent durable queue record with claim, heartbeat and fenced producer
completion operations. This slice adds persistence only; it does not expose or run
registration in the product.
**Data contract:** schema v18 stores the immutable request payload, request checksum,
canonical operation checksum, requester/idempotency identity, target job, queue state
and lease/fencing columns. The store verifies payload checksum and duplicated row
columns, rejects key reuse with a different request checksum, and requires
proposal/report refs for proposed or ambiguous results. A worker lease expiry fails
that request; retry uses a new request ID because the registration state machine does
not permit silently requeueing the same request.
**Tests:** additive upgrade from v17 with old row preservation; idempotency replay
and conflict; two concurrent SQLite claimers; heartbeat, terminal output binding,
expired lease and stale-worker rejection; row/payload drift and cross-job output refs
are rejected. The new queue-specific concurrency and migration proof uses SQLite.
**Exit:** [x] migration and queue-state persistence are tested locally;
[ ] admission/resource reservations and worker dispatch;
[x] exact staged-source/header verification and job-lineage resolver delivered in S4b;
[ ] API authorization for actor/project/source assembly before worker dispatch;
[ ] API, confirmation CAS, artifact publication, consumers and Studio UI;
[ ] held-out registration qualification and real browser/registered-map acceptance.

#### AUD-19.S4a Result / Evidence

Commit base: `0da7b21`. Added `src/services/orchestration/jobs/registration_operations.py`
and additive RuntimeDatabase migration v18 in `src/services/orchestration/jobs/database.py`.
The store persists only checksum-verified requests, seals mutable state with a
canonical operation checksum, deduplicates by requester and idempotency key, claims
queued work transactionally, renews only the active lease, and rejects stale
completion by checksum, lease token and fencing generation. Proposal and QA
references are constrained to the target job. Migration tests now expect v18.

Verification: focused registration/migration suite — 61 passed; repository Ruff
check passed; Ruff format check passed for 545 Python files; `codegraph sync` reported
up to date; `graphify update .` rebuilt 20,802 nodes, 61,089 edges and 690 communities. Concurrency
evidence uses local SQLite. The operation store has test callers only; it is not
connected to API or worker dispatch. Admission, cancellation, server-side source
binding, artifact resolver verification at publication, scene CAS and Studio remain
open. No real registration accuracy, GPU, collision-safety or browser feature proof
is claimed.

Pre-flight (GUIDE.md Rule 13)
- codegraph: `RuntimeDatabase` migration, registration request/state transitions,
  import queue and input-run persistence patterns were explored before edits; the
  new operation store currently has test callers only.
- impact: schema version advances from 17 to 18; `RuntimeDatabase` applies the
  additive migration, and migration tests plus schema-version consumers were checked.
- understand: sealed request → durable queued record → fenced worker lease → terminal
  proposal state; understand-anything tool was unavailable, so task/architecture docs
  and executable CodeGraph call paths were used.
- minimal-code: reused `RuntimeDatabase`, `RuntimeTransaction.lock_suffix`, existing
  registration state transitions and checksum verification; `ValidationQueue` is
  tied to Isaac runs/configuration and is not interchangeable; no new dependency.
- checks: `ruff check src/ tests/` PASS; `ruff format --check src/ tests/` PASS
  (545 files); focused pytest PASS (61 tests).
- DevTools: n/a — no UI change. The existing authenticated QA route was inspected
  read-only; its sample job remains waiting for metric confirmation.

### AUD-19.S4b — Exact staged-source verification and job-lineage resolution

**Input:** sealed map-registration request, exact input assembly revision, selected
registered-map/static-cloud file, target job/project and worker workspace.
**Output:** ephemeral `VerifiedRegistrationSource` with a verified local PCD/PLY
path, source/header checksums, parsed format/count, declared units/frame and a
same-scene lineage flag.
**Data contract:** verify the request and immutable assembly checksums, role/file-ID
binding, server upload probe, exact whole-upload checksum, selected member checksum
for ZIP inputs, cloud-state/unit/frame declarations, parsed PCD/PLY header checksum,
format and point count against the sealed profile. ZIP members are copied to a
server-named worker path and checked against the staged member size/hash. Sensor
package and raw-scan modes stay on their existing/AUD-17 routes. `same_scene_lineage_verified`
is true only when the same declared assembly revision is the accepted target-job
run, its exact recipe selects both the requested LiDAR file/role and RGB video, and
the project still references that recipe. This verifies the stored evidence chain;
it cannot establish that two sensors actually viewed the same physical place.

`ProjectPersistence.input_run_for_job` reads the durable row and rejects drift in
duplicated requester/key/job/project/assembly/revision/report/recipe columns and
the exact recipe reference. The resolver only checks the PCD/PLY header at this
stage; complete point-payload validation, unit conversion, actor/project/source
authorization, resource admission, queue dispatch and API wiring remain worker/API
work in later S4 slices. It does not expose a user-facing command by itself.

**Tests:** direct PLY resolution (including a false lineage result without an
accepted job run); exact ZIP member extraction; forged-header rejection; positive
same-job RGB+LiDAR lineage; durable input-run row/payload drift.
The suite uses local artifact files and SQLite. It does not prove registered-map
accuracy, production storage, real-scene identity or collision safety.
**Exit:** [x] exact source assembly/bytes/header and stored job-recipe lineage are
resolved fail-closed; [ ] API authorizes target and source before enqueue; [ ] worker
validates full point payload, converts declared units and consumes the resolver.

#### AUD-19.S4b Result / Evidence

Added `src/services/orchestration/jobs/registration_sources.py` and the read-only
`ProjectPersistence.input_run_for_job` lookup. The resolver re-reads the exact
assembly, verifies its upload records and artifact bytes, checks selected role,
units/frame/cloud-state, and parses the supported scalar PCD/PLY header. For ZIPs
it materializes only the selected checksum-bound member under a generated worker
filename. Same-scene lineage requires an accepted recipe for the target job that
includes both exact RGB and LiDAR bindings; absent or separate lineage remains
unverified. The flag documents byte/recipe lineage only, not physical co-location.

Verification: focused source, operation, contract, assembly-resolution and input-run
integration suite — 59 passed; repository Ruff check passed; Ruff format check passed
(547 Python files); CodeGraph reported current; Graphify rebuilt 20,848 nodes,
61,352 edges and 704 communities. No schema migration or user-visible API/UI change
was needed. The resolver is not yet wired into queue dispatch. Full payload decoding,
unit conversion, authorization/admission, API/UI, real held-out qualification,
browser flow and consumer publication remain open.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored `RegistrationSourceBinding`, `InputAssemblyService`, staged
  upload probes, `ArtifactResolver`, `CloudHeader`, accepted input-run persistence,
  RGB recipe bindings and operation-store callers before edits; re-explored the new
  resolver and `input_run_for_job` after indexing.
- impact: no database migration; a new `ProjectPersistence` read path is exercised
  against the existing v18 schema. New source verification has tests but no API or
  worker callers yet.
- understand: request → exact assembly revision → role/file binding → source bytes
  and header → optional accepted RGB+LiDAR recipe lineage. Same-scene lineage does
  not prove physical scene identity; source declarations remain declarations.
- minimal-code: reused `InputAssemblyService.verify_upload_sources`, `ArtifactResolver`,
  `CloudHeader`, existing checksummed `InputRecipe` and the existing runtime DB;
  no new parser, dependency or queue.
- checks: focused pytest PASS (59 tests); `.venv/bin/ruff check src/ tests/` PASS;
  `.venv/bin/ruff format --check src/ tests/` PASS (547 files).
- DevTools: n/a — no UI/runtime behavior changed.

### AUD-19.S4c — Exact payload decode and metric XYZ normalization

**Input:** `VerifiedRegistrationSource` from S4b and the sealed registration
profile. **Output:** finite `(N, 3)` XYZ coordinates in canonical meters for the
source frame. **Data contract:** re-read only scalar PCD/PLY payloads already
accepted by `CloudHeader`; verify header checksum, full source checksum, format,
declared point count and profile point budget while decoding. Resolve XYZ by field
name, reject malformed/truncated/extra records and non-finite coordinates, then
convert declared `m`/`cm`/`mm` coordinates to meters. The source frame remains
attached to `VerifiedRegistrationSource`; this helper does not transform frames.
Odometry's PCD-only `load_xyz_points` behavior remains unchanged. PCD
`binary_compressed` and PLY list/mesh layouts remain outside the current accepted
file contract; the existing header gate rejects them before decoding.

**Tests:** PLY ASCII/little-endian/big-endian and PCD ASCII/uncompressed binary;
reordered XYZ fields and unit conversion; exact source/header checksum drift;
count and profile-budget mismatch; truncated/non-finite payloads; and source-byte
mutation between resolve and decode. Existing odometry and payload-guard tests must
continue to pass. This slice does not load target RGB geometry, run BEV/ICP, dispatch
workers or expose an API.
**Exit:** [x] the worker-facing source loader returns only exact, finite XYZ meters
under the sealed point budget; [x] target geometry and floor evidence are resolved;
[ ] proposal/QA producer and durable worker dispatch are connected.

#### AUD-19.S4c Result / Evidence

`load_registration_source_points` now delegates to the existing bounded PCD/PLY
record decoder, rechecks header and complete-file checksums while consuming payload,
binds the observed format/count to S4b metadata, enforces `profile.max_source_points`,
and converts the declared unit to meters. The existing odometry loader still accepts
only PCD and keeps its prior 5M-point default.

Verification: focused source, registration, payload-guard, odometry, assembly and
integration suite — 106 passed, 1 skipped (the isolated KISS-ICP known-motion test
requires `REC17_LIDAR_ODOMETRY_PYTHON`, which was not set); repository Ruff check
passed; Ruff format check passed (548 Python files); CodeGraph is current; Graphify
rebuilt 20,870 nodes, 61,451 edges and 689 communities. No API, worker queue, GPU
solver, target geometry loader or UI behavior changed in this slice.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored `CloudHeader`/`read_header`, `_ascii_records`, `_binary_records`,
  `inspect_point_cloud`, `load_xyz_points`, the four odometry callers, and S4b's
  `VerifiedRegistrationSource` before editing; re-explored the new source loader.
- impact: four existing odometry callers retain the PCD-only function and behavior;
  registration uses a new checked loader with focused tests. No schema migration.
- understand: AUD-19 S4 input contract plus CodeGraph's payload/odometry call graph;
  understand-anything is not installed in this environment.
- minimal-code: reused the existing strict header and streaming record decoders;
  preserved the existing odometry contract; added no dependency or native parser.
- checks: focused pytest PASS (106 passed, 1 skipped: KISS-ICP known-motion test
  requires `REC17_LIDAR_ODOMETRY_PYTHON`); `.venv/bin/ruff check src/ tests/` PASS;
  `.venv/bin/ruff format --check src/ tests/` PASS (548 files).
- DevTools: n/a — no UI/runtime behavior changed.

### AUD-19.S4d — Canonical target geometry and measured floor resolution

**Input:** sealed registered-map/static-cloud request, exact same-job `RgbGeometry`
and one `FloorFitEvidence` ref, profile, and a worker-supplied maximum GLB byte size.
**Output:** checksum-verified collision-surface samples/normals in canonical world
meters and the matching measured target floor plane.
**Data contract:** recheck the request/profile checksums and target ref type, stage,
job and URI. Accept only independent-map modes. Resolve exact GLB and floor bytes
through `ArtifactResolver`; reject meshes above the worker byte cap or sealed point
budget. The strict collision GLB parser supplies canonical mesh triangles. Sample
triangle centroids deterministically from the sealed seed, capped by
`max_points_per_map`, and derive a unit face normal for each sample. `FloorFitEvidence`
is the published artifact envelope; its `FloorModel` is embedded rather than stored
as a standalone artifact. Accept evidence only when its exact source ref matches
the target `RgbGeometry`, its metric-confirmation ref, or its Gaussian master ref
from that geometry's provenance. Bind the floor normal, offset and confirmed up
direction only from exactly one embedded `FloorModel` whose status is `supported`;
uncertain and prior-fallback models, unbound evidence, and ambiguous refs remain
unresolved. This adapter does not infer source-map floor or prove that two sensors
observed the same physical space.

**Tests:** both independent-map modes and each supported floor-evidence source;
exact surface coordinates and normalized normals; seeded sample stability and
profile cap; missing/ambiguous/non-measured floor; malformed and over-budget mesh;
worker byte cap; exact geometry/floor checksum rejection; and rejection of floor
evidence bound to another same-job artifact. No worker/API/Studio integration is
included.
**Exit:** [x] the target loader returns exact canonical surface/floor evidence or
fails closed; [ ] source-map floor estimation from gravity/reference evidence,
proposal/QA execution and durable worker dispatch are connected.

#### AUD-19.S4d Result / Evidence

Added `RegistrationTargetResolver` and `VerifiedRegistrationTarget` in
`src/services/orchestration/jobs/registration_targets.py`. It accepts only registered
maps and static clouds, rechecks the sealed request/profile and exact same-job
geometry/floor references, uses the strict collision GLB reader, and requires a
caller-provided worker byte limit. It samples triangle centroids deterministically
under `max_points_per_map`, derives normalized face normals, and constructs the
world-frame floor plane from the `FloorModel` embedded in one checksum-bound
`FloorFitEvidence` artifact. The evidence must bind to the geometry or its exact
metric-confirmation/Gaussian-master lineage. It rejects uncertain or prior-fallback
floor models and does not choose among multiple floor refs. The schema-1.0 field
`floor_model_refs` is retained on the wire, while new map preflight requires a
`FloorFitEvidence` artifact there and stops legacy bare `FloorModel` refs before
worker admission. There are no production callers yet; API authorization,
target-revision CAS, source floor fitting, proposal/QA production and durable worker
dispatch remain open.

Verification: focused registration, source, target, GLB, BEV, ICP, QA, contract,
floor-evidence and durable-operation suite passed (104 tests); target-resolver tests
passed separately after import formatting (17 tests). `.venv/bin/ruff check src/ tests/`
passed; `.venv/bin/ruff format --check src/ tests/` passed (550 Python files);
`git diff --check` passed. CodeGraph sync reported up to date and the final resolver/
preflight call graph was explored. `graphify update .` rebuilt 20,919 nodes,
61,720 edges and 728 communities. These are local artifact and synthetic mesh tests;
no real map accuracy, worker resource behavior, browser flow or collision safety is
claimed.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored `RegistrationRequest`, `FloorModel`, `ArtifactResolver`,
  `read_collision_glb` and its callers, BEV target-point/floor contracts, and the
  existing registration source resolver before edits; re-explored the new resolver.
- impact: no production caller yet; the resolver is exercised by its focused tests.
  Existing GLB parser callers and their contracts are unchanged.
- understand: S4 input-binding flow plus the actual producer contract:
  `FloorFitEvidence` embeds `FloorModel` and binds it to an exact source ref;
  understand-anything is not installed in this environment.
- minimal-code: reused `ArtifactResolver.require_uri`, `read_collision_glb`,
  `FloorFitEvidence`, `FloorModel` and `RegistrationFloorPlane`; added no dependency
  or parser format.
- checks: focused pytest PASS (104 tests; 17 target-resolver tests after the
  import-only lint fix); `.venv/bin/ruff check src/ tests/` PASS;
  `.venv/bin/ruff format --check src/ tests/` PASS (550 files);
  `git diff --check` PASS.
- DevTools: n/a — no UI/runtime behavior changed.

### AUD-19.S4e — Bounded source-plane hypotheses without guessing the floor

**Input:** exact decoded source-map points in meters, exact source checksum, declared
non-world source frame and a bounded hypothesis profile.
**Output:** deterministic report of zero or more checksum-bound, unoriented plane
hypotheses with support, residual and two-dimensional span evidence.
**Data contract:** `status="hypotheses"` means only that broad planes were found;
`reason="orientation_unclassified"` remains set even when there is exactly one
candidate. Results contain no `is_floor`, `up_direction`, selected-candidate or PASS
field and cannot be passed as `RegistrationFloorPlane`. The report binds source and
profile checksums but does not independently re-read source bytes. Sampling is capped
at 50,000 points, RANSAC at 256 iterations per hypothesis, and output at eight
hypotheses. The support ratio, residuals and projected spans are descriptive
measurements; they are not floor probability or registration qualification.

Implement: deterministically sample oversized clouds; fit and refine separated planes
with seeded RANSAC/PCA; reject narrow or under-supported planes; order retained
hypotheses by measured support and span. Invalid coordinates, missing source identity,
world-frame input, and maps without supported planes return explicit `insufficient`
reasons. Do not classify a largest/dominant plane as floor and do not connect this
diagnostic result to BEV/ICP, target publication, API, worker or collision consumers.
The next producer slice must either receive a verified up/gravity prior or score
multiple orientation hypotheses under held-out registration QA while preserving
ambiguity.

**Tests:** two broad orthogonal planes plus outliers are both surfaced; a single
horizontal plane remains unclassified; random volumetric points return insufficient;
point capping and evidence are deterministic/checksum-bound; malformed, non-finite,
world-frame and invalid-checksum inputs fail closed.
**Exit:** [x] bounded, deterministic diagnostic algorithm and explicit unknown-axis
behavior are tested; [ ] source-floor selection, BEV/ICP execution and held-out QA
remain separate, unqualified work.

#### AUD-19.S4e Result / Evidence

Added `src/services/reconstruction/alignment/source_planes.py` with a fixed bounded
profile and a pure diagnostic producer. It returns checksum-bound plane geometry,
support counts/ratios, residuals and projected spans. Even a single supported plane
stays `orientation_unclassified`; the result has no floor or up-axis field and has no
production caller. Invalid input and point-budget sampling remain explicit and
deterministic. No scene, alignment or collision artifact is produced.

Verification: the focused hypothesis suite passed (5 tests); BEV, constrained ICP,
registration source and target regressions passed with it (48 tests total). Full
`.venv/bin/ruff check src/ tests/` passed; `.venv/bin/ruff format --check src/
tests/` reported 554 files formatted; `git diff --check` passed. CodeGraph reports
892 files, 17,821 nodes and 52,787 edges, and its exploration shows the new producer
has test callers only. `graphify update .` rebuilt 20,995 nodes, 61,995 edges and
702 communities. Real source-map floor identity, gravity metadata, BEV/ICP
integration, held-out qualification, worker/API/browser behavior and safety remain
**UNVERIFIED**.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored the registration input binding, verified source loader,
  measured target-floor resolver, floor-fit prior and BEV floor contract. The source
  map contract has units/frame but no up/gravity declaration; BEV requires a separate
  measured floor/up direction.
- impact: the new function currently has test callers only. It does not alter source
  bindings, request/profile checksums, existing trajectory alignment, scene revisions
  or any production consumer.
- understand: independent-map source points are verified and converted to meters;
  target floor evidence is measured. Source orientation is missing, so hypotheses
  cannot be promoted into the existing `RegistrationFloorPlane` contract.
- minimal-code: added one bounded pure-NumPy diagnostic module and focused tests; no
  dependency, schema migration, persistence, worker, API or UI changes.
- checks: 48 focused registration tests passed; full repository Ruff check/format
  passed; `git diff --check` passed. CodeGraph and Graphify indexes were refreshed.
- DevTools: n/a — no UI/runtime behavior changed.

### AUD-19.S4f — Cancellation persistence and shared admission identity

**Input:** a sealed registration operation in `QUEUED` or `RUNNING` state and the
existing shared `OperationAdmissionRequest` contract.
**Output:** an idempotent queued cancellation or a durable running cancellation
request that the future worker can observe without losing its lease.
**Contract:** queued cancellation becomes terminal and cannot be claimed. Running
cancellation only records intent; the lease remains owned until a worker acknowledges
termination. Once intent is stored, the worker cannot finish with a proposal or QA
output. A failed shutdown remains `FAILED` with an error, not a false successful
cancellation. The `rgb_lidar_register` admission kind binds to a job and uses the
existing shared reservation primitive. No SQL migration is needed.

Implement: add the registration operation kind to `OperationKind`; add a locked,
idempotent `cancel` transition to `RegistrationOperationStore`; expose the flag in
the persisted record/checksum for later worker polling; retain schema-1.0 payload
checksum compatibility by omitting only the false/default value from the checksum.
Do not release a reservation or claim a child process has stopped in this store-only
slice. API authorization, admission execution, process kill/reap, retry, status API,
confirmation, SceneHead publication and UI stay in later dependent work.

Tests: old payload without the new field; tampered cancellation identity; queued
cancel/claim race; duplicate cancellation; running cancellation observed by heartbeat;
proposal fencing until the worker acknowledges `CANCELLED`; expired unacknowledged
cancellation ending `FAILED`; and CPU-only registration admission with a job parent.
**Exit:** [x] queue state and cancellation intent are checksum-bound and race-safe;
[x] shared admission accepts registration identity; [ ] registration API/worker and
process lifecycle are connected.

#### AUD-19.S4f Result / Evidence

- Source baseline: `25d13ff` (`AUD-03/AUD-04/AUD-12`). The owner-authored
  `AUD-18.S1` commit `58513c6` landed during this work and remains untouched; it is
  the parent of the S4f commit. CodeGraph traced `RegistrationOperationStore`,
  `RegistrationOperationRecord`, lease/finish paths, `OperationAdmissionRequest`,
  `OperationKind`, and focused test helpers. The registration store has no production
  API/worker caller yet.
- Behavior before/after: queued operations had no cancellation API at the store
  boundary, and a running record could not durably expose cancellation intent. The
  store now atomically cancels queued work, preserves a running lease while marking
  cancellation requested, returns that flag through reads/heartbeats, and rejects
  proposal/QA completion after a cancellation request. Worker acknowledgement remains
  the only path to `CANCELLED`; expired unacknowledged cancellation remains `FAILED`.
- Compatibility/resource contract: additive payload field only; no SQL migration.
  False/default is excluded from the logical checksum so schema-1.0 payloads retain
  their existing identity; true cancellation is checksum-bound. The shared admission
  model accepts `rgb_lidar_register` with a job parent and the existing CPU-only
  resource profile. This sprint does not call admission from a worker, release a
  reservation, kill/reap a process, or expose an API/UI.
- Changed files: `registration_operations.py`, `admission.py`, their two focused test
  files, and this task/plan record.
- Verification: **60 passed** across registration-operation persistence and shared
  resource-admission tests. `.venv/bin/ruff check src/ tests/` passed;
  `.venv/bin/ruff format --check src/ tests/` reported 566 files formatted;
  `git diff --check` passed. CodeGraph is current at 904 files, 18,204 nodes and
  54,159 edges. Graphify rebuilt 21,282 nodes, 63,285 edges and 740 communities.
- Limitations: SQLite exercised the durable queue; PostgreSQL locking, a real worker,
  process cancellation, resource release, API authorization, browser behavior,
  held-out map qualification and Isaac/collision safety remain **UNVERIFIED**.
- Next: a worker slice must wire exact source/target resolution and bounded
  orientation hypotheses through BEV/ICP/QA, honor
  cancellation before publishing, and release reservations only after in-process
  work has stopped. It must not enable production `PASS` until held-out S3
  qualification exists.

Pre-flight (GUIDE.md Rule 13)
- codegraph: before-edit exploration read `RegistrationOperationStore`, its
  lease/finish callers, `OperationAdmissionRequest`, `OperationKind`, and focused test
  helpers; post-edit exploration confirmed the new cancellation method is test-covered
  and not connected to a production worker/API.
- impact: new store method has no production callers yet; registration kind adds one
  accepted literal while existing admission consumers/tests retain their behavior.
- understand: current registration operation persistence is not connected to an
  API/worker. `understand-anything` is unavailable in this environment; source and
  task flow were traced directly with CodeGraph.
- minimal-code: reused existing transitions, row lock suffix, lease/fencing rules,
  checksum utility and shared operation admission; no schema migration or scheduler.
- checks: 60 focused tests passed; full-repository Ruff check and format passed;
  `git diff --check` passed. CodeGraph sync and Graphify update passed.
- DevTools: n/a — no rendered screen or exposed runtime path changed in S4f.

### AUD-19.S4g — Durable resource wait and claim resumption

**Input:** a `RUNNING` registration operation with a current lease when shared
resource admission cannot yet reserve the requested resources.
**Output:** either a checksum-bound `WAITING_RESOURCES` record with a bounded reason
and no worker lease, or `CANCELLED` when cancellation intent won before requeue.
**Contract:** waiting work relinquishes its lease and reservation owner can return to
the worker loop. `claim_next` may claim `QUEUED` or `WAITING_RESOURCES`, then issues a
new lease token and fencing generation. Cancellation of queued/waiting work is
terminal and immediate. A running cancel racing a resource wait is acknowledged
atomically by the wait operation. `attempt` counts claimed leases, including claims
that return to resource wait; it is not an execution count. Additive default payload
fields are omitted from the logical checksum when absent/default, preserving v18 and
schema-1.0 records; no SQL migration is required.

Implement: add `WAITING_RESOURCES` to the registration state machine; persist a
500-character maximum `resource_wait_reason`; add a lease/fencing checked
`wait_for_resources` transition; clear lease, heartbeat, wait reason and error at the
appropriate terminal/reclaim boundaries; allow fresh claims from resource wait.
Do not add resource measurements, start solver work, release reservations, dispatch
workers or alter API/UI in this slice.

Tests: state transition validity; legacy payload checksum with both additive fields
absent; wait reason required only in the waiting state and checksum-bound; stale
worker cannot publish after requeue; a new worker receives a fresh token/generation;
waiting work can be cancelled without claim; running cancellation observed during
requeue ends `CANCELLED`; and terminal/cancelled rows are never reclaimed.
**Exit:** [x] resource waits release the lease durably and can resume with new fencing;
[x] cancellation remains fail-closed across the wait boundary; [ ] worker/admission
execution and resource release are connected.

#### AUD-19.S4g Result / Evidence

- Behavior before/after: registration operations could be queued, claimed or
  completed, but had no durable resource-wait state. They can now relinquish a live
  lease when admission waits, retain a sealed wait reason, and resume with a new
  lease/fencing pair. A cancellation that wins before requeue becomes terminal
  `CANCELLED`; cancelled/waiting work cannot be claimed accidentally.
- Compatibility/state contract: the existing SQLite/PostgreSQL schema remains v18;
  only operation payload/state changes. `resource_wait_reason` and the existing
  cancellation flag default are omitted from the canonical checksum when absent or
  default, preserving the previous schema-1.0 payload checksum. The attempt field
  remains a claim counter; this store does not count actual solver executions.
- Changed files: `rgb_lidar_registration.py`, `registration_operations.py`, their
  focused contract/store tests, the audit README, AGENT_GUIDE, INTEGRATION_MAP and
  this task record.
- Verification: **101 passed** across state-machine, registration-operation and shared
  admission tests. `.venv/bin/ruff check src/ tests/` passed;
  `.venv/bin/ruff format --check src/ tests/` reported 566 files formatted;
  `scripts.check_contract_mirror` passed (5 enums, 6 models); `git diff --check`
  passed. CodeGraph is current at 904 files, 18,214 nodes and 54,229 edges.
  Graphify updated to 21,295 nodes, 63,346 edges and 734 communities.
- Limitations: no production worker or admission caller exists yet. PostgreSQL
  concurrency, process cancellation, reservation release, API/browser behavior,
  held-out map qualification and Isaac/collision safety remain **UNVERIFIED**.
- Next: a worker integration slice must claim, resolve exact source/target bytes,
  construct a conservative resource profile, and invoke BEV/ICP/QA only with a
  bounded cancellation contract. Unknown source orientation remains multi-hypothesis
  and ambiguous; no production `PASS` without held-out qualification.

Pre-flight (GUIDE.md Rule 13)
- codegraph: traced `RegistrationOperationState`, transition validation, store claim/
  cancel/heartbeat/finish, shared `ResourceAdmission` wait behavior, and operation
  store tests before editing.
- impact: no schema migration, API, worker or UI path; the state literal and store
  methods are local until later dispatch wiring. Existing registration terminal
  results remain unchanged.
- understand: waiting releases its lease so workers do not hold ownership while
  blocked on shared admission; a later claim is fenced with a new token/generation.
- minimal-code: reused the existing transaction lock, lease verifier, checksum and
  transition helper; no scheduler, retry policy or resource estimator was added.
- checks: focused pytest PASS (101 tests); `.venv/bin/ruff check src/ tests/` PASS;
  `.venv/bin/ruff format --check src/ tests/` PASS (566 files);
  `.venv/bin/python -m scripts.check_contract_mirror` PASS (5 enums, 6 models);
  `git diff --check` PASS. CodeGraph is current (904 files, 18,214 nodes,
  54,229 edges); Graphify update completed (21,295 nodes, 63,346 edges,
  734 communities).
- DevTools: n/a — no rendered screen or exposed runtime path changed in S4g.

### AUD-19.S4h — Bounded registration worker integration

**Input:** a durable `QUEUED` or `WAITING_RESOURCES` registration operation, its
checksum-sealed request and profile, the accepted RGB+LiDAR input assembly, and the
exact canonical RGB collision geometry for the requested target revision.

**Output:** an exact byte copy of the selected PCD/PLY in the target job, a manifest
binding its source checksum, header, point count, unit, frame and assembly lineage,
source-plane hypotheses, worker diagnostics, a bounded registration proposal and an
INCONCLUSIVE QA report. The operation finishes with proposal and QA refs only after
all artifacts are published and the lease/fencing token still owns the operation.

**Contract:** the worker handles `REGISTERED_MAP` and `STATIC_CLOUD`; the existing
sensor-package path remains in `FinalizeWorker`. It does not assert a canonical up
axis for uploaded map bytes. For each bounded plane hypothesis it evaluates both
normal signs, then runs floor-constrained BEV and ICP with per-hypothesis time and
candidate caps. Plane discovery is bounded by the profile's refinement budget. Before
search, the worker returns `INSUFFICIENT` if the two-sign count exceeds that cap or if
the sealed runtime budget cannot allocate at least one second each to BEV and ICP for
every sign. Shared CPU admission uses
point-count and target-size estimates; unmeasured RAM/disk requirements wait instead
of starting work. A resource wait relinquishes the claim and yields to the worker's
poll delay. Claims order eligible work by last update so a repeatedly waiting
operation does not monopolize the registration queue. Lease heartbeat loss,
cancellation or reservation loss sets a cancellation event passed through BEV and
ICP. Exact target revision is rechecked before operation completion. No scene
geometry or alignment record is mutated.

Same-scene lineage means the checksum-verified accepted recipe includes the selected
LiDAR source and RGB video under the user's same-scene declaration. It does not prove
that both recordings depict the same physical place. The worker therefore refuses to
solve when accepted lineage is missing, but it never returns QA `PASS`: no held-out
qualification record is loaded by this worker. Point-cloud decoding and one FFT call
are not interruptible internally, so cancellation and deadlines are checked between
library calls, bounded solver loops and pipeline phases.

**Tests:** exact byte-copy checksum/idempotency; resource estimate and durable wait;
both up signs per plane and ambiguity preservation; cancellation before BEV/ICP work;
worker deadline forwarding and solver budget enforcement; ICP candidate cap;
resource-wait polling and queue fairness; proposal/source-manifest contracts. Also
run source/target resolver, registration operation, admission, QA, collision and
geometry regressions.

**Exit:** worker dispatches durable registration operations in the existing worker
loop; source and target are checksum-resolved; admission wait persists and releases
the claim; solver work is bounded/cancellable at loop boundaries; outputs remain
provisional and cannot enable canonical geometry or collision consumption.

**Open:** no API/UI operation producer or user confirmation route is wired; no
held-out qualification, physical same-scene verification, browser acceptance or
Isaac/collision proof exists. Source floor still has multiple geometric hypotheses
without gravity/up evidence.

#### AUD-19.S4h Result / Evidence

- Commit base: `2b7632d`; this sprint's worktree changes are based on that revision.
- Behavior: the worker now claims registration operations in the existing worker
  loop, verifies and copies the exact point-cloud bytes, resolves the target
  collision surface, runs bounded plane-sign/BEV/ICP hypotheses, and publishes a
  provisional proposal with INCONCLUSIVE QA. Resource waits release the lease and
  return control to the worker poll loop. Updated-at ordering prevents a requeued
  wait from blocking other registration requests.
- Compatibility: the sensor-package `FinalizeWorker` path is unchanged. The copied
  cloud manifest records unit/frame/assembly lineage without asserting world up.
  No job scene, canonical geometry or collision selection is modified.
- Contract delta: `RegistrationSourceCloudManifest` binds the point-cloud byte hash,
  header, unit, frame and accepted assembly lineage. A proposal's
  `proposal_checksum` remains its canonical logical identity; each artifact
  reference's `artifact_checksum` now hashes the exact pretty-printed JSON bytes.
  The shared artifact serializer is used by model publication, and QA binding
  verifies the byte checksum independently of the logical checksum.
- Artifact/consumer proof: a worker publication regression test publishes a sealed
  proposal through `FilesystemArtifactStore`, then reads it back and verifies the
  reference hash against the file bytes. The durable operation worker is wired into
  `worker_cli`; a full production registration/Studio confirmation flow is not yet
  connected.
- Changed files:
  `docs/plans/active/2026-10-07-codegraph-audit/AGENT_GUIDE.md`,
  `docs/plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md`,
  `docs/plans/active/2026-10-07-codegraph-audit/README.md`,
  `docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-19-automatic-rgb-lidar-registration.md`,
  `src/models/contracts/__init__.py`, `src/models/contracts/identity.py`,
  `src/models/contracts/rgb_lidar_registration.py`,
  `src/services/orchestration/artifacts/store.py`,
  `src/services/orchestration/jobs/registration_operations.py`,
  `src/services/orchestration/jobs/registration_worker.py`,
  `src/services/orchestration/jobs/worker_cli.py`,
  `src/services/reconstruction/alignment/bev_search.py`,
  `src/services/reconstruction/alignment/constrained_icp.py`,
  `src/services/reconstruction/alignment/registration_qa.py`,
  `tests/test_contracts/test_rgb_lidar_registration.py`,
  `tests/test_orchestration/test_registration_operations.py`,
  `tests/test_orchestration/test_registration_worker.py`,
  `tests/test_reconstruction/test_bev_registration.py`,
  `tests/test_reconstruction/test_constrained_icp.py`, and
  `tests/test_reconstruction/test_registration_qa.py`.
- Verification: 173 tests passed across registration operations, worker, source and
  target resolvers, shared admission, BEV, ICP, QA, collision and registration
  contracts. `.venv/bin/ruff check src/ tests/` passed; `.venv/bin/ruff format
  --check src/ tests/` reported 570 files formatted; the contract mirror passed
  (5 enums, 6 models); `git diff --check` passed. CodeGraph and Graphify are synced.
- Limits: no API/UI producer or confirmation route invokes this worker yet; source
  lineage does not prove physical same-scene capture; no held-out qualification is
  loaded, so QA cannot return `PASS`; resource profiles without sufficient measured
  RAM/disk wait safely. A running FFT or point-cloud decode cannot be interrupted
  inside the library call.
- Next: wire an authorized API producer and Studio proposal/status/overlay plus
  confirmation CAS, then verify exact source/report/transform publication in the
  alignment consumer. Keep manual fallback and held-out qualification as separate
  gates; no confirmed transform may silently rewrite canonical geometry.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored `RegistrationOperationWorker`, worker CLI dispatch,
  `RegistrationOperationStore.claim_next`, source/target resolvers, resource
  admission, BEV/ICP solvers, contracts and their focused callers/tests before edits.
- impact: worker dispatch is in `worker_cli.main`; registration solvers have the new
  worker as caller; claim order affects registration operations only. Existing
  sensor-package finalize and scene consumers are unchanged.
- understand: accepted recipe lineage proves the user's declared RGB+LiDAR input
  relationship, not that both capture the same physical place.
- minimal-code: reused existing durable store, fencing, `ResourceAdmission`,
  `ArtifactResolver`, streaming publication, checksum, source/target resolvers and
  BEV/ICP functions; only worker integration, queue fairness and bounded controls
  were added.
- checks: focused pytest 173 passed; full repo Ruff check/format passed; contract
  mirror and `git diff --check` passed; CodeGraph sync/status and Graphify update/query
  completed.
- DevTools: n/a — UI-free worker and solver changes; no rendered screen changed.

### AUD-19.S4i — Authorized operation API

**Input:** authenticated contributor, exact checksum-sealed `RegistrationRequest`,
job path, required `Idempotency-Key`, and a database-backed registry with a
committed target scene revision.
**Output:** HTTP 202 with a durable operation ID; job-bound status and cancellation
routes for the shared registration worker.
**Data contract:** the API binds the path job, request job/project, requester identity
and current scene revision before enqueue. Only `REGISTERED_MAP` and `STATIC_CLOUD`
are accepted by the currently integrated worker, and `registration_preflight` must
be `READY`. The required key is 1–128 characters and replay returns the same exact
operation; reusing it with another sealed request is 409. Guest mutation uses the
existing own-job rule; Editor/Reviewer cross-owner mutation keeps the existing audit
event. The public response contains state, attempt, timestamps and exact proposal/QA
refs, but excludes the request body, idempotency key, lease identity and raw worker
error. Missing durable persistence is 503; stale project/revision is 409; invalid
mode or insufficient preflight is 422. Enqueue does not alter SceneIR, metric state
or collision consumers. Creating an operation requires an authenticated actor so
the durable requester foreign key cannot be spoofed or left unattributed.
**Tests:** authenticated guest owner, guest cross-owner rejection, Editor/Reviewer
intervention audit, unauthenticated rejection, request/requester/project/revision
binding, insufficient preflight, rejection of `SENSOR_PACKAGE` from the independent-map
worker, idempotent replay and key conflict, safe status projection, job-path binding,
queued cancellation/idempotent cancel and no-database failure.
**Exit:** [x] durable API producer/status/cancel and authorization slice implemented;
[ ] Studio status/proposal/overlay and confirmation CAS; [ ] exact alignment consumer
publication; [ ] held-out map qualification and real browser/registered-map acceptance.

#### AUD-19.S4i Result / Evidence

Commit base: `ef9b081` (current branch tip when S4i started). Added
`src/api/product/registration.py` and registered it in the product router. Authenticated
contributors can enqueue a sealed request with a required idempotency key, read a
job-bound operation projection, or cancel queued/running work. The API checks guest
ownership, preserves Editor/Reviewer intervention audit, binds requester/project/job/
scene revision, rejects unsupported worker modes and insufficient preflight, and
requires persistent operation storage. Status responses omit the request, idempotency
key, lease, worker identity and raw error. The scene and alignment consumers remain
unchanged.

Changed files: `src/api/product/registration.py`,
`src/api/product/__init__.py`, `tests/test_api/test_registration_routes.py`,
`docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-19-automatic-rgb-lidar-registration.md`,
`docs/plans/active/2026-10-07-codegraph-audit/README.md`,
`docs/plans/active/2026-10-07-codegraph-audit/AGENT_GUIDE.md`, and
`docs/plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md`.

Verification: new route suite **13 passed**; full `tests/test_api` **206 passed,
15 existing httpx cookie deprecation warnings**; registration operation/worker/source/
target/QA suites **61 passed**. `.venv/bin/ruff check src/ tests/` passed;
`.venv/bin/ruff format --check src/ tests/` reported 572 files already formatted;
contract mirror passed (5 enums, 6 models); `git diff --check` passed. `codegraph sync`
reported up to date (910 files, 18,471 nodes, 55,171 edges); `graphify update .`
completed with 21,456 nodes, 64,259 edges and 715 communities. Graphify notes that
saved community labels need refresh after reorganization; this does not affect the
updated graph data. No browser gate applies because this sprint adds only backend routes.

Limits: the Studio client does not yet create requests or display proposal/QA overlays;
confirmation CAS and exact alignment-consumer publication remain for later S4 slices.
Held-out registration qualification and real browser/registered-map acceptance remain
open. API acceptance plus the worker's local tests do not establish end-to-end warehouse
registration accuracy or collision safety.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored product-router inclusion, mutation authorization, worker-supported
  input modes, durable operation store, scene revision access and API test patterns.
- impact: `registration` is added to the product router; the route reuses
  `authorize_job_mutation` and the existing `RegistrationOperationStore`; the worker
  continues to consume its shared database queue. No AUD-18 files or behavior changed.
- minimal-code: uses existing request checksum/preflight, job ownership guard, scene
  head, operation store and worker dispatch; introduces only a bounded HTTP DTO and
  route module. It does not change SceneIR or canonical alignment.
- checks: focused API 13 passed; full API 206 passed; registration operation/worker/
  source/target/QA tests 61 passed; full repository Ruff and format checks passed;
  contract mirror and `git diff --check` passed.
- DevTools: n/a — backend-only routes; no rendered screen changed.

### AUD-19.S4j — Server-owned request preparation from accepted map recipes

**Input:** an authenticated actor, target job and expected current scene revision;
the durable accepted `InputRunRecord`/`InputRecipe`, exact immutable assembly
revision and source bytes; current `SceneIR` and its product-visible artifacts.
The client does not submit checksum, header, same-scene, target-ref, or metric/floor
claims as preparation facts.
**Output:** a checksum-sealed `RegistrationRequest` and `RegistrationPreflight`
projection for the existing S4i enqueue endpoint. Preparation queues no work and
publishes or mutates no artifact.
**Data contract:** only an accepted R2 registered-map or R3 single-static-cloud
recipe with one exact supported PCD/PLY binding is eligible. The service derives
mode, source role, unit, source frame, assembly identity and same-scene declaration
from that immutable recipe/assembly; it re-verifies upload bytes and parses the actual
header/count. The target is the current scene's canonical RGB geometry, its exact
metric provenance and the current `floor_fit.artifact_ref`. A deterministic world
ROI is derived from the checksum-verified collision GLB bounds, subject to the
server-owned provisional profile's byte and extent limits. The request binds the
expected scene revision. Sensor-package work remains on FinalizeWorker; raw sequences
remain AUD-17; a separate new upload and cross-scene physical identity remain outside
this slice and do not become verified by the input's same-scene declaration.
**Implement:** add a shared source-inspection seam used by both request preparation
and worker resolution, so preparation cannot compute different source identity from
the worker. Add a server-owned provisional profile/default; expose an authenticated,
guest-own-job guarded preparation route with safe status/error projection. Missing,
stale, ambiguous, unsupported or oversized evidence must return a precise 4xx and no
request; preflight INSUFFICIENT may be returned as an explicit finding set, never as
READY. The request is checked again by the existing worker at execution time. No
quota, persistence schema or scene-consumer change.
**Tests:** accepted R2/R3 recipe builds the exact binding; changed upload/header,
assembly/recipe checksum drift, wrong source role, missing units/frame, false/missing
same-scene declaration, raw/sensor mode, wrong/stale scene revision, wrong geometry
or floor lineage, absent/ambiguous floor, invalid bounds, byte/ROI limits, and guest
cross-owner denial all fail closed. Assert preparation has no operation/quota/artifact
side effect and that returned requests pass the existing contract checksum verifier.
**Exit:** [x] prepared requests are built from one accepted R2/R3 lineage and are
worker-revalidated; [x] negative/authorization tests pass; [ ] frontend flow and
proposal confirmation remain later S4 slices; [ ] held-out qualification remains
pending.

#### AUD-19.S4j Result / Evidence

Added `RegistrationRequestPreparer` and the authenticated
`POST /jobs/{job_id}/rgb-lidar-registration/prepare` route. It binds the current
scene revision, accepted recipe and exact input assembly, derives map mode/role/unit/
frame/same-scene declaration from immutable evidence, reads the PCD/PLY header and
point count from verified source bytes, and seals a server-owned provisional profile
and request. The target uses the current SceneIR's canonical RGB geometry, metric
provenance, floor-fit evidence and a padded world AABB ROI from the checksum-verified
collision GLB. The response contains the sealed request and preflight but does not
queue work, charge quota or mutate scene/artifact state. The worker uses the same
source-inspection seam and independently revalidates source bytes when it claims work.
Unsupported accepted recipe groups, stale scene revisions, invalid source/target
lineage and oversized targets fail closed. No AUD-18 file or behavior was changed.

Changed files: `src/services/orchestration/jobs/registration_preparation.py`,
`src/services/orchestration/jobs/registration_sources.py`,
`src/api/product/registration.py`, `tests/test_orchestration/test_registration_preparation.py`,
`tests/test_orchestration/test_registration_sources.py`,
`tests/test_api/test_registration_routes.py`, this task record, the audit README,
`AGENT_GUIDE.md` and `INTEGRATION_MAP.md`.

Verification: focused source/preparation/API tests **32 passed**; full API suite
**212 passed, 15 existing httpx cookie deprecation warnings**; registration contract,
operation, source, preparation, target, worker, QA, BEV and constrained-ICP tests
**126 passed**. Full `.venv/bin/ruff check src/ tests/` passed; full
`.venv/bin/ruff format --check src/ tests/` reported 574 files formatted; contract
mirror passed (5 enums, 6 models). The route tests verify authorization and no queue
side effect; the service test verifies the sealed R2/R3 request fields with isolated
source/target resolver stubs, while source resolver tests parse actual direct and ZIP
member PLY bytes.

Limits: the frontend does not yet call preparation or show proposals/QA/overlays;
confirmation CAS and alignment consumer publication remain open. The server profile
is provisional, so this API does not claim a qualified or production-accurate result.
Separate new-upload binding, physical same-place proof, held-out warehouse QA, browser
flow and collision/Isaac safety remain **UNVERIFIED**.

Pre-flight (GUIDE.md Rule 13)
- codegraph: traced the accepted `InputRunRecord`/`InputRecipe`, assembly bindings and
  probes, current SceneIR geometry/floor provenance, request resolver, worker source
  loader, target verifier and API mutation ownership before editing.
- impact: S4i enqueue remains compatible; preparation uses its exact sealed request
  contract, and worker source identity now shares the inspector with preparation.
  SceneIR, registration operation storage, quota, collision selection, frontend and
  AUD-18 are unchanged.
- minimal-code: one preparation service and route use current assembly/scene/artifact
  resolvers; no new persistence, schema, profile configuration or registration bypass.
- checks: API 212 passed; registration boundary suite 126 passed; Ruff check/format,
  contract mirror and diff checks passed. CodeGraph and Graphify were refreshed after
  the edits.
- DevTools: n/a — backend-only route/service; no rendered screen changed.

### AUD-19.S4k — Studio preflight, durable operation status and cancellation

**Input:** the current committed SceneIR revision, an authenticated actor with the
existing job-mutation capability, and the exact accepted R2 registered-map or R3
static-cloud recipe. The browser does not assemble source, target, metric, floor or
checksum claims.
**Output:** an on-demand eligibility check, a durable registration operation, a
recoverable operation status and a cancellation action in the scene's
"Kiểm tra & duyệt" tab. The screen reports a candidate as a proposal only; it does not
apply a transform, publish collision geometry or change the current scene.
**Data contract:** call S4j `POST .../prepare` with `expected_scene_revision`; enable
enqueue only when the returned sealed request matches the job/actor/revision and the
preflight is `READY`. Call S4i `POST .../operations` with that unchanged request and
`Idempotency-Key=request_id`. Save the pending sealed request in session storage before
enqueue so an uncertain network result can replay the exact request/key after reload;
scope storage by authenticated user and job, then discard the request after an
operation ID is received. Poll the job-bound status endpoint with abortable,
visibility-aware polling. Cancel only queued/running/resource-waiting operations and
keep polling across proposal/review/confirmation transitions until the operation is
terminal. A changed scene revision marks
the operation stale; no UI action may bypass backend authorization or revision checks.
**Implement:** add typed API parsing for preparation, preflight and the safe operation
projection; add a focused panel to ReviewTab using existing Cards, Notices, Buttons and
`usePolling`; translate finding codes into useful Vietnamese labels; show explicit
read-only/unsupported/stale states. Keep the proposal and QA references as status-only
in this slice; read-only report inspection, overlay and confirmation are follow-up
slices. No schema or worker changes.
**Tests:** READY preparation enables enqueue; non-READY preflight never enqueues;
request/job/actor/revision mismatches fail closed; same request retry reuses the same
idempotency key; uncertain response recovery replays the cached request; status polling
continues across proposal/review states, stops at terminal states and aborts on unmount;
cancellation follows the server acknowledgement; stale revision and read-only roles
cannot start or cancel; API parser rejects malformed status payloads.
**Exit:** [x] READY preparation enables an accepted R2/R3 request;
[x] uncertain-response recovery reuses the sealed request and idempotency key;
[x] operation status and cancellation remain server-authoritative;
[x] proposals cannot change SceneIR/collision consumers in this slice;
[x] DevTools evidence limitation is recorded as UNVERIFIED.

### Result / Evidence — AUD-19.S4k

- Implementation: typed registration API parsing, sealed-request actor/job/revision
  checks, idempotent pending-request recovery, and the ReviewTab preflight/status/
  cancellation panel. Polling follows backend state transitions through proposal and
  review while cancellation remains limited to worker-active states. The panel reports
  proposals without applying transforms or changing SceneIR/collision state.
- Changed files: `docs/plans/active/2026-10-07-codegraph-audit/AGENT_GUIDE.md`,
  `docs/plans/active/2026-10-07-codegraph-audit/INTEGRATION_MAP.md`,
  `docs/plans/active/2026-10-07-codegraph-audit/README.md`, this AUD-19 task file,
  `frontend/src/lib/api/registration.ts`,
  `frontend/src/features/studio/scene/RegistrationPanel.tsx`,
  `frontend/src/features/studio/scene/ReviewTab.tsx`,
  `frontend/tests/registration-api.test.ts`,
  `frontend/tests/registration-panel.test.tsx`,
  `frontend/tests/floor-fit-diagnostics.test.tsx`.
- Gate report: CodeGraph traced the sealed request through the registration API,
  RegistrationPanel, ReviewTab and ScenePage callers; Graphify was updated and its
  post-change query found the S4k task and ReviewTab/panel path. Minimal-code scope
  reuses the existing API routes and abortable `usePolling`; no backend schema,
  worker, transform, viewer or collision-consumer changes were made.
- Checks: `npx tsc --noEmit` passed; ESLint passed for changed frontend files;
  focused Vitest passed (4 files / 32 tests); full frontend Vitest passed (54 files /
  417 tests); `git diff --check` passed.
- DevTools: **UNVERIFIED**. Chrome DevTools loaded the authenticated local scene
  route, but `GET /api/v1/jobs/job-1bb733ae40ad/scene` returned 404 and ReviewTab
  stopped at its existing missing-scene error before mounting this panel. Console
  showed only the resulting 404 resource failures; no registration request was sent.
  No job or scene data was created to bypass this missing fixture.

### AUD-19.S4l — Read-only proposal and QA inspection

**Input:** an authenticated contributor, a job-bound durable registration operation,
and the proposal/QA artifact references recorded by that operation.
**Output:** an inspection response and ReviewTab details showing candidate transforms,
solver scores, observed QA metrics/findings, and whether the target scene revision is
still current.
**Data contract:** `GET .../operations/{operation_id}/inspection` returns only outputs
whose refs match the job URI and ID, operation ID, sealed request checksum,
`producer_stage=RGB_LIDAR_ALIGN`, and `data_class=DERIVED`. Resolve bytes through
`ArtifactResolver`; verify artifact-byte checksums, canonical proposal/report checksums,
and the exact request/proposal/report binding before returning either payload. A QA
report may supply its own proposal ref when the operation record omits a proposal ref,
but that ref must pass the same operation provenance and checksum checks. Include the
expected and current scene revisions so the client can label stale results. No sealed
request, worker lease/error, filesystem path or idempotency key is returned. This sprint
does not draw a 3D overlay, confirm a candidate, publish an `AlignmentRecord`, or modify
SceneIR, collision geometry or consumers.
**Implement:** add a contributor-authenticated, job-bound read route; reuse the artifact
resolver and registration binding validators; parse the response at the TypeScript API
boundary; display each candidate's explicit `T_world_from_source` convention,
translation/quaternion, solver ranking and optional RGB scale hypothesis, plus global and
per-region QA metrics/findings and stale-revision status in the existing registration
panel. Keep the content visible in read-only mode and expose no confirmation or apply
control.
**Tests:** contributor/auth requirement, job/operation binding, missing/corrupt bytes,
operation provenance, producer stage, derived data class, job-scoped URI and exact
request/report binding; QA-derived proposal ref; stale-current revision projection;
frontend rejects mismatched job/revision/checksum; panel renders candidate, scale and
regional QA values without offering confirmation; inspection fetch aborts on unmount.
**Exit:** [x] exact proposal/report bytes are verified against the stored operation;
[x] stale scene identity is exposed to the panel; [x] read-only inspection cannot
change alignment or scene state; [ ] DevTools screen acceptance with an available
committed scene fixture.

### Result / Evidence — AUD-19.S4l

- Implementation: added an authenticated operation inspection route. It resolves
  checksum-bound proposal and QA artifacts, checks the job-scoped URI, alignment producer
  stage, derived data class, and artifact provenance against the operation and request,
  validates logical checksums and registration bindings, and returns the current scene
  revision. The panel displays the explicit transform convention, ranked candidates,
  transform values, an optional RGB scale hypothesis, global and per-region QA metrics,
  findings and stale state without confirmation or apply actions. The QA report's
  proposal reference is supported when the operation record contains only the report ref.
- Changed files: `src/api/product/registration.py`,
  `tests/test_api/test_registration_routes.py`,
  `frontend/src/lib/api/registration.ts`,
  `frontend/src/features/studio/scene/RegistrationPanel.tsx`,
  `frontend/tests/registration-api.test.ts`,
  `frontend/tests/registration-panel.test.tsx`, this task file, and the audit README.
- Gate report: CodeGraph traced the registration route/store/contracts/artifact
  resolver and panel callers in `ReviewTab`; Graphify was queried before edits and
  updated after the code change. The route reuses `ArtifactResolver.load_model` and
  existing content/binding validators. No worker, schema, SceneIR or collision
  consumer changed.
- Checks: `.venv/bin/pytest tests/test_api/test_registration_routes.py -q` **28 passed**;
  focused Vitest **15 passed**; `npx tsc --noEmit`, changed-file ESLint,
  repository-wide `ruff check src/ tests/`, repository-wide
  `ruff format --check src/ tests/`, CodeGraph sync, Graphify update and
  `git diff --check` passed.
- DevTools: **UNVERIFIED**. Chrome DevTools showed an authenticated Reviewer session,
  but the available completed scenes returned 404 from `/api/v1/jobs/{job_id}/scene`,
  so `ReviewTab` did not mount the registration panel. No test job or scene data was
  created to bypass the missing fixture.

Pre-flight (GUIDE.md Rule 13)
- codegraph: explored the registration route, operation record/store, proposal/QA
  contracts and binding validators, artifact resolver, existing artifact-content
  allow-list, ReviewTab panel callers and focused API/frontend tests.
- impact: the new API route is consumed only by `RegistrationPanel`; that component is
  mounted by `ReviewTab`. Existing operation status/cancel routes, worker outputs and
  scene/collision consumers remain unchanged.
- understand: this is the product inspection path from a durable operation to its
  immutable proposal/report artifacts; those artifacts do not authorize alignment.
- minimal-code: reuses `ArtifactResolver.load_model`, exact artifact refs, checksums,
  registration binding validators, existing API client parsing and Studio primitives.
- checks: API 28 passed; focused Vitest 15 passed; TypeScript, changed-file ESLint,
  repository-wide Ruff lint/format, CodeGraph/Graphify updates and diff check passed.
- DevTools: **UNVERIFIED** — the authenticated local jobs have no committed scene
  available to render the ReviewTab panel.

### AUD-19.S4m — Bounded BEV proposal overlay (diagnostic-only)

**Input:** the exact immutable proposal/QA artifacts for one registration operation,
the verified source and target point samples, and each listed candidate transform.
**Output:** a bounded, checksum-bound top-down overlay for each candidate in the
read-only ReviewTab inspection panel.
**Data contract:** transform source samples with the listed `T_world_from_source`;
project both layers onto world XY. For an explicit RGB scale hypothesis, scale target
points and the request ROI in the verified target-floor frame, matching the solver's
scale semantics. Derive the preview's world XY bounds from that scaled ROI. Each
preview binds the operation ID, request checksum, candidate ID and transform,
source/target geometry refs, source input checksum, target-floor evidence checksum,
target scene revision, request ROI, and the candidate's scale hypothesis. The preview
is `derived` evidence with an explicit diagnostic-only label; it is not QA, does not
infer geometry outside observed samples, cannot turn an INCONCLUSIVE report into
PASS, and does not select/apply a transform or mutate SceneIR/collision state.
Samples are deterministic and capped at 512 points per cloud; the artifact records
full in-ROI counts and the cap so visual density cannot be read as measured coverage.
**Implement:** publish one immutable preview artifact per proposal candidate, bind
its refs into the existing QA evidence list, resolve and validate previews through
the existing operation-inspection route, and display an accessible XY overlay with
candidate selection in the existing panel. Keep the existing registration request,
operation, alignment and collision contracts unchanged.
**Tests:** deterministic sampling and transform direction; ROI clipping, finite
coordinates and size bounds; exact operation/request/candidate/geometry binding;
tampered or cross-operation artifacts rejected by inspection; parser rejects
malformed previews; panel renders both layers and changes candidate without offering
an apply control. Browser rendering remains a separate acceptance gate.
**Exit:** [x] each returned preview matches its exact candidate and geometry refs;
[x] point counts/caps and diagnostic-only status are visible; [x] no scene or
collision consumer changes; [ ] browser screen acceptance with a committed scene
fixture; real held-out/Isaac registration acceptance remains pending.

### Result / Evidence — AUD-19.S4m

- Implementation: added a checksum-sealed `RegistrationOverlayPreview` bound to the
  exact operation, request, candidate transform/scale, geometry refs, scene revision,
  target-floor evidence and ROI. The worker transforms source and RGB samples through
  the solver's target-floor frame, scales the RGB hypothesis and ROI consistently,
  then publishes one diagnostic artifact per proposal candidate in the QA evidence
  list. Projection runs in fixed-size chunks and retains at most 512 deterministic
  in-ROI samples per layer while preserving exact point counts.
- Inspection: the existing authenticated inspection route verifies the artifact
  reference and logical checksum, enforces one preview per proposal candidate, and
  rejects corrupt or cross-bound artifacts. The API parser also rejects malformed,
  duplicate or incomplete overlay sets. The ReviewTab panel renders a BEV SVG with
  candidate selection, layer legend, scale, counts and sample cap. The view is
  explicitly diagnostic-only and does not change QA, SceneIR, collision geometry or
  alignment state.
- Changed files: `src/models/contracts/rgb_lidar_registration.py`,
  `src/services/reconstruction/alignment/registration_overlay.py`,
  `src/services/orchestration/jobs/registration_worker.py`,
  `src/api/product/registration.py`, their focused backend tests,
  `frontend/src/lib/api/registration.ts`,
  `frontend/src/features/studio/scene/RegistrationOverlay.tsx`,
  `frontend/src/features/studio/scene/RegistrationPanel.tsx`, focused frontend tests,
  this task file and the audit README.
- Checks: focused backend suites **81 passed**; focused Vitest **17 passed**;
  repository-wide `ruff check src/ tests/`, `ruff format --check src/ tests/`,
  `pnpm typecheck`, targeted ESLint, and `git diff --check` passed. CodeGraph sync
  completed; Graphify rebuilt **21,934 nodes / 66,878 edges / 732 communities**.
- DevTools: **UNVERIFIED**. The authenticated local Reviewer session opened completed
  scenes with metric scale and collision, but their `/api/v1/jobs/{job_id}/scene`
  requests returned 404 and ReviewTab displayed “Không tìm thấy dữ liệu”; the
  registration panel did not mount. No fixture or scene state was created to bypass
  the missing data. Held-out map quality and real Isaac acceptance remain open.

Pre-flight (GUIDE.md Rule 13)
- codegraph: traced the proposal/QA worker, inspection route, artifact resolver,
  RegistrationPanel callers and the new contract/component before editing, then
  synchronized CodeGraph after implementation.
- impact: one immutable diagnostic artifact per candidate flows through the existing
  QA evidence reference and inspection response; no alignment, scene or collision
  consumer contract changed.
- understand: RGB scale and ROI use the same target-floor frame as the registration
  solver; source samples use the listed `T_world_from_source` transform. Preview
  samples and their counts never serve as QA evidence of registration accuracy.
- minimal-code: reuses existing artifact and inspection paths, caps samples at 512,
  and bounds intermediate projection memory with fixed-size chunks.
- checks: 81 backend tests, 17 frontend tests, repository Ruff lint/format,
  TypeScript, targeted ESLint, Graphify update, CodeGraph sync and diff check passed.
- DevTools: **UNVERIFIED** — no available completed-scene fixture could load the
  ReviewTab scene payload; held-out and Isaac qualification were not claimed.

### AUD-19.S4n — Qualified candidate confirmation with durable CAS

**Input:** the exact operation checksum, expected scene revision, selected
candidate ID, and the server-verified proposal/QA/overlay artifacts for a
registration operation.
**Output:** a durable `CONFIRMED` operation record naming the exact candidate,
confirming user, confirmation time, source operation checksum, and immutable
target scene revision. This sprint does not publish an `AlignmentRecord`, change
SceneIR, or enable collision consumers; those belong to the next consumer sprint.

**Contract:** the command is available only to an authenticated authorized job
mutator. It requires an unambiguous `PROPOSED` result, a `PASS` QA report bound to
the same selected candidate and exact operation artifacts, and the overlay for
that candidate. The command's expected checksum must equal the operation's
current checksum; the command revision, request revision, and current SceneIR
revision must agree. A scale-changing candidate cannot be confirmed because a
rigid `AlignmentRecord` cannot encode RGB rescaling; it needs a separate explicit
metric-correction/reconstruction run. The operation-row CAS commits the decision
once. Replaying the same user/candidate/base-checksum decision returns the
existing confirmation; a conflicting replay or stale state returns a conflict.
Optional confirmation fields are omitted from the logical checksum while null so
legacy schema-1.0 operation payloads retain their existing checksums.

**Implement:** add checksum-bound confirmation fields to the durable operation
record and validate their state/time invariants; expose the current operation
checksum needed for optimistic concurrency; add an authorized `confirm` route
that reuses the verified inspection path, checks current scene/QA/candidate/scale,
and calls a transactional store CAS; add a Studio action tied to the selected
overlay candidate, with explicit disabled/stale/confirmed states. Keep ambiguous,
INCONCLUSIVE, FAIL, stale, tampered, and scale-changing candidates unconfirmable.

**Tests:** legacy payload checksum compatibility; valid decision; response-loss
retry/idempotency; same-candidate/actor/base-checksum binding; stale checksum and
scene revision; concurrent conflicting confirmations; authorization including
Guest ownership; malformed/tampered refs; QA not PASS; non-selected candidate;
scale-changing candidate; frontend parser/action disabled and success states. The
confirmation action must leave the current SceneIR revision and collision source
unchanged. Browser rendering is a separate acceptance gate.

**Exit:** [x] exact qualified candidate confirmation survives operation-store
reload; [x] retries are idempotent and stale/conflicting decisions lose; [x] no
unqualified or scale-changing candidate can confirm; [x] UI only confirms the
candidate represented by its selection and QA; [x] SceneIR/collision remain
unchanged; [ ] browser acceptance with a committed scene fixture. Held-out map
qualification and Isaac/collision acceptance remain open.

### AUD-19.S4o — Publish a confirmed registration into the reconstruction bundle

**Status:** Planned; not implemented. This is the consumer sprint after S4n.

**Input:** a `CONFIRMED` operation plus its exact source operation checksum,
selected candidate, immutable scene revision, QA `PASS`, verified proposal/overlay,
and the current job manifest and `ReconstructionBundle` identity.

**Output:** a byte-verified immutable `AlignmentRecord`, a new
`ReconstructionBundle` carrying its `lidar_geometry_ref` and `alignment_record`,
and a durable operation transition to `COMMITTED` that names the published bundle
and alignment artifact checksums. Preserve `canonical_geometry_ref` as the RGB
geometry source.

**Contract:** revalidate the complete S4n decision and exact artifact bytes at the
consumer boundary. Adapt the registration source into the existing REC-09
`AlignmentRequest` contract without weakening `RgbLidarAlignmentService` checks:
world target frame, same-job RGB/LiDAR geometry, same-scene evidence, explicit
confirmation, and a verifier that binds the current operation decision. `AlignmentRecord`
must retain the exact proposal, QA, source, overlay and confirmation identities in
its evidence/provenance. Publish a new immutable bundle and advance the job's
manifest by compare-and-swap against the input manifest checksum/revision; an
identical replay returns the same publication, while stale source, scene, QA or
manifest state conflicts without changing the current manifest. Do not add a
registration field to `SceneIR`: current `SceneIR` has no alignment slot, and the
canonical RGB geometry must not be replaced. Do not publish or activate collision
geometry from this sprint; that remains behind AUD-12's eligibility and selection
contract. Existing sensor-package finalization continues through its current REC-09
path.

**Tests:** build and reload the exact `AlignmentRecord` and bundle; verify source
and QA byte checksums, transform/candidate identity, confirmation actor and base
checksum; reject missing/corrupt refs, non-`CONFIRMED` state, stale target or
manifest CAS; exercise duplicate and concurrent publication; prove SceneIR's
canonical RGB ref and collision selection are unchanged; retain existing
sensor-package REC-09/REC-10 regressions.

**Exit:** [ ] operation reaches `COMMITTED` only after exact alignment and bundle
publication; [ ] retries resolve to identical artifact identities; [ ] stale or
tampered inputs leave manifest and bundle head unchanged; [ ] canonical RGB and
collision source are unchanged; [ ] bundle consumers reload the exact alignment
evidence. Held-out map/browser and Isaac collision acceptance remain separate gates.

### Result / Evidence — AUD-19.S4n

- **State:** Local implementation complete; commit pending. S4o consumer
  publication, registered-map quality qualification and production evidence remain
  open.
- **Base:** `c3c9b244` (AUD-23 real-capture audit record already on the branch).
- **Implementation:** durable operation checksum CAS, checksum-compatible optional
  confirmation fields, authorized confirm API, and selected-overlay UI. Confirmation
  records the exact candidate, user, time, and pre-confirm operation checksum; it
  leaves the current SceneIR and collision source unchanged.
- **Verification:** backend registration operation/API tests: **67 passed**;
  frontend registration API/panel tests: **20 passed**; Ruff check/format,
  targeted ESLint, TypeScript typecheck and `git diff --check` passed. CodeGraph is
  current (934 files, 19,181 nodes, 57,908 edges). Graphify refresh completed
  (21,961 nodes, 67,046 edges, 753 communities).
- **Chrome DevTools:** **UNVERIFIED**. Reviewer session reached a completed local
  scene's Review tab, but its `/api/v1/jobs/job-6bc02e5de4ed/scene` request returned
  HTTP 404, so no committed-scene confirmation rendering could be exercised.
  Held-out registration quality and Isaac/collision acceptance were not claimed.
