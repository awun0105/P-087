# AUD-21 — Guest signup và quyền theo ownership

## Metadata và goal

- IN PROGRESS — S1–S4 code implementation is complete; S4 browser acceptance and rollout gates remain pending. P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. S2 adds Guest signup behind a closed rollout flag; S3 adds backend ownership guards. No production account or rollout flag was changed.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Role hiện chỉ editor/reviewer, Reviewer rank cao hơn và server sessions re-read
current user. Register cần invite; require_editor sẽ reject Guest nếu chỉ thêm rank.
Frontend canEdit hiện cho mọi signed-in user; trash route chưa phân quyền theo
owner. Product router áp require_editor toàn router, Studio áp tương tự cho hầu hết
module; đây là role gate, chưa phải resource ownership. Reviewer paths có guard
riêng. `JobManifest` là artifact checksum-bound và chưa có creator; không được
thêm metadata vào bytes cũ để giả owner.

CodeGraph/source inventory đã đi qua auth/session, project/job persistence,
upload/import/trash, scene edits/objectify, metric, simulation, demo, review,
product router và Studio router. Những điểm thiếu được phân định rõ ở matrix S1.
CodeGraph call graph là evidence điều hướng; route inventory bên dưới được đối
chiếu với decorators, router-level dependencies và service write paths hiện tại.
Không lấy việc ẩn button làm access control.

## Input / output / data contract

Ba roles guest < editor < reviewer. Guest có Editor workflows trên resources mình
sở hữu; không edit/delete job của user khác. Shared read như Editor hiện tại; không
invent private tenancy. Editor/Reviewer giữ cross-user collaboration hiện có, gồm
can thiệp job Guest; reviewer-only review/release/team admin vẫn chỉ Reviewer.
Guest signup cần email + display_name + password, không invite, server hardcode
role guest. Invited registration vẫn lấy role editor/reviewer từ invitation hợp lệ.
Email verification deferred; email syntactically valid không nghĩa verified. Guest
là authenticated account, khác anonymous visitor. Không mở anonymous editor APIs.
Stable creator user_id là ownership; run actor không thay owner. Kiểm tra job và
mọi parent/resource thực sự bị mutate. Legacy owner unknown: Guest read được,
mutation denied; không gán owner theo tên/email/current login. Proposed resource
capabilities phản ánh server policy; frontend chỉ dùng để hiển thị.
Reviewer user-management nhận Guest, không cho self-demote tới guest/editor hoặc
self-disable; thay role có hiệu lực session request kế tiếp. Không cấp quyền qua
client role, snapshot role hoặc numeric rank đơn lẻ.

## Logic change và dependent updates

Risk: **Rất cao** khi chỉ sửa một phần. Logic delta: Three-role ownership policy toàn bộ mutations.
Cần sửa đồng bộ: auth role schemas/session/Team UI/invite/signup, contributor dependency, Studio/legacy API/service/worker mutation ingress, frontend capability và audit.
Acceptance xuyên consumer: Guest own/foreign/unknown resources, anonymous/auth-disabled, Editor/Reviewer intervention và reviewer-only paths tested end-to-end; no global canEdit bypass.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập, phối hợp AUD-20.S1. S2/S3 trước rollout open signup; S4 dùng AUD-22.S2
atomic quota. AUD-06/07/08/09/10/16/17/18/19 consumers phải áp dụng resource guard
trước enqueue/commit. Contract có thể tích hợp sớm; không cycle chờ whole epics.

## Ma trận quyền AUD-21.S1

Role hierarchy là mức chức năng; resource ownership là chiều kiểm tra độc lập.
Không dùng so sánh rank làm phép kiểm duy nhất. Guest nhận các chức năng Editor,
nhưng thao tác ghi chỉ trên resources mình sở hữu; Editor và Reviewer giữ khả
năng can thiệp cross-user như hiện tại. Role trong Actor/creator snapshot chỉ để
hiển thị/audit; authorization luôn đọc UserRecord hiện tại.

