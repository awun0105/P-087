# T-060: Một vòng poll mỗi trang, không re-render khi không đổi

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md` (mục "Làm song song").

## Goal
Trang scene chỉ poll `GET /jobs/{id}/pipeline`. Khi phản hồi không đổi (304 hoặc cùng `version`), React không render lại gì.
Xác nhận mét ở tab khác vẫn làm trang này đi tiếp.

## Context (đã kiểm trong code; đường dẫn dưới `frontend/src/features/studio/`)
- `ScenePage.tsx:206` poll `getJobProgress` mỗi 3 s, **dừng** khi job kết thúc hoặc khi đã có preview và đang chờ xác nhận
  mét → xác nhận ở tab khác không làm trang đi tiếp. `ScenePage.tsx:181` luôn `setProgress(result.data)` (đối tượng mới)
  → cả trang render lại mỗi 3 s, kể cả tab Studio đang ẩn.
- `scene/useObjectify.ts:52,76` đọc `/scene/objectify`, poll 5 s khi đang chạy; `useObjectifyState` trả object literal mới
  mỗi render (`:117`) và đưa thẳng vào provider (`ScenePage.tsx:314`) → mọi consumer render lại.
- `GaussianMembershipEditor.tsx:64` tự poll objectify mỗi 1,5 s bằng `setInterval`, khởi động lại khi `operation` đổi (`:77`).
- Hai đồng hồ 1 s: `ProgressTab.tsx:45` và `scene/NextAction.tsx:84` (`useNow`), chạy cả khi đang chờ người.
- `usePolling(task, intervalMs, active, key)` (`usePolling.ts`) đã bỏ qua khi tab trình duyệt ẩn.
- `lib/api/client.ts` là nơi gọi fetch chung (đọc để biết cách thêm header `If-None-Match` và nhận 304).

## Thiết kế
1. API client: `getJobPipeline(jobId: string, etag: string | null, signal?: AbortSignal):
   Promise<ApiResult<{ view: PipelineView; etag: string } | { notModified: true }>>` trong `lib/api/studio.ts`. Gửi
   `If-None-Match` khi có `etag`; 304 → `{ notModified: true }`.
2. `scene/usePipeline.ts`:
   ```ts
   export interface PipelineHandle { view: PipelineView | null; error: string | null; refresh: () => void }
   export function usePipeline(jobId: string): PipelineHandle
   ```
   - Lưu `view` trong `useState`; chỉ `setView` khi nhận thân mới **và** `view.version` khác bản đang giữ.
   - Nhịp: 3000 ms khi `next_action.owner === "system"` hoặc có bước `running`/`queued`; 15000 ms khi chờ người
     (`owner === "user"` và chưa xong); 60000 ms khi `next_action.kind` ∈ {`released`, `job_failed`, `job_cancelled`,
     `scene_ready`, `create_package`, `review_package`, `await_review`, `fix_preflight`, `confirm_objects`}. Không bao giờ
     dừng hẳn (vẫn bắt được thay đổi từ tab khác). Dùng `usePolling`.
   - `refresh()` tăng `key` của `usePolling` để hỏi ngay (sau mỗi thao tác của người dùng).
3. `scene/pipelineContext.tsx`: `PipelineProvider` / `usePipelineContext()`; giá trị context được `useMemo` theo
   `view`, `error`, `refresh`.
4. `ScenePage.tsx`: thay poll `getJobProgress` bằng `usePipeline`; `progress = view?.progress ?? null`. Giữ nguyên logic
   `retrySync`, `latestAppliedPoll`, nạp preview — chỉ đổi nguồn dữ liệu. `pollingKey` hiện có gọi `refresh()`.
5. `useObjectify`: bỏ fetch/poll riêng; `state` lấy từ `view.objectify`; `send`/`cancel` giữ endpoint cũ, xong gọi
   `refresh()`. Giá trị trả về `useMemo`. `GaussianMembershipEditor` đọc trạng thái từ context, bỏ `setInterval`.
6. Một đồng hồ dùng chung `scene/useSharedNow.ts`: tick 5 s, chỉ chạy khi có bước `running` (dùng để hiện "đang chạy x
   phút"). `ProgressTab` và `NextAction` dùng nó thay `useNow`.

## Steps
1. Test `frontend/tests/use-pipeline.test.tsx` (fake timers, mock fetch):
   - `keeps the same view object when the server answers 304`: render đếm số lần render của consumer; hai nhịp 304 → không
     render thêm.
   - `polls every 3 s while the system works and every 15 s while waiting for the user`.
   - `picks up a confirmation made in another tab within 15 s` (Review Focus 5): phản hồi đổi từ chờ mét sang RUNNING ở nhịp
     sau → consumer thấy trạng thái mới trước 15 s.
   - `refresh triggers an immediate request`.
   Cài thiết kế 1–3. Commit `feat(studio): poll the unified pipeline view with ETag`.
2. Chuyển `ScenePage`, `useObjectify`, `GaussianMembershipEditor` (thiết kế 4, 5). Chạy test hiện có:
   `progress-objectify.test.tsx`, `geometry-review-*.test.tsx`, test của `ScenePage`/`ux-scene-flow.test.tsx`, test
   GaussianMembershipEditor (`grep -rl GaussianMembershipEditor frontend/tests`); sửa mock fetch sang endpoint mới khi test
   hỏng vì đổi nguồn, **không** đổi kỳ vọng hành vi. Commit `refactor(studio): drive the scene page from one pipeline poll`.
3. Đồng hồ chung (thiết kế 6) + test `ticks only while a step is running`. Commit.
4. Đo: test đếm request trong 60 s (fake timers) cho bốn tình huống: job đang chạy, chờ mét, scene ready trên tab Studio,
   trang bước. Ghi bảng trước/sau vào report. Mục tiêu: ≤ 20/phút khi chạy, ≤ 4/phút khi chờ người, ≤ 1/phút khi xong.

## Acceptance criteria
1. Trang scene chỉ còn một vòng poll trạng thái (ngoài thời gian thao tác và phiên Walk).
2. Không re-render khi trạng thái không đổi.
3. Trang không bao giờ "đứng" chờ: thay đổi từ nơi khác hiện ra trong ≤ 15 s khi đang chờ người.

## Tests required
```
cd frontend && ./node_modules/.bin/vitest run tests/use-pipeline.test.tsx tests/progress-objectify.test.tsx tests/geometry-review-banner.test.tsx tests/geometry-review-bell.test.tsx tests/geometry-review-row.test.tsx tests/geometry-review-step.test.tsx <test ScenePage> <test GaussianMembershipEditor>
cd frontend && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm bảng request/phút), `status.md`.
