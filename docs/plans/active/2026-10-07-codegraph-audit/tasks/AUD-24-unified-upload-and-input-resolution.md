# AUD-24 — Một khung upload, nhận diện tập file và tự chọn luồng xử lý

## Metadata và goal

- PLANNED; P1; EX-PRODUCT upload/Studio/dispatch; EX-REC input adapters.
- Canonical REC-02/03/06/08/09, PRODUCT-02/04/08/09; task-local extension.
- Owner yêu cầu: thả tất cả file vào một khung; hệ thống xác định các file dùng
  được cho luồng nào. Không bắt chọn RGB-only/sensor/map/odometry trước upload.
- Goal: file inventory → resolve capabilities/missing data → recipe có thể kiểm
  tra → một accepted job intent; reuse pipeline và producers hiện có.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0024](../../../../decisions/0024-unified-upload-and-input-resolution.md).

## Baseline và scope

CodeGraph: UploadDropzone nhận kind và chỉ lấy files[0]; NewSceneFlow có source
routes; VideoSetupStep chọn video và LidarPackageSection riêng. detect_stream
nhận diện từng file, reject bare cloud; _detect_lidar_package yêu cầu calibration/
TUM/frame_times trước khi trả complete input kind. create_scene_from_upload nhận
video upload_id và một optional LiDAR upload. InputManifest đã có list InputFile,
nhưng registered_lidar_present yêu cầu metadata; chưa có grouped staging/resolver.

Owned: frontend dropzone/draft/setup/API contracts; per-file staged uploads/direct/
proxy verification; content classifiers và assembly resolver; manifest/project/job
binding, worker routing/adapters, upload ownership và focused tests. Source là
baseline để tìm impact; không giữ rejection của bare cloud trong mode mới khi
static-cloud registration đã được qualified. Legacy complete-package APIs vẫn
validate đầy đủ; staging file không tự là runnable package.

Trong scope video reconstruction: một selected RGB video và LiDAR/metadata optional,
file rời hoặc safe ZIP. Gaussian PLY/SOG import dùng cùng upload UI, reuse AUD-06
cho view; [AUD-25](AUD-25-imported-3dgs-continuation.md) đã Deferred nên không thêm
continuation recipe/job/CTA. Sample replay không là new job. R1–R6 bên dưới chỉ là
video recipes; PLY/SOG handoff sang import để xem, giữ existing separate import flow.
Không thêm multi-video stitching, multi-camera reconstruction, generic format
converter hoặc standalone LiDAR-only product workflow.

## Các tổ hợp khả thi và route

| Nhóm | Input tối thiểu | Recipe và điều kiện |
|---|---|---|
| R1 | RGB video | Existing RGB reconstruction, metric/floor confirmation. Metadata thêm phải được bind hợp lệ hoặc user explicitly exclude; không bỏ file lỗi ngầm. |
| R2 | RGB + registered static LiDAR map | AUD-19 map registration; units/frame/same-scene/overlap và geometry QA. Calibration/TUM/frame_times không bắt buộc cho map mode. |
| R3 | RGB + một raw/static .pcd/.ply cloud | Treat as one static observation, normalize declared units/frame và AUD-19 registration nếu đủ overlap. Không estimate multi-scan trajectory từ một file đơn. Không tự coi coverage là toàn kho. |
| R4 | RGB + raw scan sequence + supplied trajectory | Verified scan→pose bindings, units/up transform; reuse fusion để tạo registered map, rồi AUD-19. Thiếu camera calibration/timing không chặn geometric map mode; không fake sensor package để gọi ingest. |
| R5 | RGB + raw scan sequence thiếu trajectory | Ordered/time-described supported scans → AUD-17 estimated trajectory → fusion/map → AUD-19. Camera calibration/frame_times chỉ dùng sensor priors khi timing/QA đủ. |
| R6 | RGB + LiDAR raw hoặc registered + camera↔LiDAR calibration + trajectory + RGB timing binding | Sensor-guided RGB priors/alignment và AUD-13 QA. Raw cloud còn fusion; registered cloud reuse. Trajectory có thể supplied hoặc estimated với provenance đúng. |

RGB+LiDAR+calibration thuộc R2/R3/R4/R5 tùy cloud/trajectory, không mặc định R6.
Calibration+frame_times thiếu TUM có thể dùng R5 khi scan sequence đủ điều kiện,
hoặc R2 khi cloud đã là map. Calibration+TUM thiếu frame_times chỉ thành R6 khi
video PTS/source mapping và declared clock relation đủ derive binding; nếu không,
R2/R4 là alternative cần user biết metadata nào không dùng. TUM timestamps không
tự cho clock offset của video. Intrinsics/distortion cần cho projection QA có
thể supplied hoặc derived từ qualified COLMAP output theo AUD-13.

