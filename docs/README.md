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
- [Studio UX Spec](STUDIO_UX_SPEC.md): IA, màn hình, trạng thái UI và quyết định Q/D-xx của Web Studio;
  không override PRD hoặc Execution Contract.
- [Execution Documentation](execution/README.md): contracts, integration,
  task catalog, milestones và track entrypoints.

## Hiện trạng và quyết định mới nhất (2026-09-30)

- Tích hợp Studio đầu-cuối (tách vật, gói mô phỏng, duyệt/phát hành, refactor UI): PR #16,
  [plan hoàn thiện Studio](plans/active/2026-09-29-studio-completion.md).
- **Pipeline v2** — scene theo vật chỉnh sửa được, xuất USD lai cho Isaac Sim:
  [ADR 0007](decisions/0007-object-centric-hybrid-usd-pipeline.md),
  [plan pipeline v2](plans/active/2026-09-30-pipeline-v2.md),
  [audit #10](execution/audits/10_pipeline_v2_methods.md); PRD v1.16.
- Dùng lại code nghiên cứu phi thương mại: [ADR 0008](decisions/0008-research-code-license-policy.md).
- Studio MVP (video → 3DGS → editor) đã có trên `develop`:
  [plan MVP Studio](plans/active/2026-09-29-mvp-studio-demo.md),
  [ADR 0002](decisions/0002-studio-mvp-video-to-3dgs.md) (*Proposed*).
- Kiến trúc cloud, hai role và ngân sách trình duyệt đã chốt, chưa triển khai:
  [ADR 0003](decisions/0003-cloud-architecture-roles-and-browser-budget.md),
  [plan Cloud Studio](plans/active/2026-09-29-cloud-studio.md).
- Metric scale ba hướng: [ADR 0001](decisions/0001-metric-scale-strategy-and-roadmap.md) (mục Implementation:
  đề xuất tự động bằng MoGe-2, 02/10/2026).
- LiDAR của người dùng đi kèm video: [ADR 0009](decisions/0009-user-lidar-input-and-routing.md),
  [plan luồng video + LiDAR](plans/active/2026-10-02-lidar-video-flow.md).
- Tài nguyên, hàng đợi nhiều người dùng: [plan](plans/active/2026-10-02-resource-management-cleanup.md).
  Đánh giá và PSNR trên ảnh giữ lại: [plan](plans/active/2026-10-02-evaluation-system.md).
  Viewer đi bộ, chọn vật theo hình dáng, đề xuất tỉ lệ: [plan](plans/active/2026-10-02-interactive-scene-and-metric-scale.md).
- Bản đồ thư mục theo checkout thật: [`README.md`](../README.md) §Project Structure.

## Execution Entry Points

- [EX-REC](execution/tracks/ex_rec/TRACK.md)
- [EX-SCENE](execution/tracks/ex_scene/TRACK.md)
- [EX-SIM](execution/tracks/ex_sim/TRACK.md)
- [EX-PRODUCT](execution/tracks/ex_product/TRACK.md)
- [Task Template](execution/templates/TASK_TEMPLATE.md)

## Supporting Guidance

- [Project Context](CONTEXT.md): onboarding overview cho coding agent; không phải source of truth.
- `guide/`: scaffold-level coding, testing, architecture và Git guidance.
- `templates/`: execution-plan và decision templates.
- `decisions/`: accepted lasting decisions chưa được đặt trực tiếp trong
  product/architecture sources.

Task/track docs là execution projection và record; chúng không override PRD,
Dataset Playbook, Execution Contract hoặc Architecture theo decision type.
