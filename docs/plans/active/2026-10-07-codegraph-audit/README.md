# Execution Plan: Hoàn thiện codebase sau audit CodeGraph

Date: 2026-10-07

## Status

Active — implementation đang diễn ra trên branch
`docs/codegraph-audit-implementation-plan`, khởi tạo từ `develop@ef3a421`.
Đã commit: AUD-11.S1–S2, AUD-15.S1, AUD-01.S1–S3, AUD-02.S1–S3,
AUD-03.S1–S3, AUD-04.S1–S3, AUD-10.S1–S3 và AUD-07.S1. AUD-07.S2 đã hoàn tất
trong commit `5173750`; AUD-20.S1 trong `6fea33e`; AUD-20.S2 producer/API attribution
trong `7d5fcac`. AUD-20.S3 đã có code badge creator/role ở Scenes và imports cùng
test CLI; browser và live-seed acceptance đang chờ môi trường. AUD-21.S1 đã chốt ma trận quyền,
identity owner và migration contract trong commit `31ffac2`. AUD-22.S1 calendar
contract đã hoàn tất; browser DevTools MCP gate của AUD-03.S3 vẫn
UNVERIFIED; PostgreSQL proof của AUD-04.S3 chưa chạy vì thiếu
`R2S_TEST_POSTGRES_URL`. AUD-21.S2 đã implement Guest signup và role lifecycle,
nhưng `AUTH_GUEST_SIGNUP_ENABLED` đang mặc định `false`; browser gate của form
còn UNVERIFIED. AUD-21.S3 đã thêm owner guards, immutable job owner và audited
operator intervention; browser DevTools gate còn UNVERIFIED do Chrome profile lock.
AUD-22.S2 đã implement quota Guest atomic và enforcement trên các API tạo job/Retry.
AUD-22.S3 đã thêm quota/reset UI, refresh sau accepted run và stale-tab 429 recovery.
AUD-21.S4 đã áp dụng server capability cho các thao tác Studio và quyền theo
ownership. Local verification: API 152 pass, frontend 300 pass, typecheck/lint,
Ruff check/format đều pass. PostgreSQL qualification pending vì
`R2S_TEST_POSTGRES_URL` chưa được cấu hình; DevTools visual gate **UNVERIFIED** do
Chrome profile lock. Guest rollout vẫn đợi database qualification, browser
acceptance và AUD-20.S3 seed acceptance.
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
Active scope: 24 packages/80 sprints. AUD-25/ADR0025 Deferred theo yêu cầu owner
2026-10-07; không là dependency hoặc implementation work trong kế hoạch hiện tại.

## Outcome

