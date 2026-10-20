# T-065: Tải lười — Ammo, lưới va chạm, collider chỉ khi Walk; trang bước tải song song; chia nhỏ JS

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Mở Studio hoặc một trang bước chỉ tải đúng thứ cần để **nhìn**. Phần chỉ cần khi đi bộ (Walk) tải khi bật Walk. Các request
đầu trang chạy song song. Trang không cần 3D thì không tải thư viện 3D.

## Context (đã kiểm trong code; dưới `frontend/src/features/`)
- `viewer/usePhysicsPlay.ts:158,166-178`: `enabled` đúng khi có bất kỳ vật CANDIDATE (mọi scene thật) → Ammo (453 KB JS +
  750 KB wasm), GLB va chạm (0,1–1 MB; 29 MB ở `job-f9f14e7fbfb1` trước T-052) và collider tải ngay khi mở Studio.
- `studio/MetricSceneView.tsx:208,708`, `viewer/PlayCanvasScene.tsx:258-271`: bước 6 (Metric) cũng tải GLB va chạm ngay.
- `studio/StageViewer.tsx:101-113`: bước 8 (Collision mesh) tải **cả SOG** chỉ để hiện một lưới 0,1–1 MB.
- `viewer/glb-mesh.ts:166-185`: parse GLB trên luồng chính theo lát 2048; `setCollisionMeshAsync` dựng cấu trúc va chạm cũng
  trên luồng chính.
- `studio/inspection/StageInspectionPage.tsx:55-64`: `getJobProgress` → (`getJob` ∥ `listJobArtifacts`) → `getProject`
  (chỉ để lấy tiêu đề) nối tiếp; sau đó mới tải chunk viewer, rồi `getStageViews`, rồi file 3D.
- `studio/scene/PreviewScene.tsx:97-133`: bước 5 chờ stage-views (camera) xong mới bắt đầu tải SOG.
- `StageViewer.tsx:5-21` import tĩnh three/r3f/drei và `MetricSceneView`; `viewer/scene-overlay.ts:33`, `viewer/shell-glow.ts:19`
  import tĩnh `playcanvas` → bước Cameras (chỉ vẽ SVG) vẫn kéo ~2,8 MB JS.
- Tất cả host ép `renderer="webgl"` (`StageViewer.tsx:198`, `PreviewScene.tsx:137`, `MetricSceneView.tsx:692`).

## Thiết kế
1. Walk lười: `usePhysicsPlay` chỉ `enabled` khi người dùng bật Walk (hoặc chế độ cần va chạm thật). Ammo, GLB va chạm,
   collider tải khi bật lần đầu; giữ lại trong phiên. Nút Walk hiện trạng thái "Đang chuẩn bị đi bộ…" trong lúc tải.
   Bước 6 chỉ tải GLB va chạm khi người dùng bật lớp va chạm.
2. Bước 8: chỉ tải lưới (không SOG). Có nút "Hiện kèm 3DGS" để tải SOG khi cần.
3. Web Worker `viewer/collision-worker.ts`: parse GLB + dựng mảng đỉnh/mặt cho va chạm, trả `Float32Array`/`Uint32Array` qua
   transferable. Luồng chính chỉ nhận mảng. Giữ hàm hiện có làm đường dự phòng khi `Worker` không có (test jsdom).
4. Trang bước: chạy `getJobProgress`, `getJob`, `listJobArtifacts`, `getStageViews` song song ngay khi vào trang;
   `getProject` chạy song song và không chặn hiển thị (tiêu đề hiện khi về). `PreviewScene` bắt đầu tải SOG song song với
   stage-views; camera áp vào viewer khi về (qua handle, T-064).
5. Chia JS: `StageViewer` import động theo loại lớp (`frames`, `cameras` không import 3D; `gaussian`/`mesh` import động
   `MetricSceneView`/three). `scene-overlay.ts`, `shell-glow.ts` chỉ được import từ module đã import động.
6. Renderer: thêm thiết lập `NEXT_PUBLIC_VIEWER_RENDERER` (`webgl` mặc định, `auto` cho phép WebGPU khi trình duyệt hỗ trợ).
   Không đổi mặc định trong task này; ghi khuyến nghị thử `auto` vào report.

## Steps
1. `frontend/tests/walk-lazy-load.test.tsx`: mở Studio scene ready (mock) → không request Ammo/walk-collision; bật Walk →
   có. Cài thiết kế 1. Commit `perf(studio): load physics and walk collision only when walking`.
2. `frontend/tests/stage-mesh-only.test.tsx`: bước 8 → không request SOG; bấm "Hiện kèm 3DGS" → có. Cài thiết kế 2. Commit.
3. `frontend/tests/collision-worker.test.ts`: kết quả worker bằng kết quả hàm cũ trên GLB fixture; khi không có `Worker`
   dùng đường cũ. Cài thiết kế 3. Commit `perf(viewer): parse collision meshes off the main thread`.
4. `frontend/tests/stage-inspection-parallel.test.tsx`: bốn request đầu khởi chạy trước khi request đầu tiên trả về (mock
   fetch giữ promise). Bước 5: request SOG khởi chạy trước khi stage-views trả. Cài thiết kế 4. Commit.
5. Thiết kế 5. Kiểm bằng `npm run build` **một lần** (nặng, chạy khi máy rảnh) và so kích thước chunk của route trang bước
   trước/sau (`.next/static/chunks`); test `frames and cameras views do not import playcanvas` dùng `vi.mock` bắt import.
   Commit `perf(studio): split stage viewer bundles by layer`.
6. Thiết kế 6 + test đọc biến. Commit.

## Acceptance criteria
1. Mở Studio không tải Ammo, lưới va chạm, collider cho tới khi bật Walk.
2. Bước 8 tải dưới 1 MB khi chưa bật 3DGS.
3. Trang bước bắt đầu tải file 3D sau một vòng request song song, không phải bốn vòng nối tiếp.
4. Bước Frames và Cameras không tải thư viện 3D.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/walk-lazy-load.test.tsx tests/stage-mesh-only.test.tsx tests/collision-worker.test.ts tests/stage-inspection-parallel.test.tsx tests/studio-inspection.test.tsx tests/collider-loading.test.ts tests/preview-scene-camera.test.tsx
cd frontend && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```
`tests/studio-inspection.test.tsx` vừa được phiên khác sửa (commit `b47c80e4`): đọc bản mới nhất, giữ kỳ vọng.

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm kích thước chunk trước/sau), `status.md`.
