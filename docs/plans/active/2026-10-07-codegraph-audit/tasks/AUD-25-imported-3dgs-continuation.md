# AUD-25 — Xử lý tiếp scene 3DGS import thành SceneIR có objects và colliders

## Metadata và goal

- DEFERRED theo yêu cầu owner 2026-10-07 vì độ phức tạp; không implement trong
  kế hoạch hiện tại. Sáu sprint bên dưới chỉ giữ làm thiết kế tham khảo; không là
  dependency của active tasks, chỉ mở lại khi owner yêu cầu.
- P1 nếu mở lại; EX-REC source/geometry; EX-SCENE objects; EX-PRODUCT jobs/Studio;
  EX-SIM candidate/validation consumers.
- Canonical REC-04/05/06/09, SCENE-02/03/06/08, SIM-02/04/07,
  PRODUCT-02/04/06/08/09/10/11; task-local extension, không đổi foundation IDs.
- Owner muốn PLY/SOG là input để pipeline xử lý tiếp từ Gaussian source có sẵn;
  SuperSplat export cả hai formats, không bắt user tự convert trước upload.
- Goal: imported Gaussian source → metric/floor confirmation → geometry/object
  preparation → editable SceneIR DRAFT → existing candidate/validation/review flow.
- Giữ riêng luồng import 3DGS hiện tại. Sau READY, user chọn xem bằng scene viewer
  hoặc Xử lý tiếp để tạo linked processing job. Không bắt user mở viewer mới có nút.
  Upload chung nhận diện Gaussian thì hand off sang import; không tự chạy processing.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0025](../../../../decisions/0025-imported-3dgs-continuation.md).

## Baseline và scope

ImportService hiện nhận gaussian_ply/gaussian_ply_colmap, publish SOG và READY;
detector chưa nhận SOG làm input, SOG hiện là delivery format. AUD-06 mở durable
view import cho PLY/SOG; chưa tạo processing job/bundle hoặc continuation.
3DGS đã là 3D visual representation; tính năng mới thêm geometry,
objects/colliders và simulation preparation, không phải làm file đó thành 3D lần đầu.

CodeGraph: uploads/scene_imports.py, FinalizeWorker._execute/floor_seed, VisualResolver.load,
RgbGeometryService và scene/objectify.py. Finalize hiện yêu cầu metric confirmation
từ preview, source_camera_poses/frame_set, first camera seed và camera-bounded crop.
VisualResolver chỉ nhận BrushVisualArtifact đúng frame/training lineage. Semantic
objectify dùng real camera views/frames. Import delivery_ref là VisualArtifact SOG,
không thể đưa ref đó vào các consumers này bằng cách đổi artifact_type/job_id.

Owned: shared source/preparation contracts/resolvers, import-to-job binding và queue,
source canonicalization/geometry adapters, scene extraction/publication, source-aware
candidate/verifiers, API/frontend import workspace/scene/progress và focused tests.
Minimal shared ports reuse REC math/voxel/packaging, geometric extraction, SceneEditor,
admission/quota và exporters. Không giả RGB/Brush run, tạo dummy camera/frame artifacts,
disable checksums hoặc viết lại import thành completed video job.

## Các mức input và capability

| Nhóm | Input | Xử lý tiếp |
|---|---|---|
| G1 | Gaussian PLY hoặc bundled SOG hợp lệ, không source cameras/images | View; declare/confirm units/scale/up/floor/ROI; Gaussian-derived coarse geometry; geometric/manual object correction. No semantic-image inference hoặc COLMAP claim. |
| G2 | PLY/SOG + verified COLMAP/camera metadata, optional original images/video | Reuse poses/ROI khi model đúng frame/capture; images đúng bindings mới enable image-assisted extraction. Cameras không có images vẫn dùng G1 extraction. Không retrain 3DGS chỉ để tạo receipt. |
| G3 | PLY/SOG + same-scene LiDAR và metadata cần cho selected LiDAR recipe | Reuse AUD-24 fusion/odometry nếu raw; AUD-19 registration/metric support; AUD-12 qualified collision source. Gaussian visual giữ nguyên vai trò, không đổi thành LiDAR visual. |