Scene sau chỉnh sửa phải xuất đúng collision/physics. Candidate phải được
validation trên đúng runtime trước review. Release phải giữ cùng một identity
qua retry. Import và reobjectify phải phục hồi được, dùng admission và không ghi
đè chỉnh sửa của người dùng. Collision quality được đo cùng obstacle retention;
LiDAR QA/adaptive floor, measured latency và Fast Preview có producer/consumer
contract. Automatic map registration giảm manual landmarks và mở independent-map
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
| Collider editor chưa có | Source: dimensions chỉ hiển thị; transform edit chỉ position/rotation object | AUD-09 |
| Recovery revision tuyến tính, giới hạn 1.000 | Source: SceneEditor._recover; chưa có probe 1.000 revision | AUD-10 |
| Hai test không khớp fixture/runtime hiện tại | Backend suite: 1.522 pass, 2 fail, 40 skip; real child cancellation kill/reap thành công | AUD-11 |
| Collision clearance kém trên traversal được đo | 3DGS 0,05 m: 33/50; LiDAR 0/100 cần refusion min_range 2/3 m + floor_band 0,15 m; chưa đo obstacle recall | AUD-12 |
| LiDAR projection QA thiếu | Package syntax checks và world-cloud overlay có; chưa có scored calibration/timing QA | AUD-13 |
| Floor extraction chưa adaptive | Default clearance 0,06 m và raw-z mask; chưa có fitted floor/noise evidence | AUD-14 |
| Worker latency cần đo đủ và tối ưu | Brush 42,6–45 phút ở partial attempts; chưa là complete job latency | AUD-15 |
| Fast Preview lifecycle chưa có | Knob 7k iterations đã hợp lệ; preset/tier/lineage/promotion/UX chưa có | AUD-16 |
| Raw scans thiếu trajectory bị reject | LiDAR odometry khả thi; cần explicit mode/runtime/provenance/drift QA | AUD-17 |
| Auto anonymizer producer thiếu | Self-attested flow có; strict QA gate có; detection/tracking/redaction integration chưa có | AUD-18 |
| Automatic registration cho independent maps cần bổ sung | Trajectory-based no-point fit đã có; geometric BEV/ICP proposal/QA cho independent maps chưa có | AUD-19 |
| Video chưa nén trước upload, rotation/time mapping chưa explicit | Source: upload giữ bytes, decode passthrough, quality probe640×360; LiDAR ghép frame_id gốc | AUD-23 |
| SOG chưa accepted input; imported continuation chưa có | Source: ImportService chỉ package PLY/ZIP thành SOG viewer; Finalize/VisualResolver/objectify yêu cầu Brush/camera/frame lineage | AUD-06/24 cho view; AUD-25 Deferred |

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
| [AUD-16: Fast Preview](tasks/AUD-16-fast-preview.md) | P1 — EX-PRODUCT + EX-REC | REC-04/05, PRODUCT-02/08/09 | 3 |
| [AUD-17: LiDAR odometry](tasks/AUD-17-lidar-odometry.md) | P2 — EX-REC + EX-PRODUCT; opt-in | REC-08/06, PRODUCT-02/08/09 | 3 |
| [AUD-18: Privacy anonymizer](tasks/AUD-18-privacy-anonymizer.md) | P2 — EX-REC + EX-PRODUCT; opt-in | REC-02, PRODUCT-01/02/09 | 3 |
| [AUD-19: Automatic RGB–LiDAR registration](tasks/AUD-19-automatic-rgb-lidar-registration.md) | P1 — EX-REC + EX-PRODUCT; SCENE/SIM consumers | REC-06/08/09, PRODUCT-04/08/09 | 4 |
| [AUD-20: Tên và creator attribution](tasks/AUD-20-user-display-name-and-creator.md) | P1 — EX-PRODUCT | PRODUCT-01/02/06/09 | 3 |
| [AUD-21: Guest signup và ownership](tasks/AUD-21-guest-signup-and-ownership.md) | P1 — EX-PRODUCT | PRODUCT-01/02/06/09 | 4 |
| [AUD-22: Guest quota 3/ngày](tasks/AUD-22-guest-daily-job-quota.md) | P1 — EX-PRODUCT | PRODUCT-01/02/06/09 | 3 |
| [AUD-23: Nén video trước upload](tasks/AUD-23-client-video-normalization.md) | P1 — EX-PRODUCT + EX-REC | REC-02/03/04/08/09, PRODUCT-02/04/08/09 | 5 |
| [AUD-24: Unified upload và input resolution](tasks/AUD-24-unified-upload-and-input-resolution.md) | P1 — EX-PRODUCT + EX-REC | REC-02/03/06/08/09, PRODUCT-02/04/08/09 | 5 |
| [AUD-25: Imported PLY/SOG continuation](tasks/AUD-25-imported-3dgs-continuation.md) | Deferred — không implement; EX-REC/SCENE/PRODUCT/SIM nếu mở lại | REC-04/05/06/09, SCENE-02/03/06/08, SIM-02/04/07, PRODUCT-02/04/06/08/09/10/11 | 6 |

Active: **24 work packages / 80 sprint**. AUD-25 có 6 sprint Deferred giữ để
tham khảo; tổng tài liệu vẫn có 25 packages/86 sprint definitions. Mỗi sprint có Input, Output, Contract,
implementation steps, Tests và Exit; mỗi task có dependencies, verification/DoD
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

