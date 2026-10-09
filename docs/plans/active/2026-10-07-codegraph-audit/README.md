# Execution Plan: Hoàn thiện codebase sau audit CodeGraph

Date: 2026-10-07

## Status

Active — implementation đang diễn ra trên branch
`docs/codegraph-audit-implementation-plan`, khởi tạo từ `develop@ef3a421`.
Đã commit: AUD-11.S1–S2, AUD-15.S1, AUD-01.S1–S3, AUD-02.S1–S3,
AUD-03.S1–S3, AUD-04.S1–S3, AUD-10.S1–S3 và AUD-07.S1. AUD-07.S2 đã hoàn tất
trong commit `5173750`; AUD-20.S1 trong `6fea33e`; AUD-20.S2 producer/API attribution
trong `7d5fcac`. AUD-20.S3 đã có badge creator/role ở Scenes và imports cùng test CLI;
authenticated Chrome DevTools xác nhận grid/list và seed display names/roles. AUD-20.S3a
bổ sung API fallback tên hiện tại cho import legacy; bản ghi vẫn thiếu snapshot bất biến
và role lịch sử giữ unknown. Browser check mới, stable seed IDs và migration receipt còn pending.
AUD-15.S2 đã commit: resume-cache integrity và cold/warm recovery
được kiểm tra bằng software integration tests. AUD-15.S3 đã bỏ ETA tĩnh không có
profile hỗ trợ; paired GPU latency và quality acceptance vẫn pending.
AUD-21.S1 đã chốt ma trận quyền,
identity owner và migration contract trong commit `31ffac2`. AUD-22.S1 calendar
contract đã hoàn tất; AUD-03.S3 review-screen gate đã xác nhận bằng Chrome DevTools
MCP trong phiên Reviewer. Real Isaac proof vẫn thuộc AUD-05. PostgreSQL qualification đã hoàn tất trên PostgreSQL 16 container
(`R2S_TEST_POSTGRES_URL`): toàn bộ suite orchestration 667 passed (0 skipped)
gồm migration v1→v16, row locking, release sealing, scene head CAS và guest quota
ledger. AUD-21.S2 đã implement Guest signup và role lifecycle; Chrome DevTools
xác nhận trang Guest signup đóng fail-closed khi response `/auth/me` thiếu flag.
Enabled-form/API submission vẫn UNVERIFIED vì process hiện tại không expose flag.
AUD-21.S3 đã thêm owner guards, immutable job owner và audited operator intervention;
three-role browser acceptance vẫn pending vì chưa có phiên Guest.
AUD-22.S2 đã implement quota Guest atomic và enforcement trên các API tạo job/Retry.
AUD-22.S3 đã thêm quota/reset UI, refresh sau accepted run và stale-tab 429 recovery.
AUD-21.S4 đã áp dụng server capability cho các thao tác Studio và quyền theo
ownership. Local verification: API 152 pass, frontend 300 pass, typecheck/lint,
Ruff check/format đều pass; PostgreSQL proof pass 100%. Reviewer-session DevTools
verification does not cover the three-role Guest flows. Guest rollout vẫn đợi browser
acceptance, PostgreSQL concurrency qualification và AUD-20 stable-ID/migration evidence.
AUD-06.S2 lease recovery/admission và AUD-06.S3 retry/cancel đã hoàn tất trong
`b149974` và `2b0a1b6`. AUD-05.S1 local implementation đã thêm durable validation
operation, idempotency, worker lease/fencing/recovery, candidate/profile binding,
status APIs và owner checks. Focused local verification: 52 passed, 4 skipped;
Ruff check/format pass. Isaac Sim/Isaac Lab và server validation config/profile
không có trong môi trường hiện tại, nên runtime qualification và S2 real-simulator
acceptance vẫn **UNVERIFIED**; không lấy test fixture làm bằng chứng runtime.
AUD-07.S3 đã nối queued/running cancellation từ API tới process-group kill/reap,
đảm bảo reservation chỉ nhả sau khi child chết và giữ quy tắc thắng/thua rõ ràng
ở cancel-vs-commit race. Local focused tests và API/UI checks pass; GPU contention
smoke và Chrome DevTools screen gate còn **UNVERIFIED** vì không có qualified GPU
workload và Studio tại `127.0.0.1:3100` trả `ERR_CONNECTION_REFUSED`.
AUD-23.S1 đã thêm profile/media contracts dùng chung Python–TypeScript, input-
specific capability blockers, dimension fitting cho portrait/landscape và
checksum compatibility cho `InputManifest` cũ. AUD-23.S2 đã thêm local Worker
decode/resize/downselect/AVC encode/MP4 mux, bounded OPFS artifacts, incremental
hash và output-frame/source-PTS map verification. AUD-23.S3 đã thêm server-side
byte/PTS verification, source-frame mapping qua REC/LiDAR consumers, calibration
transform và quality profile v2 giữ tỉ lệ. S3 local verification: backend focused
tests, Ruff và real FFmpeg filter fixtures pass. AUD-23.S4 đã nối picker 1080/720/480,
720p mặc định, chuẩn bị/xem trước trước upload, lựa chọn rõ khi output lớn hơn hoặc
audio cần bỏ, cùng resume theo account + digest + preparation identity và gate chờ
server verification. Nền video preview dùng token `bg-media-preview-surface`, giữ màu
đen ở cả bốn biến thể palette. S4 local verification: 330 Vitest pass (including 52
focused), typecheck, changed-file ESLint, isolated Next.js Webpack build (16 routes),
54 backend tests và Ruff pass. Chrome DevTools MCP hiện không có phiên Studio đăng nhập;
browser flow được ghi **UNVERIFIED**. Browser codec/runtime, actual bandwidth,
held-out quality and paired-sensor reconstruction remain S5 acceptance gates.
AUD-08.S1–S4 now persist revision/source-bound Gaussian membership, regenerate
artifacts on merge/reassign, preserve exclusive source collision ownership, and
wire revision-bound API/UI commands to canonical SceneIR publication. Focused API,
domain-consumer, and frontend regressions pass. Correction routes run synchronously;
there is no in-flight status/cancel operation, and “Hủy chọn” clears staged UI
selection only. Real runtime COACD/GPU/inpaint/SOG and Isaac qualification are
**UNVERIFIED**. Chrome DevTools reached the local login page, but no authenticated
Studio session was available, so browser acceptance is **UNVERIFIED**.
AUD-09.S3 committed as `d0df32d`; collider preflight now uses edited local bounds
and the focused package/candidate regressions passed. AUD-12.S1 is locally
complete: saved collision logs parse with immutable file checksums and evidence
labels, typed source/quality contracts bind exact refs, and synthetic fixtures
reject empty-world and unsupported-region physics claims; verified claims also
require a frozen acceptance profile with PASS. Verification: 31 focused tests,
Ruff, format and contract mirror pass. No production collision producer,
held-out capture, independent obstacle recall or Isaac proof is enabled by S1;
those remain **UNVERIFIED** for later sprints.
AUD-13.S1 adds a checksum-bound calibration source ref to new LidarPackageRecord
1.1 artifacts while retaining 1.0 reads, preserves whether camera distortion was
actually declared, and introduces a typed calibration-QA profile/report. Structural
errors fail; missing units, intrinsics, timing or overlap remain INCONCLUSIVE. The
consumer fixture proves an observable sample still cannot PASS before projection
scoring. AUD-13.S2 adds checksummed projection metrics, z-buffered overlay samples,
exact pixel-basis binding, and synthetic 1°/5° plus 5 cm perturbation separation;
all results remain `diagnostic_only`. Verification: 46 focused projection tests
passed, alongside repository checks recorded in the sprint result. Real held-out
threshold qualification, persisted/rendered overlays and production source gating
remain pending for AUD-13.S3.
AUD-14.S1 adds deterministic constrained floor fitting; AUD-14.S2 replaces fixed-Z
filters in geometric fallback, SAMPro3D, objectify, Gaussian growth and source
collision correction with plane-relative masks. Sparse support uses an explicit
schema-1.1 REC-06 prior fallback; high-noise and competing planes remain uncertain.
AUD-14.S3 persists content-addressed `FloorFitEvidence` bound to the source artifact,
point checksum and fit profile; SceneIR carries a compatibility-safe summary and the
Review tab shows actionable fallback/uncertain states. Verification: 84 backend
tests across focused floor/object-extraction regressions (including REC-06 floor
frame), 3 frontend tests, typecheck/lint, repository Ruff/format, contract
mirror and current CodeGraph index pass. Chrome DevTools verified the notice on a
local mocked job fixture; authenticated API/browser acceptance is **UNVERIFIED**.
No production sloped-floor artifact or collision-retention benchmark is qualified,
so empirical floor/obstacle quality remains pending.
AUD-12.S2 adds persisted RGB cleanup counts/config/source/output checksums to
`GeometryArtifact` 1.2 and rejects crops that would silently coarsen the selected
voxel profile. The output is diagnostic-only: the initial finalize stage has no
source-bound floor/noise model, and available Aisle_CW artifacts do not contain the
filtered PLY/inspection intermediates needed to reproduce cleanup. Ghost-block
improvement and thin-obstacle retention remain pending; no new floor clipping or
radius/SOR filter is enabled.
Focused verification passed: 48 reconstruction/contract tests, Ruff check and
format, contract mirror, and `git diff --check`. CodeGraph is current. The
`understand-anything` gate is unavailable in this session; no UI changed, so the
browser DevTools gate does not apply.
AUD-19.S1 adds checksum-sealed registration input/profile/request/proposal/QA
contracts and binding/state guards. Independent maps bind exact PCD/PLY file and
parsed-header identity, m/cm/mm units, frame, assembly revision, project context,
metric/floor evidence and bounded ROI/search budgets; raw scans remain routed through
AUD-17. Unknown scale may produce a bounded proposal but cannot pass QA or alter
canonical geometry. The existing sensor-package alignment path and REC-09 contracts
remain unchanged. Focused contracts plus REC-06/08/09 regressions, repo Ruff/format,
contract mirror and CodeGraph pass. These contract checks alone do not qualify
independent-map runtime behavior; later local algorithm work and open gates are
recorded below.
AUD-19.S2 has bounded synthetic BEV candidate search and S3 has constrained ICP
refinement; S4a–S4g add durable operation/source/target preparation, source-plane
hypotheses, cancellation and resource-wait persistence. S4h connects a CPU worker
that verifies and copies exact source bytes, resolves the target collision surface,
searches both signs of every detected plane and publishes provisional proposal/QA
artifacts. S4i adds the authorized durable producer/status/cancel API. S4j prepares a
server-sealed request from the accepted R2/R3 recipe and current scene, with source
bytes/header rechecked by the worker. S4k adds Studio preflight/start/status/cancel
with idempotent recovery. Proposal/overlay and confirmation CAS remain open. The
assembly contract still has no gravity/up declaration. Held-out qualification,
source-floor qualification, scene confirmation and collision-consumer integration
stay open.
AUD-12.S3b adds compatibility-safe SceneIR refs for the selected collision candidate
and selection record, includes them in artifact closure, and makes simulation
packaging refuse an unconsumed selection instead of falling back to RGB. Sensor QA is
still diagnostic-only and LiDAR object-region ownership is not mapped to the selected
mesh; candidate publication, viewer selection, export integration, held-out obstacle
retention and Isaac proof remain open.
AUD-12.S3c adds an identity-bound eligibility assessment across bundle/alignment,
package, calibration/timing projection, aligned world-point receipt, floor, self-mask
and collision profile. A report that claims PASS while its projection remains
diagnostic-only is blocked, as is registered-map mode pending AUD-19 QA.
AUD-12.S3d adds an immutable, content-addressed candidate publisher that reruns this
gate, validates the exact point/floor/self-mask receipts and publishes the manifest
last. It is still an internal producer seam: no production-qualified projection
receipt or worker-produced point-order mask exists. AUD-12.S3e adds source-OBB to
candidate-triangle ownership, SceneEditor CAS selection, artifact closure, object-edit
invalidation, viewer-layer identity, and fail-closed simulation/USD consumers. The
selection service still has no live API/worker route; diagnostic-only QA, held-out
retention, browser selected-candidate behavior and Isaac proof remain open.
Active scope: 26 packages/96 sprint slices, including the AUD-19.S4e–S4l follow-ups.
AUD-16/ADR0017 (3 sprints) và AUD-25/ADR0025 (6 sprints) Deferred theo yêu cầu owner; không là dependency hoặc implementation work trong kế hoạch hiện tại.