G1–G3 là import-continuation capabilities có thể kết hợp, khác R1–R6 của video
reconstruction. Một PLY point cloud/triangle mesh không có Gaussian fields không
tự là 3DGS import. ZIP có COLMAP không chứng minh images/cameras/model cùng scene
hoặc units metric. SuGaR là hướng mesh khả thi khi có compatible pretrained model
và COLMAP dataset; không là bare-PLY drop-in và không mandatory dependency của task.

## Nhược điểm và cách xử lý

| Hạn chế | Ảnh hưởng khi xử lý tiếp | Implementation/acceptance |
|---|---|---|
| Gaussian appearance không là measured surface | Floaters, holes/unobserved regions và thin obstacles làm collider sai dù viewer đẹp | S3 dùng quality/coverage/obstacle-retention gates; manual correction hoặc qualified LiDAR source; không claim render quality là collision PASS. |
| Units/up/floor có thể thiếu | Scale sai hoặc plane sai làm mọi collider/export lệch | S2 yêu cầu declaration/reference/alignment phù hợp và floor/ROI confirmation; thiếu independent reference thì accuracy unknown. |
| Bare PLY/SOG thường không có capture images/poses | Existing image-assisted SAM2/seed/crop consumers không dùng trực tiếp; geometric/manual path ít tự động hơn | S1–S4 source-aware adapters; G1 geometric/manual, G2 verified real image/camera bindings; no fake capture metadata. |
| SOG lossy hoặc export đã giảm SH/xóa splats | Decode không khôi phục dữ liệu đã mất; quality cần đánh giá theo actual source | Preserve uploaded bytes, use original PLY khi đó là chosen import source; decoded SOG giữ quantization/field provenance; qualified tolerances, không re-encode vòng lặp. |
| Import READY trước continuation cần packaging/readability và giữ derived artifacts | Thêm thời gian import, CPU/GPU/RAM/storage; processing vẫn cần admitted worker | Reuse exact verified packaging/source refs, bounded decode, profile/resource diagnostics; measure source-specific latency/storage, không chạy lại COLMAP/Brush. |
| Viewer state khác persisted processing source | Camera display/unsaved edits có thể làm user tưởng đang xử lý bản nhìn thấy | S5 bind original hoặc saved source snapshot và hiện source choice; viewer camera không capture camera, no silent source selection. |

Tách import/view khỏi processing không làm giảm khả năng của thuật toán. Cần
giữ lifecycle độc lập: import READY/view không bị overwrite khi derived job fail,
cancel hoặc cần xác nhận metric. Nút Xử lý tiếp báo missing capabilities và tạo
job khi user chủ động chọn; không tự spend Guest quota khi import/view.

## Input / output / data contract

Input: authorized READY import_id/source revision, verified original Gaussian PLY/SOG
hoặc explicit saved edited snapshot, exact byte refs/checksums, selected processing
profile, optional assembly/COLMAP/image/LiDAR refs và user metric/floor/ROI decisions.
Default source là actual uploaded master đã verify: SOG-only import dùng chính SOG
đó; không yêu cầu original PLY. Nếu có cả PLY/SOG thì bind source được chọn, không
merge hoặc giả hai file cùng export. Unsaved viewer edits cần saved immutable
snapshot nếu user muốn xử lý bản đang sửa; UI không silently dùng original.
Snapshot giữ source import/upload lineage và format validation.
Xử lý tiếp binds exact READY import/source snapshot; worker re-verifies bytes và
decode support trước geometry. Không tạo job bằng delivery_ref giả Brush manifest.
Frame extraction/COLMAP/3DGS training không cần chạy lại khi đã có Gaussian source;
source-aware stages bắt đầu từ decode/metric/floor preparation. Import READY là
source/view availability, không geometry QA; xem viewer và processing là hai lựa chọn.

SOG reader/decoder dùng qualified pinned runtime, không tự viết codec mới khi port
hiện có đáp ứng. Validate bundled ZIP + meta version/model/count/ranges/codebooks,
required textures/dimensions/channels, local member references và decoded finite
Gaussian fields; bounded bytes/count/decode memory. No external member fetch.
SOG quantization lossy; lossless WebP chỉ giữ quantized values, không phục hồi độ
chính xác PLY trước nén, SH đã bỏ hoặc splats đã bị xóa khi export. Internal
Gaussian arrays/derived PLY là decoded artifacts, giữ input/output checksums,
decoder/tool version, field/SH coverage và quantization provenance. Không ghi
derived PLY thành original PLY hoặc recovery of lost observations.

