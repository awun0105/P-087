# Report T-013

Trạng thái: **in-progress**. Bước 1–6 xong; bước 7 (preset) chưa làm, chờ T-009 accepted. Chi tiết ở "Deviations".

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
- `frontend/tests/object-review.test.tsx`: stub nhận `lockedReason`; thêm 3 test (Draft khoá và banner, khoá USD, nguồn collider).
- `frontend/tests/metric-effective-collision.test.tsx`: thêm 3 test (Đi bộ khoá, Đi bộ không khoá ở ready, Dịch/Xoay khoá).
- `.ai/tasks/T-013/report.md` (mới). `.ai/status.md` không đổi (vẫn in-progress).

## Tests

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

Không chạy full suite. Phần backend không đổi trong T-013 đến hiện tại.

## Deviations from plan

- **Bước 7 (preset) chưa làm, bị chặn**: đổi mọi preset sang `scene.geometry_method = shell` và `scene.geometry_review = required` làm mọi job mới vào Draft. Lúc đó "Tạo mesh" phải chạy được end-to-end. Hiện route `scene/geometry/build` đã có trong HEAD (`c32ed6ba`), nhưng worker `object_geometry_build.py` và `objectify.py` còn thay đổi chưa commit ở phiên T-009, và T-009 chưa accepted (roadmap ghi T-013 "Cần" T-009). Đề xuất: làm bước 7 sau khi T-009 accepted, rồi đặt T-013 implemented. Đây là quyết định đổi hành vi mặc định, cần người dùng xác nhận.
- **Nút Đi bộ khoá là control riêng**: viewer chỉ hiện nút Đi bộ khi `walkAllowed` đúng, nên trong Draft nút đó không tồn tại. Thêm nút "Đi bộ" disabled vào thanh điều khiển của `MetricSceneView` (chỉ hiện khi khoá) để có tooltip như plan.
- **Lớp "Collision mesh" trống trong Draft**: không gọi walk-collision khi khoá (server trả 409), nên lớp này không có dữ liệu. Trước đây lớp hiện thông báo lỗi 409.
- **Thao tác khác chưa khoá trên UI**: thêm box, thêm asset thư viện, nhân bản và đánh dấu mặt collision đã bị server chặn ở T-012 round 2, nhưng nút vẫn bật trên UI. Plan không yêu cầu khoá các nút này, nên giữ nguyên; cần quyết định khoá ở T-013 hay T-016.
- **`region` vào type trước**: plan bước 2 cho phép (`geometry`, `region` nếu chưa có); T-011 gửi mode này.
- **Test ngoài danh sách**: thêm test vào `metric-effective-collision.test.tsx` vì nút Đi bộ khoá nằm trong `MetricSceneView`. Test thuần và banner gom vào `geometry-review-banner.test.tsx` để lệnh "Tests required" phủ được.

## Known issues / TODO

- Phụ thuộc: T-013 "Cần" T-009, hiện T-009 `implemented`, chưa `accepted`. Bước 7 chờ T-009 accepted.
- "N vật" của banner đếm mọi vật chưa DELETED/MERGED/IGNORED. Backend chỉ dựng vật có nhãn Gaussian, nên con số có thể lớn hơn số vật được dựng (ví dụ sàn không có Gaussian). Cần reviewer xác nhận cách đếm.
- Chưa kiểm bằng trình duyệt: vị trí banner trên viewport, nút Đi bộ khoá trên thanh điều khiển của viewer, và độ tương phản của cảnh báo vỏ lỗi. Theo quy ước, người dùng tự kiểm bằng mắt.
- `ObjectifyNotice` nhánh region không có nút thử lại; sẽ bổ sung khi T-016 nối Region Editor.

## Round 2 (review.md: "Làm thêm cùng bước 7")

**Trạng thái: vẫn `in-progress`.** Phần 1 đã xong. Bước 7 (preset) chưa làm: commit `14e08357` đã đặt T-009 thành `changes-requested` (T-008 accepted, T-009 mở lại vì lỗi thứ tự config extraction). Chưa đặt implemented cho đến khi bước 7 xong.

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

### Phần 2: bước 7 (preset) — chưa làm

- Khi bắt đầu bước 7, `status.md` ghi T-009 `accepted`, nên tôi đã áp thay đổi: 8 preset chuyển sang `scene.geometry_method = shell` và `scene.geometry_review = required`; thêm choice `shell` và param `scene.geometry_review`; đổi tên test thành `test_every_preset_seals_shell_geometry_review_and_multiview`. Bốn file test liên quan: 109 passed.
- Sau đó `14e08357` mở lại T-009. Theo yêu cầu "chỉ làm khi T-009 accepted", tôi không commit bước 7, và khôi phục hai file về HEAD.
- Patch đã lưu: `/tmp/claude-1000/-home-lqaq-PROJECT-AI20K-P-087/7792b60f-c313-47d1-8e79-e36c243e36c0/scratchpad/t013-step7.patch` (149 dòng).

Việc còn lại khi T-009 `accepted`:
1. `git apply` patch trên.
2. Chạy `tests/test_orchestration/test_processing_config.py tests/test_orchestration/test_processing_presets_schema.py tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_scene_objectify_queue.py`, cộng `tests/test_orchestration/test_preset_recommender.py` và `tests/test_orchestration/test_resource_admission.py` vì hai file này cũng đọc preset.
3. Commit bước 7, rồi đặt T-013 implemented.