## Outcome

Scene sau chỉnh sửa phải xuất đúng collision/physics. Candidate phải được
validation trên đúng runtime trước review. Release phải giữ cùng một identity
qua retry. Import và reobjectify phải phục hồi được, dùng admission và không ghi
đè chỉnh sửa của người dùng. Collision quality được đo cùng obstacle retention;
LiDAR QA/adaptive floor và measured latency có producer/consumer
contract; Fast Preview (AUD-16) đã hoãn vì bản 7k thiếu độ nét hình học và thiếu checkpoint resume. Automatic map registration giảm manual landmarks và mở independent-map
input có QA. LiDAR odometry và anonymizer là opt-in extensions có qualification.
Video nén trước upload với preset720p/1080p/480p, giữ aspect dọc/ngang và source
time/pixel mapping. Coding agent nhận một task và một sprint cụ thể.
Một khung upload nhận video/LiDAR/metadata rời hoặc ZIP; server tự resolve recipe
khả thi và hiển thị missing/ambiguous facts trước accepted Run.
Giữ luồng import 3DGS riêng: Gaussian PLY/SOG → import READY → Xem scene.
Owner hoãn xử lý tiếp scene import; không thêm nút Xử lý tiếp, derived processing
job hoặc source-aware geometry/object pipeline cho imported Gaussian trong active scope.

## Context

Audit đã index 736 files, 12.900 nodes, 36.125 edges. Đã kiểm tra sâu đường
reconstruction → scene edits → candidate → review/release và các queue liên quan.
Index toàn repo không đồng nghĩa đã đọc mọi file hoặc chạy mọi runtime.

Theo chỉ đạo owner ngày 07/10/2026, PRD/docs là tham chiếu có thể cũ. Chọn hướng
đáp ứng tính năng tốt hơn dựa trên code, contract và evidence. Không rollback
implementation tốt chỉ để khớp tài liệu cũ. Ghi quyết định và đồng bộ tài liệu
khi thay đổi được kiểm chứng. Quyền truy cập, integrity và quyền sở hữu dữ liệu
vẫn là invariant; không tự thay chúng khi giải quyết khác biệt docs/code.

