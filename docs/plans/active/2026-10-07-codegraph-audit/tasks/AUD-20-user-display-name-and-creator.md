# AUD-20 — Tên người dùng và thông tin người tạo trên scene

## Metadata và goal

- IN PROGRESS; P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. AUD-20.S1 có implementation; không đọc hoặc sửa live DB.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Display name đã có trong UserRecord/PublicUser, RegisterForm và CLI. Actor hiện
snapshot user_id/display_name; ScenesHome đã render created_by và requested_by,
imports có created_by_name. Còn thiếu role attribution và consistency giữa card,
table/import/job. REUSE các fields này; không tạo subsystem identity thứ hai.
Seed accounts được giữ qua studio data packaging; chưa đọc hoặc đổi live DB.

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
Legacy thiếu role hiển thị chưa xác định; không giả historical role từ current role.
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
**Output:** Creator name/role trên create/list/detail responses.
**Contract:** Creator immutable; Editor rerun Guest job không đổi owner.

Implement: Capture creator ở transaction tạo record; requested_by ghi actor từng run. Batch-resolve legacy metadata nếu cần, không N+1 hoặc public email directory. Client không tự chọn creator/role. Phân biệt snapshot role và current role.
Tests: Forged creator JSON, intervention, renamed/deactivated user, absent legacy role, imports/card/table projection.
**Exit:** [ ] mọi supported scene/job input có attribution rõ.

## Sprint AUD-20.S3 — Studio và seed acceptance

**Input:** S2 responses + two identified seed accounts.
**Output:** Name input hoàn thiện, creator/role badges trên cards/table/imports.
**Contract:** Badge chỉ thông tin; không quyết định quyền.

Implement: Reuse RegisterForm name input. Render tên người tạo job và role dễ đọc; separate chạy bởi khi actor khác creator. Update intended two seed names bằng migration đã review; add responsive/accessibility loading/error cases.
Tests: Guest/Editor/Reviewer create, card/table/import, rename snapshot, unknown role, XSS plain text, seed rerun idempotence và real browser.
**Exit:** [ ] browser attribution đúng và seed-name evidence không chứa secrets.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_auth_service.py tests/test_api/test_auth_routes.py tests/test_api/test_studio_routes.py tests/test_packaging/test_data_package.py -q
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
