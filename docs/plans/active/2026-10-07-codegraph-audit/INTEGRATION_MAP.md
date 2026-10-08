# Logic changes, integration map và regression requirements

## Quy tắc owner chốt 07/10/2026

Chọn logic mới khi nó cải thiện project/tính năng và có contract/evidence rõ.
Code/tests/docs hiện tại là baseline để xác định impact, không buộc cải tiến giữ
behavior cũ. Khi logic đổi, cập nhật những phần code/tính năng liên quan để cả
pipeline dùng cùng behavior mới. Không ép logic mới quay về chỉ để tránh sửa
consumer. Không thêm workaround ở UI nếu policy/domain/API/worker vẫn lệch nhau.

Một sprint có thể sửa nhiều module và owner boundaries khi có dependency trực
tiếp với outcome của sprint. Danh sách file trong task là điểm bắt đầu; CodeGraph
callers và runtime ingress xác định danh sách cần sửa thật. Unrelated refactor và
speculative features vẫn ngoài scope. Không chạy song song edits chung contract/file.

## Evidence và giới hạn của risk map

Risk dưới đây là khả năng regression khi implement một phần hoặc giữ assumptions
cũ ở consumers; không là kết quả đo xác suất failure và không là bug do source
implementation mới. 24 tasks hiện PLANNED; AUD-25 Deferred theo yêu cầu owner,
không là active dependency/scenario. Đã dùng CodeGraph/source/callers cho
SceneEditor.publish_next, ResourceAdmission, enforce_gpu_quota và camera_priors:

- publish_next có apply_object_action/add_box_object/add_catalog_object/restore_revision;
  SceneEditor.apply/publish_initial và objectify/extraction phải cùng publication contract.
- enforce_gpu_quota có retry_job, create_scene_from_upload và request_objectify;
  quota không chỉ thuộc màn hình tạo scene. Kiểm kê action units cho mỗi caller.
- camera_priors có preview_worker._guidance, lidar.metric.propose_metric_from_lidar,
  finalize._lidar_alignment, eval/reference/torwic và eval/path/lidar_clearance;
  media mapping cần đồng bộ cả consumers sản phẩm và evaluator, không để evaluator
  dùng indices cũ mà producer dùng timeline mới. Reference labels không thành product input.
- ResourceAdmission dùng từ runner/worker_cli; thêm non-job operations phải thống
  nhất reservation/admission semantics và không bỏ baseline job waiting behavior.

Call graph là best effort; trước mỗi sprint cập nhật HEAD và đi tiếp direct/legacy
routes, callbacks, string-based config/stage routing, migrations và runtime consumers.
Không coi bảng này là inventory source hoàn chỉnh hoặc proof browser/GPU/cloud.

## Impact map cho từng task

