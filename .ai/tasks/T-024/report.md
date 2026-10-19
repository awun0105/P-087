# Report T-024

## Done
- **GR-03 (banner):** `GeometryReviewBanner` tính `shellErrors` trên mọi vật có nhãn trong membership, kể cả vật đã
  Ignore/Delete/Merge (builder vẫn dựng vỏ cho các vật này). Vật đã loại hiện "Vỏ của {tên} (đã loại) chưa dựng được —
  Khôi phục, sửa vùng, rồi Tạo mesh". Không bỏ vật khỏi build.
- **GR-04 (donor):** `preview_region` trả thêm `donor_remaining` và `blockers` (không raise cho donor). Apply vẫn từ chối
  đúng điều kiện này. Panel nêu "{tên} sẽ chỉ còn {n} Gaussian (tối thiểu 50)" trên dòng "Lấy luôn" và khoá Apply kèm lý do
  (`title` và dòng nêu tên). Target giữ hành vi cũ (422).
- **GR-06 (409 preview):** `useRegionPreview` giữ `errorStatus`. 409 ở preview hiện nút Tải lại như Apply; box và claim giữ
  nguyên. Apply chỉ bật lại khi có preview khớp revision/checksum mới. Thêm: dòng "Lấy luôn" vẫn hiện khi chưa có kết quả
  preview (trước đó bị mất khi 409 hoặc đang tính).

## Files changed
- `src/services/orchestration/scene/object_region.py`: `_donor_status`; `preview_region` trả `donor_remaining`, `blockers`.
- `tests/test_scene/test_object_region.py`: test donor 49 → blocker, Apply refuse; 50 → cho phép.
- `tests/test_scene/test_object_geometry_build.py`: test vật đã loại có lỗi vỏ chặn build và được nêu (3 trường hợp).
- `frontend/src/features/studio/GeometryReviewBanner.tsx`: shell error theo membership; cụm từ cho vật đã loại.
- `frontend/src/features/studio/region/RegionEditor.tsx`: dòng donor bị chặn; khoá Apply; 409 preview; dòng "chưa có kết quả".
- `frontend/src/features/studio/region/useRegionPreview.ts`: `errorStatus`.
- `frontend/src/lib/api/studio.ts`: `RegionPreview.donor_remaining`, `blockers`.
- `frontend/tests/geometry-review-banner.test.tsx`: vật đã loại được nêu; vật không còn trong membership không được nêu.
- `frontend/tests/region-editor.test.tsx`: donor 49/50; 409 preview → Tải lại → Apply bật.

## Commits
- `e4e86134` Name shell errors of archived members in the review banner (GR-03)
- `4fb1115d` Show donors left under the minimum before Apply (GR-04)
- `784bbadf` Offer reload when preview returns 409, keeping boxes and claims (GR-06)
- Báo cáo và trạng thái: commit riêng ở cuối task.

## Tests
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_api/test_scene_v2_routes.py -q -k 'not three_hundred_thousand'
→ 85 passed, 1 deselected
.venv/bin/ruff check src tests            → All checks passed!
.venv/bin/ruff format --check src tests   → 672 files already formatted

cd frontend && ./node_modules/.bin/vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/geometry-review-banner.test.tsx
→ Test Files 3 passed, Tests 131 passed
npm run typecheck → không lỗi
eslint (các file đã sửa) → không lỗi
```
Test mới bị đỏ trên mã cũ: banner (vật đã loại không được nêu), donor (không có `blockers`), 409 (không có nút Tải lại).

## Deviations from plan
- **Acceptance 2, Draft và Ready:** quy tắc server giống nhau (`_require_remaining_rows` ở cả Apply Draft và rebuild Ready),
  nhưng không có test riêng cho nhánh Ready của donor. Chỉ kiểm nhánh Draft.
- **Acceptance 1, test service:** thêm test trong `test_object_geometry_build.py` (build bị chặn đúng vật đã loại), vì plan
  ghi "test service dùng chung dữ liệu ca".
- **Mở rộng ngoài plan (GR-06):** hiện dòng "Lấy luôn" khi chưa có preview (`kind: "unknown"`). Không có yêu cầu này trong
  plan nhưng cần để "giữ claim" thật sự thấy được sau 409.

## Known issues / TODO
- Chưa kiểm trên trình duyệt (banner, panel): theo quy ước, người dùng kiểm.
- Chưa chạy full suite (T-019 lo).
- Nhánh Ready của quy tắc donor chưa có test riêng (xem Deviations).
