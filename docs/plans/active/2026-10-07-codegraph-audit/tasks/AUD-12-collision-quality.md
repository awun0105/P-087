# AUD-12 — Collision cleanup, QA và selectable LiDAR collision

## Metadata và goal

- PLANNED; P0; EX-REC geometry, EX-SIM collision QA, PRODUCT selection/publication.
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
source refs/checksums, input/registration mode, alignment/QA refs, config checksum, effective resolution/
filters, output collision ref, supported coverage. CollisionQualityReport:
source/config/output identity, floor/support evidence, free-space consistency,
obstacle retention tests, observed/unsupported region refs, motion-suspicion
signals/source và limitations. Region evidence ghi source/frame/time/coverage;
absence of measurements không là free space. Report metrics không tạo GT accuracy
claim nếu reference là input trajectory hoặc cùng LiDAR nguồn.

Keep existing canonical RGB artifacts unchanged; explicit scale correction AUD-19
tạo new canonical target trước source selection. Collision ref
selection chốt cùng SceneEnvironment consumers ở S1. Ownership AUD-01 bind
selected collision geometry, không reuse mesh-face indices giữa RGB/LiDAR.
Filtering diễn ra source/sensor frame đúng; no global 2 m trajectory eraser.
Floor_band 0,15 là ablation parameter, không default universal. Low obstacles
phải giữ. Requested/effective config rõ; không âm thầm tăng resolution khi vượt
voxel capacity — chờ/block/explicit ROI/profile change theo khả năng runtime.

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
**Contract:** record exact source/config/hardware/robot envelope; label GT-assisted;
free-space proxy tách independent obstacle recall; acceptance thresholds freeze trước test.

Implement: reproduce metrics khi data/runtime có; otherwise preserve saved
evidence label. Build thin obstacle/floor fixtures: shelf legs/pallet feet/cable,
wall/ramp/low boxes, genuine narrow passage và camera offset. Define measured
retention/contact criteria; include unobserved/motion-suspected region diagnostics.
Define supported static-capture/observed-region evidence and consumer state:
unknown, inferred or motion-suspected geometry cannot claim verified physics.
Tests: benchmark parser/units/envelope, known clear vs real blocked, negative
"delete all geometry" must fail retention/support, source checksum mismatch,
moving/ghosted or unobserved-region fixture flagged rather than verified clear.
**Exit:** [ ] baseline conditions pinned; [ ] QA cannot pass empty-world solution.

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

Pending — source/profile/report/candidate identity, removals, proxy vs independent
metrics, supported sensors/coverage và GPU/Isaac limitations theo từng sprint.
