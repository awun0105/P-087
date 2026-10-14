# AUD-20 — Tên người dùng và thông tin người tạo trên scene

## Metadata và goal

- IN PROGRESS; P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. AUD-20.S1 có implementation; không đọc hoặc sửa live DB.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Display name đã có trong UserRecord/PublicUser, RegisterForm và CLI. AUD-20.S1–S2
đã đưa actor snapshot xuyên project/job/import producers và API: project giữ
`created_by`, job event giữ `requested_by` theo lần QUEUED, import giữ
`created_by_name`/`created_by_role`. ScenesHome đã render creator/requester nhưng
badge và consistency card/table/import còn thuộc S3. REUSE các fields này; không
tạo subsystem identity thứ hai. Seed accounts được giữ qua studio data packaging;
chưa đọc hoặc đổi live DB.

CodeGraph trước implementation đã lần Actor/actor_of → upload/project/demo và
`AuthService.actors()` → legacy `requested_by`; project owner nằm ở
`ProjectRecord.created_by`, còn import đang giữ ID/tên rời nhau. Đã kiểm tra
bootstrap container và account packaging; seed identities không được khai báo cố
định trong source, nên migration yêu cầu hai stable ID rõ ràng. Không lấy việc ẩn
button làm access control.

## Input / output / data contract

Registration input: email, display_name, password và invitation theo mode AUD-21.
Tên Unicode 1–100 ký tự sau trim, reject blank/control characters; render plain text.
Không dùng tên/email làm khóa ownership. Output PublicUser giữ stable user_id.
Creator attribution: immutable owner/creator user_id và name/role snapshot tại tạo;
requested_by là actor của run, khác creator. Role hiện tại từ server dùng authorization.
`Actor.role` và `ImportedScene.created_by_role` optional cho records cũ, bị loại khỏi
serialization khi thiếu; không rewrite artifact/checksum bất biến.
Legacy thiếu role: phản hồi API điền role hiện tại của đúng tài khoản (owner 2026-10-09, mục cuối Result); dữ liệu đã lưu không bao giờ bị ghi role suy ra.
Hai seed: Reviewer tên “Minh An”, Editor tên “Hà Linh”. Apply qua migration/setup
được định danh bằng stable ID/role, không rename mọi Reviewer/Editor. Nếu không tìm
đúng hai seed thì báo blocker, không chọn account bất kỳ; giữ email, ID, password,
active và role. Không lưu credential trong task/fixture hoặc tạo seed production mới.

## Logic change và dependent updates

Risk: **Vừa** khi chỉ sửa một phần. Logic delta: Identity/creator projection, role snapshot.
Cần sửa đồng bộ: UserRecord/Actor/PublicUser, register/seed setup/migration, project/job/import creator producer, API/list/card/table và packaging.
Acceptance xuyên consumer: Creator immutable khác run actor; snapshot role khác current auth; old payload/checksum và non-seed users không bị rewrite.
Mỗi sprint áp dụng [integration checklist](../INTEGRATION_MAP.md), ghi before/after,
actual callers/fields/config/migrations và related-code updates vào Result/Evidence.
Logic mới được chọn dẫn dắt consumers/tests; không giữ assumption cũ bằng workaround.

## Dependencies

S1 độc lập; S2 phối hợp AUD-21.S1 identity/owner matrix. S3 dùng S2 projection;
không đợi quota. Seed update không tự cấp quyền sửa archived bundles/checksums.

## Sprint AUD-20.S1 — Identity và migration

**Input:** Existing names/Actor/seed packaging fixtures.
**Output:** Compatible identity + creator DTO và seed migration spec.
**Contract:** Historical attribution khác current authorization.

Implement: Reuse name validation; chốt optional role snapshot/serialization. Inventory creator ownership của project/job/import; chỉ backfill từ provenance đáng tin. Migration dùng `--reviewer-user-id` và `--editor-user-id`, kiểm role hai ID trong cùng transaction, không tự tìm theo role.
Tests: Unicode/blank/control text, old payload/checksum, missing creator, repeated migration, non-seed untouched, seed credentials unchanged.
**Exit:** [x] contract/migration fixtures bảo vệ identity cũ.