Đọc [hướng dẫn coding agent](AGENT_GUIDE.md) và
[integration/risk map](INTEGRATION_MAP.md) trước khi nhận sprint. Owner chốt:
cải tiến có đổi logic thì sửa đồng bộ code/tính năng phụ thuộc theo logic mới;
source hiện tại là baseline để dò impact, không là constraint giữ mọi behavior cũ. Các nhãn
`AUD-*` chỉ là work package của plan này; không thêm task ID vào foundation
crosswalk. Mỗi package bên dưới ánh xạ tới task hiện có.

Audit Gemini đã được đối chiếu lại với source/log: đọc
[GEMINI_FINDINGS.md](GEMINI_FINDINGS.md) để biết số đo xác nhận, điều kiện thiếu
và nhận định đã sửa. [TECHNOLOGY_LIMITS.md](TECHNOLOGY_LIMITS.md) phân biệt thiếu
observability, runtime chưa qualified, research limits và tính năng khả thi.

## Baseline evidence

| Finding | Evidence tại base commit | Work package |
|---|---|---|
| Move/delete giữ collision vật ở vị trí gốc | Repro local: confirm còn 12 environment faces; delete trả lại 9.228; move khoét 0 faces | AUD-01 |
| USD fallback thiếu collider mesh | Repro local: preflight PASS, có ZIP, Mesh thiếu points/topology/mass | AUD-02 |
| Report UNVERIFIED vẫn được release | Repro local: PASS, không paths/evidence, runtime proof false → RELEASED | AUD-03 |
| Retry seal lệch manifest ZIP/API | Fault injection sau publish ZIP, trước publish manifest; retry RELEASED nhưng manifest khác | AUD-04 |
| Isaac worker chưa nối production | CodeGraph callers của record_validation_report chỉ nằm trong tests | AUD-05 |
| Import dùng process API | Source: PACKAGING + BackgroundTasks; crash deployment chưa thử | AUD-06 |
| Reobjectify thiếu admission và có race revision | Source: process_next chạy trực tiếp; reobjectify đọc lại current trước publish | AUD-07 |
| Merge/reassign chưa nối UI/API | Source: merge_candidates 0 callers; chưa có reassign flow | AUD-08 |
| Collider editor và export/preflight gates | API/UI/editor, local pose export và revision invalidation đã implement; browser/Isaac acceptance chưa có | AUD-09 |
| Recovery revision tuyến tính, giới hạn 1.000 | Source: SceneEditor._recover; chưa có probe 1.000 revision | AUD-10 |
| Hai test không khớp fixture/runtime hiện tại | Backend suite: 1.522 pass, 2 fail, 40 skip; real child cancellation kill/reap thành công | AUD-11 |
| Collision clearance kém trên traversal được đo | 3DGS 0,05 m: 33/50; LiDAR 0/100 cần refusion min_range 2/3 m + floor_band 0,15 m; chưa đo obstacle recall | AUD-12 |
| LiDAR projection QA thiếu | Package syntax checks và world-cloud overlay có; chưa có scored calibration/timing QA | AUD-13 |
| Floor extraction chưa adaptive | Default clearance 0,06 m và raw-z mask; chưa có fitted floor/noise evidence | AUD-14 |
| Worker latency cần đo đủ và tối ưu | Brush 42,6–45 phút ở partial attempts; chưa là complete job latency | AUD-15 |
| Fast Preview lifecycle (AUD-16) | Deferred theo yêu cầu owner 2026-10-08 vì 7k iters thiếu độ nét/hình học và nguy cơ chậm pipeline | AUD-16 |
| Raw scans thiếu trajectory bị reject | LiDAR odometry khả thi; cần explicit mode/runtime/provenance/drift QA | AUD-17 |
| Auto anonymizer producer thiếu | Self-attested flow có; strict QA gate có; detection/tracking/redaction integration chưa có | AUD-18 |
| Automatic registration cho independent maps cần bổ sung | Trajectory-based no-point fit đã có; synthetic BEV/ICP components exist, but source-floor selection, integrated proposal/QA and held-out qualification are incomplete | AUD-19 |
| Video chưa nén trước upload, rotation/time mapping chưa explicit | Source: upload giữ bytes, decode passthrough, quality probe640×360; LiDAR ghép frame_id gốc | AUD-23 |
| SOG input và durable view import | AUD-06.S1 nhận bundled SOG v2, queue import bền và đồng bộ UI; S2/S3 vẫn giữ lease recovery/admission, retry/cancel và runtime decode validation. Finalize/VisualResolver/objectify vẫn yêu cầu Brush/camera/frame lineage | AUD-06.S1 implemented; AUD-25 continuation Deferred |

Các số test là kết quả audit trước khi viết plan, không phải kết quả chạy lại
cho thay đổi docs này. Ruff check/format pass; frontend lint/typecheck/build
pass; Vitest 269 pass. Browser/GPU/Isaac/cloud E2E chưa có acceptance.

Lần đối chiếu registration ngày 07/10 chạy focused REC-06/LiDAR fit tests:
19 passed. Đây là baseline của existing scale/floor/trajectory logic, không là
BEV/ICP implementation hoặc independent-map/browser acceptance.

## Scope và task map

