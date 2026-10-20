# T-062: Một nguồn "việc cần làm" cho chuông, banner, đầu trang, danh sách

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Chuông, banner Tạo mesh, thông báo trong Studio, nhãn đầu trang và nhãn ở danh sách scene đều nói cùng một điều, lấy từ
`next_action` của backend và một bảng nhãn duy nhất. Chuông không còn tự tải SceneIR mỗi 10 giây.

## Context (đã kiểm trong code; dưới `frontend/src/features/studio/`)
- Sáu nơi tự tính "bước tiếp theo": `scene/ProgressTab.tsx:69-113` (đã chuyển ở T-061), `scene/NextAction.tsx:114-200`,
  `GeometryReviewBanner.tsx:14-20`, `ObjectifyNotice.tsx:17-116`, `scene/StudioTab.tsx:392-400`, `sceneStatus.ts`
  (`sceneStatus`, `progressSceneStatus`, `deriveStatus`).
- Mâu thuẫn đã thấy: dựng lại vùng thì đầu trang "Đang tạo mesh", chuông "Đang dựng lại vùng", Studio "Đang áp vùng";
  `deriveStatus:99` gán "Đang dựng collision" cho bước xác nhận mét; nút hủy job ẩn khi chờ mét nhưng hiện khi chờ bản che
  trong khi panel bản che bảo dùng nút hủy (`ScenePage.tsx:97-99`, `AnonymizationReviewPanel.tsx:421`).
- `NextAction.tsx:89-106` tải `/scene`, `/simulation-package`, `/review` mỗi 10 s chỉ để đếm vật chờ và đọc trạng thái gói:
  3,9–5,8 MB/phút.
- Bảng nhãn trùng lặp: `sceneStatus.ts:44-48`, `NextAction.tsx:114-118,170-179`, `ObjectifyNotice.tsx:25-49`,
  `scene/badges.tsx:72`, `StudioTab.tsx:394-399`, `AttemptHistory.tsx:10`, `PipelineTimeline.tsx:282`.
- Sau T-059: `SceneSummary.next_action`; sau T-060: context pipeline.

## Thiết kế
1. `nextAction.ts`:
   ```ts
   export interface NextActionView { title: string; description: string; target: { tab: Tab; mode?: StudioMode } | null;
     status: SceneStatusView }
   export function nextActionView(action: NextAction, ctx: { wait: PipelineWait | null; objectifyMode: ObjectifyMode | null;
     phase: ObjectifyPhase | null; isReviewer: boolean }): NextActionView
   export function operationLabel(mode: ObjectifyMode): string   // "Đang tạo mesh" | "Đang dựng lại vùng" | "Đang tách lại vật" | ...
   ```
   Một bảng `Record<NextActionKind, ...>` chứa toàn bộ câu chữ (lấy câu hiện có ở `NextAction.tsx` làm gốc, giữ nghĩa).
   `wait_system` dùng `operationLabel` khi `wait.kind === "scene_operation"`, "Đang chờ tài nguyên" / "Đang chờ GPU" /
   "Đang chờ máy xử lý" theo `progress.waiting_for`, còn lại "Đang chạy · <tên ngắn của bước>".
2. Thay thế:
   - `NextAction.tsx`: bỏ `load`/`usePolling` tải scene–gói–duyệt và chuỗi `if`; giữ phần trạng thái thử lại phía máy khách
     (`retryState`) và mất tín hiệu (`stale`) đứng trước `nextActionView`. Xoá biến thể `variant="banner"` (chỉ test dùng):
     test chuyển sang mở popover.
   - `GeometryReviewBanner`: nút Tạo mesh bật khi `next_action.kind === "review_objects" && pending_count === 0`.
   - `ObjectifyNotice`, `StudioTab` thông báo dự phòng: lấy câu từ `nextActionView`.
   - Đầu trang: `progressSceneStatus` thay bằng `nextActionView(...).status`.
   - Danh sách: `sceneSummaryStatus(scene)` dùng `scene.next_action` khi có; giữ đường cũ chỉ khi trường vắng (API cũ) và
     đánh dấu `// TODO(T-063): remove after deploy`.
   - `ScenePage.tsx:97-99`: cho hủy job cả khi chờ bản che (đúng với hướng dẫn trong panel).
3. Một từ vựng: "Lưới va chạm môi trường" cho `ST-RGB-GEOMETRY`, "Tạo mesh" cho `ST-SCENE-DECOMPOSE`. Sửa `GeometryBadge`
   (`badges.tsx:72`) cho đúng nghĩa.

## Steps
1. `frontend/tests/next-action-view.test.ts`: một test cho mỗi `NextActionKind`; `region rebuild says "Đang dựng lại vùng"
   everywhere` (đầu trang, chuông, thông báo cùng một câu); `metric wait never says collision`. Cài thiết kế 1. Commit
   `feat(studio): one table of next-action wording`.
2. Chuyển `NextAction` (bỏ tải scene) + test `bell makes no scene request` (mock fetch: không có URL `/scene`). Sửa
   `geometry-review-bell.test.tsx`, `ux-scene-flow.test.tsx` sang dữ liệu pipeline. Commit
   `refactor(studio): drive the bell from the pipeline next action`.
3. Banner, notice, StudioTab, đầu trang, hủy khi chờ bản che. Sửa `geometry-review-banner.test.tsx`. Commit.
4. Danh sách scene: `sceneSummaryStatus` + test trong `imported-scenes-home.test.tsx` / test ScenesHome. Commit.

## Acceptance criteria
1. Cùng một tình huống, mọi chỗ hiện cùng câu.
2. Chuông không tải SceneIR, gói, trạng thái duyệt.
3. Không còn chuỗi `if` quyết định "bước tiếp theo" ngoài `nextAction.ts` và các trạng thái thuần phía máy khách (đang gửi
   thử lại, mất tín hiệu).

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/next-action-view.test.ts tests/geometry-review-bell.test.tsx tests/geometry-review-banner.test.tsx tests/ux-scene-flow.test.tsx tests/imported-scenes-home.test.tsx <test ScenesHome> <test ObjectifyNotice>
cd frontend && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.
