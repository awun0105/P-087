# Execution Plan: Complete Coding Agent Harness

Date: 2026-09-23

## Status

Completed

## Outcome

`AGENTS.md` trở thành entrypoint đủ dùng cho coding agent: khôi phục đúng context,
xác định authority và task boundary, triển khai theo code conventions, kiểm chứng
bằng evidence, và dừng/báo user khi source documents mâu thuẫn hoặc thiếu quyết
định. Mọi tài liệu bắt buộc được link từ harness phải tồn tại và resolve.

## Context

- `AGENTS.md`: repository-wide agent instructions hiện tại.
- `.harness-core/base/`: upstream Harness Core 0.1.10 đã có trong working tree.
- `docs/execution/README.md`: authority order và execution entrypoints.
- `docs/execution/tracks/README.md`: coding-agent rules và shared handoff.
- `docs/execution/templates/TASK_TEMPLATE.md`: task lifecycle và evidence record.
- `docs/guide/`: Python, testing, architecture, Git và anti-pattern guidance.
- `ARCHITECTURE.md`: canonical placement và ownership.

## Scope

In scope:

- Hoàn thiện `AGENTS.md` thành workflow bắt buộc, có conflict protocol và
  anti-hallucination/context-recovery rules.
- Materialize `docs/WORKFLOW.md` và
  `docs/patterns/encoding-invariants.md` vì `AGENTS.md` bắt buộc tham chiếu chúng.
- Tạo các README tối thiểu cho lifecycle `docs/plans/` mà harness sử dụng.
- Cập nhật `docs/README.md` thành documentation map đúng với Real2Sim và bỏ
  `AGENTS.md` khỏi `.gitignore` để harness được chia sẻ qua Git.
- Kiểm tra link, cấu trúc, policy wording và diff formatting.

Out of scope:

- Implement các task Real2Sim.
- Thay đổi product scope, artifact schema hoặc task IDs.
- Cài hook, sửa CI, commit, push hoặc thay đổi branch protection.
- Tạo task database/control plane ngoài repository documents.

## Approach

1. Giữ các convention hợp lệ hiện có, loại reference tới file/skill không tồn tại.
2. Đưa authority order, task bootstrap, execution loop, conflict protocol,
   validation ladder và handoff contract vào `AGENTS.md`.
3. Materialize workflow/invariant guidance cần thiết từ Harness Core, rồi tailor
   cho task files và authority model của Real2Sim.
4. Chạy structural/link/format checks và rà lại các lệnh validation được nêu.

## Risks And Recovery

- Working tree đang có nhiều thay đổi của user: chỉ sửa/tạo các file liệt kê ở
  Scope; không stage hoặc đụng các thay đổi không liên quan.
- Quy tắc quá cứng có thể gây block giả: chỉ dừng ở policy boundary thực sự mâu
  thuẫn; cho phép tiếp tục phần độc lập, an toàn.
- Recovery: các thay đổi chỉ là Markdown, có thể review/revert theo từng file.

## Progress

- [x] Đọc `AGENTS.md`, execution docs, guide, current repository layout và
  upstream Harness Core.
- [x] Xác định broken references và authority model.
- [x] Hoàn thiện `AGENTS.md`.
- [x] Materialize workflow/invariant/plan support docs.
- [x] Làm `AGENTS.md` trackable và cập nhật documentation map.
- [x] Validate và hoàn tất plan.

## Decisions

- 2026-09-23: Task file là execution record chính cho một task đã được assign;
  durable plan chỉ dùng cho cross-task/cross-session work để tránh control plane
  trùng lặp.
- 2026-09-23: Khi docs conflict, agent không dùng quy tắc “file mới hơn thắng” và
  không tự chọn; phải báo exact sources, impact và decision cần user/owner khóa.
- 2026-09-23: Evidence phải phân biệt static/mock, fixture, integration và real
  runtime/GPU acceptance.

## Validation

- Required files: `docs/WORKFLOW.md`, invariant pattern, plan/decision lifecycle
  files và templates đều resolve.
- Link proof: 9 harness Markdown files, 0 broken local links.
- Structure proof: Markdown code fences balanced; required AGENTS sections,
  Task Capsule, evidence labels và conflict report format đều present.
- Formatting: `git diff --check` pass trên toàn harness scope.
- Tracking: `git check-ignore AGENTS.md` không còn match; file xuất hiện trong
  working tree để có thể được review/commit.
- Code tests: không chạy vì thay đổi chỉ là documentation/workflow, không thay
  product code hoặc runtime behavior.

## Result

Hoàn thành coding-agent harness với authority-first bootstrap, durable context,
anti-hallucination evidence labels, explicit docs-conflict escalation, bounded
implementation loop, Python/TypeScript/Three.js conventions, validation ladder,
task lifecycle và evidence-based handoff. Các references bắt buộc trước đây bị
thiếu đã được materialize, và `AGENTS.md` không còn bị Git ignore.