| Nhóm hành động / entrypoint hiện có | Guest | Editor | Reviewer | Ranh giới cần enforce |
|---|---|---|---|---|
| Đăng nhập/đăng xuất; đăng ký hiện yêu cầu invite (`api/auth.py`) | Signup mới không invite tạo Guest ở S2; không nhận role từ payload | Invite flow giữ nguyên | Invite flow giữ nguyên | Server gán Guest; invite hợp lệ mới cấp Editor/Reviewer; invalid invite không fallback |
| User list/update, invite, audit (`api/auth.py`) | Không | Không | Toàn quyền như hiện tại, kể cả quản lý Guest | Chặn self-demotion/self-disable; role mới có hiệu lực ở request kế tiếp |
| Tạo upload (`POST /uploads`, `POST /uploads/direct`) | Có, tạo upload do mình sở hữu | Có | Có | `UploadRecord.uploaded_by.user_id` là owner; giữ nguyên qua verify/complete |
| Upload session (`POST .../urls`, `complete`, `abort`) | Chỉ session/upload của mình | Cross-user như hiện tại | Cross-user như hiện tại | Kiểm tra session ID + owner trước khi cấp URL, complete hoặc xóa part; background verify giữ creator |
| Tạo project/scene/job (`POST /projects`, `/projects/{id}/jobs`, `/scenes/from-upload`) | Tạo được; chỉ project của mình và chỉ dùng upload của mình | Có thể tạo ở project/dùng upload người khác như hiện tại | Như Editor | Creator project và từng job được lưu riêng; Guest không tạo child dưới project foreign |
| Import 3DGS (`POST /imports`) | Có, chỉ từ upload của mình | Cross-user như hiện tại | Cross-user như hiện tại | `ImportedScene.created_by` là owner; gói nền không thay owner |
| Shared reads: project/job/scene/progress/artifacts/imports/review-state/trash | Đọc như Editor | Đọc hiện tại | Đọc hiện tại | Giữ shared workspace; creator không thành tenant boundary |
| Job lifecycle: cancel (`POST /jobs/{id}/transitions`), retry (`POST /jobs/{id}/retry`) | Chỉ job của mình; Retry thêm áp dụng quota AUD-22 | Cross-user như hiện tại | Cross-user như hiện tại | Job owner, không project owner hay người chạy attempt gần nhất |
| Scene edits, object actions/add/catalog, restore revision, objectify (`api/product/scene.py`) | Chỉ job của mình | Cross-user như hiện tại | Cross-user như hiện tại | Owner check trước khi ghi revision/xếp queue; CAS/revision gate vẫn bắt buộc |
| Metric read/compute/preview (`metric/lidar`, `/preview`) | Shared read như Editor | Shared read | Shared read | Preview hiện chỉ tính toán; vẫn giữ shared-read semantics |
| Metric confirmation (`POST .../metric/confirm`) | Chỉ job của mình | Cross-user như hiện tại | Cross-user như hiện tại | Job owner guard trước commit và queue continuation |
| Simulation package create | Chỉ job của mình | Cross-user như hiện tại | Cross-user như hiện tại | Package/revision thừa hưởng owner job; download vẫn shared read |
| Demo reset | Chỉ job của mình | Cross-user như hiện tại | Cross-user như hiện tại | Reset tạo revision nên là job mutation |
| Demo baseline mark/clear; review decision/release (`api/studio/review.py`, `api/product/review.py`) | Không | Không | Reviewer-only như hiện tại | Guard riêng không bị hạ khi contributor gate mở cho Guest |
| Scene/import delete; trash restore | Chỉ resource mình sở hữu | Cross-user như hiện tại | Cross-user như hiện tại | Xóa scene kiểm project và toàn bộ descendants thực sự bị xóa; restore xét owner gốc, không xét `deleted_by` |
| Trash purge | Không | Không | Reviewer-only như hiện tại | Per-entry failure; foreign Guest entry không bị xóa do request ghép |
| Chat, processing evaluate và public options/samples | Guest có quyền Editor với chat; evaluate/options/samples giữ behavior hiện tại | Giữ nguyên | Giữ nguyên | Không gắn ownership cho endpoint không có resource; quota job không áp dụng |

