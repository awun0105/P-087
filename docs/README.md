# Real2Sim Documentation Map

Đọc surface nhỏ nhất nhưng đủ authority cho công việc.

## Agent And Workflow

- [Agent Harness](../AGENTS.md): entrypoint, authority map, quality gates,
  conflict protocol và completion contract.
- [Repository Workflow](WORKFLOW.md): work shapes, authority/proof gates,
  context checkpoints và validation ladder.
- [Execution Plans](plans/README.md): durable memory cho cross-task/session work.
- [Encoding Invariants](patterns/encoding-invariants.md): cách enforce một rule
  đã được accepted.

## Product And Architecture Authority

- [Product Requirements](PRD.md): scope, priority, behavior và acceptance.
- [Dataset Playbook](DATASET_PLAYBOOK.md): dataset/evaluation/leakage rules.
- [Architecture](../ARCHITECTURE.md): canonical placement và module ownership.
- [Execution Documentation](execution/README.md): contracts, integration,
  task catalog, milestones và track entrypoints.

## Execution Entry Points

- [EX-REC](execution/tracks/ex_rec/TRACK.md)
- [EX-SCENE](execution/tracks/ex_scene/TRACK.md)
- [EX-SIM](execution/tracks/ex_sim/TRACK.md)
- [EX-PRODUCT](execution/tracks/ex_product/TRACK.md)
- [Task Template](execution/templates/TASK_TEMPLATE.md)

## Supporting Guidance

- `guide/`: scaffold-level coding, testing, architecture và Git guidance.
- `templates/`: execution-plan và decision templates.
- `decisions/`: accepted lasting decisions chưa được đặt trực tiếp trong
  product/architecture sources.

Task/track docs là execution projection và record; chúng không override PRD,
Dataset Playbook, Execution Contract hoặc Architecture theo decision type.
