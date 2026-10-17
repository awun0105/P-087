# T-021: Tiến trình, chuông và trạng thái đầu trang hiểu Draft

## Goal
Pipeline mới dừng ở Draft sau "Tách vật thể"; job đã `SUCCEEDED` nhưng scene chưa có collider. Hiện tab Tiến trình báo mọi
bước xong, chuông gợi ý "Sẵn sàng tạo gói" (bị 409 trong Draft), đầu trang không nói gì. Task này cho cả ba nơi biết Draft:
thêm hàng **"Duyệt vật & Tạo mesh"** sau "Tách vật thể", nhánh Draft trong chuông, nhãn trạng thái đầu trang; sửa mô tả bước cũ.

Quyết định đã chốt với chủ dự án:
- **Không** thêm `StageId` backend, không đổi job pipeline/manifest/receipt. Hàng mới là hàng **ảo phía frontend**, trạng thái lấy
  từ `ObjectifyState` (đã được poll và chia sẻ qua `ObjectifyContext`).
- Mọi demo sẽ chạy lại từ đầu: không cần xử lý riêng job cũ ngoài quy tắc "scene thiếu khoá `object_geometry` → không có hàng mới".
- Chuông không phải thông báo theo người dùng: ai mở job cũng thấy cùng gợi ý; nút sang Studio chỉ hiện khi `canMutateJob`.

## Context
`architecture.md` §5, §7.4 (phase build), §9. Code hiện có:
- `src/services/orchestration/scene/objectify_queue.py:97` `ObjectifyState`, `:243` `state()` (đọc scene hiện tại).
- `frontend/src/lib/api/studio.ts` `ObjectifyState`; `frontend/src/lib/scene/geometry-state.ts` (`objectGeometryState`, `geometryPhaseLabel`).
- `frontend/src/features/studio/stages.ts` (`OBJECT_STAGE`, `GEOMETRY_STAGE`, `stagesFor`), `PipelineTimeline.tsx` (`StageView`,
  `StageAction`, link "Xem giai đoạn" cho bước xong), `scene/ProgressTab.tsx`, `scene/useObjectify.ts` (`objectifyStageOverride`),
  `scene/NextAction.tsx`, `sceneStatus.ts` (`progressSceneStatus`), `ScenePage.tsx` (Provider ở dòng ~293 bao cả chuông và tab).
- Banner Draft trong Studio: `GeometryReviewBanner.tsx` (giữ nguyên, T-021 không đổi Studio).

## Files
- Sửa: `src/services/orchestration/scene/objectify_queue.py` (trường mới)
- Sửa: `frontend/src/lib/api/studio.ts`, `frontend/src/features/studio/stages.ts`, `PipelineTimeline.tsx`,
  `scene/ProgressTab.tsx`, `scene/useObjectify.ts`, `scene/NextAction.tsx`, `sceneStatus.ts`, `ScenePage.tsx`
- Test: `tests/test_orchestration/test_scene_objectify_queue.py`, `tests/test_api/test_scene_v2_routes.py`,
  `frontend/tests/` các file đang test `ProgressTab`, `NextAction`, `sceneStatus`, `PipelineTimeline`, `objectifyStageOverride`
  (tìm bằng codegraph; thêm file mới `frontend/tests/geometry-review-step.test.tsx` nếu cần).

## Interfaces
Backend (`ObjectifyState`, thêm một trường, mặc định `None` để payload cũ vẫn hợp lệ):
```python
#: Trạng thái hình học theo vật của scene hiện tại; None = scene không có khoá `object_geometry` (luồng cũ).
object_geometry: Literal["awaiting_review", "ready"] | None = None
```
`state()`: `provenance.get("object_geometry")` nếu là một trong hai giá trị; giá trị lạ → `"awaiting_review"` (khớp quy tắc
khoá-lại của `objectGeometryState`); thiếu khoá → `None`.

