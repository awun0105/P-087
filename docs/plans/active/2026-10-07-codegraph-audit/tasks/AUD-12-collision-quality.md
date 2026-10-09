# AUD-12 — Collision cleanup, QA và selectable LiDAR collision

## Metadata và goal

- IN PROGRESS; P0; EX-REC geometry, EX-SIM collision QA, PRODUCT selection/publication.
- Canonical REC-05/08/09, SIM-02/04/06, PRODUCT-08/12. REUSE existing voxel/
  clearance tools; ADAPT radius/statistical filters theo qualified source.
- Goal: giảm ghost blocking nhưng giữ obstacle/support thật, có source/quality
  evidence và exact-candidate simulator acceptance.
- [Agent guide](../AGENT_GUIDE.md), [verified findings](../GEMINI_FINDINGS.md),
  [ADR 0016](../../../../decisions/0016-collision-quality-and-lidar-selection.md).

## Baseline và scope

33/50 blocked ở mesh 0,05 m là thật. LiDAR 0/100 cần min_range 2/3 m + floor_band
0,15 m; raw registered cloud vẫn 100/100. Đây là demo GT-assisted trajectory,
không independent obstacle recall hoặc Isaac proof. Current geometry dùng voxel
adapter, đã có opacity/scale/cleanup config; inspect/reuse trước thêm filter mới.

CodeGraph: FinalizeWorker._execute/_bundle, RgbGeometryService,
SplatTransformVoxelAdapter, lidar fusion/alignment, _carved_environment,
eval.path.path_clearance/lidar_clearance. Inspect clearance vertex/capsule
approximation và camera/robot extrinsic trước gọi mọi BLOCKED là false positive.
Owned: reconstruction/rgb/geometry/, lidar processing ports, simulation/colliders/
preflight/, scene extraction ownership glue và typed config/report refs.
Eval code ở eval/path/ theo boundary giữ product independent GT; API/UI chỉ chọn
explicit source/profile và report status. Không rewrite old canonical artifacts.

## Input / output / data contract

Input: confirmed metric RGB geometry/visual hoặc LiDAR + confirmed world alignment,
selected cleanup/collision profile và mode-specific source QA. Sensor package cần
calibration/timing QA AUD-13; independent registered static map cần registration
QA AUD-19, không fabricate rig extrinsic/trajectory.
Output: immutable collision artifact + CollisionQualityReport/source selection,
SceneEnvironment binding và candidate inventory, hoặc blocker.

Proposed CollisionSourceSelection: version, mode rgb_cleaned/lidar_derived,
source refs/checksums, input/registration mode, mode-specific alignment QA kind/ref,
config/profile checksums, effective resolution và output collision ref.
CollisionQualityReport: selection/source/config/output identity, hardware/robot
profile refs, effective resolution, robot envelope, frozen acceptance profile
and result, floor/support retention, free-space proxy, independent obstacle
reference, observed/unsupported region refs, motion diagnostics và Isaac contact
ref. Region evidence ghi source, observation IDs và coverage; absence of
measurements không là free space. Free-space proxy không
thể thay independent obstacle recall; report không tạo GT accuracy claim nếu
reference là input trajectory hoặc cùng LiDAR nguồn.

Keep existing canonical RGB artifacts unchanged; explicit scale correction AUD-19
tạo new canonical target trước source selection. Collision ref
selection chốt cùng SceneEnvironment consumers ở S1. Ownership AUD-01 bind
selected collision geometry, không reuse mesh-face indices giữa RGB/LiDAR.
Filtering diễn ra source/sensor frame đúng; no global 2 m trajectory eraser.
Floor_band 0,15 là ablation parameter, không default universal. Low obstacles
phải giữ. Requested/effective config rõ; không âm thầm tăng resolution khi vượt
voxel capacity — chờ/block/explicit ROI/profile change theo khả năng runtime.

## Logic change và dependent updates

