# T-063: Một nguồn dữ liệu scene/gói/duyệt; dọn nhánh chết

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
SceneIR, gói mô phỏng và trạng thái duyệt của revision hiện tại được tải **một lần mỗi revision** cho cả trang, dùng chung
cho mọi tab. Code giao diện không còn dùng được thì xoá.

## Context (đã kiểm trong code; dưới `frontend/src/features/studio/`)
- SceneIR (650 KB) được tải riêng ở `ObjectReviewView.tsx:446`, `scene/ReviewTab.tsx:32`, `scene/ResultsTab.tsx:39`
  (NextAction đã bỏ ở T-062). Gói/duyệt tải riêng ở `ResultsTab.tsx:36-42`, `ReviewTab.tsx:239`,
  `SimulationPackagePanel.tsx:55`, `ReviewPanel.tsx:59`, mỗi chỗ một luật so revision (`ResultsTab.tsx:57-58`,
  `SimulationPackagePanel.tsx:86-87`, `ReviewPanel.tsx:76`).
- `ValidationRunsPanel.tsx:80-84` tự viết vòng `setTimeout` 5 s.
- Nhánh chết: `GAUSSIAN_EDIT_ENABLED = false` (`scene/state.ts:13`) và dây nối `mode=gaussian`, `EditorFrame`,
  `onOpenGaussian` (`ScenePage.tsx:101,366,425`, `StudioTab.tsx:380`, `ResultsTab.tsx:74-76`); `StageState` 4 giá trị
  (`scene/state.ts:29`) cạnh kiểu 6 giá trị của contract; đường dự phòng cũ của `sceneSummaryStatus` (T-062).
- `/jobs/{id}/scene` có ETag + gzip sau T-053.

## Thiết kế
1. `scene/sceneRecord.tsx`:
   ```ts
   export interface SceneRecord { scene: SceneIR | null; pkg: SimulationPackage | null; review: ReviewState | null;
     loading: boolean; error: string | null; reload: (what?: "scene" | "package" | "review") => void }
   export function SceneRecordProvider(props: { jobId: string; revision: string | null; children: ReactNode }): JSX.Element
   export function useSceneRecord(): SceneRecord
   ```
   Tải khi `revision` (từ `view.scene_revision`) đổi; dùng ETag để `reload` rẻ; gói và duyệt chỉ tải khi có consumer đang
   hiển thị cần (cờ `need` đăng ký qua hook `useSceneRecord({ needPackage: true })`). Một luật duy nhất: dữ liệu chỉ dùng khi
   `scene_revision` của nó bằng `revision` hiện tại.
2. Chuyển `ObjectReviewView`, `ReviewTab`, `ResultsTab`, `SimulationPackagePanel`, `ReviewPanel` sang `useSceneRecord`;
   thao tác sửa scene xong gọi `reload("scene")` thay cho tự fetch. Giữ xử lý 409 hiện có (`ObjectReviewView.tsx:617-631`)
   nhưng đi qua `reload`.
3. `ValidationRunsPanel`: dùng `usePolling` 5 s khi có lượt đang chạy.
4. Xoá: `GAUSSIAN_EDIT_ENABLED` và mọi nhánh phụ thuộc; `StageState` 4 giá trị (dùng kiểu contract); đường dự phòng của
   `sceneSummaryStatus`; `useObjectify` các hàm `objectifyStageOverride`, `geometryReviewStep` nếu không còn ai dùng.
   Mỗi lần xoá: `grep` không còn tham chiếu, typecheck xanh.

## Steps
1. `frontend/tests/scene-record.test.tsx`: `loads the scene once for two consumers`, `reloads on revision change`,
   `ignores a response for an older revision`, `does not fetch package until a consumer needs it`,
   `reload uses If-None-Match`. Cài thiết kế 1. Commit `feat(studio): share one scene record per revision`.
2. Chuyển từng consumer, mỗi consumer một commit, chạy test của nó (`object-review.test.tsx`, `studio-results.test.tsx`,
   test ReviewTab/SimulationPackagePanel/ReviewPanel). **Lưu ý**: `object-review.test.tsx` vừa được phiên khác sửa
   (commit `7bc06356`, `e0e9746a`); đọc bản mới nhất trước khi sửa, giữ đúng kỳ vọng của họ.
3. `ValidationRunsPanel`. Commit.
4. Dọn nhánh chết (thiết kế 4). Commit `chore(studio): remove unreachable gaussian edit mode and legacy state types`.
5. Đo: test đếm số lần gọi `/scene` khi mở trang ready rồi chuyển qua cả bốn tab → mục tiêu 1. Ghi report.

## Acceptance criteria
1. Một revision → một lần tải SceneIR cho cả trang.
2. Không còn hai luật so revision khác nhau.
3. Không còn code không thể chạy tới đã liệt kê.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/scene-record.test.tsx tests/object-review.test.tsx tests/studio-results.test.tsx <test ReviewTab> <test SimulationPackagePanel> <test ReviewPanel> <test ValidationRunsPanel>
cd frontend && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