## Sprint AUD-20.S2 — Producer và API projection

**Input:** S1 schema + authenticated creator.
**Output:** Creator name/role trên create/list/detail responses và actor snapshot
cho từng lượt tạo job/retry.
**Contract:** Creator immutable; Editor rerun Guest job không đổi owner. Actor chỉ
gắn với event bắt đầu lượt chạy `QUEUED`; worker status events không đổi người chạy.

Implement: Capture `ProjectRecord.created_by` lúc tạo, role creator cho import,
và `JobAttemptRecord.requested_by` trên lần tạo job/retry. Không thay đổi
`JobManifest` đã checksum. Batch-resolve audit legacy theo user ID; legacy name có
thể dùng tên hiện tại, role vẫn unknown. Không N+1 hoặc public email directory.
Client không tự chọn creator/role. Product job-create route cũng áp dụng quota hiện
có và ghi GPU-run audit để giữ cùng behavior với Studio upload/retry.
Tests: Forged creator JSON, intervention/role đổi sau khi ghi, absent legacy role,
project/job/import projection, quota guard trên product job-create route.
**Exit:** [x] mọi supported scene/job producer lưu attribution; list/detail API
trả snapshot hoặc trạng thái legacy unknown.

## Sprint AUD-20.S3 — Studio và seed acceptance

**Input:** S2 responses + two identified seed accounts.
**Output:** Name input hoàn thiện, creator/role badges trên cards/table/imports.
**Contract:** Badge chỉ thông tin; không quyết định quyền.

Implement: Reuse RegisterForm name input. Render tên người tạo job và role dễ đọc; separate chạy bởi khi actor khác creator. Update intended two seed names bằng migration đã review; add responsive/accessibility loading/error cases.
Tests: Guest/Editor/Reviewer create, card/table/import, rename snapshot, unknown role, XSS plain text, seed rerun idempotence và real browser.
**Exit:** UI implementation and CLI tests complete; [ ] browser attribution and
live seed-name evidence verified without secrets.

### AUD-20.S3a — Legacy import creator-name projection

**Input:** imported-scene rows with `created_by` but no creation-time name/role
snapshot, plus the existing batch actor lookup by user ID.
**Output:** list/detail/action responses can display the current account name for
legacy imports while keeping the historical role unknown.
**Contract:** projection only; never update the stored import or infer historical
role from the current account. Existing snapshots always take precedence. Unknown
or deleted creator IDs remain unresolved. Ownership and capabilities continue to
use the immutable `created_by` ID.