Qualified bundled .sog là required input; unbundled meta.json+textures, compressed
PLY dialects và Streamed SOG/LOD chỉ enable khi support matrix kiểm chứng riêng.
LOD fragment không được coi complete source. Rendering-readable khác geometry-
decoder compatible; thiếu decoder báo continuation capability unavailable, vẫn
giữ view khi viewer hỗ trợ. Reuse exact verified SOG delivery khi chỉ xem; không
bắt re-compress. Geometry processing qua worker/admission, không API/browser decode
toàn scene rồi giả server verification. Canonical output encode profile explicit.

Proposed ImportedGaussianSourceArtifact: schema/version/origin=user_import,
source/import/snapshot refs and checksums, format/dialect/SOG version/model,
decoder/config/tool identity, decoded refs/fields/SH/count và compression provenance,
source frame/unit/scale status, optional verified camera/frame bindings,
rights/privacy provenance, config/tool version và content checksum.
Proposed source-capability report: view/metric/geometry/geometric_objects/
image_assisted_objects/LiDAR_collision/candidate capabilities, missing facts,
unsupported reasons và exact source/config identity. Capability availability khác QA PASS.

S1 chọn minimum typed source adapter/discriminated source contract cần cho consumers;
legacy RGB Brush manifests vẫn strict. Imported visual không giả Brush training IDs,
held-out frames/quality evidence. New source-aware preparation/bundle contract chỉ
serialize verified optional camera/image refs khi có; update all readers of required
camera_pose_refs[0], rgb_frame_refs, metric_visual_master/seed/ROI semantics.
Không blanket optionalize shared fields mà consumer vẫn dereference như cũ.

Metric decision: source refs, scale s>0, rigid source→world transform, method/origin
(declared units/measured reference/qualified alignment), floor/up/ROI evidence,
confirmation actor/checksum và uncertainty/unknown fields. Missing scale/floor không
tạo canonical metric geometry. Real metric reference khác declared assumption;
không serialize missing independent_error_m thành zero hoặc forge Verification PASS.
Rigid Transform không chứa scale; preserve existing canonicalization semantics.
Format coordinate convention, source up axis và canonical Z-up cần explicit binding;
không áp SOG Y-up convention rồi double-rotate existing source metadata.

Apply same similarity to visual, geometry, camera poses khi có và Gaussian
covariances/scales/orientations; SH/view consistency cần qualification. Publish
new canonical master/delivery/geometry refs, không mutate original/saved snapshot.
Gaussian indices thuộc exact source/decoded artifact; format conversion có thể
reorder. Membership/splitting phải bind decoded source identity hoặc explicit
index mapping, không dùng PLY indices lên SOG vì count giống nhau.
Camera-dependent crop/seed có source-specific alternatives: confirmed ROI/bounds
và checked floor/navigation seed; virtual viewer camera không thành capture pose.

Output: immutable prepared source/canonical artifacts, estimated geometry+QA,
extraction membership và SceneIR revision DRAFT, linked processing job/progress;
candidate chỉ qua existing supported export/validation gates. Original import
READY/delivery vẫn giữ; processing failed/cancelled không biến import thành FAILED.
Store import→derived job relationship with original upload/assembly lineage,
exact source revision/decisions/recipe và
operator/owner lineage. Continuation là new run, không resumable RGB training attempt.

Ownership theo AUD-20/21: source/target guarded; Guest chỉ continue own import;
Editor/Reviewer intervention không chuyển source ownership. S1 bind target creator/
owner/actor rõ theo shared matrix, không gán legacy unknown owner bằng current login.
One accepted continuation intent charged to initiating actor theo AUD-22; child
geometry/objectify/registration không charge thêm. Manual Retry counts as accepted
manual run; duplicate/automatic worker attempts không thêm charge.
Import/view-only không spend Guest processing quota. Explicit Xử lý tiếp tạo một
new run; source decode/geometry/objectify child work không charge thêm. Reuse
verified delivery/packaging nếu compatible, không re-encode chỉ vì tạo linked job.
Metric/floor confirmation của run đang chờ
input tiếp tục cùng intent; không tự biến confirmation thành manual Retry/new job.