Các route từ `api/product/*` nằm dưới router-level `require_editor`; các module
Studio như upload/scene/import/metric/simulation/trash cũng có dependency này.
Đổi gate đó thành authenticated contributor chỉ mở chức năng cho Guest, không tự
cấp quyền ghi foreign resource. `samples`/`processing` đang public; reviewer review
vẫn có guard riêng. Khi `AUTH_REQUIRED=false`, giữ bypass local hiện có cho route
đi qua `require_editor`; endpoint đòi reviewer thật tiếp tục fail-closed. Khi bật
auth, anonymous chỉ dùng endpoints vốn public và luồng auth.

### Ownership và tương thích dữ liệu

- Owner là `user_id` bất biến. `display_name`/role snapshot là metadata hiển thị,
  không phải owner key hoặc quyền hiện tại.
- Project dùng `ProjectRecord.created_by.user_id`; upload/session dùng
  `uploaded_by.user_id`; import dùng `ImportedScene.created_by`. Endpoint tạo
  project thường hiện chưa truyền actor, nên phải bổ sung producer trước khi mở Guest.
- Job owner là user tạo job tại `POST /projects/{project_id}/jobs`; khác project
  owner và `requested_by` của run/retry. Thêm `owner_user_id` nullable vào row
  authoritative `r2s_jobs`, ghi cùng transaction lần tạo job. Không đưa owner vào
  checksum-bound `JobManifest`; không sửa manifest/artifact cũ.
- Guest tạo child job/input trong parent project chỉ khi sở hữu parent và mọi input
  upload gắn vào thao tác. Job-scoped edit chỉ yêu cầu owner job nếu parent không bị
  ghi. Xóa project kiểm project và mọi child job/import/upload sẽ bị xóa; một
  descendant foreign/unknown làm hủy cả thao tác trước side effect.
- Derived revisions, objectify/package work thừa hưởng owner của job; import package
  thừa hưởng import owner. Operator can thiệp chỉ đổi actor/event, tuyệt đối không
  đổi owner. Trash giữ owner gốc; `deleted_by` chỉ là người chuyển vào thùng rác.
- Migration additive trong `RuntimeDatabase`, chạy SQLite/PostgreSQL. Job owner
  nullable cho legacy/anonymous, set đúng một lần lúc insert và không đổi khi
  status/retry cập nhật. Backfill chỉ từ creator ID đã lưu; không suy từ tên,
  email, parent owner, `requested_by` mới nhất hoặc current account. Hiện job cũ
  chưa có creator authoritative nên owner unknown: Guest shared-read only,
  Editor/Reviewer vẫn được can thiệp. Không rewrite ArtifactRefs/checksums hoặc reset DB.
- Ownership được kiểm tra trong cùng transaction/CAS với mutation khi có thể;
  multi-select giữ semantics per-entry nhưng project cascade không xóa một phần.
  Deny Guest foreign/unknown write trước enqueue, artifact publication hoặc quota
  charge. Dùng 403 cho known foreign/unknown owner, 404 cho resource không tồn tại;
  giữ lỗi domain hiện có ngoài authorization.

### Worker handoff

API/service dựng command từ authenticated UserRecord: actor ID, target resource IDs,
owner IDs, operation ID và expected revision/checksum. Browser payload không thể
chỉ định owner, actor hoặc role. Worker continuation giữ nguyên actor/owner đã
authorize; role snapshot chỉ là audit. Durable commit kiểm tra owner mapping,
parent/target identity, expected revision và lease fencing trước khi publish
pointer/state. System continuation của intent đã accept không tạo owner mới hoặc
quota charge mới. Worker không được bypass shared guard hoặc tin `Actor.role`.

