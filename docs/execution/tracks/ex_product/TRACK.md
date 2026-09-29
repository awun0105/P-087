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
- Next.js + TypeScript trong root `frontend/`.
- `playcanvas/engine` (v2.22.4): **Tier A — Web 3D Runtime Core**, Single Scene Graph (`pc.Entity`), Depth-synced GSplat & Mesh, Transform Gizmos (`TranslateGizmo`, `RotateGizmo`). Xem [Audit #8](../../audits/08_playcanvas_engine.md).
  **Trạng thái 2026-09-27: mới chỉ khai báo trong `package.json`, chưa có dòng code nào
  `import` từ `playcanvas`.** Không có `pc.Entity`, `TranslateGizmo`, `RotateGizmo`
  hay `RenderPassPicker` nào được dùng. Xem `PRODUCT-06.md` §13.1.
  **Cập nhật 2026-09-29:** `playcanvas` đã được import (`features/viewer/splat-inspection.ts`);
  vẫn chưa dùng `TranslateGizmo`/`RotateGizmo`/`RenderPassPicker` trong `frontend/src`.
- `@playcanvas/supersplat-viewer` (v1.35.2): **Tier A — Embedded 3DGS Viewport Core**, nạp SOG/Streamed SOG LOD và collision GLB, API `createViewer({ ui: false })` với WebGPU/WebGL2 fallback tự động. Xem [Audit #9](../../audits/09_supersplat_viewer.md).
- `playcanvas/splat-transform` (v3.6.6): Core utility cho Gaussian artifact validation, SOG conversion và voxel collision mesh generation. Xem [Audit #4a](../../audits/04a_splat_transform.md).
- `playcanvas/supersplat`: Code donor cho logic `EntityTransformHandler`, `EditHistory` (Undo/Redo) và shaders selection (`PRODUCT-07`).
  **Trạng thái 2026-09-27: chưa lấy module nào.** Không có undo/redo, không có
  `EntityTransformHandler`, không có selection shader; selection chỉ là click vào
  proxy box của Three.js. `PRODUCT-07` DoD mới đạt 1/4.
  **Cập nhật 2026-09-29:** toàn bộ editor SuperSplat 3.4.2 (MIT) được vendor tại
  `frontend/vendor/supersplat/`, build ra `public/editor/` và nhúng vào Studio
  (`features/studio/EditorFrame.tsx`). Editor chạy WebGPU; không có WebGPU thì Studio
  dùng viewer WebGL2 (supersplat-viewer). Chỉnh sửa trong editor **chưa** lưu về
  backend thành SceneIR revision — chỉ export file (ADR 0002); PRODUCT-07 DoD không đổi.
- Single Scene Graph: Toàn bộ các lớp (Visual SOG, Mesh GLB, Collider GLB) đều nằm chung một Scene Graph trên PlayCanvas Engine, chia sẻ chung GPU Render Pass và Depth buffer, gắn chặt với canonical `SceneIR` transforms; không có scene truth riêng trong browser.
  **Trạng thái 2026-09-27: đạt một phần.** Collider GLB của environment đã đi qua
  `createViewer({ collisionUrl })` nên nằm trong **cùng** `pc.AppBase` với SOG — đây
  là phần Single Scene Graph đã có thật. Ba view kỹ thuật còn lại (Geometry mesh,
  Point Cloud, Collider object) vẫn do `SceneCanvas` (Three.js) dựng ở renderer
  riêng và **loại trừ nhau** với view Visual, nên chưa thể depth-sync hay so sánh
  splat-vs-collider trực tiếp. Transform canonical vẫn là nguồn duy nhất cho cả hai
  qua `features/viewer/layers.ts`.
- Generic Web shell: [`Kiranism/next-shadcn-dashboard-starter`](https://github.com/Kiranism/next-shadcn-dashboard-starter), [`arhamkhnz/next-shadcn-admin-dashboard`](https://github.com/arhamkhnz/next-shadcn-admin-dashboard) và [`shadcndashboard/next-shadcn-dashboard`](https://github.com/shadcndashboard/next-shadcn-dashboard) là **UI references tham khảo, không phải codebase được adapt**.
  **Đính chính 2026-09-27:** dòng này trước đây ghi "được adapt có chọn lọc" — sai,
  và `PLAN.md:123` đã ghi `❌ Không — shell viết tay`. Thực tế: không có
  `@radix-ui`, `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`
  hay `components.json` trong `frontend/`; `components/ui/` gồm 6 file ~150 dòng viết
  tay bằng Tailwind, icon là ký tự Unicode. Sửa lại để khớp `PLAN.md`.
  **Cập nhật 2026-09-29:** Studio MVP dùng `lucide-react`, `class-variance-authority`,
  `clsx`, `tailwind-merge` cho primitives tại `components/studio/` (viết lại theo pattern
  shadcn, không copy starter); vẫn không có `@radix-ui` hay `components.json`.
- **Studio MVP (2026-09-29, ADR 0002):** route group `(studio)` là UI mặc định
  (Scenes, Scene mới + video mẫu, trang scene + editor); UI P0 đầy đủ nằm ở
  `(legacy)`, ẩn trừ khi `LEGACY_UI=1`. Route Studio ở `src/api/studio/`, queue
  worker `orchestration/jobs/worker_cli.py` + `runner.py` chạy REC thật qua process.
- **Kiến trúc cloud (ADR 0003, chưa triển khai):** Vercel (UI), Railway (FastAPI +
  Postgres), Cloudflare R2 (file, upload/download thẳng), RunPod (GPU tự bật/tắt);
  hai role Editor/Reviewer, khách chỉ dùng video mẫu; trình duyệt chỉ nhận bản nhẹ.
- P0 không yêu cầu advanced scheduler hoặc multi-tenant infrastructure.
- Product workflow/lifecycle là project-owned; starter chỉ cung cấp generic UI patterns, không mang Clerk/organization/billing hoặc Next.js business backend vào hệ thống.

## Authority Gates

- EX-PRODUCT được phép tạo và sở hữu scaffold `frontend/` theo cấu trúc trong `ARCHITECTURE.md`.
- Frontend gọi FastAPI qua typed API client; không tạo backend/business-state implementation cạnh tranh trong Next.js.
- Persisted edits phải đi qua backend SceneIR revision; React state không phải source of truth.
- Release phải bind exact candidate, validation và approval; EvaluationReport bắt buộc theo run type/protocol.
- Editor/Reviewer authorization và source-rights/privacy gates không được bypass cho demo.
  **Ghi chú 2026-09-29:** Studio MVP đang chạy privacy `self_attested`
  (`PRODUCT_PRIVACY_MODE`), mặc định code vẫn `qa_verified`. Quyết định này nằm ở
  ADR 0002 (*Proposed*) và cần Product Owner + QA Lead chấp nhận hoặc từ chối.

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
- P0 real Brush 3DGS Visual và các view Geometry/Point Cloud/Collider render/chuyển được trong browser, bind đúng artifact checksums; missing/incompatible Visual không được báo pass AC-11.
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