12 active ADRs remain Proposed and ADR 0022 is Accepted; ADR0025 is Deferred and
does not define active policy.
Không giả lập owner acceptance. Bug fixes trên
invariant hiện có có thể làm độc lập. Sprint thiết kế phải ghi rõ phần mới cần
producer/consumer review trước khi trở thành shared contract/policy.

## Approach và thứ tự thực hiện

Triển khai theo dependency của từng sprint. AUD number là identifier, không là
execution order; không cần xong toàn bộ một task mới được chuyển sang task khác.
Trong bảng, `S1–S3` là ba sprint liên tiếp, thực hiện theo thứ tự tăng dần.
Thứ tự mặc định gồm đủ **80 active sprint, mỗi sprint một lần**; không có AUD-25:

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
| 9 — Latency và Fast Preview | AUD-15.S2–S3 → AUD-16.S1–S3 | Measured optimization và preview/final lifecycle giữ đúng preparation identity và quality gates. |
| 10 — Input qualification và extensions | AUD-17.S1–S3 → AUD-24.S5 → AUD-18.S1–S3 | Estimated trajectory/input matrix R1–R6 và PLY/SOG view import; anonymizer opt-in có provenance/QA. |

Execution order bắt đầu ở **AUD-11.S1**; các sprint AUD-11.S1–S2, AUD-15.S1,
AUD-01–04, AUD-10.S1–S3, AUD-07.S1–S2, AUD-20.S1–S2, AUD-21.S1–S2 và AUD-22.S1
đã hoàn tất ở mức code/task của từng sprint. AUD-21.S3 đã thêm backend ownership
guards; AUD-20.S3 và AUD-21.S2 còn browser acceptance, AUD-20.S3 còn live-seed
acceptance. AUD-22.S2 code/API acceptance đã hoàn tất trên SQLite; AUD-22.S3 local
UX/API regression đã hoàn tất. PostgreSQL multi-process qualification và DevTools
browser acceptance còn pending. AUD-21.S4 caller-specific Studio capability/API
coverage is locally verified (152 API tests, 300 frontend tests, typecheck and
changed-file lint); browser three-role acceptance, shared-PostgreSQL qualification
and seed acceptance still block public Guest rollout.
AUD-15.S1 được làm sớm để AUD-23.S5 có measurement protocol; optimization
AUD-15.S2–S3 vẫn làm sau quality work.
AUD-07.S3 làm sau AUD-06/AUD-05 để kiểm tra admission trên consumer thật;
không đợi toàn bộ AUD-07 trước khi triển khai hai consumer này.

Sau mỗi sprint: sửa đồng bộ producer/persistence/API/worker/UI/config/tests bị
logic mới ảnh hưởng, chạy focused checks và integration scenario liên quan,
ghi Result/Evidence trước khi chuyển sprint phụ thuộc. Cuối mỗi đợt chạy regression
của các flows đã thay đổi; không dồn related-code updates hoặc integration tới cuối
80 active sprint. Trước enable schema mới, kiểm tra forward migration/read compatibility
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
hai package không đợi toàn bộ epic của nhau. AUD-15.S1 tạo timing protocol cho
AUD-16; AUD-15.S3 có thể dùng current pipeline, không bắt Fast Preview hoàn tất.
AUD-19 uses AUD-12.S1 quality fixtures; AUD-12 sensor-package path không đợi
AUD-19. Static-map consumer chỉ enable sau registration QA, không bắt AUD-19
đợi whole AUD-12 epic. Sensor calibration QA và map registration QA không tráo nhau.