| Task | Risk | Logic thay đổi | Code/tính năng cần đồng bộ | Regression/consumer acceptance |
|---|---|---|---|---|
| [AUD-01](tasks/AUD-01-collision-background.md) | Cao | Background source-region và object collision sau edit | extraction/objectify provenance → SceneIR edits → legacy/hybrid simulation_package → USD/candidate → validation; không carve theo pose đã sửa | Move/delete/ignore/restore giữ đúng background + active collider, exported candidate không còn collider gốc hoặc collision kép. |
| [AUD-02](tasks/AUD-02-usd-capabilities.md) | Cao | USD requirements/capability và blocker thay false success | physics_enrich, package builder, OpenUSD fallback/hybrid, candidate inventory/API/ReviewPanel và validation worker | Unsupported capability không publish candidate/revision giả; supported export giữ mesh topology, local offsets/physics và exact refs. |
| [AUD-03](tasks/AUD-03-validation-gate.md) | Cao | Review/release eligibility dựa trusted run | ValidationRun producer, report DTO/verifier, workflow eligibility, review/release endpoints/UI, sealing và stale-revision invalidation | Thiếu/stale/synthetic proof không release; producer thật và report/candidate/config cùng identity. |
| [AUD-04](tasks/AUD-04-release-sealing.md) | Cao | Sealing identity qua retry/crash | DB seal intent, archive/manifest writer, review workflow commit, API download/status và recovery | Fault injection publish ZIP/manifest + concurrent seal trả cùng release identity, không đánh lại timestamp khi retry. |
| [AUD-05](tasks/AUD-05-isaac-validation.md) | Cao | Durable Isaac run và evidence lifecycle | candidate inventory/config, operation queue/admission, Isaac adapter/report publication, audit/status/ReviewPanel và AUD-03 gate | Queue/restart/cancel/stale lease và report identity pass; real Isaac proof được phân biệt local fake-run. |
| [AUD-06](tasks/AUD-06-durable-import.md) | Cao | Durable PLY/SOG view import | input kind/format registry/validators, upload/import DTOs/allowlists, import queue/worker/admission, SOG byte reuse, workspace/polling/retry/trash/restore và AUD-24 view consumers | Old READY readable; PLY packaging/SOG reuse verified; source bytes/format retained; waiting/cancel/fail không bị coi READY hoặc physical eligibility. |
| [AUD-07](tasks/AUD-07-heavy-operation-admission.md) | Cao | Shared resource admission và operation fencing | ResourceAdmission, job runner/worker_cli, objectify/import/validator commands, telemetry/status UI và cancellation | Cạnh tranh job/operation không double reserve/overcommit; waiting giữ chosen config, stale worker không commit/release reservation của worker mới. |
| [AUD-08](tasks/AUD-08-object-correction.md) | Cao | Membership merge/reassign tạo revision mới | extraction membership producer, object correction command/API/UI, visual/geometry/background rebuild, CAS publication và candidate invalidation | Membership partition, source geometry và revision đồng bộ; merge/reassign không copy collider cũ, confirmed/moved unsupported case báo rõ. |
| [AUD-09](tasks/AUD-09-collider-editor.md) | Cao | Collider dimensions/local offset khác object pose | ColliderSpec/edit DTO, domain validation, API/TypeScript/UI, SceneIR CAS, legacy/hybrid exporter, candidate và validation | World collider transform = object × local collider; export khớp editor, edit invalidates approval và source carve vùng gốc giữ đúng. |
| [AUD-10](tasks/AUD-10-revision-head.md) | Rất cao | Committed head/CAS thay local recovery authority | SceneEditor apply/publish_initial/publish_next/current/revision/restore, objectify/extraction, physics_enrich, object/collider mutations, package readers và packaging | Mọi reader thấy committed head, mọi writer dùng cùng CAS; crash/concurrent/stale publication không overwrite user edit hoặc tạo orphan thành current. |
| [AUD-11](tasks/AUD-11-test-baseline.md) | Thấp | Fixtures/tests đúng runtime và retry eligibility | test auth/project registry fixtures, failed-job eligibility, subprocess fake poll/wait/returncode và focused test callers | Không sửa production policy chỉ để pass mock; expected assertions của behavior mới phải có business reason/regression rõ. |
| [AUD-12](tasks/AUD-12-collision-quality.md) | Cao | Collision source/quality selection | RGB cleanup/LiDAR aligned producer, FloorModel/QA ports, finalize/bundle/SceneEnvironment, simulation_package/USD, viewer/source selection và Isaac validation | Visual/canonical geometry khác collision source; cleanup retention/coverage và exact aligned refs được dùng ở export/validation. |
| [AUD-13](tasks/AUD-13-lidar-calibration-qa.md) | Cao | Sensor QA dùng exact calibration/timing/image convention | LiDAR ingest, intrinsics/frame-map/pixel transforms AUD-23, projection overlay, sensor-source selection gate, diagnostics/UI và held-out evaluation | Rotated/resized/downsampled RGB projection đúng, missing metadata INCONCLUSIVE; sensor QA không bị dùng để reject independent-map registration. |
| [AUD-14](tasks/AUD-14-adaptive-floor.md) | Cao | Fitted floor thay raw-z/static-clearance classification | REC-06 floor prior port, object extraction/geometric clustering, background ownership, collision cleanup/source QA và classification thresholds | Sloped/noisy floor, low/thin obstacles và canonical units/frame consistency pass; source ownership không suy từ edited collider. |
| [AUD-15](tasks/AUD-15-worker-latency.md) | Cao nếu sửa cache/stage reuse | Latency optimization và reusable preparation identity | source/preparation/sanitization refs, processing config/resource estimate, prepare/pose/train/package stages, retry/cache reader và telemetry | Cache hit chỉ exact content/profile/tool/maps; fail/cancel không fake complete timing, held-out geometry/visual quality không bị silently degrade. |
| [AUD-16](tasks/AUD-16-fast-preview.md) | Deferred | Preview/final lifecycle và lineage | Không implement (Deferred theo yêu cầu owner 2026-10-08 vì 7k iters thiếu độ nét/hình học và nguy cơ chậm pipeline khi không có resume) | Giữ làm tài liệu tham khảo thiết kế; không là dependency của active tasks. |
| [AUD-17](tasks/AUD-17-lidar-odometry.md) | Cao | Estimated trajectory mode khác supplied trajectory | input detection/routing, safe scan ingest, odometry worker/provider/version, trajectory/frame bindings, RGB priors/metric/alignment và QA consumers | Explicit supplied/estimated modes, unsupported/drift diagnostics và timestamps giữ identity; estimated trajectory không tự tạo calibration PASS. |
| [AUD-18](tasks/AUD-18-privacy-anonymizer.md) | Cao | Sanitized source identity trước reconstruction | privacy contracts/gate, detector/tracker/redaction producer, prepared InputManifest/frame set, cache/preview/train consumers, storage access và review diagnostics | Train/cache không reuse raw source khi chọn anonymized; timeline/redaction coverage và approval refs match actual sanitized bytes. |
| [AUD-19](tasks/AUD-19-automatic-rgb-lidar-registration.md) | Cao | Static-map registration mode và metric/floor correction | input mode/ingest binding, trajectory fit/BEV/ICP, proposal/QA/confirmation, canonical scale/alignment record, CAS scene update và collision selection | Final rigid transform đúng units/frame; scale correction creates new artifacts; ambiguity/stale target không auto publish và không rescale edited scene ngầm. |
| [AUD-20](tasks/AUD-20-user-display-name-and-creator.md) | Vừa | Identity/creator projection, role snapshot | UserRecord/Actor/PublicUser, register/seed setup/migration, project/job/import creator producer, API/list/card/table và packaging | Creator immutable khác run actor; snapshot role khác current auth; old payload/checksum và non-seed users không bị rewrite. |
| [AUD-21](tasks/AUD-21-guest-signup-and-ownership.md) | Rất cao | Three-role ownership policy toàn bộ mutations | auth role schemas/session/Team UI/invite/signup, contributor dependency, Studio/legacy API/service/worker mutation ingress, frontend capability và audit | Guest own/foreign/unknown resources, anonymous/auth-disabled, Editor/Reviewer intervention và reviewer-only paths tested end-to-end; no global canEdit bypass. |
| [AUD-22](tasks/AUD-22-guest-daily-job-quota.md) | Rất cao | Atomic Guest calendar quota và accepted intent | create_scene_from_upload/retry_job/request_objectify policy inventory, auth helpers, UserRecord/Me quota projection, DB reservations/CAS queue, manual/auto retry và UI | 3 accepted run intents across replicas; duplicate/manual/auto retry và midnight Vietnam đúng; giữ owner khác charged actor, Editor rolling24h/Reviewer unlimited theo role người chạy. |
| [AUD-23](tasks/AUD-23-client-video-normalization.md) | Rất cao | Client video encode thay uploaded input/time/pixels | local demux/encoder/mux + cleanup, content-bound direct/proxy resume, UploadRecord/InputManifest/config/frame set, camera_priors/metric/finalize/overlay, cache/privacy/preview và viewer | 60→30 mapping source poses đúng; resize/rotation projection đúng; actual uploaded digest/duration match, original local không giả server source proof. |
| [AUD-24](tasks/AUD-24-unified-upload-and-input-resolution.md) | Rất cao | Per-file classification khác executable assembly; automatic recipe/source intent selection | staged/direct/proxy upload, PLY/SOG/ZIP shared format registry, role/binding resolver, assembly/InputManifest DTOs, create-job ownership/quota/CAS, REC worker/fusion/priors, AUD-17/19 ports, media/cache identity và unified Studio UI | Loose/ZIP parity; SOG vs generic ZIP; unknown facts/ambiguous masters không fake ready; Gaussian chỉ view import; stale assembly không dispatch, one accepted reconstruction intent và retry giữ recipe/ref identity. |
| [AUD-25](tasks/AUD-25-imported-3dgs-continuation.md) | Deferred; risk rất cao nếu mở lại | Thiết kế imported-source continuation giữ tham khảo | Không implement source adapter/geometry/object pipeline hoặc processing CTA trong active tasks; không là dependency | Không có active acceptance; chỉ mở lại khi owner yêu cầu. Import/view PLY/SOG của AUD-06/24 vẫn active. |

