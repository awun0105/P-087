# Real2Sim Execution Documentation

Thư mục này là entrypoint cho kế hoạch triển khai Real2Sim Studio. Product scope,
dataset methodology và shared contracts vẫn nằm ở các source of truth tương ứng;
track/task files không được override chúng.

## Authority Order

1. [`PRD.md`](../PRD.md) — product scope, priority và acceptance.
2. [`EVALUATION.md`](../EVALUATION.md) — dataset, leakage và evaluation protocol (bản cũ: [`archived/DATASET_PLAYBOOK.md`](../archived/DATASET_PLAYBOOK.md)).
3. [`TEAM_EXECUTION_CONTRACT.md`](./TEAM_EXECUTION_CONTRACT.md) — shared artifact, runtime, review và handoff contracts.
4. [`ARCHITECTURE.md`](../../ARCHITECTURE.md) — canonical repository placement và module ownership.
5. [`INTEGRATION_PLAYBOOK.md`](./INTEGRATION_PLAYBOOK.md) — technical baseline và tool choices.
6. [`TRACK_IMPLEMENTATION_GUIDE.md`](./TRACK_IMPLEMENTATION_GUIDE.md) — task catalog và implementation scope.
7. [`TEAM_EXECUTION_PLAN.md`](./TEAM_EXECUTION_PLAN.md) — timeline, ownership và milestones.

Nếu hai nguồn thực sự mâu thuẫn, coding agent phải dừng ở policy boundary và yêu
cầu owner sửa source document; không tự chọn một bên trong task file.

## Cập nhật 2026-09-29

- **Studio MVP** (lát cắt video → EX-REC → 3DGS → editor) đã merge vào `develop`
  (PR #9). Công việc này đi qua plan, **không tạo task ID mới**; mapping sang task
  PRODUCT/REC hiện có ghi ở [`ex_product/PLAN.md`](tracks/ex_product/PLAN.md) §6.
- **ADR 0003** (Accepted): Web UI Vercel, FastAPI Railway, PostgreSQL Supabase, kho file R2,
  GPU Vast.ai (dự phòng RunPod) tự bật/tắt; hai role Editor/Reviewer, khách chỉ dùng video mẫu; trình
  duyệt chỉ nhận bản 3DGS nhẹ. Contract §7.4 có amendment cho backend S3-compatible.
- **ADR 0002** (Proposed): privacy tự xác nhận cho MVP — còn chờ Product Owner và
  QA Lead; lệch với `ex_product/TRACK.md` §Authority Gates và Contract §3.3.1.
- **Đường dẫn module đổi** (ảnh hưởng nhánh đang mở): `reconstruction/rgb/` chia theo
  stage (`preflight/ frames/ pose/ splat/ geometry/ canonical/`),
  `src/api/routes_studio.py` → `src/api/studio/`, `orchestration/jobs/preview_cli.py`
  → `jobs/runner.py`, `orchestration/demo/` → `samples/`.
- CI có thêm job frontend; GitHub Actions của org đang không chạy do billing
  (từ 26/09) — kết quả kiểm tra hiện là local.

## Execution Entry Points

- [Execution Tracks](./tracks/README.md)
- [EX-REC](./tracks/ex_rec/TRACK.md)
- [EX-SCENE](./tracks/ex_scene/TRACK.md)
- [EX-SIM](./tracks/ex_sim/TRACK.md)
- [EX-PRODUCT](./tracks/ex_product/TRACK.md)
- [Task Template](./templates/TASK_TEMPLATE.md)

## Task Workflow

```text
Tech Lead locks task ID/scope
→ assignee reads TRACK.md and task file
→ assignee fills Implementation Plan
→ implementation + focused tests
→ behavior-level validation
→ assignee records Result / Evidence
→ producer/consumer review when a shared contract changes
```

Task files are execution records, not a parallel product specification. A task
may clarify implementation details only inside its accepted scope.