Risk: **Cao** khi chỉ sửa một phần. Logic delta: Collision source/quality selection.
Cần sửa đồng bộ: RGB cleanup/LiDAR aligned producer, FloorModel/QA ports, finalize/bundle/SceneEnvironment, simulation_package/USD, viewer/source selection và Isaac validation.
Acceptance xuyên consumer: Visual/canonical geometry khác collision source; cleanup retention/coverage và exact aligned refs được dùng ở export/validation.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập; S2 dùng floor/noise contract AUD-14.S1. LiDAR sensor-package source S3
cần AUD-13 QA và confirmed alignment; optional independent-map source dùng
AUD-19.S3/S4 sau qualification. Sensor-package path không đợi AUD-19, registration
producer dùng source contract S1, không đợi whole S3. Old RGB path vẫn available.
S4 phối hợp AUD-01 composition, AUD-02 export, AUD-05 Isaac và held-out dataset.

## Sprint AUD-12.S1 — Repro, quality protocol và source contract

**Input:** saved clearance logs/protocol + same source refs nếu available.
**Output:** baseline parser/regressions, tuning/held-out matrix, proposed typed
quality/source contracts và collision-source consumer fixtures.
**Contract:** record exact source/config/hardware/robot profile and envelope; label
GT-assisted; free-space proxy tách independent obstacle recall; synthetic fixture
acceptance thresholds freeze trước test.

Implement: reproduce metrics khi data/runtime có; otherwise preserve saved
evidence label. Build thin obstacle/floor fixtures: shelf legs/pallet feet/cable,
wall/ramp/low boxes, genuine narrow passage và camera offset. Define measured
retention/contact criteria; include unobserved/motion-suspected region diagnostics.
Define supported static-capture/observed-region evidence and consumer state:
unknown, inferred or motion-suspected geometry cannot claim verified physics.
Tests: benchmark parser/units/envelope, known clear vs real blocked, negative
"delete all geometry" must fail retention/support, source checksum mismatch,
moving/ghosted or unobserved-region fixture flagged rather than verified clear.
**Exit:** [x] baseline conditions pinned; [x] QA cannot pass empty-world solution.

## Sprint AUD-12.S2 — Qualified cleanup cho RGB collision

**Input:** RGB source + immutable cleanup profile + floor/noise model.
**Output:** cleaned geometry/collision artifact và before/after metrics/provenance.
**Contract:** preserve source input/quality choice; removal counts/criteria recorded;
no hallucinated support hoặc blanket floor/trajectory deletion.

Implement: reuse opacity/scale/component cleanup; evaluate radius/statistical
outlier removal trước mesh, optionally visibility-supported cleanup. Gaussian
centers không đủ chứng minh occupied surface; giữ Gaussian fields/source semantics
và test output geometry. Qualify thresholds by scale/density/noise; preserve thin
obstacles/floor/walls. Gate unknown/unsupported quality, không lower quality silently.
Tests: synthetic floaters + sparse true obstacles, varying density/noise/slopes,
outlier aggressive-filter negative, effective config identity, source conservation.
**Exit:** [ ] ghost blocking improves on tuning data; [ ] retention/support matrix pass.

Current code boundary: `FloorFitEvidence` is persisted by scene extraction/objectify
after the initial `FinalizeWorker` RGB collision stage. The current finalize request
has no supported pre-collision floor/noise model input. Do not treat that later
evidence as an input to the earlier stage or remove points by floor height. The
cleanup report must remain diagnostic-only until a source-bound model is produced
before collision generation and retention is qualified.

## Sprint AUD-12.S3 — Opt-in LiDAR-derived collision

**Input:** mode-specific QA-qualified LiDAR/alignment + explicit selected collision mode.
**Output:** LiDAR collision artifact, source provenance và current scene binding.
**Contract:** same metric world frame; origin/time/range/self-mask known; raw
trajectory not rewritten; RGB visual/canonical artifact not silently replaced.

Implement: reusable LiDAR→occupancy/mesh adapter; filter robot self points in
sensor frame using evidence/self-mask, preserve obstacles observed from other scans.
Independent registered maps không có scan-native self-mask evidence thì không
guess sensor-range deletion; dùng qualified map cleanup/coverage. Route QA by mode,
never turn geometric PASS into calibration PASS.
Floor separation dùng confirmed/fitted plane/noise, không drop mọi point dưới
15 cm. Show source/coverage/blockers; no auto fallback on QA/alignment failure.
Tests: missing/unconfirmed alignment, wrong units, self points vs nearby obstacles,
low obstacle, data gaps, region ownership/source mismatch, unavailable source.
Include independent-map binding and wrong/missing QA-kind negatives when AUD-19 lands.
**Exit:** [ ] opt-in path exported đúng refs/frames; [ ] low-obstacle retention proof.