AUD-24.S1 defines the shared staged-file, assembly, resolution, recipe and runtime
qualification contract in `src/models/contracts/input_assembly.py`; it leaves the
legacy `InputManifest` untouched. AUD-17 consumes explicit sensor-trajectory and
ordered scan bindings; AUD-19 consumes explicit map/cloud refs with units/frame
provenance; AUD-06 reuses the Gaussian source-format labels while owning SOG
validation. No consumer or R1–R6 runtime is enabled by the S1 schema alone.

## Checklist logic change cho mỗi sprint

1. Viết behavior trước/sau và lý do chọn hướng mới. Phân biệt intended behavior
   change với accidental regression. Không giữ false success/unsafe bypass vì tests cũ.
2. Lập impact inventory bằng CodeGraph: symbol → callers → producer → contract →
   persistence → API/worker → UI/viewer/export/evaluator. Kiểm config/migration paths
   mà graph không resolve. Ghi consumer được sửa, consumer không ảnh hưởng và lý do.
3. Chốt một domain rule/schema/source-of-record cho từng behavior. Shared policy
   ở backend/domain; mọi entrypoint dùng nó. UI projection không tự tạo rule cạnh
   tranh; worker không giữ bản copy hardcoded khác API.
4. Cập nhật DTO/version/default/serializer và parser ở cả producer/consumer. Với
   old data, chọn adapter/backfill/new artifact/read compatibility hoặc explicit
   migration/blocker. Artifact bất biến giữ checksum; new semantics không rewrite
   old bytes/ref để giả tương thích. Historical evidence chỉ áp đúng old identity.