Frontend:
```ts
// studio.ts — ObjectifyState
object_geometry?: "awaiting_review" | "ready" | null;

// stages.ts — id chỉ có ở frontend, KHÔNG thêm vào contracts/StageId
export const GEOMETRY_REVIEW_STAGE_ID = "UI-GEOMETRY-REVIEW" as const;
export type TimelineStageId = StageId | typeof GEOMETRY_REVIEW_STAGE_ID;
export const GEOMETRY_REVIEW_STAGE: TimelineStageMeta;   // StageMeta với id kiểu TimelineStageId

// useObjectify.ts
export type GeometryStep = { state: StageState; phase: string | null; error: string | null; mode: ObjectifyMode | null };
export function geometryReviewStep(state: ObjectifyState | null): GeometryStep | null;  // null = không có hàng
```
`PipelineTimeline`: `StageView.stage_id`, `StageAction.stageId`, `stageList` dùng `TimelineStageId`. Hàng
`UI-GEOMETRY-REVIEW` **không** có link "Xem giai đoạn" (không có route inspect).

## Quy tắc trạng thái hàng "Duyệt vật & Tạo mesh"
`geometryReviewStep(state)`; chỉ khi `state.object_geometry` khác `null`. "Việc dựng" = `mode ∈ {geometry, region, membership}`.

| Điều kiện (ưu tiên từ trên) | `state` hàng | Phụ đề | Nút (chỉ khi `canAccept`) |
| --- | --- | --- | --- |
| việc dựng `queued`/`running` | `running` | `geometryPhaseLabel(phase)` hoặc "đang xếp hàng"; `cancellation_requested` → "Đang dừng…" | "Hủy yêu cầu" (ẩn khi đang dừng) |
| `object_geometry = awaiting_review` và lần dựng gần nhất `mode=geometry` `failed`/`cancelled` cùng revision | `failed` | `state.error` (vd. "Vỏ của Ghế không dựng được…") | "Mở để sửa vùng" · "Thử lại Tạo mesh" |
| `object_geometry = awaiting_review` | `waiting` | "Chỉnh vùng nếu cần, rồi Tạo mesh" | "Mở để duyệt" |
| `object_geometry = ready` và `mode ∈ {region, membership}` `failed`/`cancelled` | `succeeded` + ghi chú lỗi | "Dựng lại vùng thất bại; scene giữ bản trước. {error}" | "Mở Studio" |
| `object_geometry = ready` | `succeeded` | — | — |

- "Mở để duyệt"/"Mở để sửa vùng"/"Mở Studio" → tab Studio, mode `scene` (dùng `openTab` của `ScenePage`; thêm prop
  `onOpenStudio?: () => void` cho `ProgressTab`, undefined khi `!canMutateJob`).
- "Thử lại Tạo mesh" → `objectify.send("geometry", state.scene_revision)`.
- Job `geometry_review=auto`: Draft được xếp build ngay → hàng `running` rồi `succeeded`; không có trạng thái `waiting` dài.
- `objectifyStageOverride`: hàng "Tách vật thể" chỉ chuyển `running` khi việc đang chạy là `objectify`/`boxes`. Việc dựng
  (`geometry`/`region`/`membership`) hiện ở hàng mới, không làm hàng "Tách vật thể" quay về "đang chạy".

## Chuông (`NextAction`)
Thêm nhánh **trước** `awaitingChoice`/`pending`, dùng `useObjectify` (context sẵn có) + `detail.scene`:

| Điều kiện | Tiêu đề | Mô tả | Nút |
| --- | --- | --- | --- |
| việc dựng đang chạy | "Đang tạo mesh" (mode `geometry`) / "Đang dựng lại vùng" | nhãn phase | "Xem tiến trình" → tab progress |
| Draft + build `failed` | "Tạo mesh chưa xong" | `error` | "Mở để sửa vùng" → studio/scene |
| Draft | "Duyệt vật rồi Tạo mesh" | "{n} vật chờ xác nhận. Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio." (n=0 → bỏ vế đầu) | "Mở để duyệt" → studio/scene |

Nhánh Draft phải chặn các nhánh "Sẵn sàng tạo gói"/"Đã có gói" (Draft không đóng gói được). Ready: hành vi cũ không đổi.
Quy tắc `canMutateJob` hiện có (ẩn action tab studio) giữ nguyên.

## Trạng thái đầu trang (`progressSceneStatus`)
Thêm tham số `geometry: GeometryStep | null`. Khi `progress.status === "SUCCEEDED"`:
- `running` → `{ label: "Đang tạo mesh", tone: "ember", active: true, group: "running" }`
- `waiting` hoặc `failed` → `{ label: "Chờ duyệt vật", tone: "ochre", active: false, group: "action" }`
Thứ tự ưu tiên: sau `anonymization_review`, sau `awaitingObjectChoice`. Kiểm mọi nơi gọi `progressSceneStatus` (trang tổng quan
danh sách scene không có ObjectifyState → truyền `null`, giữ hành vi cũ; ghi rõ trong report).

