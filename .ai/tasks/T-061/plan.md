# T-061: Dòng tiến trình vẽ từ bước thật

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Tab Tiến trình hiện đúng danh sách bước backend trả về, không còn bước giả, không còn ghi đè trạng thái; mỗi bước có một chỗ
nút hành động, tính theo một hàm.

## Context (đã kiểm trong code; dưới `frontend/src/features/studio/`)
- `scene/ProgressTab.tsx:52-67` ghép: ghi đè `ST-OBJECT-EXTRACT` bằng `objectifyStageOverride` (mã bịa
  `OBJECTIFY_FAILED`), chèn hàng giả `UI-GEOMETRY-REVIEW` (`stages.ts:75-90`); hàng giả được đếm vào thanh "n/N bước"
  (`PipelineTimeline.tsx:93,123`) trong khi đầu trang nói "Đã dựng scene".
- `ProgressTab.tsx:69-113` tự quyết nút cho từng bước; nút "Dùng hộp ứng viên" hiện cả trên scene khoẻ.
- `stages.ts:117` `stagesFor` tự chèn bước LiDAR; metadata bước (`title`, `short`, `description`) ở `stages.ts`.
- `fraction` luôn `null` nên phần ước lượng "Còn …" (`scene/estimation.ts:13`) không bao giờ hiện cho job thật.
- Sau T-060: `usePipelineContext()` có `view.steps`, `view.next_action`, `view.wait`, `view.objectify`.

## Thiết kế
1. `stages.ts`: thêm metadata cho `ST-ANONYMIZATION-REVIEW` ("Xem bản đã che"), `ST-OBJECT-CONFIRM` ("Duyệt vật"),
   `ST-SCENE-DECOMPOSE` ("Tạo mesh và lưới va chạm từng vật"). Đổi `title` của `ST-RGB-GEOMETRY` thành "Lưới va chạm môi
   trường". Hàm `stepMeta(id: StageId): StageMeta` (ném nếu thiếu — test bảo đảm đủ). Xoá `GEOMETRY_REVIEW_STAGE*`,
   `TimelineStageId`, `stagesFor` khi không còn chỗ dùng (kiểm `demoStages.ts` — xem bước 3).
2. `scene/stepActions.ts` (thuần):
   ```ts
   export interface StepActionHandlers { confirmMetric?: () => void; openStudio?: () => void; showAnonymization?: () => void;
     retryJob?: () => void; retryGeometry?: () => void; cancelOperation?: () => void; rerunObjectify?: () => void; useBoxes?: () => void }
   export function stepActions(view: PipelineView, handlers: StepActionHandlers, busy: boolean): StageAction[]
   ```
   Một nhánh cho mỗi `next_action.kind` gắn nút vào `next_action.step_id`; thêm "Hủy yêu cầu" khi `wait.kind ===
   "scene_operation"` hoặc bước `SCENE_DECOMPOSE`/`OBJECT_EXTRACT` đang `running`/`queued`. "Dùng hộp ứng viên" **chỉ** với
   `choose_object_method`. Handler `undefined` (không có quyền) thì không có nút.
3. `ProgressTab`: nhận `view` từ context; `stages = view.steps.map(...)`, `stageList = view.steps.map(s => stepMeta(s.step_id))`;
   thời lượng: bước hệ thống hiện `completed_at - started_at` (đang chạy: tới `now` của đồng hồ chung); bước người dùng hiện
   "Chờ bạn x phút" khi `waiting`, "Bạn xử lý trong x phút" khi xong; `timing_source === "none"` không hiện số. Bỏ
   `objectifyStageOverride`, `geometryReviewStep`, `geometryNote`. Ghi chú bước lấy từ `step.note` và nhãn pha
   (`geometryPhaseLabel(step.phase)`).
   Demo replay (`demoStages.ts`, `useDemoReplay.ts`): đổi id hàng giả sang `ST-OBJECT-CONFIRM`/`ST-SCENE-DECOMPOSE` để dùng
   chung metadata.
4. `PipelineTimeline`: `React.memo`; "n/N bước hoàn tất" đếm theo `view.steps` (không còn hàng giả); bỏ nhánh ETA nếu
   không còn caller nào truyền `fraction` khác `null` (grep cả demo); nếu demo còn dùng thì giữ.
5. `errorGuidance.ts`: hướng dẫn cho `OBJECTIFY_AWAITING_CHOICE` và `OBJECT_GEOMETRY_BUILD_FAILED`.

## Steps
1. `frontend/tests/step-actions.test.ts`: một test cho mỗi `next_action.kind` có nút; `no "use candidate boxes" on a
   healthy scene`; `cancel shows while a scene operation runs`; `no buttons without handlers`. Cài thiết kế 2. Commit
   `feat(studio): compute step actions from the pipeline next action`.
2. `frontend/tests/step-meta.test.ts`: `every StageId has metadata`. Cài thiết kế 1. Commit.
3. Chuyển `ProgressTab`, `PipelineTimeline`, demo (thiết kế 3, 4). Sửa test `pipeline-timeline.test.tsx`,
   `progress-objectify.test.tsx`, `geometry-review-row.test.tsx`, `geometry-review-step.test.tsx` sang dữ liệu `PipelineView`
   (giữ kỳ vọng hiển thị: hàng Duyệt vật / Tạo mesh, nút, ghi chú). Thêm `count excludes nothing fake: 12/12 when done`.
   Commit `refactor(studio): render the progress timeline from backend steps`.
4. Thiết kế 5 + test guidance. Commit.

## Acceptance criteria
1. Không còn id bước chỉ có ở giao diện; số bước và trạng thái khớp backend.
2. Mọi nút ở dòng tiến trình đến từ `stepActions`.
3. Demo replay vẫn chạy.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/step-actions.test.ts tests/step-meta.test.ts tests/pipeline-timeline.test.tsx tests/progress-objectify.test.tsx tests/geometry-review-row.test.tsx tests/geometry-review-step.test.tsx <test demo replay> <test errorGuidance>
cd frontend && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md`, `status.md`.

## Bổ sung 20/10: thông báo khởi động máy GPU
- Khi `view.gpu?.state` ∈ {`off`, `starting`} và job đang chờ máy (QUEUED hoặc `waiting_for` resources/runtime): hiện
  `GpuStartupNotice` (component của phiên deploy, `frontend/src/features/studio/GpuStartupNotice.tsx`, nhận `{capacity}`)
  ở khung "Đang chờ máy xử lý" của `ProgressTab` thay cho câu chung. Không sửa component đó; truyền `now` của đồng hồ chung
  nếu component nhận.
- Test: `shows GPU startup notice while the GPU machine is starting`, `no GPU notice once the GPU is ready`.
