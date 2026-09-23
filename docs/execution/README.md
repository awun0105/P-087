# Real2Sim Execution Documentation

Thư mục này là entrypoint cho kế hoạch triển khai Real2Sim Studio. Product scope,
dataset methodology và shared contracts vẫn nằm ở các source of truth tương ứng;
track/task files không được override chúng.

## Authority Order

1. [`PRD.md`](../PRD.md) — product scope, priority và acceptance.
2. [`DATASET_PLAYBOOK.md`](../DATASET_PLAYBOOK.md) — dataset preparation, leakage và evaluation protocol.
3. [`TEAM_EXECUTION_CONTRACT.md`](./TEAM_EXECUTION_CONTRACT.md) — shared artifact, runtime, review và handoff contracts.
4. [`ARCHITECTURE.md`](../../ARCHITECTURE.md) — canonical repository placement và module ownership.
5. [`INTEGRATION_PLAYBOOK.md`](./INTEGRATION_PLAYBOOK.md) — technical baseline và tool choices.
6. [`TRACK_IMPLEMENTATION_GUIDE.md`](./TRACK_IMPLEMENTATION_GUIDE.md) — task catalog và implementation scope.
7. [`TEAM_EXECUTION_PLAN.md`](./TEAM_EXECUTION_PLAN.md) — timeline, ownership và milestones.

Nếu hai nguồn thực sự mâu thuẫn, coding agent phải dừng ở policy boundary và yêu
cầu owner sửa source document; không tự chọn một bên trong task file.

## Execution Entry Points

- [High-level team track overview](../TRACKS.md)
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
