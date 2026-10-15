# Report T-013

Trạng thái: **implemented**. Bước 1–7 đều xong. Bước 7 (preset) làm ở Round 2 sau khi T-009 accepted; chi tiết ở "Round 2".

## Done

- **Bước 1 — `be84b782`**: `frontend/src/lib/scene/geometry-state.ts`. `objectGeometryState(scene)`: thiếu khoá là `ready`, `ready` là `ready`, giá trị lạ là khoá (`awaiting_review`). `GEOMETRY_NOT_READY_REASON = "Cần tạo mesh trước"`. `geometryPhaseLabel(phase)` ánh xạ shell, quality, collider, objectgs, environment, publish sang nhãn tiếng Việt.
- **Bước 2 — `815cb30b`**: `buildObjectGeometry(jobId, expectedRevision)` gọi `POST scene/geometry/build` với `expected_scene_revision`. `ObjectifyMode` thêm `geometry` và `region`. Hook `useObjectify`: `send("geometry")` đi qua route build; `cancel` gửi `operation_id` của yêu cầu đang hiển thị (không có thì huỷ theo job như trước).
- **Bước 3 — `d81e4cb2`**: `GeometryReviewBanner` (vùng `Duyệt tách vật`). Nội dung: "Đang duyệt tách vật · N vật · chưa có collider" với N là số vật chưa DELETED/MERGED/IGNORED; cảnh báo từng vật có `shell_error`; nút **Tạo mesh** gửi revision đang hiển thị và bị khoá khi có việc objectify đang chạy.
- **Bước 4 — `f45e58b2`**: `ObjectifyNotice` có nhánh `geometry`: "Đang tạo mesh · {phase}", nút Hủy gửi `operation_id`; khi thất bại hoặc đã huỷ thì báo lỗi kèm Thử lại (gửi lại đúng revision). Nhánh `region`: báo tiến độ và lỗi, không có Thử lại vì vùng sửa ở Region Editor (T-016).
- **Bước 5 — `3b109c7a`**: khoá trong Draft:
  - Đi bộ: `MetricSceneView` không gọi walk-collision, và hiện nút "Đi bộ" disabled với `title` là lý do khoá.
  - Dịch/Xoay: hai nút disabled với `title` là lý do; `ObjectReviewView` không truyền gizmo khi bị khoá và tự đóng gizmo đang mở.
  - Xuất USD: `SimulationPackagePanel` nhận `lockedReason`, nút disabled với `title`; `ReviewTab` tính khoá từ scene đã tải.
- **Bước 6 — `b7ff375f`**: panel vật đã dựng hiện dòng `Collider: Vỏ Gaussian` hoặc `Collider: ObjectGS` theo `provenance.surface_selection.chosen`, kèm `surface_selection.reason` nếu có.
- **Bước 7 — `07ecbfcd`** (Round 2): 8 preset chuyển sang `scene.geometry_method = shell` và `scene.geometry_review = required`; schema khai báo choice `shell` và param `scene.geometry_review`. Chi tiết ở "Round 2".

## Files changed

- `frontend/src/lib/scene/geometry-state.ts` (mới): trạng thái hình học, lý do khoá, nhãn phase.
- `frontend/src/lib/api/studio.ts`: `ObjectifyMode` thêm `geometry`, `region`; `buildObjectGeometry`.
- `frontend/src/features/studio/scene/useObjectify.ts`: geometry qua route build; cancel theo `operation_id`.
- `frontend/src/features/studio/GeometryReviewBanner.tsx` (mới): banner Draft và nút Tạo mesh.
- `frontend/src/features/studio/ObjectifyNotice.tsx`: nhánh geometry và region.
- `frontend/src/features/studio/MetricSceneView.tsx`: prop `lockedReason`; nút Đi bộ khoá; không nạp lưới va chạm khi khoá; Dịch/Xoay disabled.
- `frontend/src/features/studio/ObjectReviewView.tsx`: lock state, chặn đặt công cụ, gizmo, banner overlay, `colliderSourceLine` và dòng Collider.
- `frontend/src/features/studio/SimulationPackagePanel.tsx`: prop `lockedReason`; nút tạo gói disabled với tooltip.
- `frontend/src/features/studio/scene/ReviewTab.tsx`: truyền khoá xuất USD.
- `frontend/tests/geometry-review-banner.test.tsx` (mới): 8 test (trạng thái, nhãn phase, banner).
- `frontend/tests/progress-objectify.test.tsx`: thêm 4 test cho thông báo geometry và region.
- `frontend/tests/object-review.test.tsx`: stub nhận `lockedReason`; thêm test (Draft khoá và banner, khoá USD, nguồn collider, khoá thêm vật).
- `frontend/tests/metric-effective-collision.test.tsx`: thêm test (Đi bộ khoá, Đi bộ không khoá ở ready, Dịch/Xoay khoá, nhân bản và bề mặt khoá).
- `configs/product/processing_presets_v1.json`: 8 preset có `shell` và `geometry_review = required`; param `scene.geometry_method` có choice `shell`; param mới `scene.geometry_review` (Round 2).
- `tests/test_orchestration/test_processing_config.py`: đổi tên test preset thành `test_every_preset_seals_shell_geometry_review_and_multiview` (Round 2).
- `.ai/tasks/T-013/report.md` (mới). `.ai/tasks/T-013/step7.patch` đã áp rồi xoá trong commit `07ecbfcd`. `.ai/status.md`: T-013 thành `implemented`.