## Input / output / data contract

Input: authenticated draft/assembly owner, selected File[] hoặc verified upload
refs; archive member inventory; compression config; available verified metadata;
user declarations nếu units/cloud frame/capture/clock không xác định được.
Multiple videos/maps/trajectories/calibrations không tự pair theo filename/mtime.
Đề xuất bindings khi có evidence; ambiguous thì hỏi lựa chọn ngay trong cùng UI.

Proposed InputAssemblyManifest: schema/version, assembly_id/revision/owner,
immutable per-file refs/byte SHA256/size + member identities; role candidates và
selected bindings; declared units/frame/cloud state/same-scene/capture/clock;
normalization/preparation refs; provenance và canonical assembly checksum.
Client-declared facts tách server-observed facts; refs phải authorized/checksummed.
Staging record mutable/revisioned tách khỏi committed manifest/report bất biến.
Gaussian master selection binds exact PLY/SOG upload/snapshot and format metadata.
Two PLY/SOG files không tự là cùng export; không merge, duplicate jobs hoặc apply
indices qua formats. Recommend verified richer PLY when appropriate, but source
choice explicit nếu relationship chưa chứng minh. SOG-only remains usable source.
Video+Gaussian yêu cầu chọn video reconstruction hoặc Gaussian view import; không
tự chạy cả hai. Không bind video/camera thành G2 continuation vì AUD-25 Deferred.

Proposed InputResolutionReport: exact assembly checksum/revision, resolver/profile
version, file role evidence, candidate recipes và recommended recipe, required
facts/missing fields, capability/runtime compatibility, state ready/needs_input/
pending_verification/unsupported/invalid, reasons và explicitly excluded files.
ready chỉ là input/recipe executable, không là calibration/alignment/physics PASS.
Recipe binds producers/config/tool versions, supplied/estimated trajectory origin,
scan→pose và RGB→time bindings, normalization identity và required QA stages.
Shape/version/shared placement chốt S1; không thêm arbitrary JsonObject để bypass DTO.

Resolver ưu tiên supported sensor route khi structural metadata/bindings đủ,
otherwise supported map route hoặc scan-fusion/estimate route; không claim route
nhiều metadata luôn chính xác hơn. Invalid/conflicting metadata trả remediation,
không silently exclude hoặc switch RGB-only. Alternative hiện rõ files/metadata
không dùng và user chọn trước Run. Runtime thiếu module khác thiếu GPU headroom:
module incompatible báo unsupported/remediation; resource waiting giữ chosen recipe.
Unknown units/registered state/clock không đoán từ extension, file count hay naming.

Nén RGB local trước upload theo AUD-23; grouping không thay bytes/hash của LiDAR
hoặc metadata. Output frame/pixel mapping được dùng khi resolve sensor recipe.
Đổi file/config/binding tạo assembly revision mới, invalidate resolution cũ;
accepted job giữ immutable manifest/recipe. Worker re-verifies bound refs/version,
không đọc mutable latest draft hoặc tự resolve sang route khác sau retry.

Một Run được chấp nhận tạo một quota intent theo AUD-22; probing/upload/resolution
không tính lượt job. Odometry/fusion/registration child work của cùng intent không
charge thêm; manual Retry và separate explicit new run giữ existing quota policy.
Server kiểm owner/resource refs và CAS; request trùng không enqueue/charge lại.
Không merge project/job ownership khi dùng cross-user upload refs.

R4 map adapter dùng fusion/geometry ingest riêng với verified pose/frame lineage;
không tạo identity calibration hoặc giả frame_times để thỏa LidarPackageRecord.
New raw/partial assembly contract được materialize thành canonical artifacts khi
producers hoàn tất; InputManifest modality flags phản ánh đúng semantics/version.
Old manifests/packaged inputs vẫn đọc được, không rewrite checksums hay ZIP gốc.

## Logic change và dependent updates