Progress hiện tại: AUD-11.S1–S2, AUD-15.S1, AUD-01.S1–S3, AUD-02.S1–S3,
AUD-03.S1–S3, AUD-04.S1–S3, AUD-10.S1–S3 và AUD-07.S1–S2 đã được commit riêng
theo sprint.
AUD-01.S3 verified legacy
ownership recovery, candidate ZIP/manifest, current rotated object pose,
retained floor collision, relative USD asset composition, và bất biến bytes của
artifact cũ bằng OpenUSD runtime. AUD-02.S3 nối capability blocker qua typed
API/UI, giữ Preflight riêng, ngăn tải candidate khi export bị block và kiểm tra
quyền GET/POST/download. Automated checks pass; browser DevTools còn UNVERIFIED
vì Chrome DevTools MCP không lấy được session đang khóa profile. AUD-03.S3 đã
commit API/UI projection và stale request regressions; component harness QA
passed qua CLI, còn MCP gate và real Isaac acceptance (AUD-05) chờ môi trường.
AUD-04.S1 đóng băng release timestamp/manifest theo approval identity trong DB.
AUD-04.S2 xác minh ZIP closure và commit marker, lưu diagnostics an toàn, phục hồi
partial/missing artifacts, chặn download khi bytes sai; 53 backend tests (4 skip
vì thiếu `R2S_TEST_POSTGRES_URL`), 275 frontend tests, ESLint, typecheck, production
build, Ruff và CodeGraph đều pass. AUD-04.S3 kiểm tra hai registry độc lập trên
SQLite, stale revision ngay trước seal marker và API ZIP/manifest byte equality;
matrix pass 56 với 4 PostgreSQL skips do thiếu `R2S_TEST_POSTGRES_URL`. Browser
MCP gate còn UNVERIFIED; frontend checks không thay thế browser review hay
PostgreSQL proof. AUD-10.S1 added migration v12, checksummed head/backfill records,
bounded verify/recheck repair pages, a read-only/apply CLI, package import/export
and trash/restore consumers. Its matrix passed 123 tests with 4 PostgreSQL skips.
AUD-10.S2 routes DB-backed SceneIR writes through reserve/publish/verify/CAS and
reads through the committed head; legacy artifacts without a head require the
verified repair CLI. The S2 regression matrix, package/deletion consumers and
scene pipeline callers pass locally; PostgreSQL and live S3 proof remain pending.
AUD-10.S3 measures one head query, one `ArtifactResolver.locate` and zero list
calls at both rev-001 and rev-1005, checks independent DB/cache freshness and
fail-closed remote checksum verification, then reads a validated SceneIR after
package import and restores a checksummed head/repair history through trash. Its
matrix passed 180 tests with one PostgreSQL skip. CodeGraph is current; live
PostgreSQL locking and S3 provider proof remain pending.

AUD-21.S3 adds contributor-level shared read access and resource-level Guest
ownership guards across Product and Studio mutations. Job ownership is an
immutable nullable column outside the checksum-bound manifest; deletion checks
the entire cascade; Editor/Reviewer cross-owner actions are audited. The API suite
passed 138 tests, orchestration passed 578 with 20 skips, and processing/upload
integration passed 9. Four migration tests skipped without `R2S_TEST_POSTGRES_URL`;
Chrome DevTools remains UNVERIFIED because MCP cannot attach to its locked profile.
`AUTH_GUEST_SIGNUP_ENABLED` remains false. AUD-22.S2 implements the durable
Guest quota ledger; AUD-22.S3 implements local quota/reset UX and stale-tab refresh.
Frontend/API checks pass; DevTools browser acceptance and PostgreSQL qualification
remain pending.

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
- [ ] Implementation AUD-08–09 và browser acceptance.
- [ ] Implementation AUD-12–14 và held-out collision/LiDAR/floor acceptance.
- [ ] Implementation AUD-15–16 và real latency/preview/browser acceptance.
- [ ] Implementation AUD-17–18 và qualified opt-in runtime/QA acceptance.
- [ ] Implementation AUD-19 và held-out independent-map/QA/browser acceptance.

- [x] Implementation AUD-20.S1 identity/seed migration contract and AUD-20.S2 producer/API actor attribution.
- [x] AUD-21.S4 local Studio capability/API implementation and UI regression.
- [ ] AUD-20.S3 browser/seed acceptance; AUD-21.S2/S4 browser gates; AUD-21.S3–S4
      full browser/API acceptance before opening Guest signup.