### Sprint AUD-12.S3a — Bounded LiDAR collision candidate adapter

**Input:** ordered `(N, 3)` LiDAR coordinates already expressed in metric world
space, an exact-checksum-bound supported `FloorModel`, a versioned voxel/resource
profile, and optionally a boolean self-mask plus its `ProductArtifactRef`.
**Output:** deterministic embedded GLB candidate and `LidarCollisionBuildReport`
with source/floor-model/floor-profile/profile/output checksums, profile ID and
effective voxel size, input/retained/masked/floor counts, occupied voxel and mesh
counts, and explicit unverified physics/calibration status.
**Contract:** this is a geometry adapter, not a source-selection or QA gate. The
caller must resolve and validate the self-mask artifact, sensor/world registration,
units and selected alignment QA before supplying the array. The adapter checks the
mask shape/type and records a source-bound mask digest/ref; it cannot resolve an
artifact ref or prove the world transform. No floor-height, fixed-band or range
deletion is applied: all unmasked points, including below-floor points, contribute
to occupied voxels. Mesh vertices are separated across disconnected six-neighbor
components so edge/corner-only fixture contacts do not merge shells; the floor
model is diagnostic only.

Implement: deterministic six-neighbor voxel boundary extraction; bound point,
voxel-grid and triangle counts before mesh construction; encode/read using the
strict collision GLB boundary. Do not connect this candidate to `FinalizeWorker`,
`SceneEnvironment`, USD, API or viewer until S3 QA/source contracts are qualified.
Tests: source checksum and floor support, stale/uncertain floor, missing or
misaligned self-mask evidence, exact retained/voxel counts, low/below-floor
retention, invalid input, each resource limit, deterministic bytes and closed
topology on edge/corner-touching fixture cells.
**Exit:** [x] bounded local candidate/report contract; [x] focused synthetic tests.
QA-qualified mode selection, artifact-store resolution, production publication,
held-out retention and Isaac acceptance remain S3/S4 work.

### Sprint AUD-12.S3b — Immutable SceneIR collision-source binding

**Input:** exact collision-candidate ref and immutable `CollisionSourceSelection` ref.
**Output:** optional `SceneEnvironment` refs for the selected source and selection
record, plus an artifact allow-list that keeps both refs reachable across publication.
**Contract:** `collision_source_ref` identifies the selected candidate while
`collider_ref` may identify a later carved/effective mesh. The refs are paired,
same-job and the selection ref must have type `CollisionSourceSelection`. Absent
fields are omitted from legacy SceneIR serialization/checksums. Simulation packaging
must refuse these refs until its source-QA and object-ownership consumer is
source-aware; it must not silently keep using canonical RGB geometry.

Tests: legacy SceneIR serialization, missing or cross-job binding, exact selection
identity after carving, artifact allow-list closure, and a package-composer negative
proving selected LiDAR sources do not fall back to RGB.
**Exit:** [x] typed binding and backward-compatible serialization; [x] refs included
in SceneEditor artifact closure; [x] simulator composer fails closed. QA-qualified
source publication, viewer selection and LiDAR object-region ownership remain open.

### Sprint AUD-12.S3c — Source-specific eligibility assessment

**Input:** the exact mixed `ReconstructionBundle` and `LidarPackageRecord`; calibration/timing
report and projection evidence; confirmed alignment; a world-meter point-cloud receipt;
source-bound floor and self-mask evidence; and a bounded `LidarCollisionProfile`.
**Output:** `LidarCollisionEligibilityAssessment` with `eligible` or `blocked`, stable
blocker codes, exact source refs and profile checksum. The assessment has no publishing
or mesh-building side effects.
**Contract:** `LidarAlignedPointCloudEvidence` binds the package geometry, exact
`AlignmentRecord`, world frame, point checksum and point count. Floor-fit and self-mask
evidence must refer to that same aligned-point receipt. Sensor-package QA must bind the
same package/calibration/trajectory/timing and a scored production-qualified projection
receipt. Registered maps return a mode-specific blocker pending AUD-19 qualification.
Missing, wrong-mode, stale or `diagnostic_only` evidence cannot authorize a candidate
or source switch. The existing AUD-13 projection contract only emits
`qualification_status="diagnostic_only"`; this sprint does not create a production PASS
or infer qualified thresholds.

