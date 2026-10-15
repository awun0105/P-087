# Report T-023

## Done
- Bước 1 (service): `fit_region(registry, job_id, object_id, expected_revision)` trong `object_region.py`. Tính min/max
  của các hàng membership gán cho vật, trong khung nguồn (`source_transform`, cùng phép đổi `_local` với `resolve_region`).
  `center = (min+max)/2`, `half = (max−min)/2 + 1e-4`, kẹp [0.005, 20]. Không lưu gì; không đổi revision.
- Bước 2 (route): `GET /jobs/{id}/scene/objects/{id}/region/fit?expected_scene_revision=…` — 200 box; 409 revision lệch;
  404 vật không có trong membership (`ObjectRegionNotFoundError`); 422 vật < `MIN_OBJECT_ROWS` hoặc vật đã xoá/bỏ qua/gộp.
  Guard giống route preview (`require_contributor` + `authorize_job_mutation`).
- Bước 3 (frontend):
  - `fetchRegionFit` và kiểu `RegionFit` trong `studio.ts`.
  - `initialRegionSession(object, fit)` lấy box từ máy chủ; bỏ đường tạo box từ `primitive_dimensions_xyz_m`.
  - Component mới `RegionFitGate.tsx`: gọi fit đúng một lần mỗi lần mở; đang chờ chỉ có dòng trạng thái (không có panel,
    không có Apply); lỗi hiện thông báo của máy chủ và nút Thử lại; không tạo box khi lỗi.
  - `ObjectReviewView`: "Chỉnh vùng" mở qua cổng fit; nút không còn phụ thuộc kích thước (`disabled={busy}`).
  - `RegionEditor` nhận prop `fit`; "Đặt lại" trở về đúng box của máy chủ.

## Files changed
- `src/services/orchestration/scene/object_region.py`: `fit_region`, `ObjectRegionNotFoundError`.
- `tests/test_scene/test_object_region.py`: 4 test mới (GR-02 sau khi mở rộng một phía, Move và donor, lỗi 409/404/422, Draft = Ready).
- `src/api/product/scene.py`: route GET `…/region/fit`.
- `tests/test_api/test_scene_v2_routes.py`: test ánh xạ 409/422/404 của route.
- `tests/test_api/test_role_matrix.py`: thêm route fit vào nhóm AUTHENTICATED (cùng guard với preview).
- `frontend/src/lib/api/studio.ts`: `RegionFit`, `fetchRegionFit`.
- `frontend/src/features/studio/region/region-session.ts`: `initialRegionSession(object, fit)`.
- `frontend/src/features/studio/region/RegionFitGate.tsx` (mới): cổng lấy box ban đầu.
- `frontend/src/features/studio/region/RegionEditor.tsx`: prop `fit`, "Đặt lại" dùng fit.
- `frontend/src/features/studio/ObjectReviewView.tsx`: mở panel qua cổng fit; bỏ điều kiện dims trên nút.
- `frontend/tests/region-editor.test.tsx`: phiên dựa trên fit; 2 test cổng (chờ/gọi một lần, lỗi + Thử lại).
- `frontend/tests/object-review.test.tsx`: route fit mặc định; 3 test mới (một lần gọi fit, lỗi fit không tạo box,
  vật không có kích thước vẫn mở được); các test cũ chờ panel bằng `findByRole`.

## Tests
Backend (lệnh trong plan):
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_api/test_scene_v2_routes.py \
  tests/test_api/test_role_matrix.py -q -k 'not three_hundred_thousand'
→ 90 passed, 1 deselected
.venv/bin/ruff check src tests                → All checks passed!
.venv/bin/ruff format --check src tests       → 672 files already formatted
```
Frontend:
```
./node_modules/.bin/vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/region-box-model.test.ts
→ Test Files 3 passed, Tests 173 passed
npm run typecheck → Types generated successfully, tsc --noEmit không lỗi
eslint (5 file đã sửa + RegionFitGate.tsx) → không lỗi
```
Lỗi lint đã sửa trong quá trình làm: `setError(null)` đồng bộ trong effect (chuyển sang handler Thử lại).

## Deviations from plan
- **Tên và vị trí:** plan không liệt kê `RegionFitGate.tsx`; tách cổng thành component riêng để panel không có trạng thái
  nửa vời. Chữ ký `initialRegionSession(object, fit)` trả `RegionSession` (không còn `null`).
- **Acceptance 1 (GR-02 600 hàng):** fixture có sẵn `draft` (pose 90°, 400 hàng của vật đích). Ca "mở rộng một phía" được
  tái hiện bằng cách áp một box lệch rồi mở lại: `removed_count == 0`. Không dựng lại đúng fixture 600 hàng.
- **Acceptance 2:** "vật đã Move" kiểm bằng cách đổi `transform`, giữ `source_transform`; fit không đổi. "Donor đã bị claim"
  kiểm bằng `fit(OTHER).rows` khớp số hàng còn lại của nhãn donor sau khi claim.
- **Commit:** 3 commit theo bước của plan: `f2cd4c12` (service + test), `de3d00e7` (route + role matrix + test route),
  `016cc2ae` (frontend). Báo cáo và trạng thái nằm trong commit riêng sau đó.

## Known issues / TODO
- Chưa kiểm trên trình duyệt (thao tác box thật, hiển thị panel): theo quy ước dự án, phần đó do người dùng kiểm.
- Chưa chạy full suite (T-019 lo).
- Draft và Ready cho cùng box vì build không đổi membership hay `source_transform` (test `test_fit_is_identical_on_draft_and_ready`).