## Chữ mô tả bước (stages.ts)
- `GEOMETRY_STAGE.title`: "Collision môi trường"; `short`: "Collision". Mô tả: "Quy đổi 3DGS và camera sang mét, dựng
  collision của cả không gian bằng voxel và khoét chỗ cho robot, kiểm lại tỉ lệ bằng đoạn C–D. Collider riêng của từng vật
  được tạo sau, ở bước Tạo mesh."
- `OBJECT_STAGE.description`: "Tách scene thành từng vật ứng viên (SAM2 phân đoạn, gán nhãn theo đóng góp render) kèm vỏ thô
  để bạn duyệt. Chưa vá nền và chưa có collider. Thử tối đa 3 lần; vẫn lỗi thì bạn chọn chạy lại hoặc dùng hộp ứng viên."
- `GEOMETRY_REVIEW_STAGE`: title "Duyệt vật & Tạo mesh", short "Tạo mesh", description "Bạn xác nhận vật, chỉnh vùng nếu cần,
  rồi bấm Tạo mesh: hệ thống dựng vỏ mịn, collider CoACD, vá nền và collision môi trường theo vật. Chưa xong bước này thì chưa
  Walk hay xuất USD được."
- Test đang khẳng định chữ cũ: sửa theo chữ mới, ghi từng chỗ trong report.

## Steps
1. Backend trường `object_geometry` + test (`ready`, `awaiting_review`, thiếu khoá → None, giá trị lạ → `awaiting_review`). Commit.
2. Frontend type + `geometryReviewStep` + sửa `objectifyStageOverride` + test bảng trạng thái (mỗi dòng một test). Commit.
3. `stages.ts` + `PipelineTimeline` nhận `TimelineStageId`, hàng ảo không có link; chữ mô tả mới. Test. Commit.
4. `ProgressTab` chèn hàng sau `ST-OBJECT-EXTRACT` (chỉ khi `geometryReviewStep` khác null), nút theo bảng; `ScenePage` truyền
   `onOpenStudio`. Test: Draft chờ, đang dựng (phase + Hủy), build lỗi, Ready, scene cũ (không có hàng), Guest không quyền (không nút). Commit.
5. `NextAction` nhánh Draft. Test: Draft có 3 ứng viên, Draft 0 ứng viên, đang tạo mesh, build lỗi, Draft không bao giờ ra
   "Sẵn sàng tạo gói", Ready giữ nguyên. Commit.
6. `progressSceneStatus` + nơi gọi. Test. Commit.

## Acceptance criteria
1. Scene Draft: tab Tiến trình có hàng "Duyệt vật & Tạo mesh" ở trạng thái chờ, ngay sau "Tách vật thể", có nút "Mở để duyệt".
2. Đang Tạo mesh: hàng `running` với nhãn phase tiếng Việt; hàng "Tách vật thể" vẫn `succeeded`.
3. Tạo mesh lỗi: hàng `failed` hiện lý do và hai nút; bấm "Thử lại Tạo mesh" gửi `mode=geometry` với revision hiện tại.
4. Ready: hàng `succeeded`. Scene thiếu khoá `object_geometry`: không có hàng, mọi thứ như trước.
5. Chuông trên Draft không bao giờ gợi ý tạo gói/duyệt/phát hành.
6. Đầu trang Draft hiện "Chờ duyệt vật"; đang dựng hiện "Đang tạo mesh".
7. Không có `StageId` mới trong `frontend/src/lib/contracts/` hay backend; `scripts/check_contract_mirror.py` PASS.
8. Người không có quyền sửa job thấy chữ nhưng không thấy nút sang Studio / Thử lại / Hủy.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
.venv/bin/python scripts/check_contract_mirror.py
cd frontend && ./node_modules/.bin/vitest run <các file test đã sửa/tạo> && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
```
Không chạy full suite (T-019 lo).

## Commit
Theo Steps, `git add` đúng path (cây đang có thay đổi chưa commit của T-019 — không stage chúng). Không Co-Authored-By.
`graphify update .`, `report.md`, `status.md` (chỉ dòng T-021).

## Out of scope
Thông báo theo người dùng (hộp thư, email, chuông trang tổng quan). Đổi job pipeline backend. Đổi banner Studio. Bundle video mẫu.