Implement: compare bundle geometry and confirmed alignment checksums; revalidate the
serialized identities for package, QA, projection, point-cloud, floor and self-mask
receipts; compare metric frame, point ordering/count and full pose coverage; require an
explicit profile. Tighten `is_sensor_package_collision_eligible()` so a report alone
or an overlay artifact can never grant eligibility. The assessment is an internal gate
for the later S3d publisher and is not yet connected to a worker/API/SceneIR source
selection path.
Tests: forged PASS report paired with diagnostic projection remains blocked; missing
calibration QA and QA bound to another calibration are blocked; stale report checksum;
stale alignment receipt cannot be reused by floor/mask evidence; missing floor, self-mask
or collision profile; registered map cannot enter the sensor-package route.
**Exit:** [x] deterministic, identity-bound blocker assessment; [x] diagnostic QA and
registered-map mode fail closed; [ ] production-qualified sensor receipt and candidate
publication remain pending AUD-13.S3 qualification and AUD-12.S3d.

### Remaining AUD-12.S3 slices

**AUD-12.S3d — Publish an eligible candidate; do not select it yet.** Input is the
resolved S3c evidence, the exact world-meter point array and its point-order-bound
self-mask. The array is already aligned by the producer named in
`LidarAlignedPointCloudEvidence`; applying that transform again here would misplace
the candidate. Output is an immutable candidate mesh, build report and manifest.
The publisher recomputes S3c eligibility first, resolves every assessment evidence
ref, verifies point count/checksum, floor receipt and mask digest, then builds.
Blocked inputs write nothing. Content-addressed retries reuse verified bytes; changed
inputs/config produce a new identity. The manifest is published last as the bundle
commit marker. S3d does not mutate SceneIR or call SceneEditor: selecting before
source-aware object ownership could apply RGB triangle membership to a LiDAR mesh.

**AUD-12.S3e — Source-aware ownership, selection and export consumers.** Map
ownership to the candidate source using source-bound LiDAR regions; never reuse RGB
triangle indices. Only after that mapping is available may the source and selection
refs be committed through `SceneEditor` CAS. Update viewer, background carving,
USD/candidate inventory and invalidation together. Missing region mapping blocks
selection/export and reports coverage; it cannot silently fall back to RGB.
Registered-map mode stays blocked until AUD-19 registration QA is qualified.

## Sprint AUD-12.S4 — Held-out quality và Isaac consumer

**Input:** frozen profile/source selection + held-out traversal/reference + candidate.
**Output:** paired baseline/new QA, independent obstacle proof và real Isaac outcomes.
**Contract:** no tuning on acceptance split; input trajectory-origin flag preserved;
candidate loaded is exported candidate; motion/unobserved risk cannot become verified.

Implement: run RGB/LiDAR ablations and supported sensor conditions; publish
quality report/evidence with existing benchmark taxonomy; evaluate independent
surface/contact evidence, not just camera path. Test object move/delete on selected
collision source; robot contact/path safety checks via AUD-05.
Wire coverage/static-assumption diagnostics into preflight and validation config:
unsupported regions/pairs are flagged or blocked, not returned as verified CLEAR.
Offer static recapture or independently verified LiDAR/CAD/reference replacement;
any motion mask requires source/frame provenance and must not erase unobserved
obstacles. No general dynamic reconstruction or generative collider implementation.
Tests: all known obstacles retained/contacted, clear paths not ghost blocked,
held-out traversal, thin/low/near-sensor obstacles, no-floor support negative,
unsupported-region path gate, stale coverage/source identity and motion diagnostics.
**Exit:** [ ] frozen acceptance achieved; [ ] any remaining unsupported conditions documented;
[ ] no 0/100-as-production-safety claim.

## Verification và DoD

Existing: tests/test_reconstruction/test_rec05_collision.py, test_rec05_clearance.py,
test_rec05_product_pipeline.py, test_rec08_lidar_ingest.py, test_rec09_alignment.py;
tests/test_simulation/test_preflight.py, test_carve.py. Planned
tests/test_simulation/test_collision_quality.py. Runtime commands follow
eval/protocols/collision_path_clearance.md, recording exact input/profile refs.
DONE cần cleanup/source artifacts + frozen retention/support/held-out metrics +
Isaac contact handoff; CPU regression không đóng real acceptance.

