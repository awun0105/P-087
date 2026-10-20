# T-064: Viewer không dựng lại, không vẽ thừa, tab ẩn thì nghỉ

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md` (mục "Làm song song").

## Goal
Viewer 3D chỉ dựng một lần mỗi lần mở trang, chỉ vẽ khi có gì thay đổi trên màn hình, và gần như không tốn CPU/GPU khi tab
Studio bị ẩn hoặc trình duyệt ở tab khác.

## Context (đã kiểm trong code; dưới `frontend/src/features/`)
- `studio/ObjectReviewView.tsx:839` truyền `surfacePlanes={(scene.provenance.collision_surface_planes ?? [])}`: mảng mới
  mỗi render (trường này vắng ở mọi scene thật đã kiểm) → hiệu ứng `studio/MetricSceneView.tsx:615-617` gọi
  `overlay.setSurfaceMarkers` → `redraw()` (`viewer/scene-overlay.ts:615-634,1034`) → vẽ lại cả khung splat mỗi lần render.
- Prop đối tượng/hàm mới mỗi render ở `ObjectReviewView.tsx:831-880`: `inspection={{…}}`, `collisionDiagnostics`,
  `regionEdit`, `gizmo`, `onMarkSurface`, `onFill`, `onRemove`, `onTransform`, `placement` → hiệu ứng ở
  `MetricSceneView.tsx:344,351,447` chạy lại mỗi render; `JSON.stringify` 60 vật mỗi render (`MetricSceneView.tsx:222,268`,
  `viewer/usePhysicsPlay.ts:159`).
- `viewer/PlayCanvasScene.tsx:511-527` publish trạng thái runtime ở mỗi `animationTime:changed` và `progress:changed` →
  `setRuntime` ở PlayCanvasScene và host (MetricSceneView 953 dòng) → render lại cả cây mỗi khung khi phát quỹ đạo / đang tải.
- `PlayCanvasScene.tsx:574-575`: hiệu ứng tạo viewer phụ thuộc 17 prop gồm `cameras`, `initialCamera`.
  `ObjectReviewView.tsx:372` khởi tạo `cameras = []` rồi điền sau từ stage-views (`:462-471`) trong khi viewer mount ngay khi
  có scene (`:824`) → nếu scene về trước, viewer dựng hai lần, SOG môi trường tải hai lần. `useJobCameras` đã có cờ
  `settled` (`studio/scene/useJobCameras.ts:50`).
- Tab Studio đã mở thì giữ mount, ẩn bằng `invisible` (`studio/ScenePage.tsx:396-401`); vẫn nhận callback mới mỗi render.
  Đang Walk thì `usePhysicsPlay.ts:242` đặt `renderNextFrame` mỗi update → vẽ hết tốc độ kể cả sau khi đổi tab.
- Viewer vẽ theo yêu cầu (`autoRender=false` sau khung đầu) nhưng vòng `requestAnimationFrame` không bao giờ dừng.
- Dọn dẹp khi unmount đã đúng (không rò bộ nhớ).

## Thiết kế
1. Hằng mảng rỗng dùng chung (`EMPTY_PLANES` cấp module) thay cho `?? []`; `useMemo`/`useCallback` cho mọi prop ở
   `ObjectReviewView.tsx:831-880`; bỏ `JSON.stringify` trong render, thay bằng so khoá đã tính một lần khi dữ liệu đổi
   (`useMemo` theo `scene.scene_revision`).
2. `MetricSceneView` và `PreviewScene` chỉ mount viewer khi `useJobCameras(...).settled` (cùng cách `PreviewScene` đã làm ở
   bước 5). Thay đổi camera/quỹ đạo sau khi viewer đã dựng đi qua handle (`gotoPose`, `seekTrajectory`), không qua prop
   của hiệu ứng dựng viewer. Danh sách phụ thuộc của hiệu ứng tạo viewer chỉ còn: URL/ checksum nguồn, renderer, các
   callback ổn định.
3. `PlayCanvasScene` publish: `animationTime` và `progress` giữ trong `ref`, phát cho UI tối đa 4 lần/giây (throttle);
   các trường khác (loaded, cameraMode, walkAllowed…) phát ngay khi đổi.
4. Tab ẩn: `StudioTab` nhận `active: boolean`. Khi `false`: thoát Walk nếu đang Walk, gọi hàm mới
   `PlayCanvasHandle.setSuspended(true)` (dừng cập nhật: `app.timeScale = 0`, `app.autoRender = false`, không đặt
   `renderNextFrame`); khi `true` lại: `setSuspended(false)` + vẽ một khung. Cũng tạm dừng khi `document.visibilityState
   === "hidden"`. `StudioTab` bọc `React.memo`; callback truyền vào từ `ScenePage` dùng `useCallback`.
5. Overlay (`scene-overlay.ts`, `shell-glow.ts`): handler mỗi khung chỉ chạy khi có hoạt ảnh thật (đánh dấu cờ `animating`);
   không có thì bỏ qua.

## Steps
1. `frontend/tests/viewer-render-churn.test.tsx`: render `ObjectReviewView` với scene fixture, đếm số lần
   `setSurfaceMarkers` / `redraw` (mock overlay) sau 5 lần render cha không đổi dữ liệu → 0. FAIL. Cài thiết kế 1. Commit
   `perf(studio): keep viewer props stable across renders`.
2. `frontend/tests/viewer-mount-once.test.tsx`: scene về trước stage-views → viewer constructor (mock) gọi đúng 1 lần.
   Cài thiết kế 2. Commit `perf(viewer): mount once after cameras settle`.
3. `frontend/tests/viewer-publish-throttle.test.tsx`: 60 sự kiện `animationTime:changed` trong 1 s → host render ≤ 5 lần.
   Cài thiết kế 3. Commit.
4. `frontend/tests/studio-suspend.test.tsx`: chuyển sang tab Tiến trình → `setSuspended(true)` được gọi, Walk tắt; quay lại
   → `setSuspended(false)`. Tab trình duyệt ẩn → tạm dừng. Cài thiết kế 4. Commit
   `perf(studio): suspend the hidden viewer and exit walk when leaving the tab`.
5. Thiết kế 5 + test overlay hiện có (`shell-glow.test.ts` — **phiên khác vừa sửa** ở commit `0ac16a12`, đọc bản mới nhất,
   giữ kỳ vọng). Commit.
6. Đo thủ công không bắt buộc (người dùng tự xem bằng mắt). Ghi trong report các số từ test (số lần render/vẽ trước/sau).

## Acceptance criteria
1. Render lại trang không làm viewer vẽ lại khi dữ liệu 3D không đổi.
2. Viewer dựng đúng một lần mỗi lần mở trang.
3. Tab Studio ẩn: không Walk, không cập nhật mỗi khung.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/viewer-render-churn.test.tsx tests/viewer-mount-once.test.tsx tests/viewer-publish-throttle.test.tsx tests/studio-suspend.test.tsx tests/shell-glow.test.ts tests/object-review.test.tsx tests/preview-scene-camera.test.tsx tests/collider-loading.test.ts
cd frontend && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