Progress records actual executed/reused/external/not-required stages with reasons
và compatible serialization; không mark COLMAP/Brush SUCCEEDED hoặc timing=0 như
đã chạy. Privacy/rights declarations của import/images không thành verified QA.
New source/profile/metric decisions invalidate derived geometry/scene/candidate/
validation; edited SceneIR không bị overwrite bởi late source canonicalization.

## Logic change và dependent updates

Risk: **Rất cao** nếu chỉ thêm CTA. Logic delta: external visual origin và optional
capture metadata trở thành supported processing source sau import.
Cần sửa đồng bộ: InputKind/upload/import allowlists và shared format registry,
SOG validation/decoder, source contracts/resolvers, import/job/assembly relationships,
metric canonicalizer/finalize seed+crop, Gaussian geometry/QA, geometric/semantic
objectify, bundle/views/SceneComposer, CAS editors/exporters/verifiers, queue/quota/
auth/status và ImportWorkspace/SceneWorkspace/API/TypeScript/tests.
Acceptance xuyên consumer: G1 không dummy cameras; G2 uses verified real bindings;
G3 qualified collision; import remains viewable; DRAFT/candidate không tự là release.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 dùng AUD-06 source/import lifecycle, AUD-24.S1 assembly port, AUD-21 permission
matrix và AUD-10 publication semantics; source adapter có thể design trước consumers.
S2 dùng S1 và AUD-14.S1 floor evidence; optional G3 dùng AUD-19 qualified registration
port với source-space proxy contract S1, không fake metric GeometryArtifact.
S3 dùng S2, AUD-12.S1 quality protocol/cleanup; G3 source gate theo AUD-12/19.
S4 dùng S3, AUD-01/08/09 source membership/edit/collider ports và AUD-10 CAS.
S5 dùng AUD-06/AUD-07 durable ports, AUD-22 quota, AUD-24.S3–S4 UI/binding; enable
only supported source/worker modes. S6 dùng AUD-02/03/04/05 export/runtime gates,
AUD-12/19 qualification; raw estimated G3 cần AUD-17.S3. Không đợi whole AUD-25
để implement AUD-19: source adapter S1 review trước, imported-source QA ở S6.

## Sprint AUD-25.S1 — Import source, capability và downstream contract

**Input:** current import/Brush/metric/bundle/objectify contracts, PLY/SOG G1–G3 fixtures.
**Output:** typed source/capability/decision/continuation DTOs và consumer inventory.
**Contract:** source origin truthful, optional camera/image capability explicit;
PLY/SOG visual khác physical geometry; decoded SOG không là recovered original;
old RGB/import payloads/checksums remain valid.

Implement: trace resolvers/views/seed/crop/bundle/extraction/export consumers;
define minimum source adapter and compatible preparation contract. Extend typed
input-kind/upload/import/API/TypeScript enums and all serializers/allowlists for
SOG using AUD-06/24 shared format ports; don't overload gaussian_ply. Qualify pinned
SOG decoder and supported version/model/SH/limits with real SuperSplat exports.
Agree ownership,
source snapshot selection, metric evidence levels, supported Gaussian dialect/SH/
limits, geometry methods and stage-status semantics. Source-space registration
proxy may use arbitrary units with explicit uncertainty, never canonical metric ref.
Tests: bare PLY/SOG, source+COLMAP without images, model/image mismatch, non-Gaussian
PLY, corrupt meta/textures, unsupported version/model, unsafe/duplicate/truncated
ZIP, decode bounds/nonfinite values, wrong artifact_type/origin, old records,
foreign/unknown-owner import, unsaved edits, PLY/SOG source choice and SH reduction.
**Exit:** [ ] source-aware shared contract agreed; [ ] no forged capture/training metadata.

## Sprint AUD-25.S2 — Metric/floor confirmation và canonical source

**Input:** S1 source + declared/measured/qualified metric/up/floor/ROI decisions.
**Output:** immutable canonical Gaussian master/delivery và applicable pose refs.
**Contract:** exact same transform across consumers; unknown metric not verified;
virtual camera/ROI/seed khác source capture trajectory.