## Sprint AUD-21.S1 — Permission matrix và resource identity

**Input:** Current routes/services, two-role tests.
**Output:** Three-role operation matrix, immutable ownership và migration spec.
**Contract:** Reviewer > Editor > Guest; existing higher-role rights preserved.

Implement: Inventory create/read/edit/rename/cancel/retry/trash/restore/purge, object/metric/registration/import, review/admin và legacy routes. Chốt resource checks cho từng action; worker command giữ authorized actor/owner và recheck role/ownership tại durable commit khi cần.
Tests: Matrix Guest own/foreign/unknown, Editor/Reviewer cross-user, anonymous/auth-disabled local, job khác parent owner.
**Exit:** [x] matrix phủ mọi mutation route/worker ingress; ownership và legacy
data migration contract đã chốt từ source inventory.

## Sprint AUD-21.S2 — Guest registration và role lifecycle

**Input:** S1 + existing invite/session service.
**Output:** Guest signup API/UI; invited flow unchanged; public enablement remains off until S3/S4.
**Contract:** No invite always Guest; invalid supplied invite không nâng quyền hoặc silently fallback.

Implement: Separate explicit guest/invited mode; reject forged role, reuse email/password/name validation, transactional duplicate handling và current limiter. Extend role schemas/Team UI/CLI where supported; invite roles vẫn Editor/Reviewer. Giữ secure cookies/session and audit; không thêm SMTP hoặc verified claim.
Tests: No invite Guest success, invited roles regression, invalid/used invite, duplicate normalized email concurrent, role injection, inactive users, promotion/demotion/self-demotion.
**Exit:** [x] signup/role changes server-enforced; public rollout remains gated until ownership/quota checks pass. Browser acceptance is separately tracked below.

## Sprint AUD-21.S3 — Backend ownership và interference

**Input:** S1 immutable owner + S2 users.
**Output:** Resource guard trên mọi supported mutation; audited operator intervention.
**Contract:** Editor/Reviewer can operate Guest jobs; Guest chỉ own.

Implement: Reuse shared guard trong API/service boundaries; do not blanket downgrade require_editor on quota-gated operations. Product and Studio shared-read roots admit contributors; every supported mutation checks owner before write/queue/artifact work. Check legacy endpoints, foreign object/artifact refs, cancel/retry/delete/restore and background publish paths. Preserve revision CAS and denied request no side effects. Job creation, Retry, scene-from-upload and objectify retain explicit Editor gates until AUD-22.S2 integrates their run/admission policies.
Tests: Direct HTTP bypass, forged owner/resource IDs, foreign cancel/delete/retry, same-parent foreign job, inactive/demoted actor, denied no enqueue/artifact write, cross-user higher roles.
**Exit:** [x] direct API tests deny Guest mutations of foreign/unknown resources before side effects; own-job cancellation, Editor/Reviewer intervention and Reviewer-only routes remain covered.

## Sprint AUD-21.S4 — Studio permissions và rollout acceptance

**Input:** S2/S3 + AUD-22.S2 quota.
**Output:** Guest experience và regression evidence.
**Contract:** Frontend capabilities không thay server authorization.