Risk: **Rất cao** nếu chỉ đổi dropzone. Logic delta: per-file upload kind khác
processable assembly; auto routing thay user chọn technical input mode.
Cần sửa đồng bộ: upload completion/classification, input DTOs/manifest, grouped
ownership/persistence, project/create/quota, REC stage routing/fusion/priors,
AUD-17/19 adapters, preparation/cache keys, Studio setup/status/retry và tests.
PLY/SOG format detection, import enums/registry/delivery refs và view source
selection phải dùng cùng semantics; archive có SOG không bị coi LiDAR ZIP.
Acceptance xuyên consumer: loose files/ZIP cùng recipe khi cùng content/bindings;
unknown metadata không fake PASS, stale assembly không tạo job, retry dùng recipe gốc.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 dùng AUD-23.S1 media identity và current manifest/runtime contracts; phối hợp
AUD-17/19 design ports, không đợi full implementations. S2 dùng S1 và AUD-06.S1
shared format/validation ports. Geometry continuation đã Deferred, không là dependency.
S3 dùng S1/S2, AUD-21 guards, AUD-22 atomic intent, AUD-07 admission và AUD-23.S3
sensor mapping; AUD-06 nếu dispatch existing 3DGS import. Chỉ enable recipes có
compatible runtime/consumers; structural detection vẫn hiển thị future route unavailable.
S4 dùng S2/S3 và AUD-23.S4 upload lifecycle. S5 cần AUD-13/14/19 qualified paths,
AUD-17.S3 cho estimated raw mode, AUD-23.S5 media acceptance; không đợi AUD-18.
AUD-17/19 implement consumer ports từ S1; không tạo whole-epic dependency cycle.
AUD-06.S1 chốt SOG view-import ports. AUD-25 Deferred; S1–S5 không đợi hoặc implement
source adapter, geometry decoder qualification hay continuation command từ task đó.

## Sprint AUD-24.S1 — Inventory, capability matrix và assembly contracts

**Input:** current upload/detection/manifest/create-job source; R1–R6 fixtures.
**Output:** typed staged-file/assembly/resolution/recipe contracts và binding matrix.
**Contract:** registered map khác RGB alignment; calibration không tự là trajectory;
observed/declared/estimated khác verified; new raw mode không giả legacy package.

Implement: CodeGraph callers và route/config inventory; freeze actual supported
file formats/limits, roles, clock/frame conventions, ambiguous selection semantics,
recipe precedence/alternatives và qualified-runtime registry. Reuse shared DTO/
checksum/resolver ports. Agree raw-map fusion adapter với AUD-17/19 và canonical
manifest transition; define forward/read compatibility and worker rollout order.
Define Gaussian PLY/SOG view/import intents separately from R1–R6; shared format
validation/version ports coordinated AUD-06. Không design active G1–G3 processing schema.
Tests: seven owner-listed combinations mapped into R1–R6, single cloud vs sequence,
camera vs sensor trajectory conventions, missing clocks/units, old payload checksums.
**Exit:** [ ] no duplicated pipelines; [ ] producer/consumer contracts and recipe matrix agreed.

## Sprint AUD-24.S2 — Content classifiers và deterministic input resolver

**Input:** S1 staged refs/member inventory + verified cheap probes/declarations.
**Output:** versioned resolution report với recommended/alternative/blocked recipes.
**Contract:** filename/extension không là proof; ambiguous/invalid không auto ready;
structural availability không là geometry QA PASS.

Implement: bounded classify video/cloud/Gaussian/calibration/trajectory/timestamp
contents, including bundled SOG meta/textures rather than extension-only match;
safe ZIP member/path/count/decompressed-size handling. Allow valid loose
metadata/PCD trong authenticated assembly staging, retain legacy detector semantics.
Detect conflicting/duplicate candidates and create explicit bindings; clock/scan
timestamps khác RGB frame_times. Same accepted files/declarations/config gives same
semantic recipe, independent drop order; accepted scan chronology remains explicit.
Tests: reorder files, misleading extensions, TXT/JSON multi-role ambiguity, unsafe/
truncated ZIP, SOG vs LiDAR/COLMAP ZIP, corrupt/unsupported SOG, ambiguous PLY+SOG
master or video+3DGS intent, unrelated meta.json/WebP files, contradictory timestamps,
unsupported format. No geometry decode in cheap API probes; worker re-verifies.
**Exit:** [ ] deterministic report; [ ] missing facts identified without guessed values.

## Sprint AUD-24.S3 — Durable assembly và job/worker dispatch

**Input:** S2 report + immutable verified uploads/config + authorized Run intent.
**Output:** persisted assembly, compatible job InputManifest/recipe và consumer adapters.
**Contract:** exact assembly/revision/recipe at commit; atomic quota/enqueue; legacy
jobs retain old semantics; partially uploaded assembly không được dispatch.