Implement: decode SOG to immutable internal Gaussian data/derived PLY with truthful
lineage, reuse scale/transform/packaging ports through import adapter. Offer
known-unit/reference measurement and fitted-floor confirmation; G3 coarse source
proxy/alignment may propose scale before final canonicalization. Bind selected
proposal/ref to explicit confirmation; keep source proxy distinct from final collision.
Update seed/crop logic for no-camera source; validate Gaussian orientation/covariance/
log-scale and SH appearance under transformed views. No MoGe accuracy claim from
rendered synthetic images, no metric receipt fabricated to pass existing resolver.
Tests: known scale/rigid transform and projection, covariance/SH/quantization
consistency, Y-up→Z-up without double conversion, unknown units/up/floor, wrong
plane, ambiguous map fit, source changed after decision, reordered source membership.
**Exit:** [ ] canonical refs verify; [ ] source and derived decisions/provenance align.

## Sprint AUD-25.S3 — Gaussian/LiDAR geometry và quality gates

**Input:** canonical source/ROI/seed S2 + selected geometry/cleanup profile.
**Output:** coarse collision/surface candidate, metadata/coverage và QA artifacts.
**Contract:** Gaussian-derived occupancy is estimated geometry; clean mesh không
tự là measured physical truth; missing coverage/reference remains explicit.

Implement: reuse SplatTransformVoxelAdapter independently of Brush-only resolver;
add source adapter for PLY/SOG decoded fields at agreed port, no new mandatory mesh
model. Gaussian support/orientation/opacity conventions must match selected dialect.
Decode/voxel memory remains bounded; no full in-memory duplicate per downstream stage.
AUD-12 cleanup and
AUD-14 floor preserve low/thin obstacles; G3 can select qualified LiDAR collision.
Capture counts/density/floaters, ROI/unobserved coverage, seed clearance and failure
reasons. Poisson/other surface methods only after qualified input/normals/profile,
not blindly meshing Gaussian centers as observed surface. Keep actual config while waiting.
Tests: floaters, floor-only/low/thin structures, crop/seed without cameras, empty/
degenerate cloud, source checksum mismatch, format-specific geometric tolerances,
imported-vs-RGB parity on supported data; lossy differences not hidden as exact equality.
**Exit:** [ ] estimated/qualified states truthful; [ ] geometry source feeds same downstream ports.

## Sprint AUD-25.S4 — Object extraction và editable SceneIR

**Input:** S3 geometry/master and source capabilities, optional verified frames/poses.
**Output:** extraction candidates/membership, environment/object visuals/colliders,
committed SceneIR DRAFT and correction/editor actions.
**Contract:** no-frame G1 uses geometric/manual path; image-assisted path only real
qualified bindings; objects require confirmation, geometry source ownership stable.

Implement: extend geometric extraction/source adapters and manual boxes/reassign;
enable existing SAM2 path only for supported G2 images/cameras. Update objectify
working-set/ROI assumptions and gaussian_split/master lineage; preserve background
membership and AUD-01 carve behavior. Publish via shared CAS, reuse AUD-08/09 editors
and current catalog/physics confirmation. Unknown semantics/physical properties not
filled as measured truth; failure in chosen semantic runtime not silently switched.
Tests: G1 no camera dereference, G2 missing/misaligned images, membership partition,
move/delete/merge/collider edit, reobjectify stale revision, background export parity.
**Exit:** [ ] editable DRAFT through supported path; [ ] membership/revision/geometry consistent.

## Sprint AUD-25.S5 — Durable continuation command và Studio UI

**Input:** READY import/source revision, S1–S4 worker recipe và authorized user.
**Output:** Xem scene và Xử lý tiếp actions trên import/card/workspace, linked job/status và
immutable accepted source decisions.
**Contract:** original import remains viewable; one manual intent; no fake video
pipeline completion; failed processing does not overwrite import or user scene edits.

Implement: continuation endpoint/service, atomic intent/job/link and idempotency;
reuse queue/admission/lease/fencing/cancel/retry. Show capability/missing-data setup,
saved snapshot choice, metric/floor/ROI and real stages. Existing separate import
flow/deep links stay; unified upload detects PLY/SOG then routes to same import
ports via AUD-24. After READY, expose Xem scene and Xử lý tiếp, with no automatic
processing job on import completion. Show source format/available capabilities and SOG-derived limitations
without requiring user to convert formats manually.
Xử lý tiếp enters decode/capability then metric/floor/geometry/object stages;
READY import required, actual viewer visit optional. Reuse original validated
upload/snapshot, not compressed delivery when richer original exists. Import READY
doesn't bypass worker source/profile checks; failures keep source and diagnostics.
Use source/target ownership gates and charge actor at accepted run only. Worker
version compatibility precedes enabling recipe; no API-process geometry/objectify.
Tests: two simultaneous continuations, stale snapshot/decision, Guest own/foreign,
Editor/Reviewer intervention, quota/manual/auto retry, restart/cancel/publication,
API+real browser import→READY→view and import→READY→continue→DRAFT, continue from
card without opening viewer, import alone no processing intent/quota, one charge
for accepted continuation, original viewer after processing failure.
**Exit:** [ ] durable command/status correct; [ ] one quota intent and retained source viewer.