## Result / Evidence

### AUD-12.S1 — local contract/protocol complete

- **Base:** `d0df32d` (`AUD-09.S3`).
- **Logic before → after:** saved JSONL rows were manually interpreted and only
  carried clearance counts; now a parser validates units/count consistency,
  computes a file SHA-256 and preserves GT-assisted/proxy labels and missing
  provenance. New typed source/report contracts bind exact source/config/output,
  hardware/robot profiles, support/obstacle retention, region coverage, a frozen
  acceptance-profile result and Isaac evidence. `SceneEnvironment.collider_ref` remains the selected consumer ref;
  a fixture-level validator rejects any URI/checksum/report mismatch.
- **CodeGraph impact:** audited `FinalizeWorker._execute/_bundle`,
  `RgbGeometryService`, `SplatTransformVoxelAdapter`, LiDAR fusion/alignment,
  `eval.path.path_clearance`, `eval.path.lidar_clearance`,
  `SceneEnvironment`, and collision package consumers. S1 has no live producer,
  persistence, API, viewer, USD or Isaac source-selection caller; therefore it
  adds a versioned internal contract and consumer fixture without changing
  SceneIR or legacy artifact serialization. AUD-12.S2–S4 will wire actual
  producers/consumers with the selected source.
- **Changed files:** `eval/path/collision_quality.py`,
  `eval/fixtures/collision_quality.py`,
  `eval/protocols/collision_path_clearance.md`,
  `src/models/contracts/collision_quality.py`,
  `src/models/contracts/__init__.py`,
  `tests/test_contracts/test_collision_quality.py`,
  `tests/test_reconstruction/test_collision_quality.py`, this task, ADR 0016,
  and the plan README.
- **Saved evidence parsed:** `aisle-cw-local-t2000.jsonl` SHA-256
  `b7779a0bdbbfe75977f16a25f73b7f37256de3dc82788faaffd7f71e5344b39c`;
  33/50 at 0.05 m. `aisle-cw-100-lidar-job.jsonl` SHA-256
  `e8a4d1bf129ee1eef2cb573eaa61dcfb7a3cbfbcc32636850742bc3253e40716`;
  0/100 at min-range 2 m + floor-band 0.15 m, explicitly GT-assisted. Both are
  free-space proxies; neither contains independent obstacle-recall evidence.
- **Acceptance freeze:** deterministic synthetic cases use 100% expected
  obstacle/support sample retention, empty output always fails, known-clear is
  0/1 blocked and known-blocked is 1/1 blocked. Matrix includes shelf legs,
  pallet feet, cable, wall, ramp, low box, 0.90/1.05 m passages, 0.05 m camera
  offset sensitivity and unsupported/motion-suspected regions. These are fixture
  thresholds only; production thresholds and an independent held-out capture are
  not available yet and must be frozen on tuning data before AUD-12.S4 holdout.
- **Schema/config/migration:** added version 1.0 internal Pydantic contracts only.
  No SceneIR/API/TypeScript payload, DB migration or persisted artifact changed;
  old SceneIR and saved JSONL bytes remain readable and immutable.
- **Verification:** `pytest tests/test_contracts/test_collision_quality.py
  tests/test_reconstruction/test_collision_quality.py -q` — 31 passed;
  combined with `tests/test_contracts/test_scene.py` and
  `tests/test_packaging/test_package_publish.py` — 73 passed;
  Ruff check passed for `src/`, `tests/` and the two new evaluation modules;
  `ruff format --check src/ tests/` — 508 files formatted;
  `.venv/bin/python scripts/check_contract_mirror.py` — pass; the parser CLI
  read both saved JSONL files and verified their SHA-256/check counts.
- **Gate report:** CodeGraph used before source edits and after contract creation;
  scope limited to source contracts/evaluation fixtures/docs; focused checks pass.
  No GPU, Isaac Sim, production capture, independent obstacle reference or real
  held-out proof was available. These remain explicitly **UNVERIFIED**.
