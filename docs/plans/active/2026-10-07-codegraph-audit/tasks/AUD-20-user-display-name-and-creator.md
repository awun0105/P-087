# AUD-20 — Tên người dùng và thông tin người tạo trên scene

## Metadata và goal

- PLANNED; P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. Chỉ lập kế hoạch; chưa sửa source hoặc tài khoản.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Display name đã có trong UserRecord/PublicUser, RegisterForm và CLI. Actor hiện
snapshot user_id/display_name; ScenesHome đã render created_by và requested_by,
imports có created_by_name. Còn thiếu role attribution và consistency giữa card,
table/import/job. REUSE các fields này; không tạo subsystem identity thứ hai.
Seed accounts được giữ qua studio data packaging; chưa đọc hoặc đổi live DB.

CodeGraph đã đọc auth/models.py, auth/service.py, api/auth.py, auth/cli.py,
product/jobs.py, product/projects.py, AuthForms.tsx, ScenesHome.tsx và frontend
API/auth.ts. Trước implementation đi tiếp callers của symbols được sửa, inventory
Studio/legacy mutation routes, runtime services, packaging/bootstrap và tests.
Không lấy việc ẩn button làm access control.

## Input / output / data contract

Registration input: email, display_name, password và invitation theo mode AUD-21.
Tên Unicode 1–100 ký tự sau trim, reject blank/control characters; render plain text.
Không dùng tên/email làm khóa ownership. Output PublicUser giữ stable user_id.
Creator attribution: immutable owner/creator user_id và name/role snapshot tại tạo;
requested_by là actor của run, khác creator. Role hiện tại từ server dùng authorization.
Snapshot role optional cho records cũ, không rewrite artifact/checksum bất biến.
Legacy thiếu role hiển thị chưa xác định; không giả historical role từ current role.
Hai seed: Reviewer tên “Minh An”, Editor tên “Hà Linh”. Apply qua migration/setup
được định danh bằng stable ID/role, không rename mọi Reviewer/Editor. Nếu không tìm
đúng hai seed thì báo blocker, không chọn account bất kỳ; giữ email, ID, password,
active và role. Không lưu credential trong task/fixture hoặc tạo seed production mới.

## Dependencies

S1 độc lập; S2 phối hợp AUD-21.S1 identity/owner matrix. S3 dùng S2 projection;
không đợi quota. Seed update không tự cấp quyền sửa archived bundles/checksums.

## Sprint AUD-20.S1 — Identity và migration

**Input:** Existing names/Actor/seed packaging fixtures.
**Output:** Compatible identity + creator DTO và seed migration spec.
**Contract:** Historical attribution khác current authorization.

Implement: Reuse name validation; chốt optional role snapshot/serialization. Inventory creator ownership của project/job/import; chỉ backfill từ provenance đáng tin. Thiết kế idempotent seed-name update cho đúng hai seed, packaging giữ tên mới sau explicit repack.
Tests: Unicode/blank/control text, old payload/checksum, missing creator, repeated migration, non-seed untouched, seed credentials unchanged.
**Exit:** [ ] contract/migration fixtures bảo vệ identity cũ.

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

Pending — schema/migration, command outputs, permission matrix, browser/API traces,
legacy compatibility và failure/recovery evidence.