## Sprint AUD-25.S6 — G1–G3 consumer/runtime qualification và rollout

**Input:** completed source pipeline + real external Gaussian captures and references.
**Output:** qualified supported profiles, migration/rollout evidence and candidate flow.
**Contract:** no universal watertight/industrial-safe mesh claim; existing validation/
release requirements unchanged; source-specific insufficient evidence stays blocked.

Implement: qualify real SuperSplat PLY/SOG exports for bare, rich camera/image
package and registered/raw LiDAR variants; record dialect/tool/input/decision/
quality identity and source export settings when known. PLY/SOG pair comparison
uses spatial/covariance/render tolerances and field coverage, not index equality
or guaranteed original precision. Test canonical
visual/geometry/SceneIR/USD parity and obstacle retention on independent reference
when available. Verify real SOG runtime/browser and supported pxr/Isaac candidate
validation, review/sealing identity. Run forward compatibility for legacy imports/
RGB jobs and source-aware bundle consumers; no retrospective VERIFIED claims.
Tests: held-out captures/known transforms, material coverage/degeneracy failures,
camera/SH/metric/render consistency, exact validation bindings, worker/version/CAS
recovery, browser edit/export and unchanged source import after cancellation.
**Exit:** [ ] enabled G1–G3 profiles qualified; [ ] pending/unsupported clearly named;
[ ] real candidate/runtime proof separated from fixture or viewer-only acceptance.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_scene_imports.py tests/test_reconstruction/test_input_detection.py tests/test_contracts/test_input_manifest.py tests/test_reconstruction/test_rec05_scale.py tests/test_reconstruction/test_lidar_world_alignment.py tests/test_reconstruction/test_rec09_alignment.py tests/test_orchestration/test_scene_editor.py tests/test_api/test_studio_routes.py -q
```

Frontend focused: tests/studio-input-flows.test.tsx, tests/input-kinds.test.ts,
tests/object-review.test.tsx. Add source/canonicalization/geometry/continuation/
consumer tests first, then exact focused commands. Ruff/lint/typecheck and relevant
runtime/browser gates apply implementation. Fixtures prove contracts, not real
Gaussian geometry quality, renderer compatibility or simulation safety.

## References và Result / Evidence

- [SuperSplat import/export](https://developer.playcanvas.com/user-manual/supersplat/editor/import-export/):
  exports PLY and bundled SOG; export may reduce SH and includes visible splats only.
- [SOG format specification](https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/sog/):
  ZIP metadata/textures, versioned fields and lossy quantization; lossless WebP
  preserves quantized values, not pre-quantization data.
- [SplatTransform official implementation](https://github.com/playcanvas/splat-transform):
  PLY/SOG read/write port to qualify against the installed/pinned project runtime.
- [SuGaR official implementation](https://github.com/Anttwo/SuGaR): pretrained
  Gaussian input still used with COLMAP dataset; not guaranteed bare-PLY mesh recovery.
- [Open3D surface reconstruction](https://www.open3d.org/docs/release/tutorial/geometry/surface_reconstruction.html):
  methods have input assumptions including normals; applicability to Gaussian
  occupancy requires separate qualification, không suy correct surface từ algorithm name.

Owner clarification: giữ riêng luồng import hiện tại; READY có Xem scene hoặc
Xử lý tiếp. Direct processing from upload không là required entrypoint của task.

Deferred — owner hoãn task ngày 2026-10-07 vì độ phức tạp. Không implement source
continuation, geometry/object preparation hoặc nút Xử lý tiếp trong active scope.
AUD-06/24 vẫn hỗ trợ import/view PLY/SOG, không phụ thuộc task này. Thiết kế và
sáu sprint được giữ để tham khảo; chưa có continuation implementation/evidence.