- [x] Implementation AUD-22.S2 durable Guest quota ledger/API enforcement and
      AUD-22.S3 local quota UX; SQLite/API/frontend checks.
- [ ] AUD-22.S2 shared-PostgreSQL concurrency/restart qualification; AUD-22.S3
      DevTools browser acceptance.
- [x] Audit 2026-10-08 of rounds 1–3 (AUD-01/02/03/04/07/10/11/15), local evidence only.
      Fixed and committed: background carve now rejects only overlaps between a carved and a
      kept source region; legacy ownership recovery skips duplicates, matches by geometry
      artifact, follows `restored_from`, and derives ownership from the extraction revision
      (previously recovered nothing, so every pre-AUD-01 scene with a confirmed object could not
      export); `reobjectify` now binds ownership to its new objects; `SceneEditor.revision()`
      reuses the proven lineage (122-revision walk 94 s → 3 s); hybrid `GroundPlane` top was
      +9.8 mm above z=0; a restarted worker with the same `host:pid` no longer deadlocks on its
      leftover operation reservation. Evidence: full backend suite 1782 passed / 52 skipped;
      `tests/test_orchestration` + `tests/test_api` on Postgres 16 779 passed, 0 skipped
      (single process; multi-process/restart and the deployment database remain pending).
      Real-data probes on copies of the local DB/artifacts: head backfill for the 4 scene jobs
      (including the 122-revision chain) completes, and a real scene exported end to end to a
      hybrid package that opens in OpenUSD. Open product decisions: (1) with OBB-only ownership,
      a confirmed object whose box overlaps a kept candidate blocks export (5 such pairs in the
      122-revision scene) until AUD-08 exact membership or an explicit rule exists; (2) catalog
      assets (`asset_url`) can no longer be exported because they cannot be sealed as artifacts;
      (3) completed worker validation runs make a data package unpublishable until an
      authenticated receipt exists. After the API first migrates `runtime.db`, run
      `scripts.studio.scene_head --apply` per job or those 4 scenes return SceneNotAvailable.

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
- [ ] Implementation AUD-24 và grouped upload/R1–R6 recipe/consumer/browser acceptance.
- [x] Hoãn AUD-25/ADR0025 theo yêu cầu owner; gỡ khỏi execution order và active dependencies.

## Validation và handoff

Mỗi sprint ghi command, exit code, counts, artifact refs/checksums, phạm vi proof
và phần pending trong Result của task. Checklist không thay output thực tế.
Đọc [AGENT_GUIDE.md](AGENT_GUIDE.md) để biết checks và mẫu prompt nhận task.
Plan chỉ chuyển Completed khi tất cả acceptance thuộc active scope được chứng minh.
AUD-25 giữ Deferred, không đánh dấu Completed hoặc tự implement trong các task khác.

## Result

Plan lưu 46 Markdown documents, 25 task files và 86 sprint definitions. Active
scope có 24 tasks/80 sprints/12 ADR Proposed and ADR 0022 Accepted; AUD-25 với 6 sprint và ADR0025 Deferred
theo yêu cầu owner. AUD-06/24 vẫn nhận PLY/SOG cho view; AUD-19 không đợi hoặc
implement imported-source adapter. Source/runtime chưa thay đổi.
Document checks exit 0: 25 integration sections gồm một Deferred, 231 local links,
121 existing pytest paths và 138 canonical bindings trong toàn bộ tài liệu lưu;
đủ 80 active sprint không trùng, đúng internal order và 37 active cross-task
prerequisite pairs; 6 deferred sprint không trong execution order/dependencies.
`git diff --check` exit 0. Đây là kiểm tra
kế hoạch, không là runtime acceptance. Current local additions gồm 34 Markdown
files. Base plans đã commit/push ở e5597b0;
video/integration/unified-upload/import-continuation additions chưa commit/push
hoặc runtime acceptance.