Implement: staged member upload finish/resume, binding persistence và CAS. Revalidate
access/refs/digests/runtime/report before accepting one run; integrate existing
queue/admission, recipe→stage mapping and R4 fusion adapter. Worker resolves exact
manifest and validates schema/tool versions, keeps supplied/estimated lineage;
defer heavy odometry/registration/QA to admitted workers. No API-process ICP/SLAM.
Dispatch AUD-06 PLY/SOG import through its durable command, giữ existing separate
import flow. After READY chỉ xem bằng viewer; không tạo Gaussian processing intent
hoặc Xử lý tiếp CTA vì AUD-25 Deferred. Import/view/probes không spend Guest processing quota.
Tests: cross-user refs, duplicate Run, change/delete file during submit, restart,
partial upload, incompatible worker, no calibration spoof, retry immutable recipe.
**Exit:** [ ] compatible supported recipes dispatch once; [ ] unsupported/new recipes stay explicit.

## Sprint AUD-24.S4 — Một upload UI và input remediation

**Input:** S2/S3 typed API + AUD-23 normalizer/upload callbacks.
**Output:** one multi-file dropzone, inventory/progress, recipe summary và inline choices.
**Contract:** user không chọn technical mode trước; Run chỉ khi accepted bindings
đủ; normalization/upload never automatically spends quota or starts reconstruction.

Implement: iterate FileList thay files[0], bounded upload concurrency/per-file cancel/
resume, scoped assembly draft và account cleanup. Reuse normalizer for RGB only.
Show concise detected roles/recipe, missing input choices and alternative exclusions;
new file/removal invalidates stale ready state. Existing video deep links lead to
unified upload; existing separate import deep links/flow stay compatible, with
shared file detection/import ports. Demo stays sample replay.
PLY/SOG inventory shows view capability and exact master choice; SOG
conversion handled by qualified worker, no manual converter step required from user.
PLY/SOG selection routes to import, giữ staged refs không yêu cầu upload lại.
Sau READY hiện Xem scene; không có processing CTA hoặc auto-spend processing quota.
Tests: multi-file drag/drop/keyboard, video+loose sidecars/ZIP, ambiguous picks,
account switch, cancel/resume, stale polling, guest limits, existing import flow.
**Exit:** [ ] one dropzone covers current qualified modes; [ ] browser decisions/actions match server.

## Sprint AUD-24.S5 — R1–R6 qualification và integration acceptance

**Input:** completed adapters AUD-13/14/17/19/23 + real supported capture sets.
**Output:** versioned support matrix, qualified enabled recipes và full consumer evidence.
**Contract:** recipe detection không guarantee calibration/alignment; failure keeps
artifacts/reasons and requires explicit changed input/route instead of silent fallback.

Implement: loose/ZIP parity and held-out qualification across R1–R6; verify RGB
priors/metric/QA for compressed portrait/FPS mapping, supplied and estimated scans,
registered map and one partial cloud. Measure grouped upload overhead/resources,
drift/coverage/ambiguity and source lineage. No-reference accuracy remains unknown.
Tests: all owner-listed incomplete combinations, missing clock/up/units, bad calibration,
low overlap, concurrency/restart, atomic Guest intent and real browser interaction.
**Exit:** [ ] all enabled recipes qualified; [ ] unsupported conditions and remediation documented;
[ ] exact recipe survives API/worker/artifact/scene consumers, real proof separated from fixtures.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_reconstruction/test_input_detection.py tests/test_contracts/test_input_manifest.py tests/test_reconstruction/test_lidar_fusion.py tests/test_reconstruction/test_lidar_package.py tests/test_orchestration/test_upload_input_kinds.py tests/test_orchestration/test_direct_upload.py tests/test_api/test_studio_routes.py tests/integration/test_upload_to_prepared_job.py -q
```

Frontend focused: tests/studio-input-flows.test.tsx, tests/direct-upload.test.ts,
tests/upload-route.test.ts, tests/ux-processing-form.test.tsx. Planned input assembly/
resolver/API/concurrency/browser tests; create before adding command paths.
Ruff/lint/typecheck/related suites và browser gate apply implementation. DONE cần
actual supported R1–R6 runs và binding/consumer receipts, không chỉ detector fixtures.

## Result / Evidence

Pending — inventory/assembly/recipe refs and versions, role/missing-data reports,
loose/ZIP parity, job/quota/CAS/worker identity, real browser/geometry/sensor evidence.
Task creation is docs-only; no pipeline mode implemented or enabled by this file.
