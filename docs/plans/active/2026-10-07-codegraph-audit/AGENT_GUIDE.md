# Hướng dẫn coding agent cho audit remediation

## Cách nhận việc

Nhận một `AUD-xx.Sy`, đọc task trọn vẹn, rồi làm đúng sprint đó. Các nhãn AUD là
work packages trong plan, không thay canonical task IDs. Đọc AGENTS.md, GUIDE.md,
plain-prose.md và task hiện có được ánh xạ. Source snapshot là `ef3a421`; trước
khi code phải kiểm tra HEAD, worktree, schemas và callers vì code có thể đã đổi.

Chỉ đạo owner: docs có thể sai/cũ; chọn hướng phục vụ project tốt hơn khi có
source/test/evidence. Ghi lý do và sửa docs liên quan trong handoff. Không lấy
status TODO cũ làm bằng chứng một feature chưa implement. ADR Proposed không
được tự đánh dấu Accepted hoặc Implemented. Sửa invariant hiện có không cần
phát minh policy mới; extension contract phải review cả producer và consumers.

Plan gồm 22 packages/70 sprints. Đọc GEMINI_FINDINGS.md khi xử lý AUD-12–18:
clearance/timing trong log có điều kiện cụ thể, không là general safety/speed
guarantee. TECHNOLOGY_LIMITS.md chỉ rõ phần không có production proof và practical
guards; odometry/anonymizer là opt-in work, không permanent MVP exclusion.
AUD-19 bổ sung automatic registration: independent maps dùng geometric QA,
sensor fusion dùng calibration/timing QA. Không lấy docs cũ hoặc thiếu extrinsic
làm blanket rejection cho independent static maps; scale/floor/overlap cần evidence.

## Pre-flight cho từng sprint

1. Kiểm tra dependencies của sprint, không chỉ status của epic.
2. Dùng CodeGraph trước đọc code; đi theo producer → artifact → consumer.
3. Đọc exact symbols, exported callers và tests đang bảo vệ behavior.
4. Chọn thay đổi nhỏ nhất; dùng RuntimeDatabase, ArtifactResolver, SceneEditor,
   checksum utilities, admission và subprocess lifecycle hiện có.
5. Với bug, thêm regression chứng minh output sai trước khi sửa. Với tính năng,
   dựng thin path có negative cases và consumer test.

```bash
git status --short --branch
codegraph status
codegraph explore "<symbols hoặc file paths ghi trong task>"
codegraph callers "<shared symbol được sửa>"
```

Task paths là boundary, không phải danh sách bắt buộc phải sửa tất cả. File mới
trong task là planned path nếu chưa tồn tại. Không chạy command tới planned test
file trước khi tạo nó; chạy focused suites hiện có và thêm file mới vào command.

## Shared contracts và identity

| Boundary | Quy tắc bắt buộc |
|---|---|
| SceneIR | Một parent_from_local transform/object; collider offset parented vào object.local_frame; mét, Z-up, right-handed, quaternion xyzw |
| Revisions | Artifact cũ bất biến; expected_scene_revision kiểm tra lúc commit; mỗi edit mới invalidate candidate/validation/approval cũ |
| ArtifactRef | logical artifact URI + byte checksum; resolver kiểm bytes; không serialize local path, credential hoặc presigned URL |
| Logical checksum | Canonical content checksum khác byte checksum; dùng utility hiện có, giữ array order |
| Optional extension | Chọn version/serialization trong S1; test payload cũ và checksum cũ; None bị loại khỏi serialization nếu schema hiện có yêu cầu |
| Runtime operation | Persisted mutable record tách khỏi SceneIR/report; attempt/lease/fencing bảo vệ commit |
| Reports | Observed results tách hidden expected labels; media capture lỗi không được sửa kết quả vật lý |
| Release | Exact candidate/report/approval; idempotent seal; ZIP và API cùng manifest identity |

Tên DTO/fields ghi “đề xuất” trong task chưa có trong source. Sprint S1 phải
chọn placement, version, null/default semantics, schema/fixture migration và
cập nhật producer/consumer cùng change. Không tạo competing scene format.
Giữ public API mới trong Studio flow; legacy routes vẫn giữ behavior đã có.

## Testing

Mỗi sprint có Input/Output/Contract/Tests/Exit riêng. Phân loại evidence:

- Unit/contract: synthetic payload hoặc mocked worker; chứng minh invariant.
- Local integration: real DB/artifact/subprocess; ghi SQLite hay PostgreSQL.
- USD runtime: mở stage bằng pxr, kiểm geometry/material/physics; chưa chứng minh Isaac.
- Isaac/GPU: log runtime/version/device, exact candidate/config, observed checks,
  artifact refs/checksums. Không dùng fixtures làm proof thật.
- Browser: interaction, focus/loading/error/rollback, console/network và cleanup.
  Tuân DevTools gate của GUIDE.md; thiếu session/tool ghi UNVERIFIED.
- Cloud: chỉ nhận claim khi chạy deployment thật; local object-store test không đủ.

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/pytest <focused paths của task> -q
```

Nếu chạm frontend, chạy trong `frontend/`:

```bash
npm run lint
npm run typecheck
npm test -- <test paths của task>
npm run build -- --webpack
```

Không chạy lại full suite sau mỗi sprint nhỏ. Chạy full backend/frontend khi
tích hợp nhóm thay đổi có contract/runtime boundary; mọi failure/skip phải ghi
đúng. Không thêm test chỉ mirror implementation hoặc đo thời gian flaky.

## Failure và recovery

- Unknown/insufficient resources: queued waiting có cancel; giữ config và input checksum.
- Stale revision/lease: reject commit; giữ output/diagnostics của attempt để kiểm tra.
- Failed/cancelled: không auto-xóa scratch, resume data hoặc checksum-bound output.
- Publication partial: verify artifact đã có, resume bằng identity đã persist.
- Retry: chỉ transient failures có căn cứ; deterministic bad input không retry vô hạn.
- Không ghi secrets vào logs/fixtures/contracts.

## Handoff bắt buộc

Ghi vào Result của task: sprint, commit base, files thật sự sửa, schema delta,
commands + output, artifacts/checksums, consumer proof, limitations, next sprint.
Tick Exit chỉ khi có evidence. Ghi pre-flight gate report của GUIDE.md khi có
code changes. Commit/push/merge/deploy cần yêu cầu riêng; plan không cấp quyền đó.

Mẫu giao việc:

> Thực hiện AUD-01.S1 trong task AUD-01-collision-background.md. Đọc AGENT_GUIDE,
> kiểm tra source bằng CodeGraph, làm regression và contract fixture thuộc sprint.
> Chỉ sửa scope của sprint, chạy checks liên quan, cập nhật Result và gate report.
> Không triển khai sprint khác hoặc dùng synthetic output làm GPU acceptance.

## Guest integration bắt buộc cho consumers

AUD-20–22 là owner-requested extension. Guest là account authenticated, khác visitor.
Role snapshot trên card không là quyền hiện tại. Creator immutable khác requested_by;
Editor/Reviewer can thiệp không chuyển ownership. Mọi job/scene mutation cần shared
backend resource guard, gồm legacy routes, workers, imports/object/metric/registration.
Guest quota 3/day reset Vietnam, tính manual Retry accepted; idempotent/automatic
attempt không thêm charge. Giữ Editor rolling24h và Reviewer unlimited. Không bật
public signup trước ownership guards và atomic quota. Email verification deferred.
