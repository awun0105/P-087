# AUD-19 — Automatic RGB–LiDAR map registration bằng floor, BEV và ICP

## Metadata và goal

- PLANNED; P1; EX-REC registration/geometry; EX-PRODUCT operation/API/UX;
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

Implement: define static-cloud unit/frame/header/point limits và source ownership;
inspect target-job ingest binding. Freeze scale/floor admissibility, ROI/search
budget, QA metrics/threshold qualification protocol và supported scene conditions.
State: requested/queued/running → proposed or ambiguous/insufficient/failed →
review/confirm → committed; user checkbox không forge QA PASS. Preserve old payloads.
Tests: old artifacts/checksums, missing/invalid units, input mode separation,
cross-job/project refs, unknown scale, unsupported floor, bad/empty cloud, stale target.
**Exit:** [ ] producer/consumer schema agreed; [ ] feature scope and supported input explicit.

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
**Exit:** [ ] supported ground-truth candidate retained in bounded search;
[ ] ambiguous/degenerate scenes not fabricated unique alignment.

## Sprint AUD-19.S3 — Constrained robust ICP và alignment qualification

**Input:** coarse candidates S2 + surface points/normals + frozen quality profile.
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
**Exit:** [ ] frozen acceptance and ambiguity rejection measured on supported data;
[ ] proposal confidence separated from absolute pose/geometry accuracy.

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
.venv/bin/pytest tests/test_reconstruction/test_rec06_lidar_metric.py tests/test_reconstruction/test_lidar_world_alignment.py tests/test_reconstruction/test_rec06_auto_scale.py tests/test_reconstruction/test_lidar_package.py tests/test_reconstruction/test_rec09_alignment.py tests/test_reconstruction/test_rec09_guards.py tests/test_reconstruction/test_lidar_overlay.py tests/test_reconstruction/test_finalize_lidar_binding.py -q
```

Planned tests/test_reconstruction/test_bev_registration.py,
tests/test_reconstruction/test_registration_qa.py và operation/API/frontend tests.
DONE cần supported independent-map runs + held-out QA + browser/consumer evidence;
19 baseline tests hoặc synthetic transform recovery không thay real acceptance.
Collision/Isaac safety còn nghiệm thu qua AUD-12.S4/AUD-05; no registration-score safety claim.

## Result / Evidence

Pending — source/target/config/tool refs, scale/floor identity, candidate transforms,
coverage/ambiguity/region metrics, known-reference errors vs consistency scores,
runtime/resource/search budget, no-point browser flow, manual fallback và limitations.