| Package | Priority / owner boundary | Task hiện có | Sprints |
|---|---|---|---|
| [AUD-01: Background collision](tasks/AUD-01-collision-background.md) | P0 — EX-SCENE + EX-SIM; PRODUCT handoff | SCENE-06/07, SIM-02/05 | 3 |
| [AUD-02: USD capabilities](tasks/AUD-02-usd-capabilities.md) | P0 — EX-SIM + EX-PRODUCT | SIM-03/04/05, PRODUCT-08 | 3 |
| [AUD-03: Validation/release gate](tasks/AUD-03-validation-gate.md) | P0 — EX-PRODUCT + EX-SIM | SIM-07/09, PRODUCT-10/11 | 3 |
| [AUD-04: Idempotent sealing](tasks/AUD-04-release-sealing.md) | P0 — EX-PRODUCT | PRODUCT-11 | 3 |
| [AUD-05: Isaac validation worker](tasks/AUD-05-isaac-validation.md) | P0 — EX-SIM; PRODUCT queue/UI | SIM-01/06/07/09, PRODUCT-08/10/12 | 4 |
| [AUD-06: Durable import](tasks/AUD-06-durable-import.md) | P1 — EX-PRODUCT; REC packaging port | PRODUCT-02/08/09 | 3 |
| [AUD-07: Heavy operation admission](tasks/AUD-07-heavy-operation-admission.md) | P1 — EX-PRODUCT | PRODUCT-02/08/09, SCENE-10 | 3 |
| [AUD-08: Merge và reassign](tasks/AUD-08-object-correction.md) | P1 — EX-SCENE + EX-PRODUCT | SCENE-03/06/07/08, PRODUCT-06/07 | 4 |
| [AUD-09: Collider editor](tasks/AUD-09-collider-editor.md) | P1 — EX-SIM + EX-PRODUCT | SIM-02/03, SCENE-08, PRODUCT-06/07 | 3 |
| [AUD-10: Revision head](tasks/AUD-10-revision-head.md) | P1 — EX-PRODUCT | PRODUCT-06/08, SCENE-10 | 3 |
| [AUD-11: Test baseline](tasks/AUD-11-test-baseline.md) | P0 — test owners PRODUCT + REC | PRODUCT-02/09, REC-11 | 2 |
| [AUD-12: Collision quality và LiDAR source](tasks/AUD-12-collision-quality.md) | P0 — EX-REC + EX-SIM; SCENE/PRODUCT consumers | REC-05/08/09, SIM-02/04/06, PRODUCT-08/12 | 4 |
| [AUD-13: LiDAR calibration QA](tasks/AUD-13-lidar-calibration-qa.md) | P1 — EX-REC; PRODUCT diagnostics | REC-08/09, PRODUCT-04/08 | 3 |
| [AUD-14: Adaptive floor](tasks/AUD-14-adaptive-floor.md) | P1 — EX-SCENE; REC/SIM consumers | SCENE-02/03/06, REC-06, SIM-02 | 3 |
| [AUD-15: Worker latency](tasks/AUD-15-worker-latency.md) | P1 — EX-PRODUCT + EX-REC | PRODUCT-02/08/09, REC-02/03/04/11 | 3 |
| [AUD-16: Fast Preview](tasks/AUD-16-fast-preview.md) | Deferred — không implement; EX-PRODUCT + EX-REC nếu mở lại | REC-04/05, PRODUCT-02/08/09 | 3 |
| [AUD-17: LiDAR odometry](tasks/AUD-17-lidar-odometry.md) | P2 — EX-REC + EX-PRODUCT; opt-in | REC-08/06, PRODUCT-02/08/09 | 3 |
| [AUD-18: Privacy anonymizer](tasks/AUD-18-privacy-anonymizer.md) | P2 — EX-REC + EX-PRODUCT; opt-in | REC-02, PRODUCT-01/02/09 | 3 |
| [AUD-19: Automatic RGB–LiDAR registration](tasks/AUD-19-automatic-rgb-lidar-registration.md) | P1 — EX-REC + EX-PRODUCT; SCENE/SIM consumers | REC-06/08/09, PRODUCT-04/08/09 | 4 + S4e–S4l follow-ups |
| [AUD-20: Tên và creator attribution](tasks/AUD-20-user-display-name-and-creator.md) | P1 — EX-PRODUCT | PRODUCT-01/02/06/09 | 3 |
| [AUD-21: Guest signup và ownership](tasks/AUD-21-guest-signup-and-ownership.md) | P1 — EX-PRODUCT | PRODUCT-01/02/06/09 | 4 |
| [AUD-22: Guest quota 3/ngày](tasks/AUD-22-guest-daily-job-quota.md) | P1 — EX-PRODUCT | PRODUCT-01/02/06/09 | 3 |
| [AUD-23: Nén video trước upload](tasks/AUD-23-client-video-normalization.md) | P1 — EX-PRODUCT + EX-REC | REC-02/03/04/08/09, PRODUCT-02/04/08/09 | 5 |
| [AUD-24: Unified upload và input resolution](tasks/AUD-24-unified-upload-and-input-resolution.md) | P1 — EX-PRODUCT + EX-REC | REC-02/03/06/08/09, PRODUCT-02/04/08/09 | 5 |
| [AUD-25: Imported PLY/SOG continuation](tasks/AUD-25-imported-3dgs-continuation.md) | Deferred — không implement; EX-REC/SCENE/PRODUCT/SIM nếu mở lại | REC-04/05/06/09, SCENE-02/03/06/08, SIM-02/04/07, PRODUCT-02/04/06/08/09/10/11 | 6 |
| [AUD-26: Decoupled resource tuning](tasks/AUD-26-decoupled-resource-tuning-and-observed-budget.md) | P1 — EX-PRODUCT + EX-REC; resource calibration, container limits, worker count, COLMAP GPU | REC-02/03/04, PRODUCT-02/08/09 | 5 |
| [AUD-27: Structured error diagnostics](tasks/AUD-27-structured-error-diagnostics-and-redacted-excerpts.md) | P1 — EX-REC + EX-PRODUCT; failure diagnostics | REC-02/03/04, PRODUCT-02/08/09 | 3 |
| [AUD-28: Benchmark-derived verdicts](tasks/AUD-28-benchmark-derived-verdicts-and-rule-based-insights.md) | P2 — EX-PRODUCT + EX-REC; evaluation quality | REC-02/06, PRODUCT-02/08/09 | 3 |

Active: **26 work packages / 88 base sprints + 8 AUD-19.S4 follow-up slices = 96 sprint slices**.
AUD-16 (3 sprints) và AUD-25 (6 sprints) Deferred giữ để tham khảo; tổng tài liệu có
28 packages/97 base sprint definitions + 8 follow-up slices = 105 definitions/slices.
Mỗi sprint có Input, Output, Contract, implementation steps, Tests và Exit; mỗi task có dependencies, verification/DoD
và Result/Evidence. P2 là extension triển khai sau nền tảng P0/P1, không là
permanent exclusion do PRD cũ. Không mặc định enable odometry/anonymizer mọi job.

Scope loại trừ: thay reconstruction model, thay canonical RGB bằng LiDAR, thêm
cloud provider, đổi auth provider ngoài Guest scope, rewrite viewer, tự xóa scratch hoặc
artifact thất bại, commit/push/deploy. LiDAR-derived collision trong AUD-12 là
source riêng, không thay canonical RGB visual/geometry. Không có sprint tạo
general blind calibration solver, arbitrary dynamic physics reconstruction hoặc
"true" colliders từ vùng chưa quan sát; practical guards ghi trong limits note.
Map registration AUD-19 là supported geometric extension khác blind rig calibration;
không dùng exclusion đó để bắt independent maps phải có camera extrinsic.

Owner bổ sung AUD-20–22: Guest signup không invite, có email/name/password;
Guest chỉ mutate own resources, Editor/Reviewer giữ rights hiện có. Quota Guest
3 accepted runs/ngày gồm manual Retry, không tính objectify/tách vật, reset 00:00
Asia/Ho_Chi_Minh; automatic worker retry/duplicate không thêm lượt. Objectify vẫn
chịu worker/resource admission; quota Editor hiện có không đổi. Email verification
để sau. Đây là yêu cầu
owner mới, thay scope exclusion auth/roles/quota của bản plan trước.
Owner hoãn AUD-25 ngày 2026-10-07 vì độ phức tạp. Import/view PLY/SOG ở AUD-06/24
vẫn trong active scope; source continuation/G1–G3, metric/object/collision processing
cho import và nút Xử lý tiếp không implement. Không tự mở lại từ task phụ thuộc.

## Architecture proposals

- [ADR 0012: Background collision và USD capability](../../../decisions/0012-editable-collision-and-usd-capabilities.md).
- [ADR 0013: Trusted validation và identity của release](../../../decisions/0013-validation-evidence-and-release-identity.md).
- [ADR 0014: Durable heavy operations và admission](../../../decisions/0014-durable-heavy-operations.md).
- [ADR 0015: Scene revision head và CAS](../../../decisions/0015-scene-revision-head.md).
- [ADR 0016: Collision quality và LiDAR-derived collision](../../../decisions/0016-collision-quality-and-lidar-selection.md).
- [ADR 0017: Fast Preview và final identities](../../../decisions/0017-fast-preview-and-final-artifacts.md).
- [ADR 0018: Opt-in LiDAR odometry](../../../decisions/0018-opt-in-lidar-odometry.md).
- [ADR 0019: Anonymized input preparation và QA](../../../decisions/0019-anonymized-input-preparation.md).
- [ADR 0020: Automatic map registration và QA](../../../decisions/0020-automatic-rgb-lidar-map-registration.md).

