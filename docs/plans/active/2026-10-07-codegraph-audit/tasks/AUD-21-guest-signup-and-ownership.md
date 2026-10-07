# AUD-21 — Guest signup và quyền theo ownership

## Metadata và goal

- PLANNED; P1; EX-PRODUCT identity/API/Studio/runtime DB.
- Canonical PRODUCT-01/02/06/09; task-local extension, không đổi crosswalk.
- Owner yêu cầu ngày 07/10/2026. Chỉ lập kế hoạch; chưa sửa source hoặc tài khoản.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0021](../../../../decisions/0021-guest-identity-and-ownership.md), [ADR 0022](../../../../decisions/0022-guest-daily-job-quota.md).

## Baseline và scope

Role hiện chỉ editor/reviewer, Reviewer rank cao hơn và server sessions re-read
current user. Register cần invite; require_editor sẽ reject Guest nếu chỉ thêm rank.
Frontend canEdit hiện cho mọi signed-in, trash button chưa kiểm ownership. Phải
đổi contributor gate và resource authorization đồng bộ, giữ Editor/Reviewer rights.

CodeGraph đã đọc auth/models.py, auth/service.py, api/auth.py, auth/cli.py,
product/jobs.py, product/projects.py, AuthForms.tsx, ScenesHome.tsx và frontend
API/auth.ts. Trước implementation đi tiếp callers của symbols được sửa, inventory
Studio/legacy mutation routes, runtime services, packaging/bootstrap và tests.
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

## Dependencies

S1 độc lập, phối hợp AUD-20.S1. S2/S3 trước rollout open signup; S4 dùng AUD-22.S2
atomic quota. AUD-06/07/08/09/10/16/17/18/19 consumers phải áp dụng resource guard
trước enqueue/commit. Contract có thể tích hợp sớm; không cycle chờ whole epics.

## Sprint AUD-21.S1 — Permission matrix và resource identity

**Input:** Current routes/services, two-role tests.
**Output:** Three-role operation matrix, immutable ownership và migration spec.
**Contract:** Reviewer > Editor > Guest; existing higher-role rights preserved.

Implement: Inventory create/read/edit/rename/cancel/retry/trash/restore/purge, object/metric/registration/import, review/admin và legacy routes. Chốt resource checks cho từng action; worker command giữ authorized actor/owner và recheck role/ownership tại durable commit khi cần.
Tests: Matrix Guest own/foreign/unknown, Editor/Reviewer cross-user, anonymous/auth-disabled local, job khác parent owner.
**Exit:** [ ] matrix phủ mọi mutation route và worker ingress.

## Sprint AUD-21.S2 — Open Guest registration và role lifecycle

**Input:** S1 + existing invite/session service.
**Output:** Guest signup API/UI; invited flow unchanged.
**Contract:** No invite always Guest; invalid supplied invite không nâng quyền hoặc silently fallback.

Implement: Separate explicit guest/invited mode; reject forged role, reuse email/password/name validation, transactional duplicate handling và current limiter. Extend role schemas/Team UI/CLI where supported; invite roles vẫn Editor/Reviewer. Giữ secure cookies/session and audit; không thêm SMTP hoặc verified claim.
Tests: No invite Guest success, invited roles regression, invalid/used invite, duplicate normalized email concurrent, role injection, inactive users, promotion/demotion/self-demotion.
**Exit:** [ ] signup và role changes server-enforced.

## Sprint AUD-21.S3 — Backend ownership và interference

**Input:** S1 immutable owner + S2 users.
**Output:** Resource guard trên mọi supported mutation; audited operator intervention.
**Contract:** Editor/Reviewer can operate Guest jobs; Guest chỉ own.

Implement: Reuse shared guard trong API/service boundaries; do not blanket downgrade require_editor globally. Check direct legacy endpoints, foreign object/artifact refs, cancel/retry/delete/restore và background publish paths. Preserve revision CAS and denied request no side effects.
Tests: Direct HTTP bypass, forged owner/resource IDs, foreign cancel/delete/retry, same-parent foreign job, inactive/demoted actor, denied no enqueue/artifact write, cross-user higher roles.
**Exit:** [ ] negative API tests bảo vệ foreign jobs và existing privileges.

## Sprint AUD-21.S4 — Studio permissions và rollout acceptance

**Input:** S2/S3 + AUD-22.S2 quota.
**Output:** Guest experience và regression evidence.
**Contract:** Frontend capabilities không thay server authorization.

Implement: Replace global canEdit for resource actions with typed server capability. Hide/disable foreign mutation, giữ shared viewing và own cancel/edit at exhausted quota. Distinguish Visitor/Guest, show role names; update auth/UX docs theo approved feature, forward migration/rollback feature flag không reset DB.
Tests: Real browser three roles, own/foreign card/detail/trash, direct API denied, reviewer/editor Guest intervention, auth-disabled dev regression.
**Exit:** [ ] browser/API matrix pass trước public signup enable.

## Verification và DoD

```bash
.venv/bin/pytest tests/test_orchestration/test_auth_service.py tests/test_api/test_auth_routes.py tests/test_api/test_studio_routes.py tests/test_api/test_scene_routes.py -q
```

Thêm tests mới theo sprint rồi bổ sung command. Chạy ruff; frontend lint/typecheck,
focused tests/build khi sửa UI. DONE cần real DB concurrency/API và browser evidence;
mock hoặc source review không chứng minh feature đã chạy.

## Result / Evidence

Pending — schema/migration, command outputs, permission matrix, browser/API traces,
legacy compatibility và failure/recovery evidence.
