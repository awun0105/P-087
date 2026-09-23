# EX-PRODUCT — Backend, Web Studio & Orchestration

## Mission

Ghép các workers và shared artifacts thành Web product Human-in-the-Loop để tạo
job, inspect/edit scene, validate, review và seal đúng candidate đã kiểm tra.

```text
User → Web/API → REC → SCENE → SIM → review → exact-candidate release
```

## Ownership

Track Owner / Product Owner: Cường.

- `src/api/`
- `src/services/orchestration/`
- `frontend/` tại repository root cho toàn bộ Next.js/TypeScript Web Studio
- `tests/test_orchestration/` và product E2E tests

Không sở hữu reconstruction, scene-domain algorithms hoặc simulation internals.

## Inputs And Outputs

Inputs: user actions/source-rights attestation, manifests/artifact refs, SceneIR,
ValidationReport và conditional EvaluationReport.

Outputs: project/job lifecycle, scene revisions, review history,
`ApprovalRecord`, `ReleaseManifest` và stable demo workflow.

## Technology And Strategy

- FastAPI, basic worker/queue, SSE/WebSocket/polling.
- Next.js + TypeScript + Three.js trong root `frontend/`.
- P0 viewer dùng Three.js/WebGL/WebGL2 để render geometry mesh, point cloud, collider và SceneObject transforms.
- Direct browser Gaussian-splat/WebGPU rendering là stretch/non-blocking; nếu triển khai phải load real producer output và không claim fixture là Brush proof.
- P0 không yêu cầu advanced scheduler hoặc multi-tenant infrastructure.
- Product shell và lifecycle là project-owned; framework chỉ cung cấp primitives.

## Authority Gates

- EX-PRODUCT được phép tạo và sở hữu scaffold `frontend/` theo cấu trúc trong `ARCHITECTURE.md`.
- Frontend gọi FastAPI qua typed API client; không tạo backend/business-state implementation cạnh tranh trong Next.js.
- Persisted edits phải đi qua backend SceneIR revision; React state không phải source of truth.
- Release phải bind exact candidate, validation và approval; EvaluationReport bắt buộc theo run type/protocol.
- Editor/Reviewer authorization và source-rights/privacy gates không được bypass cho demo.

## Task Index

| Task | Name | Depends on | Primary output |
|---|---|---|---|
| [PRODUCT-01](./tasks/PRODUCT-01.md) | Mock-first API | shared fixtures | project/job/artifact API |
| [PRODUCT-02](./tasks/PRODUCT-02.md) | Job states | PRODUCT-01 | persisted job lifecycle |
| [PRODUCT-03](./tasks/PRODUCT-03.md) | Worker abstraction | PRODUCT-02 | dispatch interface |
| [PRODUCT-04](./tasks/PRODUCT-04.md) | Artifact access | PRODUCT-01 | registry/resolver |
| [PRODUCT-05](./tasks/PRODUCT-05.md) | Web shell | PRODUCT-01 | product screens/navigation |
| [PRODUCT-06](./tasks/PRODUCT-06.md) | 3D Viewer | PRODUCT-05 | SceneIR viewer/editor shell |
| [PRODUCT-07](./tasks/PRODUCT-07.md) | Object actions | PRODUCT-06 + SCENE operations | HITL/edit commands |
| [PRODUCT-07A](./tasks/PRODUCT-07A.md) | Added asset/collider controls | PRODUCT-06/07 + SCENE-08A/SIM-02A | obstacle/collider UI |
| [PRODUCT-08](./tasks/PRODUCT-08.md) | Real worker orchestration | PRODUCT-03/04 + track workers | REC→SCENE→SIM flow |
| [PRODUCT-09](./tasks/PRODUCT-09.md) | Progress/error/retry | PRODUCT-02/08 | observable recovery flow |
| [PRODUCT-10](./tasks/PRODUCT-10.md) | Review lifecycle | PRODUCT-01 + SIM reports | `ApprovalRecord` lifecycle |
| [PRODUCT-11](./tasks/PRODUCT-11.md) | Exact-candidate release | PRODUCT-10 | `ReleaseManifest` |
| [PRODUCT-12](./tasks/PRODUCT-12.md) | Stable demo route | PRODUCT-05–11 | E2E demo evidence |

## Track Definition Of Done

- Project/job API và real workers chạy qua artifact contracts.
- Status/error/retry có observable evidence.
- Viewer minimum controls và persisted edits hoạt động.
- P0 geometry/point-cloud/collider artifacts render trong browser và bind đúng checksum.
- Validation/review/approve/reject/release đúng authorization và checksum lineage.
- Product E2E chạy trên cùng candidate lineage và có backup evidence.

## Required Sources

- [`PRD.md`](../../../PRD.md)
- [`TEAM_EXECUTION_CONTRACT.md`](../../TEAM_EXECUTION_CONTRACT.md)
- [`INTEGRATION_PLAYBOOK.md`](../../INTEGRATION_PLAYBOOK.md)
- [`TRACK_IMPLEMENTATION_GUIDE.md`](../../TRACK_IMPLEMENTATION_GUIDE.md)
- [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md)
- [`WIREFRAME_AND_UI_FLOW.md`](../../../WIREFRAME_AND_UI_FLOW.md)
- [`ARCHITECTURE.md`](../../../../ARCHITECTURE.md)