Implement: resolve only IDs that need a fallback, once per list response; apply the
same projection to single-import responses. Do not return email or mutate checksummed
artifacts. Tests cover legacy, snapshot, deleted-user, batch-call and ownership cases.
**Exit:** [x] API projection preserves the identity/authorization contract and
all focused tests pass; [ ] authenticated browser confirms the legacy import badge.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_auth_service.py tests/test_api/test_auth_routes.py tests/test_api/test_studio_routes.py tests/test_packaging/test_data_package.py -q
.venv/bin/pytest tests/test_api/test_guest_ownership.py -q
```

Thêm tests mới theo sprint rồi bổ sung command. Chạy ruff; frontend lint/typecheck,
focused tests/build khi sửa UI. DONE cần real DB concurrency/API và browser evidence;
mock hoặc source review không chứng minh feature đã chạy.

## Result / Evidence

### AUD-20.S1 — identity contract và seed migration

- Base: `5173750 feat(orchestration): fence objectify queue leases (AUD-07.S2)`.
- Logic delta: tên hiện được trim/validate theo Unicode 1–100 ký tự và từ chối control/separator; actor mới snapshot role khi producer có user; old actor/import thiếu role vẫn giữ trạng thái unknown và không serialize field role rỗng. `requested_by` hiện chỉ được resolve từ ID nên role để unknown cho tới AUD-20.S2; không suy từ role hiện tại.
- Producer/consumer: `actor_of` ghi role cho upload/project/demo snapshots; TypeScript `Actor` phản ánh optional role. `ImportedScene` thêm `created_by_role` optional để giữ payload cũ. `AuthService.actors()` chỉ resolve tên cho ID legacy và không gán role hiện tại.
- Migration: `scripts.studio.rename_seed_accounts` nhận đúng hai stable ID; kiểm ID tồn tại và role reviewer/editor trước mọi update, đổi tên idempotently trong một transaction. Chỉ thay display name, giữ email/ID/password hash/role/active/quota/created_at. Không chạy lệnh migration lên live DB vì ID seed chưa được xác minh.
- CodeGraph: đã đọc `UserRecord`, `Actor`, `actor_of`, `AuthService.actors`, `ProjectRecord`, `create_project_from_upload`, scene listing, `ImportedScene`/import callers và bootstrap/package paths; `codegraph sync`/`status` đều báo index up-to-date (757 files, 13,724 nodes, 39,422 edges). Auto-sync live watcher vẫn DISABLED do giới hạn OS; source được CodeGraph re-serve từ disk.
- Files: `src/services/orchestration/auth/models.py`, `src/services/orchestration/auth/service.py`, `src/services/orchestration/auth/seed_migration.py`, `src/services/orchestration/uploads/scene_imports.py`, `scripts/studio/rename_seed_accounts.py`, `frontend/src/lib/contracts/studio.ts`, `tests/test_orchestration/test_auth_identity.py`, `tests/test_orchestration/test_seed_account_migration.py`, `tests/test_api/test_studio_routes.py`, `docs/plans/active/2026-10-07-codegraph-audit/tasks/AUD-20-user-display-name-and-creator.md`, `docs/plans/active/2026-10-07-codegraph-audit/README.md`.
- Verification command:

  ```bash
  .venv/bin/pytest tests/test_orchestration/test_auth_identity.py tests/test_orchestration/test_seed_account_migration.py tests/test_orchestration/test_auth_service.py tests/test_orchestration/test_scene_imports.py tests/test_api/test_auth_routes.py tests/test_api/test_studio_routes.py tests/test_packaging/test_data_package.py -q -rs
  ```

  Result: **62 passed, 13 skipped**; all skips are PostgreSQL variants requiring `R2S_TEST_POSTGRES_URL`. `.venv/bin/ruff check src/ tests/ scripts/studio/rename_seed_accounts.py` — pass; `.venv/bin/ruff format --check src/ tests/ scripts/studio/rename_seed_accounts.py` — 472 files already formatted; `npm run lint` — pass; `npm run typecheck` — pass; CLI `--help` — pass; `git diff --check` — pass.
- Gate: CodeGraph preflight and caller inventory complete. Minimal shared validator/optional snapshot fields and one explicit migration utility. Chrome DevTools browser gate N/A vì sprint này chỉ đổi backend/type contracts, không đổi rendered UI; `list_pages` vẫn báo profile Chrome đang chạy, cần xử lý trước browser acceptance ở AUD-20.S3.
- Limitations: PostgreSQL execution và live seed IDs chưa được xác minh; không có DB access/migration receipt cho hai seed. S2 còn phải ghi actor snapshot cho accepted job-run events và project/import API projection; S3 còn UI/browser acceptance.

### AUD-20.S2 — producer và API attribution

- Logic delta: `JobAttemptRecord.requested_by` lưu actor bất biến ở event bắt đầu lượt QUEUED, bao gồm tạo job và manual retry; field optional/không serialize khi thiếu để payload cũ giữ tương thích. Validator từ chối actor trên event không phải QUEUED. Không đưa attribution vào `JobManifest`, nên checksum artifact không đổi.
- Producer/API: `ProjectRegistry.create_project` nhận `created_by`; product project/job route và Studio upload route chụp `actor_of(user)` từ dependency server-side. Retry ghi snapshot cùng CAS journal. Import route/service ghi role creator vào `ImportedScene`. Product job-create hiện áp dụng quota Editor và ghi `gpu.run` audit giống các entrypoint xử lý khác.
- Projection/legacy: Scenes list ưu tiên snapshot từ event journal; bản ghi cũ dùng audit ID + batch-loaded actor name, giữ `role=None`. Queue fairness tiếp tục dùng cùng requester và ưu tiên snapshot; không suy role lịch sử từ account hiện tại. Frontend `JobAttemptRecord` thêm optional actor contract; không đổi rendered UI trong sprint này.
- Tests: project/job actor snapshot và forged creator body; Scene summary giữ name/role cũ sau khi user record đổi tên/role; legacy requester role unknown; import role persistence; product job quota rejection; retry actor snapshot.
- CodeGraph: sync/status up-to-date, 759 files, 13,763 nodes, 39,527 edges. Callers đã truy từ product/studio create/retry routes đến Registry, persistence journal, SceneSummary, import service và frontend contract.
- Verification: `.venv/bin/pytest tests/test_api/test_product_routes.py tests/test_api/test_auth_routes.py tests/test_api/test_studio_routes.py tests/test_orchestration/test_scene_imports.py tests/test_orchestration/test_job_queue.py tests/test_orchestration/test_job_lifecycle.py -q` — **78 passed**; `ruff check src/ tests/` — pass; `ruff format --check src/ tests/` — 473 files unchanged; `npm run typecheck` — pass; `npx eslint src/lib/contracts/api.ts` — pass; `npm test` — **42 files, 275 tests passed**; `.venv/bin/python -m scripts.check_contract_mirror` — pass; `git diff --check` — pass.
- Gate: CodeGraph preflight/caller inventory and post-change sync pass. UI-only contract changed, no rendered component changed; browser gate N/A for S2. AUD-20.S3 still needs browser acceptance for badges and seed account acceptance.
- Limitations: Tests used SQLite fixtures; PostgreSQL concurrency remains for AUD-22.S2 quota integration, and live seed IDs remain unverified for S3. User display-name mutation was simulated at stored-record level because no self-rename endpoint exists yet.

### AUD-20.S3 — role badges on scene and import listings

- Implementation: Scene cards, list table, and imported-scene rows show creator name and role. A different `requested_by` is shown as “Chạy bởi”; a missing historical role is labeled “Vai trò chưa xác định”. The label map already has a Guest label for the later role extension. Badge text remains React text, including user-controlled names.
- Layout/accessibility: Attribution rows wrap on narrow cards, scene table keeps its horizontal scroll container, and tests locate the list-mode control by accessible role/name. Existing load/error states are unchanged.
- Tests: `npm test -- tests/studio-overview.test.tsx` — **6 passed**; coverage includes card, table, imported scene, changed creator role/name snapshots, unknown historical role, and markup-like display names. Full `npm test` — **42 files, 276 tests passed**; `npm run typecheck` — pass; `npx eslint src/features/studio/ScenesHome.tsx tests/studio-overview.test.tsx` — pass.
- CodeGraph: sync/status up-to-date, 759 files, 13,766 nodes, 39,541 edges. `SceneCard` and `SceneTable` each have one caller in `ScenesHome`; their consumer test is `frontend/tests/studio-overview.test.tsx`. `ImportedScene` list consumer is also `ScenesHome`.
- Browser gate: authenticated Chrome DevTools verification reached `/scenes` and `/team`. Both grid cards and list rows rendered creator names; historical jobs without a role snapshot showed “Vai trò chưa xác định”. The Team page showed the two seed display names with Reviewer and Editor roles. `GET /api/v1/auth/me`, `/api/v1/scenes`, `/api/v1/imports`, and `/api/v1/auth/users` returned HTTP 200. No console errors or warnings appeared; DevTools reported two form-field issues (`A form field element should have an id or name attribute`) on `/scenes`.
- Import evidence: the visible legacy import has `created_by`, but no `created_by_name` or `created_by_role` in its API response, so its list row correctly has no creator badge. Automated UI coverage verifies the badge when an import has a creation-time snapshot; a snapshot-bearing import was not available for browser verification.
- Seed acceptance: displayed seed names and roles are confirmed in the authenticated Team page. The expected names were already present, so no rename migration was run. Exact stable-ID verification and a migration receipt remain open; do not infer them from visible names.
- Commit: the UI implementation is in AUD-20.S3's per-sprint commit. This browser/data evidence is a follow-up acceptance update; import snapshot and stable-ID/migration evidence remain open.

### AUD-20.S3a — Legacy import creator-name projection

- Logic delta: import API list/detail/retry/cancel responses now resolve `created_by_name` from the current account only when the stored legacy row has an owner ID but no name snapshot. `created_by_role` remains unknown, current identity is not persisted, and stored creation-time snapshots are never replaced. Creator permissions still use the immutable owner ID.
- Impact: the existing `ScenesHome` import attribution row receives the legacy creator name through its current API contract; no frontend component or import payload/migration changed.
- Changed files: `src/api/studio/imports.py`, `tests/test_api/test_guest_ownership.py`, this task, and the audit README.
- Verification: `.venv/bin/pytest tests/test_api/test_guest_ownership.py -q --tb=short` — **36 passed**; `npm test -- tests/studio-overview.test.tsx` — **13 passed**; `.venv/bin/ruff check src/ tests/` — pass; `.venv/bin/ruff format --check src/ tests/` — **552 files already formatted**; `git diff --check` — pass.
- CodeGraph: read `ImportedScene`, `ImportService.list/get`, `list_imports/get_import/retry_import/cancel_import`, `AuthService.actors`, `owner_mutation_allowed`, and the `ScenesHome` consumer/tests before editing; `codegraph sync`/`status` — up to date (890 files, 17,786 nodes, 52,706 edges).
- Graphify: `graphify update .` completed; 20,964 nodes, 61,903 edges, 709 communities. The generated `graphify-out/` files remain uncommitted.
- Browser gate: **UNVERIFIED**. Chrome DevTools returned no available browsers or tabs in this session, so the updated legacy-import badge was not inspected live.
- Limitation: legacy imports still have no immutable creation-time name/role snapshot. The API uses the current name as a compatibility display fallback and leaves historical role unknown; exact seed IDs and migration receipt remain pending.

### Quyết định owner 2026-10-09 — điền role hiện tại cho bản ghi cũ

- **Thay đổi so với S1–S3a:** bản ghi cũ không có snapshot role (project, lượt chạy, import) không còn hiện "Vai trò chưa xác định" nếu tài khoản vẫn tồn tại. `AuthService.actors()` trả role hiện tại và `with_current_role` (`auth/models.py`) điền vào **phản hồi** `GET /scenes` (`project.created_by`, `requested_by`) và các phản hồi import (`created_by_role`).
- **Giữ nguyên:** snapshot đã lưu luôn thắng (đổi role sau này không làm đổi bản ghi có snapshot); không ghi gì ngược vào project/job/import; tài khoản đã bị xoá vẫn unknown nên UI vẫn có nhãn "Vai trò chưa xác định" cho trường hợp đó.
- **Hạn chế:** với bản ghi cũ, role hiển thị là role *hiện tại*, có thể khác role lúc tạo nếu tài khoản từng đổi role. Đây là hiển thị tiện lợi, không phải bằng chứng lịch sử.
- **Tests:** `test_actor_role_is_snapshotted_and_legacy_actor_gets_the_current_role_only_in_responses`; `test_studio_routes.py` (bản ghi cũ được điền role hiện tại, bản lưu không đổi, snapshot thắng khi role đổi).
