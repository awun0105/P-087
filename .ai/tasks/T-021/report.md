# Report T-021

## Done
- **Bước 1 (backend):** `ObjectifyState.object_geometry` (`awaiting_review` | `ready` | null). Khoá thiếu → null; giá trị lạ →
  `awaiting_review`. Không đổi job pipeline, manifest hay receipt.
- **Bước 2 (quy tắc trạng thái):** `geometryReviewStep(state)` trong `useObjectify.ts`, bảng quy tắc của plan, mỗi dòng một
  test. `objectifyStageOverride`: việc dựng (`geometry`/`region`/`membership`) không còn làm hàng "Tách vật thể" chạy lại.
- **Bước 3 (stages, timeline):** hàng ảo `UI-GEOMETRY-REVIEW` (chỉ ở giao diện, không có trong contracts/StageId). Hàng này
  không có link, không chọn được, không có view inspect. Chữ mới cho "Collision môi trường", "Tách vật thể" và
  "Duyệt vật & Tạo mesh".
- **Bước 4 (tab Tiến trình):** hàng chèn sau "Tách vật thể" khi scene có khoá `object_geometry`. Phụ đề và nút theo bảng.
  `ScenePage` truyền `onOpenStudio` khi người dùng có quyền sửa.
- **Bước 5 (chuông):** nhánh Draft và nhánh "đang tạo mesh" đứng trước các nhánh cũ. Draft không bao giờ ra "Sẵn sàng tạo gói".
- **Bước 6 (đầu trang):** `progressSceneStatus(progress, awaitingChoice, geometry)`: "Chờ duyệt vật" (chờ/lỗi) và
  "Đang tạo mesh" (đang chạy), chỉ khi job đã SUCCEEDED.

## Files changed
- `src/services/orchestration/scene/objectify_queue.py`: trường `object_geometry`, hàm `_object_geometry`.
- `tests/test_orchestration/test_scene_objectify_queue.py`: test 4 trường hợp của khoá.
- `tests/test_api/test_scene_v2_routes.py`: route trả `object_geometry: null` cho scene cũ.
- `frontend/src/lib/api/studio.ts`: `ObjectifyState.object_geometry`; `RegionPreview` không đổi ở task này.
- `frontend/src/features/studio/scene/useObjectify.ts`: `geometryReviewStep`, `GeometryStep`; `objectifyStageOverride` thu hẹp.
- `frontend/src/features/studio/stages.ts`: `GEOMETRY_REVIEW_STAGE_ID`, `TimelineStageId`, `TimelineStageMeta`,
  `GEOMETRY_REVIEW_STAGE`; chữ mô tả của `GEOMETRY_STAGE` và `OBJECT_STAGE`.
- `frontend/src/features/studio/PipelineTimeline.tsx`: `TimelineStageView` (có `note`), `StageAction.stageId` mở rộng; hàng ảo
  không có link và không chọn được.
- `frontend/src/features/studio/scene/estimation.ts`: nhận `TimelineStageView[]`.
- `frontend/src/features/studio/scene/ProgressTab.tsx`: hàng ảo, phụ đề, nút, `onOpenStudio`.
- `frontend/src/features/studio/ScenePage.tsx`: truyền `onOpenStudio`; truyền `geometry` cho `progressSceneStatus`.
- `frontend/src/features/studio/scene/NextAction.tsx`: nhánh chuông Draft và đang dựng.
- `frontend/src/features/studio/sceneStatus.ts`: `progressSceneStatus` có tham số `geometry`.
- Test mới: `frontend/tests/geometry-review-step.test.tsx`, `frontend/tests/geometry-review-row.test.tsx`,
  `frontend/tests/geometry-review-bell.test.tsx`.
- Test sửa chữ cũ: `frontend/tests/studio-inspection.test.tsx`, `frontend/tests/studio-sample-pipeline.test.tsx`
  ("Hình học & collision" → "Collision môi trường").

## Commits
- `cd534f60` Expose object_geometry on the objectify state (bước 1)
- `5177a52f` Derive the Draft review row state from the objectify state (bước 2)
- `3d672ab8` Add the Duyệt vật & Tạo mesh row and clarify the geometry step texts (bước 3)
- `8dac5580` Show the Draft review row on the progress tab (bước 4)
- `e41350f5` Make the bell describe Draft and geometry work (bước 5)
- `c899aeb7` Show Chờ duyệt vật or Đang tạo mesh in the scene header (bước 6)
- Báo cáo và trạng thái: commit riêng ở cuối task.

## Tests
```
.venv/bin/python -m pytest tests/test_orchestration/test_scene_objectify_queue.py tests/test_api/test_scene_v2_routes.py -q
→ 105 passed
.venv/bin/ruff check src tests            → All checks passed!
.venv/bin/ruff format --check src tests   → 672 files already formatted
.venv/bin/python scripts/check_contract_mirror.py → PASS — 5 enum, 8 model khớp Pydantic
git diff cd534f60~1 HEAD -- frontend/src/lib/contracts src/models → không có thay đổi

cd frontend && ./node_modules/.bin/vitest run <10 file liên quan: progress-objectify, geometry-review-row, geometry-review-bell,
  geometry-review-step, ux-scene-flow, anonymization-review, studio-resource-wait, studio-navigation, studio-inspection, studio-sample-pipeline>
→ Test Files 10 passed, Tests 112 passed
npm run typecheck → không lỗi
eslint (các file đã sửa) → không lỗi
```

## Deviations from plan
- **Kiểu của `StageView`:** plan đề xuất đổi `StageView.stage_id` thành `TimelineStageId`. Chọn tách thêm `TimelineStageView`
  (`stage_id: TimelineStageId`) để `SampleFlow` và phần còn lại vẫn dùng `StageView` với `StageId`. Hàm
  `estimateRemainingTime` (không có trong plan) đổi sang nhận `TimelineStageView[]`.
- **Phụ đề hàng:** plan không nói cách hiển thị phụ đề. Thêm trường `note` vào `TimelineStageView`, render dưới tên bước.
- **Nút hành động trên hàng đã xong:** `PipelineTimeline` ẩn nút của hàng `succeeded`. Thêm ngoại lệ cho hàng ảo, vì
  "Mở Studio" sau dựng lại vùng lỗi cần hiện trên hàng đã xong.
- **Nhánh chuông "đang dựng":** đặt ở đầu chuỗi, áp dụng cho mọi scene khi đang có việc dựng, không chỉ Draft. Đúng với dòng
  đầu của bảng trong plan.
- **Import kiểu:** `sceneStatus.ts` nhập kiểu `GeometryStep` từ `useObjectify.ts` (chỉ kiểu, không import runtime).
- **Test mới ngoài danh sách plan:** `geometry-review-bell.test.tsx` (plan chỉ nêu "NextAction" và file đang có); test
  bảng trạng thái header nằm trong `geometry-review-step.test.tsx`.
- **Test "Guest không quyền" (bước 4):** dùng `canAccept={false}` để mô phỏng người không có quyền sửa job; không có
  fixture tài khoản Guest riêng trong file này.

## Known issues / TODO
- Chưa kiểm trên trình duyệt (hàng, chuông, đầu trang): theo quy ước, người dùng kiểm.
- Khi hàng ảo đang chạy, ước lượng thời gian còn lại (ETA) có thể không hiện số vì hàng ảo không có thời gian đo được.
  Chưa kiểm và chưa có test cho ETA.
- Chưa chạy full suite (T-019 lo).