- [ADR 0021: Guest identity và ownership](../../../decisions/0021-guest-identity-and-ownership.md).
- [ADR 0022: Guest daily quota](../../../decisions/0022-guest-daily-job-quota.md).

- [ADR 0023: Client video normalization](../../../decisions/0023-client-video-normalization.md).
- [ADR 0024: Unified upload và input resolution](../../../decisions/0024-unified-upload-and-input-resolution.md).
- [ADR 0025: Imported PLY/SOG continuation — Deferred](../../../decisions/0025-imported-3dgs-continuation.md).
- [ADR 0026: Hiệu chỉnh ước lượng tài nguyên và auto-tune hai trục](../../../decisions/0026-decoupled-resource-tuning-and-observed-budget.md).
- [ADR 0027: Chẩn đoán lỗi COLMAP và đoạn trích log đã che](../../../decisions/0027-structured-error-diagnostics-and-redacted-excerpts.md).
- [ADR 0028: Khoảng tham chiếu chất lượng và khuyến nghị theo quy tắc](../../../decisions/0028-benchmark-derived-verdicts-and-rule-based-insights.md).

12 active ADRs remain Proposed; ADR 0022, 0026, 0027 and 0028 are Accepted; ADR0025 is Deferred and
does not define active policy.
Không giả lập owner acceptance. Bug fixes trên
invariant hiện có có thể làm độc lập. Sprint thiết kế phải ghi rõ phần mới cần
producer/consumer review trước khi trở thành shared contract/policy.

## Approach và thứ tự thực hiện

Triển khai theo dependency của từng sprint. AUD number là identifier, không là
execution order; không cần xong toàn bộ một task mới được chuyển sang task khác.
Trong bảng, `S1–S3` là ba sprint liên tiếp, thực hiện theo thứ tự tăng dần.
Thứ tự mặc định gồm đủ **80 active sprint, mỗi sprint một lần**; không có AUD-25.
AUD-26/27/28 (11 sprint, thêm ngày 2026-10-08) chưa nằm trong bảng; thứ tự của chúng:
AUD-27.S1–S2 → AUD-26.S1–S3 → AUD-26.S5 → AUD-26.S4 → AUD-28.S1–S3 → AUD-27.S3
(đã implement; log của một worker attempt thật vẫn là acceptance evidence còn thiếu).
Phần đo trên pod RunPod của AUD-26.S1, S4 và S5 làm trong cùng một đợt thuê máy:

| Đợt | Thứ tự sprint | Kết quả cần đạt |
|---|---|---|
| 1 — Baseline và đo lường | AUD-11.S1–S2 → AUD-15.S1 | Fixtures/tests phản ánh đúng behavior; timing protocol và số đo nền trước cải tiến. |
| 2 — P0 collision/export/release | AUD-01.S1–S2 → AUD-02.S1–S2 → AUD-01.S3 → AUD-02.S3 → AUD-03.S1–S3 → AUD-04.S1–S3 | Edit/export đúng geometry; validation gate và release identity không cho proof thiếu hoặc seal retry lệch. |
| 3 — Revision và admission nền tảng | AUD-10.S1–S3 → AUD-07.S1–S2 | Durable revision head/CAS, operation reservation và stale-worker guards trước các consumer mới. |
| 4 — Tên, Guest và quota | AUD-20.S1 → AUD-21.S1 → AUD-22.S1 → AUD-20.S2–S3 → AUD-21.S2–S3 → AUD-22.S2–S3 → AUD-21.S4 | Creator/ownership/quota hoàn tất trước mở public Guest signup. |
| 5 — Nén video và input resolution | AUD-23.S1–S5 → AUD-24.S1 → AUD-06.S1 → AUD-24.S2 | Local compression/media mapping; grouped input/recipe và shared PLY/SOG format contracts trước deterministic resolver. |
| 6 — Durable import, validator và unified UI | AUD-06.S2–S3 → AUD-05.S1–S4 → AUD-07.S3 → AUD-24.S3–S4 | Durable consumers/admission; grouped dispatch/UI và PLY/SOG view import. |
| 7 — Object và collider editor | AUD-08.S1–S4 → AUD-09.S1–S3 | Merge/reassign/collider edit dùng shared publication; candidate mới phải validate lại. |
| 8 — Collision quality, floor và LiDAR | AUD-12.S1 → AUD-13.S1 → AUD-14.S1 → AUD-19.S1 → AUD-14.S2–S3 → AUD-12.S2 → AUD-13.S2–S3 → AUD-19.S2–S4 → AUD-12.S3–S4 | Freeze quality/QA; adaptive floor, calibration QA, RGB–LiDAR map registration và qualified collision source. |
| 9 — Latency (AUD-15) | AUD-15.S2–S3 (AUD-16 Deferred) | Measured optimization giữ đúng preparation identity và quality gates; AUD-16 đã hoãn theo yêu cầu owner. |
| 10 — Input qualification và extensions | AUD-17.S1–S3 → AUD-24.S5 → AUD-18.S1–S3 | Estimated trajectory/input matrix R1–R6 và PLY/SOG view import; anonymizer opt-in có provenance/QA. |

Execution order bắt đầu ở **AUD-11.S1**; các sprint AUD-11.S1–S2, AUD-15.S1,
AUD-01–04, AUD-10.S1–S3, AUD-07.S1–S2, AUD-20.S1–S2, AUD-21.S1–S2 và AUD-22.S1
đã hoàn tất ở mức code/task của từng sprint. AUD-21.S3 đã thêm backend ownership
guards; AUD-20.S3 grid/list and Team rendering have authenticated browser evidence,
while legacy-import attribution and stable-ID/migration evidence remain open. AUD-21.S2
and S4 still need browser acceptance. AUD-22.S2 code/API acceptance đã hoàn tất trên SQLite; AUD-22.S3 local
UX/API regression đã hoàn tất. PostgreSQL multi-process qualification và DevTools
browser acceptance còn pending. AUD-21.S4 caller-specific Studio capability/API
coverage is locally verified (152 API tests, 300 frontend tests, typecheck and
changed-file lint); browser three-role acceptance, shared-PostgreSQL qualification
and seed acceptance still block public Guest rollout.
AUD-15.S1 được làm sớm để AUD-23.S5 có measurement protocol; sau quality work,
AUD-15.S2 đã hoàn tất ở mức software cache/warm-path verification. AUD-15.S3 đã
điều chỉnh ETA để thiếu profile thì báo chưa xác định; paired GPU measurements và
quality acceptance vẫn pending, không suy kết quả từ fixtures.
AUD-07.S3 làm sau AUD-06/AUD-05 để kiểm tra admission trên consumer thật;
không đợi toàn bộ AUD-07 trước khi triển khai hai consumer này.

Sau mỗi sprint: sửa đồng bộ producer/persistence/API/worker/UI/config/tests bị
logic mới ảnh hưởng, chạy focused checks và integration scenario liên quan,
ghi Result/Evidence trước khi chuyển sprint phụ thuộc. Cuối mỗi đợt chạy regression
của các flows đã thay đổi; không dồn related-code updates hoặc integration tới cuối
77 active sprint. Trước enable schema mới, kiểm tra forward migration/read compatibility
và deployment order của producer/worker consumers theo integration map.

