# T-024: Ba lỗi chỉ dẫn của chỉnh vùng và banner (GR-03, GR-04, GR-06, P2)

## Goal
Người dùng thấy lỗi **trước** khi bấm, không phải sau.

## GR-03 — Banner phải nêu mọi vật làm Tạo mesh lỗi
`GeometryReviewBanner.tsx:18-19` bỏ IGNORED/DELETED/MERGED trước khi tính `shellErrors`, nhưng builder dựng collider cho mọi
vật trong membership (quyết định T-007) và từ chối vật có `shell_error`. Sửa: `shellErrors` tính trên mọi vật có nhãn trong
membership. Vật đã loại hiện: "Vỏ của {tên} (đã loại) chưa dựng được — Khôi phục, sửa vùng, rồi Tạo mesh". Không bỏ vật khỏi build.

## GR-04 — Preview báo vật bị lấy bớt sẽ còn dưới 50 hàng
`preview_region` (`object_region.py:108`) không gọi `_require_remaining_rows` cho donor; Apply mới từ chối. Sửa: preview trả
thêm `donor_remaining: {object_id: rows}` và `blockers: [{object_id, remaining, minimum}]` (không raise). Panel: dòng "Lấy luôn"
của donor vi phạm hiện "{tên} sẽ chỉ còn {n} Gaussian (tối thiểu 50)"; nút Apply disabled kèm lý do. Kiểm cả vật đang sửa
(target) theo cùng cách nếu hiện đang raise 422 ở preview — giữ hành vi hiện có cho target, chỉ thêm donor.

## GR-06 — Lỗi 409 ở preview có nút Tải lại như Apply
`useRegionPreview.ts:62-65` chỉ giữ chuỗi lỗi. Sửa: giữ `status` (`ApiError.status`); `RegionEditor` hiện nút "Tải lại" khi
preview hoặc Apply trả 409, giữ boxes/claims; sau tải lại chỉ bật Apply khi có preview khớp revision/checksum mới.

## Files
`frontend/src/features/studio/GeometryReviewBanner.tsx`, `src/services/orchestration/scene/object_region.py`,
`src/services/scene/editing/region_box.py` (nếu cần đếm donor), `frontend/src/lib/api/studio.ts` (`RegionPreview`),
`frontend/src/features/studio/region/useRegionPreview.ts`, `RegionEditor.tsx`; test tương ứng.

## Acceptance criteria
1. Ignore A (có `shell_error`), giữ B → banner nêu A với hướng khắc phục (test banner + test service dùng chung dữ liệu ca).
2. Donor còn 49 → Apply disabled, nêu tên và số; còn 50 → cho phép; Draft và Ready cùng quy tắc.
3. Preview 409 → nút Tải lại, boxes/claims còn nguyên; tải lại + preview thành công → Apply bật.
4. Không đổi bộ đếm `added/removed/claimed/overlaps` hiện có.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_api/test_scene_v2_routes.py -q -k 'not three_hundred_thousand'
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
cd frontend && ./node_modules/.bin/vitest run tests/region-editor.test.tsx tests/object-review.test.tsx <file test banner> && npm run typecheck
```

## Commit
Một commit cho mỗi GR. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
