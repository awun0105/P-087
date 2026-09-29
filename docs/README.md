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

## Hiện trạng và quyết định mới nhất (2026-09-29)

- Studio MVP (video → 3DGS → editor) đã có trên `develop`:
  [plan MVP Studio](plans/active/2026-09-29-mvp-studio-demo.md),
  [ADR 0002](decisions/0002-studio-mvp-video-to-3dgs.md) (*Proposed*).
- Kiến trúc cloud, hai role và ngân sách trình duyệt đã chốt, chưa triển khai:
  [ADR 0003](decisions/0003-cloud-architecture-roles-and-browser-budget.md),
  [plan Cloud Studio](plans/active/2026-09-29-cloud-studio.md).
- Metric scale ba hướng: [ADR 0001](decisions/0001-metric-scale-strategy-and-roadmap.md).
- Bản đồ thư mục theo checkout thật: [`README.md`](../README.md) §Project Structure.

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