- **Next:** AUD-13.S1 calibration package projection/overlay QA, per default plan
  order. The AUD-12.S2 software slice is implemented, but collision-quality exits
  remain pending a pre-collision floor/noise model and independent obstacle
  retention evidence. AUD-12.S3 still needs qualified LiDAR/alignment inputs;
  AUD-12.S4 requires held-out and exact-candidate Isaac evidence.

### AUD-12.S2 — cleanup evidence and requested-resolution preservation

- **Base:** `f0d92db` (`AUD-14.S3`).
- **Logic before → after:** the adapter already measured input/retained Gaussian
  counts and file checksums, but they were attempt-local. `GeometryArtifact` 1.2
  now persists cleanup evidence in the geometry manifest: source, metric input,
  filtered Gaussian and collision checksums; exact effective config and checksum;
  input, retained and removed counts. Validators enforce config hash, count
  conservation, job/source binding and collision checksum binding. Status is
  `diagnostic_only`, not a physics-quality claim. `FinalizeWorker` also used to
  raise requested voxel and cleanup resolutions to fit a large crop; it now keeps
  both selected values or fails with an actionable capacity error.
- **Scope kept pending:** no new radius/SOR or floor clipping was enabled. The
  Aisle_CW runtime job has a source and final mesh but lacks saved filtered PLY and
  inspection intermediates, and its old collision log is not bound to the exact
  profile. No before/after ghost-blocking or obstacle-retention result can be
  recomputed from those files. Initial finalization also has no source-bound floor
  model, so output evidence remains diagnostic-only and both S2 exit checks remain
  unchecked.
- **Related test repair:** the pinned geometry runtime test's CLI mock now accepts
  the existing `cancel_event` keyword used by `VoxelProcess.qualify`.
- **Changed files:** `src/models/contracts/reconstruction.py`,
  `src/models/contracts/__init__.py`,
  `src/services/reconstruction/rgb/geometry/geometry_artifact.py`,
  `src/services/reconstruction/finalize.py`,
  `tests/test_contracts/test_geometry_artifact.py`,
  `tests/test_reconstruction/test_rec05_product_pipeline.py`,
  `tests/test_reconstruction/test_rec05_finalize_quality.py`,
  `tests/test_reconstruction/test_rec05_voxel.py`, this task, ADR 0016 and the
  plan README.
- **Schema/config/migration:** new geometry outputs use `GeometryArtifact` 1.2;
  1.0/1.1 artifacts remain readable with no cleanup evidence. No API, SceneIR,
  database migration or frontend payload changed.
- **Verification:** `pytest tests/test_contracts/test_geometry_artifact.py
  tests/test_reconstruction/test_rec05_product_pipeline.py
  tests/test_reconstruction/test_rec05_finalize_quality.py
  tests/test_reconstruction/test_rec05_voxel.py -v` — 48 passed;
  `ruff check src/ tests/` passed; `ruff format --check src/ tests/` reports 520
  files already formatted; contract mirror passed (5 enums, 6 models); `git diff
  --check` passed.
- **Gate report:** CodeGraph traces `FinalizeWorker → RgbGeometryService →
  SplatTransformVoxelAdapter → GeometryArtifactManifest`; the shared artifact has
  five direct callers and no new UI caller. `understand-anything` is unavailable in
  this session; execution order was confirmed from CodeGraph and current tests.
  GPU cleanup qualification, pre-collision floor/noise input, independent obstacle
  retention and held-out path improvement remain **UNVERIFIED**.

### AUD-12.S3a — bounded candidate adapter

- **Base:** current branch after `AUD-19.S4d`; committed as one implementation
  slice while the parent AUD-12.S3 remains in progress.
- **Logic before → after:** collision GLB accepted only the pinned
  `splat-transform` producer; it now also accepts the explicitly named internal
  LiDAR candidate producer. The new adapter bins every unmasked source point into
  a metric voxel and emits deterministic boundary faces, retaining floor,
  low-obstacle and below-floor voxels. Edge/corner-only contacts are separate
  mesh components so the regression fixture remains a closed topology. Reported
  floor counts are diagnostics; they do not filter geometry or qualify physics.
- **Contract:** the floor model must be `supported` and bind the exact ordered
  point-cloud checksum. Optional self-mask input must be a boolean vector of the
  exact point count and carry a `ProductArtifactRef`; the report stores that ref
  and a binding digest bound to the source checksum and point count. The caller still owns
  artifact resolution and calibration/registration QA. The report always states
  `physics_claim=unverified` and
  `calibration_eligibility=not_evaluated_by_mesh_builder`.