## Tests

Round 1:

```
cd frontend
./node_modules/.bin/vitest run tests/geometry-review-banner.test.tsx tests/object-review.test.tsx tests/progress-objectify.test.tsx
→ 74 passed (8 + 49 + 17)
./node_modules/.bin/vitest run tests/metric-effective-collision.test.tsx tests/stage-view-selection.test.tsx
→ 14 passed (10 + 4)
./node_modules/.bin/vitest run tests/floor-fit-diagnostics.test.tsx tests/import-scene-page.test.tsx tests/stage-workspace.test.tsx tests/studio-ownership.test.tsx tests/ux-scene-flow.test.tsx (cùng nhóm trên)
→ 120 passed trên 9 file liên quan
npm run typecheck      → exit 0
./node_modules/.bin/eslint <14 file đã sửa>   → exit 0
```

Không chạy full suite. Round 2 có kết quả riêng ở mục Round 2.

## Deviations from plan

- **Bước 7 (preset) đã làm ở Round 2 (`07ecbfcd`)**. Trước đó bị chặn: đổi mọi preset sang `shell` và `geometry_review = required` làm mọi job mới vào Draft, nên cần T-009 accepted trước.
- **Nút Đi bộ khoá là control riêng**: viewer chỉ hiện nút Đi bộ khi `walkAllowed` đúng, nên trong Draft nút đó không tồn tại. Thêm nút "Đi bộ" disabled vào thanh điều khiển của `MetricSceneView` (chỉ hiện khi khoá) để có tooltip như plan.
- **Lớp "Collision mesh" trống trong Draft**: không gọi walk-collision khi khoá (server trả 409), nên lớp này không có dữ liệu. Trước đây lớp hiện thông báo lỗi 409.
- **Thao tác khác chưa khoá trên UI** (đã xử lý ở Round 2): thêm box, thêm asset thư viện, nhân bản và đánh dấu mặt collision.
- **`region` vào type trước**: plan bước 2 cho phép (`geometry`, `region` nếu chưa có); T-011 gửi mode này.
- **Test ngoài danh sách**: thêm test vào `metric-effective-collision.test.tsx` vì nút Đi bộ khoá nằm trong `MetricSceneView`. Test thuần và banner gom vào `geometry-review-banner.test.tsx` để lệnh "Tests required" phủ được.

## Known issues / TODO

- Phụ thuộc: T-013 "Cần" T-009. T-009 đã `accepted` trong `status.md` tại thời điểm áp bước 7, nên bước 7 đã làm.
- "N vật" của banner đếm mọi vật chưa DELETED/MERGED/IGNORED. Backend chỉ dựng vật có nhãn Gaussian, nên con số có thể lớn hơn số vật được dựng (ví dụ sàn không có Gaussian). Reviewer đã chấp nhận cách đếm ở review.md.
- Chưa kiểm bằng trình duyệt: vị trí banner trên viewport, nút Đi bộ khoá trên thanh điều khiển của viewer, và độ tương phản của cảnh báo vỏ lỗi. Theo quy ước, người dùng tự kiểm bằng mắt.
- `ObjectifyNotice` nhánh region không có nút thử lại; sẽ bổ sung khi T-016 nối Region Editor.