5. Persisted jobs/leases/schema đang chạy cần rollout compatibility: reader biết
   version mới trước writer enable, hoặc coordinated deploy. Worker không hỗ trợ
   payload phải chờ worker compatible/báo incompatibility, không discard queue hoặc
   force success. Feature flag chỉ rollout; không che protocol/schema mismatch.
6. Tests bảo vệ behavior được chọn: regression case, direct service/API consumer,
   UI typed response nếu có, old records và concurrent/restart failure. Nếu expected
   cũ không còn đúng, sửa assertion/fixture với lý do before/after; giữ independent
   safety/data/authorization checks, không xóa test khó để đạt green.
7. Viết handoff logic delta, actual changed files, consumer tests, migrations,
   deployment ordering và pending runtime acceptance. DONE cần closure của các
   consumer bị ảnh hưởng; module test pass riêng không đủ khi contract đổi.

## Integration scenarios tối thiểu theo boundary thay đổi

| Boundary | Scenario |
|---|---|
| Media/time/calibration | local portrait60FPS → compressed≤30 → uploaded digest → sampled frame/source map → camera priors → metric/alignment/overlay; independent projection/pose check, không chỉ image sizes |
| Grouped inputs/routing | one dropzone → video/cloud/calibration/TUM/timestamps inventory → exact assembly/bindings → recipe/inline remediation → one accepted intent → supplied/estimated fusion or geometric/sensor alignment; malformed/ambiguous files không bị bỏ ngầm và retry không đổi route |
| View import và handoff | separate import hoặc unified dropzone Gaussian handoff → one durable import → READY → Xem scene; preserve uploaded PLY/SOG bytes và format provenance, import/view không processing intent/quota hoặc Xử lý tiếp CTA |
| Scene/collision/revisions | reconstruct → confirm/move/delete/merge/collider edit → committed CAS revision → candidate USD → validation; restore/reobjectify cạnh tranh với user edit |
| Preview/source/cache/privacy | sanitized/prepared source → preview render → explicit final run → candidate/review; incompatible source/profile/tier không reuse cache hoặc báo final ready |
| Auth/ownership/quota | Guest own vs foreign mutations qua UI/direct legacy APIs → create/manualRetry intents → quota atomics/restart/midnight; Editor/Reviewer can thiệp không đổi owner |
| Queue/admission | reconstruction + import + objectify + validator cạnh tranh tài nguyên → cancel/restart/reclaim → fencing/commit; không quota-charge automatic worker attempts |
| Review/release | exact current candidate + trusted run/report → reviewer decision → seal retry/crash → API/archive manifest same identity; scene change invalidates prior approval |

Chọn scenarios liên quan change, không chạy mọi suite sau mỗi edit. Sau nhóm
boundary changes, chạy integration thật tương ứng và full suites cần thiết. Unit/
fixtures chỉ chứng minh local invariant; browser/GPU/Isaac/cloud acceptance phải
có actual runtime receipts hoặc explicit pending.

## Mẫu handoff bổ sung

- Logic delta: before → after; approved product intent và technical rationale.
- Impact inventory: symbols/callers, entrypoints, contract/config/schema versions.
- Dependent updates: producer, consumers, persistence/API/worker/UI; unchanged reason.
- Migration/rollout: old artifacts/running jobs, version compatibility, recovery.
- Verification: commands/results; old intended path, new path, negative/concurrent path.
- Pending consumers/proofs: named blockers; không đánh dấu task DONE khi chưa closure.