- **Changed files:** `src/services/reconstruction/adapters/collision_glb.py`,
  new `src/services/reconstruction/adapters/lidar_collision.py`, new
  `tests/test_reconstruction/test_lidar_collision.py`, and this task.
- **Related-code scope:** CodeGraph shows no `FinalizeWorker`, product artifact
  publisher, SceneEnvironment, USD, API or viewer caller for the candidate. The
  adapter intentionally remains opt-in and is not wired into a live pipeline.
  Adding the producer name does not relax GLB node/accessor/topology validation.
- **Verification:** focused `pytest` for
  `test_lidar_collision.py`, `test_rec05_collision.py` and
  `test_adaptive_floor.py` — 29 passed;
  `ruff check src/ tests/` — pass; `ruff format --check src/ tests/` — 552 files
  formatted; CodeGraph explore before/after and `codegraph sync`;
  `graphify query` and `graphify update .`; `git diff --check` — pass.
- **Gate report:** the browser DevTools surface remained unavailable in this
  session, but no UI changed in this slice. No production LiDAR capture, qualified
  calibration/map QA, artifact-store resolution, held-out obstacle-retention
  evidence, GPU run or Isaac contact proof was produced. AUD-12.S3 source selection
  and AUD-12.S4 acceptance remain **UNVERIFIED** and unchecked.

### AUD-12.S3b — SceneIR source identity and fail-closed export binding

- **Base:** `6566b73` (`AUD-19.S4e`).
- **Logic before → after:** SceneIR exposed only `collider_ref`, which cannot say
  whether it names the original selected source or a downstream carved result. New
  optional `collision_source_ref` and `collision_selection_ref` keep those identities
  separate. Both are paired, job-scoped and the selection ref is typed. Existing
  scenes omit both fields from serialization, preserving legacy checksums.
- **Consumer behavior:** `SceneEditor.artifact_references` includes both refs. The
  simulation composer rejects a scene that binds a selected source until QA and
  source ownership are consumed; it does not silently export canonical RGB geometry.
  The existing RGB-only path is unchanged.
- **CodeGraph impact:** explored `SceneEnvironment`, `SceneEditor.artifact_references`,
  `validate_collision_source_binding`, `_carved_environment`, the simulation-package
  caller and their contract/package tests. Source ownership is triangle-indexed against
  the original RGB geometry, so no ownership indices were copied to a LiDAR candidate.
- **Changed files:** `src/models/contracts/scene.py`,
  `src/models/contracts/collision_quality.py`,
  `src/services/orchestration/scene/editor.py`,
  `src/services/orchestration/review/simulation_package.py`,
  `frontend/src/lib/contracts/api.ts`, focused tests, the audit README and ADR 0016.
- **Verification:** 95 focused contract/orchestration tests passed; Ruff check and
  format pass; Pydantic/TypeScript contract mirror pass; `git diff --check` pass.
- **Gate report:** no UI behavior changed, so browser DevTools was not applicable.
  CodeGraph and Graphify were refreshed after edits. No production candidate/QA was
  published. Sensor QA is diagnostic-only; source-aware object ownership, held-out
  retention and Isaac proof remain **UNVERIFIED**.
- **Next:** AUD-12.S3c resolves exact QA/alignment/self-mask/floor eligibility;
  S3d publishes candidates only after eligibility; S3e closes source ownership and
  export/viewer consumers. Parent AUD-12.S3/S4 stays unchecked.

### AUD-12.S3c — exact source eligibility assessment

- **Base:** `346074b` (`AUD-12.S3b`).
- **Logic before → after:** candidate inputs had only adapter-level point/floor
  checks, while the source-selection contract was not connected to exact package,
  alignment, calibration/timing, floor or self-mask identities. The new pure gate
  validates the current bundle's confirmed RGB/LiDAR checksums, serialized record
  refs, mode-specific QA, aligned world-point receipt, floor evidence, mask pose
  coverage and bounded profile before any later publisher may proceed.
- **Hard blocker:** current calibration worker always leaves
  `projection_evidence_ref` empty and stores a separate `diagnostic_projection_ref`;
  projection evidence itself is typed `diagnostic_only`. A synthetic or inconsistent
  PASS report paired with that evidence remains blocked. Registered-map input also
  remains blocked pending AUD-19 registration QA. No source selection is enabled.