## Round 2 (review.md: "Làm thêm cùng bước 7")

**Trạng thái: `implemented`.** Phần 1 và bước 7 đều xong. Bước 7 từng bị giữ vì commit `14e08357` mở lại T-009; khi T-009 được accept, patch được áp và commit `07ecbfcd`.

### Phần 1: khoá UI trong Draft — xong

Các nút sau bị khoá, tooltip là `GEOMETRY_NOT_READY_REASON`, khi scene là Draft. Scene sẵn sàng giữ như cũ.

| Thao tác | Nút bị khoá | Commit |
| --- | --- | --- |
| Thêm vật cản hộp | "Thêm vật cản hộp", "Thêm", "Đặt bằng chuột" (`AddObstacleForm`) | `8dd88623` |
| Thêm vật từ thư viện | "Thêm từ thư viện", "Thêm", "Đặt bằng chuột" (`CatalogForm`) | `8dd88623` |
| Nhân bản | "Nhân bản" trên thanh thao tác vật (`MetricSceneView`) | `229533cf` |
| Đánh dấu, xoá, lấp bề mặt va chạm | "Đánh dấu sàn", "Đánh dấu tường", "Xóa mặt phẳng …", "Lấp theo mặt phẳng …" | `229533cf` |

Thêm:
- Khi khoá, công cụ đánh dấu bề mặt đang bật bị tắt, và click trên viewport không gửi lệnh. Commit `229533cf` có lỗi lint (`react-hooks/set-state-in-effect`), sửa ở `7b3b4965` bằng cách điều chỉnh state khi render.
- Khi khoá, chế độ đặt vật đang chờ bị huỷ (`70e21d99`), để một cú bấm trên viewport không gửi lệnh bị chặn.
- Các thao tác "chưa khoá trên UI" ở Round 1 nay đã được khoá.

Test:
- `tests/metric-effective-collision.test.tsx`: Draft → Nhân bản và các nút bề mặt disabled, có tooltip; scene sẵn sàng → enabled. 11 passed.
- `tests/object-review.test.tsx`: Draft → Thêm vật cản hộp và Thêm từ thư viện disabled, có tooltip; scene sẵn sàng → enabled. 50 passed.
- Chạy 5 file (`geometry-review-banner`, `object-review`, `progress-objectify`, `metric-effective-collision`, `stage-view-selection`): 90 passed. `npm run typecheck` exit 0. eslint các file đã sửa exit 0. `graphify update .` exit 0.

### Phần 2: bước 7 (preset) — xong

- Điều kiện: `status.md` ghi T-009 `accepted`. Patch `.ai/tasks/T-013/step7.patch` áp bằng `git apply` sau khi dry-run pass. `git apply --numstat`: `processing_presets_v1.json` 38/9, `test_processing_config.py` 9/4, khớp bản đã lưu.
- Thay đổi:
  - 8 preset: `scene.geometry_method = shell`, thêm `scene.geometry_review = required`, giữ `scene.refinement = multiview_v1`.
  - Param `scene.geometry_method`: thêm choice `shell` "Vỏ Gaussian (mặc định)"; mô tả mới.
  - Param mới `scene.geometry_review`: `required` "Dừng để duyệt tách vật", `auto` "Tạo mesh ngay".
  - Test đổi tên thành `test_every_preset_seals_shell_geometry_review_and_multiview`: khẳng định shell, required, multiview_v1; `SceneObjectifyConfig()` mặc định vẫn legacy.
- Test:
  - `tests/test_orchestration/test_processing_config.py`, `test_processing_presets_schema.py`, `tests/test_scene/test_objectify_config_override.py`, `tests/test_orchestration/test_scene_objectify_queue.py`, `test_preset_recommender.py`, `test_resource_admission.py`: **202 passed**.
  - API liên quan preset (`tests/test_api/test_studio_routes.py`, `test_guest_quota.py`, `test_error_view.py`, lọc `-k "preset or processing or option or geometry or objectify"`): 3 passed.
  - `ruff check` và `ruff format --check` sạch trên file test.
- Commit `07ecbfcd`: presets, test và xoá `.ai/tasks/T-013/step7.patch` trong cùng commit.
- Hệ quả hành vi: job tạo từ preset mới vào Draft và phải bấm "Tạo mesh" để có collider theo vật. Đây là mặc định mới theo plan bước 7.
- Không chạy full suite.
