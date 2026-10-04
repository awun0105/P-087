# Execution Plan: Materialize Real2Sim Execution Tracks

Date: 2026-09-23

## Status

Completed

## Outcome

Tạo đầy đủ `docs/execution/tracks/` với entrypoint cho bốn execution track,
task file cho mọi task ID đã được khóa trong `TRACK_IMPLEMENTATION_GUIDE.md`,
và một task template dùng chung. Mọi task truy được về source of truth, không tự
tạo product policy mới và có dependency, I/O, ownership, test cùng Definition of
Done đủ rõ để coding agent lập implementation plan.

## Context

- `AGENTS.md`, `docs/WORKFLOW.md`: workflow và authority boundary.
- `docs/PRD.md`: product scope và acceptance.
- `docs/DATASET_PLAYBOOK.md`: dataset/evaluation boundary.
- `ARCHITECTURE.md`: repository placement và module ownership.
- `docs/execution/TEAM_EXECUTION_CONTRACT.md`: shared normative contracts.
- `docs/execution/INTEGRATION_PLAYBOOK.md`: technical baseline.
- `docs/execution/TRACK_IMPLEMENTATION_GUIDE.md`: task IDs và task scope.
- `docs/execution/TEAM_EXECUTION_PLAN.md`: timeline, milestones và ownership.

## Scope

In scope:

- Tạo `docs/execution/README.md` và `docs/execution/tracks/README.md`.
- Tạo bốn `TRACK.md` và task index có link.
- Tạo task file cho mọi task ID hiện có của EX-REC, EX-SCENE, EX-SIM và EX-PRODUCT.
- Tạo `docs/execution/templates/TASK_TEMPLATE.md`.
- Giữ task ở trạng thái `TODO`; implementation plan/result để coding agent cập nhật khi được giao.
- Kiểm tra task ID, link, dependency, source reference và phạm vi ownership.

Out of scope:

- Thay đổi product scope, artifact schema hoặc canonical coordinate policy.
- Đổi task ID đã có hoặc tự thêm task ID mới.
- Implement code của từng task.
- Xóa hoặc di chuyển `docs/TRACKS.md` hiện có.

## Approach

1. Trích task catalog, dependencies, I/O, tool strategy, tests và DoD từ source documents.
2. Tạo navigation và template trước.
3. Tạo `TRACK.md` cho từng track, sau đó tạo task stubs đầy đủ.
4. Chạy script read-only để kiểm tra catalog, file, link và dependency.
5. Rà nội dung đại diện, scope và working-tree paths rồi hoàn tất plan.

## Risks And Recovery

- Contract đang có gap đã biết: task file link về authority và ghi blocker, không tự khóa schema.
- Working tree có thay đổi của người dùng: chỉ thêm file dưới `docs/execution/` và plan này; không sửa hoặc stage file khác.
- Task catalog giữ nguyên Guide; lỗ hổng `ST-FRAME-EXTRACT` được ghi thành authority gate thay vì tạo ID mới.
- Recovery: các file mới độc lập theo đúng path; không có migration hoặc destructive operation.

## Progress

- [x] Đọc workflow, authority order và inventory hiện tại.
- [x] Trích catalog cho bốn track.
- [x] Tạo README và task template.
- [x] Tạo bốn TRACK.md.
- [x] Tạo toàn bộ task files.
- [x] Chạy consistency validation.
- [x] Rà nội dung, scope và hoàn tất plan.

## Decisions

- 2026-09-23: Dùng task IDs hiện có trong Track Guide; không thêm `REC-02A` khi source task catalog chưa được thay đổi.
- 2026-09-23: Giữ `docs/TRACKS.md` vì đây là tài liệu đã có; navigation mới trỏ tới track cards chi tiết.
- 2026-09-23: Các policy chưa khóa được ghi thành authority gate/blocker trong task liên quan thay vì suy luận từ fixture hoặc ví dụ.
- 2026-09-23: Task files là execution records/projections; PRD, Dataset Playbook, Contract, Playbook và Guide tiếp tục giữ authority theo loại quyết định.

## Validation

- Catalog: 45 IDs trong Guide, 45 task files, 45 unique filenames; không thiếu/thừa.
- Structure: 4 `TRACK.md`, 45 task files, 2 navigation READMEs và 1 task template.
- Sections: cả 45 task files có đủ 12 sections chuẩn.
- Lifecycle: cả 45 task ở `TODO` và `Result / Evidence` là pending.
- Links: kiểm tra 52 Markdown files, 0 broken local links.
- ID references: 45 unique task IDs được tham chiếu và đều resolve.
- Formatting: không có trailing whitespace; new execution docs không có task tự đánh dấu DONE.
- Scope: `docs/TRACKS.md` và các source documents hiện hữu không bị xóa/di chuyển; không stage/commit file.

## Result

Đã materialize đầy đủ task catalog cho bốn track. Mỗi task có goal, rationale,
dependencies/authority gates, input/output contract, code ownership, tool
strategy, implementation-plan placeholder, tests, Definition of Done và evidence
placeholder. Các gap contract đã biết được giữ thành explicit gate tại task liên
quan thay vì bị task file tự quyết định.