- **Data contract:** `LidarAlignedPointCloudEvidence` binds the exact package geometry
  to the confirmed `AlignmentRecord` and the world-meter point checksum/count.
  `LidarSelfMaskEvidence` binds the same alignment and point receipt plus package
  trajectory, robot profile, mask digest and pose coverage. `FloorFitEvidence` must
  use that same aligned-point receipt.
- **CodeGraph impact:** traced the bundle/align records, QA report and projection
  evidence, package record, floor evidence, collision adapter and eligibility helper.
  The gate records the exact source geometry alongside the QA/evidence refs. S3d owns
  candidate publication; source selection remains deferred until S3e ownership exists.
- **Changed files:** collision-quality contracts and exports, collision adapter
  self-mask ref check, calibration eligibility helper, new
  `src/services/reconstruction/lidar/collision_eligibility.py`, new focused tests,
  this task, ADR 0016 and the audit README.
- **Verification:** 8 eligibility tests and 81 focused LiDAR/collision/calibration
  tests passed; full `ruff check src/ tests/` passed; full `ruff format --check src/
  tests/` reports 556 files formatted; contract mirror passed; `git diff --check`
  passed. CodeGraph and Graphify are refreshed after the final edits.
- **Gate report:** no UI behavior changed. No aligned production point-cloud producer,
  production-qualified calibration receipt, held-out collision acceptance or Isaac
  contact proof was added. Candidate publication and source selection remain
  **UNVERIFIED** and open.

### AUD-12.S3d — fail-closed immutable candidate publication

- **Base:** `9618890` (`AUD-12.S3c`).
- **Logic before → after:** S3c produced an eligibility assessment but no publication
  path. `LidarCollisionCandidatePublisher` now reruns that gate, checksum-resolves
  each evidence ref, checks the supplied world-meter array against the exact aligned
  point receipt and floor evidence, and binds the boolean self-mask to its source
  checksum and ordering before it invokes the bounded builder. A blocked assessment
  returns its blockers without building or writing artifacts.
- **Output/contract:** an eligible internal call publishes a content-addressed GLB,
  `LidarCollisionBuildReport` and `LidarCollisionCandidateManifest`. The manifest
  binds source geometry, alignment, aligned points, floor/self-mask receipts, profile,
  assessment and output checksums. Candidate and report are immutable members; the
  manifest is the commit marker published last. A retry verifies and reuses exact
  bytes. No source selection or SceneIR mutation occurs in S3d.
- **Related-logic correction:** the aligned point receipt already binds points in
  world meters to the confirmed `AlignmentRecord`; S3d verifies that result instead
  of applying a second transform. Scene object ownership remains immutable and
  RGB-bound, so selection waits for S3e to map ownership onto the LiDAR candidate.
- **Changed files:** `src/services/reconstruction/adapters/lidar_collision.py`,
  `src/services/reconstruction/lidar/collision_eligibility.py`, new
  `src/services/reconstruction/lidar/collision_candidate_publisher.py`,
  `tests/test_reconstruction/test_lidar_collision_eligibility.py`, this task and
  ADR 0016.
- **Verification:** focused LiDAR collision, eligibility and quality-contract suites —
  54 passed; full-repo `ruff check src/ tests/` and `ruff format --check src/ tests/`
  passed (557 files); contract mirror and `git diff --check` passed; CodeGraph sync
  and targeted exploration passed; `graphify update .` completed.
- **Gate report:** publisher success-path tests inject an eligible assessment only to
  test artifact mechanics; the current projection contract is still fixed to
  `diagnostic_only`, so production input remains blocked. The local authenticated
  QA page for `job-a713242a38be`, run 2, had no completed QA stage; the correct
  unavailable-stage notice rendered and DevTools reported no console warnings or
  errors. No live metrics/overlay, production candidate, held-out collision result,
  GPU/Isaac contact proof or source-selection consumer was verified.
- **Pending:** no worker currently produces the point-order-bound self-mask array or
  a production-qualified projection receipt. Candidate publication mechanics are
  implemented, but production publication, S3e ownership/selection and S4 acceptance
  remain unchecked.