Real Isaac proof ở AUD-05; fixtures ở đợt 2 chỉ chứng minh contracts/gates,
không chứng minh physics runtime. Thiếu GPU/Isaac/browser proof thì phần acceptance
đó giữ Pending, tiếp tục sprint độc lập khi có thể. Không đánh dấu DONE hoặc mở
consumer đang chờ qualification. AUD-12 sensor-package path có thể làm sau
AUD-13.S3 mà không đợi independent-map registration AUD-19.S3–S4; static-map path
chỉ enable sau registration QA. Việc đổi thứ tự phải giữ prerequisites tương ứng.

Dependencies không tạo cycle: AUD-03 tạo gate với persisted proof fixture;
AUD-05 mới tạo proof thật. AUD-07 chuẩn hóa reservation trước worker consumers,
không đợi các consumer hoàn thành. AUD-10 không phụ thuộc UI mới.
AUD-12.S1 đặt benchmark protocol trước AUD-14, AUD-14.S1 fit model trước cleanup;
hai package không đợi toàn bộ epic của nhau. AUD-15.S3 dùng current pipeline,
không phụ thuộc Fast Preview (AUD-16 đã Deferred).
AUD-19 uses AUD-12.S1 quality fixtures; AUD-12 sensor-package path không đợi
AUD-19. Static-map consumer chỉ enable sau registration QA, không bắt AUD-19
đợi whole AUD-12 epic. Sensor calibration QA và map registration QA không tráo nhau.

Progress hiện tại: AUD-11.S1–S2, AUD-15.S1, AUD-01.S1–S3, AUD-02.S1–S3,
AUD-03.S1–S3, AUD-04.S1–S3, AUD-10.S1–S3 và AUD-07.S1–S2 đã được commit riêng
theo sprint. AUD-08.S4, AUD-09.S1, AUD-14.S1–S3 và AUD-19.S1 cũng đã được commit
riêng. AUD-14.S3 software gates pass; production sloped/noisy sample and obstacle-
retention benchmark remain pending and are not inferred from synthetic fixtures.
AUD-12.S3d đã commit cơ chế publish candidate nội bộ; AUD-12.S3e bổ sung source-aware
ownership/selection và các consumer viewer/export, nhưng không tự mở producer path
khi QA đầu vào còn `diagnostic_only`.
AUD-12.S4 local gate wiring kiểm checksum/ownership sidecars và buộc review gate
đối chiếu diagnostic artifact của từng path với exact candidate, collider hiệu lực,
quality report, job và coverage tĩnh.
Held-out retention, production quality report, GPU và Isaac acceptance vẫn UNVERIFIED.
AUD-09.S2 đã nối Inspector/API và preview collider với publication revision CAS;
AUD-09.S3 đã xác nhận legacy/hybrid USD local-pose fidelity, cập nhật preflight
world bounds và kiểm tra candidate/report invalidation. Focused API/domain/frontend
và OpenUSD tests pass; browser visual và real Isaac contact vẫn UNVERIFIED.
AUD-07.S3 đã thêm objectify cancellation, child-process cleanup và terminal
outcome handling; browser/GPU qualification còn UNVERIFIED.
AUD-01.S3 verified legacy
ownership recovery, candidate ZIP/manifest, current rotated object pose,
retained floor collision, relative USD asset composition, và bất biến bytes của
artifact cũ bằng OpenUSD runtime. AUD-02.S3 nối capability blocker qua typed
API/UI, giữ Preflight riêng, ngăn tải candidate khi export bị block và kiểm tra
quyền GET/POST/download. Automated checks pass. Chrome DevTools MCP đã mở Results
tab; các scene hiện có chưa có candidate/export-capability blocker, nên đúng luồng
download-block vẫn UNVERIFIED. AUD-03.S3
đã commit API/UI projection và stale request regressions; Chrome DevTools MCP xác
nhận application review screen chặn release khi revision chưa có simulation package.
Trusted worker proof và real Isaac acceptance vẫn thuộc AUD-05.
AUD-04.S1 đóng băng release timestamp/manifest theo approval identity trong DB.
AUD-04.S2 xác minh ZIP closure và commit marker, lưu diagnostics an toàn, phục hồi
partial/missing artifacts, chặn download khi bytes sai; 53 backend tests (PostgreSQL
tests pass 100% với `R2S_TEST_POSTGRES_URL`), 275 frontend tests, ESLint, typecheck, production
build, Ruff và CodeGraph đều pass. AUD-04.S3 kiểm tra hai registry độc lập trên
SQLite và PostgreSQL, stale revision ngay trước seal marker và API ZIP/manifest byte equality;
matrix pass 60/60 (0 skip với `R2S_TEST_POSTGRES_URL`). Browser
MCP gate còn UNVERIFIED; frontend checks không thay thế browser review.
AUD-10.S1 added migration v12, checksummed head/backfill records,
bounded verify/recheck repair pages, a read-only/apply CLI, package import/export
and trash/restore consumers. Its matrix passed 127 tests (0 skip trên PostgreSQL).
AUD-10.S2 routes DB-backed SceneIR writes through reserve/publish/verify/CAS and
reads through the committed head; legacy artifacts without a head require the
verified repair CLI. The S2 regression matrix, package/deletion consumers and
scene pipeline callers pass locally; live S3 proof remains pending.
AUD-10.S3 measures one head query, one `ArtifactResolver.locate` and zero list
calls at both rev-001 and rev-1005, checks independent DB/cache freshness and
fail-closed remote checksum verification, then reads a validated SceneIR after
package import and restores a checksummed head/repair history through trash. Its
matrix passed 180 tests with PostgreSQL row locking passed. CodeGraph is current;
live S3 provider proof remain pending.

AUD-21.S3 adds contributor-level shared read access and resource-level Guest
ownership guards across Product and Studio mutations. Job ownership is an
immutable nullable column outside the checksum-bound manifest; deletion checks
the entire cascade; Editor/Reviewer cross-owner actions are audited. The API suite
passed 138 tests, orchestration passed 667 with 0 skips, and processing/upload
integration passed 9; PostgreSQL migrations và locks pass.
Chrome DevTools confirmed the Guest signup closed state; enabled Guest/API and
three-role owner/quota flows remain UNVERIFIED. `AUTH_GUEST_SIGNUP_ENABLED`
remains false. AUD-22.S2 implements the durable
Guest quota ledger; AUD-22.S3 implements local quota/reset UX and stale-tab refresh.
Frontend/API checks pass; PostgreSQL qualification pass; DevTools browser acceptance
remains pending.

AUD-07.S1 adds typed operation admission over the existing reservation table,
shares resource assessment with job admission, keeps old job payloads readable,
and rejects unknown/insufficient operation resources or wrong GPU affinity.
CPU-only reservations hold RAM/disk without blocking GPU sharing; disk reclaim
protects a reservation's parent job. Its SQLite matrix passed 101 tests with
four PostgreSQL skips; Ruff and formatting pass. No DB migration or API/UI
projection was needed yet. CodeGraph source/callers were inspected before edits;
post-edit sync is pending because the active MCP daemon reported auto-sync
disabled after the OS file-watch limit was reached. Tiếp theo là AUD-07.S2.