Implement: Replace global canEdit for resource actions with typed server capability. Hide/disable foreign mutation, giữ shared viewing và own cancel/edit at exhausted quota. Distinguish Visitor/Guest, show role names; update auth/UX docs theo approved feature, forward migration/rollback feature flag không reset DB. Keep the public Guest signup flag closed until browser/API matrix and rollout prerequisites pass.
Tests: Real browser three roles, own/foreign card/detail/trash, direct API denied, reviewer/editor Guest intervention, auth-disabled dev regression.
**Exit:** [ ] browser/API matrix pass trước public signup enable. Local focused API/frontend coverage is implementation evidence, not rendered browser acceptance.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_auth_service.py tests/test_api/test_auth_routes.py tests/test_api/test_studio_routes.py tests/test_api/test_scene_routes.py -q
.venv/bin/pytest tests/test_api/test_guest_ownership.py tests/test_api/test_trash_routes.py -q
```

Thêm tests mới theo sprint rồi bổ sung command. Chạy ruff; frontend lint/typecheck,
focused tests/build khi sửa UI. DONE cần real DB concurrency/API và browser evidence;
mock hoặc source review không chứng minh feature đã chạy.

## Result / Evidence

### AUD-21.S1 — permission matrix và resource identity

- **Base:** `6fea33e` (`AUD-20.S1`).
- **Files:** task AUD-21, ADR 0021, master execution README.
- **CodeGraph/current-source evidence:** traced auth/session, router-level and
  explicit role dependencies, all API POST/PATCH/DELETE decorators, project/job
  persistence, deletion, upload/import, scene, metric, simulation, demo/review.
  Confirmed `JobManifest` has no creator; project-from-upload persists Actor but
  ordinary project creation does not pass it; job owner can live on
  `r2s_jobs` without changing manifest bytes/checksum. Manual sync reports
  up-to-date: 757 files, 13,724 nodes, 39,422 edges.
- **Decision:** shared reads stay shared; Guest gets Editor feature gates but writes
  only own resources. Ownership is immutable user ID, separate from parent project,
  latest run actor, `deleted_by`, display name and snapshot role. Known-owner sources
  and nullable job-row migration/backfill rules are recorded above. Editor/Reviewer
  cross-user rights and Reviewer-only actions are preserved.
- **Verification:** focused `codegraph explore` across auth/router, persistence,
  deletion, upload/import, scene, metric, simulation, demo/review; exact decorators
  and router dependencies cross-checked against current source. `codegraph sync`
  reports up-to-date; `codegraph status` confirms index up-to-date;
  `git diff --check` PASS; relative Markdown links PASS.
- **Gate report:** CodeGraph PASS; minimum scope PASS (docs/contract only); source
  checks N/A; browser N/A (no UI changes); docs diff/link checks PASS.
- **Pending:** S1 adds no schema/source implementation. S2–S4 own API/worker
  enforcement, migration execution, browser/API tests and rollout enablement.

### AUD-21.S2 — Guest signup API/UI và role lifecycle

- **Base:** `948c4ba` (`AUD-20.S3` UI code; its browser/seed gates remain open).
- **Implementation:** Added `guest` to account/session/actor role contracts and a
  separate `InviteRole` limited to Editor/Reviewer. Added transactional
  `AuthService.register_guest`, `/auth/register/guest`, `/auth/me` rollout flag,
  `AUTH_GUEST_SIGNUP_ENABLED=false` defaults in Settings and Compose, and a
  distinct Guest form at `/register?mode=guest`. Guest role comes only from the
  server; extra `role` or `invite_code` fields are rejected. Invite signup remains
  one-time and role-bound. The new account receives the existing httpOnly session
  cookie and an audit event; no email-verification claim or mail sender was added.
- **Role lifecycle:** Reviewer-only updates can promote/demote Guest; role checks
  use Guest < Editor < Reviewer. Self-demotion is rejected by rank, inactive users
  remain unable to authenticate, and sessions read the current role on each
  request. Team management can assign Guest but still only issues Editor/Reviewer
  invitations. CLI role choices and metric/import/job actor snapshots accept Guest.
- **UI contracts:** `/account` shows Guest as a distinct role and does not display
  the Editor 24-hour quota as if it were Guest's limit. The team page distinguishes
  the not-yet-open Guest processing limit; AUD-22 owns its enforcement/display.
- **Duplicate handling:** SQLite's `BEGIN IMMEDIATE`, the existing unique email
  constraint, and a PostgreSQL transaction advisory lock serialize normalized
  duplicate email creation. The duplicate remains a `409` domain conflict.
- **Verification:** `codegraph sync` and focused `codegraph explore` report the
  current signup/role call path; CodeGraph is up to date. Ruff check passed for
  all `src/` and `tests/`; Ruff format check passed. Backend regression command
  across auth service/routes, metric routes/records, Studio routes, auth identity,
  Compose and settings: **71 passed, 13 skipped**. Skips are PostgreSQL variants
  because `R2S_TEST_POSTGRES_URL` is not configured. Frontend: `npm run typecheck`
  passed; `npx eslint` on changed auth/contracts files passed; `npx vitest run`
  passed **42 files / 278 tests**. Compose base and merged GPU configs passed with
  `.env.example`; CLI help lists `{guest,editor,reviewer}`. `git diff --check` passed.
- **Gate report:** CodeGraph PASS; minimal scope PASS; backend lint/format/tests
  PASS; frontend typecheck/lint/tests PASS; Compose validation PASS; no schema
  migration required. Chrome DevTools MCP verified `/register?mode=guest` in an
  isolated unauthenticated context. The page shows the closed-rollout message;
  `GET /api/v1/auth/me` returned 200 with no `guest_signup_enabled` field, so the
  UI stayed closed by its documented fail-closed default. The enabled form and
  submission remain **UNVERIFIED** because this running API does not expose the
  rollout field; no account was created.
- **Pending:** Signup remains disabled by default. Do not enable
  `AUTH_GUEST_SIGNUP_ENABLED` before AUD-21.S3 ownership guards and AUD-22 quota
  enforcement are qualified. Run the enabled-form browser/API gate; local PostgreSQL
  signup-concurrency evidence is recorded in the follow-up below. AUD-21.S3 adds
  ownership checks; this sprint intentionally leaves existing Editor-only product
  gates intact.

### AUD-21.S3 — backend ownership và interference

- **Base:** `ee1f078` (`AUD-21.S2`).
- **Implementation:** Added `require_contributor` at product/Studio shared roots so
  Guest can use Editor-level reads and chat. Added a shared resource-owner guard
  and wired it before project/job/scene/import/upload/metric/simulation/demo/trash
  mutations. Guest is denied for foreign or unknown owners before queue, revision,
  signed-URL, artifact or delete/restore side effects. Project cascades validate
  every descendant. Jobs persist nullable immutable `owner_user_id` in migration
  13 outside checksum-bound `JobManifest`; old jobs remain owner-unknown. Upload,
  project and job creators survive worker/retry/trash transitions. Editor/Reviewer
  cross-owner actions write `operator.intervention` audit rows. Reviewer-only
  review, release, baseline and purge routes keep their explicit guards.
- **Tests:** Added direct HTTP coverage for foreign/unknown cancel, owned database
  job cancellation, foreign scene edit, direct-upload URL presigning, foreign
  import, and Editor/Reviewer intervention. Added DB tests for owner immutability,
  retry/operator actor separation, cascade denial without side effects, trash
  restore and migration from legacy schemas. Updated the Guest shared-read/project
  creation and reviewer-route assertions.
- **CodeGraph evidence:** Explored auth dependencies and all product/Studio mutation
  callers before edits; post-edit `codegraph sync` is current at 761 files,
  13,859 nodes and 39,881 edges.
- **Verification:** `ruff check src/ tests/` PASS; `ruff format --check src/ tests/`
  PASS; `pytest tests/test_api -q` — 138 passed; `pytest tests/test_orchestration
  -q` — 578 passed, 20 skipped; Studio processing/upload integration — 9 passed;
  runtime migration tests — 10 passed, 4 skipped; `git diff --check` PASS.
  PostgreSQL-only variants skip because `R2S_TEST_POSTGRES_URL` is unset.
- **Gate report:** CodeGraph PASS; shared callers updated and tests cover direct
  API access; minimal scope PASS; backend checks PASS. Browser DevTools is
  **UNVERIFIED**: MCP reports that the Chrome profile is already running and
  cannot attach. No rendered UI changed in S3, but the runtime permission flow has
  not received browser acceptance.
- **Pending:** `AUTH_GUEST_SIGNUP_ENABLED` remains false. AUD-22.S2 now admits
  Guest job creation, scene-from-upload and manual Retry under the daily quota;
  objectify remains outside that counter. Guest rollout still awaits AUD-22.S3,
  AUD-21.S4, browser/seed acceptance and deployed multi-replica qualification;
  local PostgreSQL signup/quota checks are recorded in the follow-up below.

### AUD-21.S4 — Studio permissions và rollout acceptance

- **Base:** `69e82dc` (`AUD-22.S3`); no migration required.
- **Implementation:** Added typed per-caller capabilities to `/scenes`, job
  `/progress`, `/imports` and `/trash`. Guest sees own-resource edit/cancel/retry,
  project-delete, import-delete and trash-restore affordances only when server
  capability allows them; Guest remains able to view shared scenes and edit an
  owned scene when daily run quota is exhausted. Editor and Reviewer receive
  cross-user mutation capabilities as before; purge stays Reviewer-only. The
  server mutation guards remain authoritative. Scene/import cards show Guest as a
  role distinct from anonymous Visitor. Updated ADR 0021, PRD v1.18 and this UX
  spec to replace stale two-role/invite-only statements. Signup flag remains false.
- **Quota clarification:** Guest quota counts accepted scene/job creation and
  manual Retry only. Objectify/tách vật is excluded and continues to use resource
  admission; see AUD-22.
- **Tests:** Added API matrix for Guest-owned/foreign/unknown and Editor/Reviewer
  job capabilities; import list capability by role; HTTP scene/trash ownership
  coverage with Guest-only restore and Reviewer purge. Frontend tests cover card,
  import, job detail/read-only editor, retry, trash selection/bulk restore, role
  labels and owner edits at quota cap.
- **Verification:** `.venv/bin/ruff check src/ tests/` PASS; `.venv/bin/ruff
  format --check src/ tests/` PASS (478 files); `.venv/bin/pytest
  tests/test_api -q` PASS (152); `cd frontend && npm run typecheck` PASS,
  changed-file `npm run lint -- ...` PASS, and `npm test -- --run` PASS
  (43 files, 300 tests); `git diff --check` PASS. The focused permission/deletion
  subset also passed (56 tests).
- **Gate report:** CodeGraph was used before editing and final index sync passed.
  Browser DevTools remains **UNVERIFIED** because the Chrome
  profile lock prevents attachment; local tests are not browser proof. PostgreSQL
  qualification was not run because `R2S_TEST_POSTGRES_URL` is unset. AUD-20
  live-seed acceptance remains a separate rollout gate.
- **Pending:** Keep `AUTH_GUEST_SIGNUP_ENABLED=false`; local PostgreSQL signup/quota
  tests pass, but browser three-role acceptance, live seed acceptance and deployed
  multi-replica qualification remain open.

### Follow-up — local PostgreSQL checks (2026-10-09)

- `.venv/bin/pytest tests/test_orchestration/test_auth_service.py -q` with the
  local PostgreSQL 16 service configured through `R2S_TEST_POSTGRES_URL`: **23 passed**.
  This includes the normalized duplicate-email concurrency path.
- These checks supersede the earlier note that PostgreSQL was unavailable for the
  signup-service test. They do not prove the deployed multi-replica configuration,
  enabled public signup, the three-role browser flow or live seed-account display.
  Keep `AUTH_GUEST_SIGNUP_ENABLED=false` until those rollout gates pass.
