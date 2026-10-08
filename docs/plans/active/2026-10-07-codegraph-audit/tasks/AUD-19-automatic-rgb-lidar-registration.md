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
fails closed; [ ] source-map floor estimation, proposal/QA execution and durable
worker dispatch are connected.

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
