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