AUD-23.S1 đã chốt client preparation identity trước AUD-15/16 cache consumers;
supported sensor mapping chốt trước AUD-13 overlay QA ở S3. Không cần full
odometry/registration
để normalize RGB-only uploads; paired sensor mode giữ mapping/projection guards.
AUD-24.S1–S2 chốt assembly/recipe ports trước AUD-17/19 implementations. S3–S4
enable từng qualified recipe, không fake support cho missing runtime. R5 estimated
raw mode chỉ nghiệm thu sau AUD-17.S3; qualification toàn matrix ở AUD-24.S5.
AUD-06.S1 format/validation ports precede AUD-24.S2 SOG classifier. AUD-25 Deferred;
AUD-06/19/24 không phụ thuộc source adapter hoặc sprint của task này. AUD-19 active
target là reconstructed RGB geometry; imported PLY/SOG giữ view-only lifecycle.
Import READY chỉ là view readiness, không là geometry/candidate/physics proof.

Các package chạm chung scene.py, database.py, workflow.py hoặc TypeScript
contracts phải được tích hợp tuần tự theo contract sprint. Không gán hai agent
đồng thời ghi cùng file; task map không tự cấp quyền spawn agent.

## Logic changes và integration

Mỗi task đã có Logic change/dependent updates và consumer acceptance. Integration
map có 24 active task và một row AUD-25 Deferred để tham khảo. AUD-10/21/22/23/24
tác động broad publication, permissions/quota, media/time/calibration và grouped
routing. Risk của AUD-25 không tạo active implementation work. Risk là technical assessment, chưa là
regression do implementation mới. Khi contract thay đổi, update producer/persistence/
API/worker/UI/config/tests cùng semantics và có migration/rollout cho old jobs.
Không claim DONE từ module tests khi related consumers còn dùng rule cũ.

## Risks And Recovery

- Legacy scene thiếu source ownership: đọc được nguyên bản; edit/export cần
  phục hồi từ artifact gốc hoặc báo blocker. Không suy source pose từ pose đã sửa.
- DB và object store không có chung transaction: publish artifact bất biến,
  verify, rồi CAS commit record. Giữ orphan để recovery; không xóa user data.
- Worker restart/multiple workers: lease + fencing token; chỉ owner hiện tại
  commit kết quả. Stale worker không được overwrite head hoặc terminal result.
- Runtime/hardware thiếu: queue có thể hủy, giữ config/checksum. Không giảm
  chất lượng hoặc giả evidence để đạt PASS.
- Quality tuning: freeze profile trước held-out traversal; clearance 0% không
  đủ nếu làm mất floor/low/thin obstacles. Unknown geometry/QA không giả PASS.
- Sensor/model limitations: calibration/timing mismatch, odometry degeneracy,
  detector misses cần uncertainty/diagnostics/manual fallback đúng source lineage.
- Rollout schema: migration forward + read compatibility. Không reset DB hoặc
  ghi lại checksum của artifact cũ.

## Identity baseline bổ sung

Source review bằng CodeGraph: auth/models.py và service.py đã có display_name,
Actor snapshot và reviewer > editor. RegisterForm đã nhập tên, ScenesHome đã hiện
creator name; thiếu role badge và Guest ownership. api/auth.py quota hiện rolling
24h audit count; Guest calendar quota cần atomic DB reservation. Các kết luận này
là source inspection, chưa chạy acceptance của feature mới.

## Video baseline bổ sung

Source review 07/10/2026: upload/direct multipart chưa compress, sample_fps3/6
là reconstruction setting, không encoded FPS. Không có16:9-only gate trong đường
đã đọc;640×360 là measurement profile. Owner chọn local compression trước upload.
Proposed cap30/preserve aspect cần record timeline/pixel transforms; camera_priors
hiện dùng original frame_id. Không claim real portrait/browser encoding acceptance.

## Unified upload và input resolution

AUD-24: owner muốn một khung nhận mọi file; không bắt chọn technical mode trước.
Sáu nhóm R1–R6 bao phủ RGB-only, registered map, single static cloud, raw scans
có trajectory, raw scans cần estimate và calibrated/time-bound sensor package.
Classifiers nhận diện content; resolver xác định missing/ambiguous bindings và
compatible recipes. Units/cloud frame/clock không suy chắc từ tên/extension hoặc
file count. Metadata sai không bị bỏ ngầm để chọn RGB-only. One accepted Run giữ
immutable assembly/recipe, one quota intent; probing/upload không charge thêm.

## Progress

- [x] Tạo branch và đối chiếu source/contracts bằng CodeGraph.
- [x] Đối chiếu audit Gemini với source/log, ghi technology/qualification limits.
- [x] Viết 24 active packages/80 sprint contracts/13 ADR Proposed; giữ AUD-25 với
  6 sprint và ADR0025 Deferred ngoài execution order.
- [x] Kiểm tra cấu trúc sprint, links, canonical task bindings, test paths và docs-only scope.
- [x] Bổ sung logic-change impact/dependent updates cho cả 25 task và integration map.
- [x] Implementation AUD-11 và AUD-15.S1 baseline.
- [x] Implementation AUD-01–04.
- [x] Implementation AUD-10 và AUD-07.S1–S2.
- [ ] Implementation AUD-06 và AUD-07.S3.
- [ ] Implementation AUD-05 và real Isaac acceptance.
- [x] Local implementation AUD-08.S1–S4; focused API/domain/frontend regressions.
- [x] Local implementation AUD-09.S1–S3; focused API/domain/frontend/export regressions.
- [ ] AUD-08 browser/Isaac acceptance; AUD-09 browser visual and real Isaac contact acceptance.
- [ ] Implementation AUD-12–14 và held-out collision/LiDAR/floor acceptance.
- [x] AUD-15.S2 resume-cache integrity, cold/warm recovery, and software integration verification.
- [ ] AUD-15.S3 paired latency/quality acceptance; AUD-16 remains Deferred.
- [x] AUD-17.S1–S2 typed timestamp roles/units, resolver prerequisites, immutable trajectory contract, and isolated synthetic provider path; R5 dispatch remains disabled.
- [x] AUD-17.S3a evaluation-only ATE/RPE report with explicit frame, units, clock, bounded interpolation and input checksums; no real-sensor qualification claimed.
- [x] AUD-17.S3b1 blocks consumer readiness for wired-unqualified odometry while preserving diagnostic poses; R5/product consumers remain disabled.
- [x] AUD-17.S3c frontend regression covers visible pending-R6 diagnostics and dispatch through the READY supplied-R4 fallback; durable R6 integration and quality acceptance remain open.
- [ ] AUD-17.S3 drift/consumer QA and real-sensor qualification; current code has a
      diagnostic-only RGB-PTS to estimated-pose mapper, not wired into product
      consumers or R5 dispatch; AUD-18.
- [x] AUD-19.S1 contracts; local S2 BEV/S3 constrained-ICP algorithms; S4a–S4l
      durable envelope, exact source/target resolution, diagnostic source-plane
      hypotheses, cancellation/resource-wait persistence, shared admission, and a
      bounded worker that publishes provisional proposal/QA artifacts, authorized
      operation/status/cancel APIs, server-sealed request preparation, and Studio
      preflight/start/status/cancel with idempotent recovery, and read-only proposal/QA
      inspection bound to exact operation artifacts and scene revisions.
- [ ] AUD-19 held-out map QA and source-floor qualification; proposal overlay,
      confirmation route; scene/collision consumer integration
      and browser acceptance.

- [x] Implementation AUD-20.S1 identity/seed migration contract and AUD-20.S2 producer/API actor attribution.
- [x] AUD-21.S4 local Studio capability/API implementation and UI regression.
- [x] AUD-20.S3 authenticated browser rendering for scene grid/list and Team seed names/roles.
- [x] AUD-20.S3a local API projection resolves current names for legacy import IDs, leaves historical roles unknown, and preserves stored snapshots/ownership.
- [ ] AUD-20.S3 browser verification with a snapshot-bearing imported scene and stable-ID/migration evidence; AUD-21.S2/S4 browser gates; AUD-21.S3–S4
      full browser/API acceptance before opening Guest signup.
- [x] AUD-21.S2 browser verification of Guest signup's fail-closed state with the rollout field absent; enabled signup remains unverified.
- [x] Implementation AUD-22.S2 durable Guest quota ledger/API enforcement and
      AUD-22.S3 local quota UX; SQLite/API/frontend checks.
- [ ] AUD-22.S2 shared-PostgreSQL concurrency/restart qualification; AUD-22.S3
      DevTools browser acceptance.
- [x] Audit 2026-10-08 of rounds 1–3 (AUD-01/02/03/04/07/10/11/15), local evidence only.
      Fixed and committed: the background carve keeps and reports triangles shared between a
      carved and an unresolved source region (exact `triangle_indices` membership wins over an
      OBB), so adjacent candidates neither block export nor lose triangles silently; catalog
      assets (`asset_url`) export as their box collider with `real2sim:catalog` provenance and a
      non-blocking `CATALOG_ASSET_EXPORTED_AS_BOX` notice (ADR 0012, Audit amendments); legacy
      ownership recovery skips duplicates, matches by geometry artifact, follows `restored_from`,
      and derives ownership from the extraction revision (previously recovered nothing, so every
      pre-AUD-01 scene with a confirmed object could not export); `reobjectify` now binds
      ownership to its new objects; `SceneEditor.revision()` reuses the proven lineage
      (122-revision walk 94 s → 3 s); hybrid `GroundPlane` top was +9.8 mm above z=0; a restarted
      worker with the same `host:pid` no longer deadlocks on its leftover operation reservation.
      Evidence: full backend suite 1842 passed / 52 skipped (clean worktree); frontend 351
      passed; `tests/test_orchestration` + `tests/test_api` on Postgres 16 779 passed, 0
      skipped before the catalog change (single process; multi-process/restart and the
      deployment database remain pending). Real-data probes on copies of the local DB/artifacts:
      head backfill for the 4 scene jobs (including the 122-revision chain) completes; the
      122-revision scene, with its 4 buried objects lifted onto the floor, exports 11 catalog
      objects as boxes to a hybrid package (preflight PASS, capability supported, 19 objects,
      11 with `real2sim:catalog`, no remote layers) that opens in OpenUSD. Open product
      decision: completed worker validation runs make a data package unpublishable until an
      authenticated receipt exists. Objects placed below the floor still fail
      `OBJECT_OUT_OF_BOUNDS` by design; the user moves them. After the API first migrates
      `runtime.db`, run `scripts.studio.scene_head --apply` per job or those 4 scenes return
      SceneNotAvailable.

- [ ] Audit 2026-10-08 follow-ups for rounds 4–6. Fixed: AUD-23.S5's SDR color check raised
      `AttributeError` (HTTP 500) when the output color reported no transfer. AUD-24.S2 now
      requires R4's `InputRole.SENSOR_TRAJECTORY` in the shared contract, alongside its ordered
      scan binding. AUD-06.S1 moves import packaging from the API to the standalone worker, so
      imports stay QUEUED when no `worker_cli` runs; AUD-06.S2 now recovers expired import leases
      and AUD-06.S3 provides retry/cancel controls. Validation queue coverage is in AUD-05.S1;
      Isaac runtime execution/report publication remains for S2/S3.

- [x] AUD-23.S1 versioned media/capability/preparation contracts, Python/TypeScript
      agreement, frame-map rules, preset dimension fitting and legacy checksum preservation.
- [x] AUD-23.S2 bounded local Worker encode, OPFS/backpressure, PTS frame sampling,
      checksummed mapping, output verification and cancellation cleanup; 20 focused
      tests/typecheck/changed ESLint/webpack build pass.
- [x] AUD-23.S3 server byte/PTS verification, REC source-frame and calibration mapping,
      aspect-preserving quality profile; synthetic and local FFmpeg checks only.
- [x] AUD-23.S4 local upload UI/content-bound recovery and regression tests.
- [ ] AUD-23.S5 browser, bandwidth, held-out quality and paired-sensor geometry
      acceptance. Local Chrome 153 upload/manifest/frame-map and candidate
      compression/SSIM measurements are recorded; representative device captures,
      held-out quality and real LiDAR/reconstruction evidence remain open.
- [x] AUD-24.S1 typed staged-file/assembly/resolution/recipe contracts and seven-case
      binding matrix; legacy InputManifest/checksum preserved. This does not enable
      a new resolver or R1–R6 runtime.
- [ ] Implementation AUD-24 và grouped upload/R1–R6 recipe/consumer/browser acceptance.
- [x] Hoãn AUD-25/ADR0025 theo yêu cầu owner; gỡ khỏi execution order và active dependencies.

## Validation và handoff

Mỗi sprint ghi command, exit code, counts, artifact refs/checksums, phạm vi proof
và phần pending trong Result của task. Checklist không thay output thực tế.
Đọc [AGENT_GUIDE.md](AGENT_GUIDE.md) để biết checks và mẫu prompt nhận task.
Plan chỉ chuyển Completed khi tất cả acceptance thuộc active scope được chứng minh.
AUD-25 giữ Deferred, không đánh dấu Completed hoặc tự implement trong các task khác.

## Result

Plan hiện có 33 Markdown documents, 28 task files và 105 sprint definitions. Active
scope có 26 work packages/96 sprint slices/12 ADR Proposed and ADR 0022 Accepted;
AUD-16 và AUD-25 giữ 9 sprint Deferred theo yêu cầu owner. AUD-06/24 vẫn nhận
PLY/SOG cho view; AUD-19 không đợi hoặc implement imported-source adapter.
Subsequent sprint work has changed source code:
AUD-19.S1 adds registration contracts; S2/S3 add local BEV/ICP algorithm components;
S4a–S4g add durable operation/source/target preparation, diagnostic plane
hypotheses, cancellation persistence/shared admission identity, and durable
resource-wait requeue; S4h connects the worker to shared admission and publishes
provisional source/diagnostic/proposal/QA artifacts; S4i adds authenticated operation
enqueue/status/cancel routes with job/project/revision binding and safe status views;
S4j adds server-sealed request preparation from accepted R2/R3 recipes and the current
scene; S4k adds Studio preflight/start/status/cancel with idempotent recovery; S4l adds
read-only proposal/QA inspection bound to exact artifacts and scene revisions. Proposal
overlay, scene confirmation/consumer paths, and runtime/held-out qualification remain
open.
Validation at initial plan creation exited 0: 25 integration sections gồm một
Deferred, 231 local links, 121 existing pytest paths và 138 canonical bindings;
80 active sprints đúng internal order, 37 cross-task prerequisite pairs và 6
AUD-25 deferred sprints ngoài execution order/dependencies. Later owner-directed
updates are reflected in the current 26/96 counts above. `git diff --check` exited
0. This validates plan documents, not runtime acceptance.
Các số liệu cấu trúc tài liệu là snapshot của lần tạo plan; Result/Evidence ở từng
task mới là nguồn hiện trạng sau từng sprint.
