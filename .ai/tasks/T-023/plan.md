# T-023: Box ban đầu khớp nhóm Gaussian hiện tại của vật (GR-02, P1)

## Goal
Mở "Chỉnh vùng" lần sau phải ra box **bao đúng các Gaussian hiện có của vật**, không phải box tâm 0 suy từ kích thước. Hiện
`initialRegionSession` (`region-session.ts:31`) đặt `center=[0,0,0]`, `half=dims/2`; sau khi chỉnh lệch một phía, tâm nhóm
không còn ở 0 (khung nguồn bất biến theo §7.1), nên preview mặc định loại 121/600 hàng và Apply ngay sẽ trả chúng về nền.

## Quyết định thiết kế
Máy chủ tính box khớp **theo yêu cầu** từ membership hiện tại, không lưu thêm vào provenance. Lý do: membership đổi qua nhiều
đường (Draft apply, Ready rebuild, Brush/Lasso, vật bị claim mất hàng); tính khi mở panel luôn đúng, không phải giữ đồng bộ.
**Không** căn lại `source_transform`.

## Interfaces
```
GET /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/fit?expected_scene_revision=…
200 {"scene_revision", "membership_checksum", "center_m": [x,y,z], "half_extents_m": [x,y,z], "yaw_rad": 0.0, "rows": n}
409 revision lệch; 404 vật không có trong membership; 422 vật < MIN_OBJECT_ROWS hàng.
```
- Tính trong khung object-local nguồn (`provenance.source_transform`, cùng phép đổi với `resolve_region`): `min/max` của hàng
  thuộc vật; `center=(min+max)/2`; `half=(max−min)/2 + 1e-4` m, kẹp vào [0.005, 20].
- Quyền: như route preview (đọc được scene). Dùng cache nguồn của preview (`load_membership_source`).
- Frontend: `fetchRegionFit(jobId, objectId, revision, signal)`; `initialRegionSession(object, fit)` dùng fit. Panel mở ở trạng
  thái "Đang lấy vùng hiện tại…" tới khi fit về; lỗi → hiện lỗi + nút Thử lại, **không** tạo box mặc định từ kích thước.

## Files
- Sửa: `src/services/orchestration/scene/object_region.py` (hàm `fit_region`), `src/api/product/scene.py` (route),
  `frontend/src/lib/api/studio.ts`, `frontend/src/features/studio/region/region-session.ts`, `ObjectReviewView.tsx` (mở phiên),
  `RegionEditor.tsx` (trạng thái chờ/lỗi)
- Test: `tests/test_scene/test_object_region.py`, `tests/test_api/test_scene_v2_routes.py`, `tests/test_api/test_role_matrix.py`,
  `frontend/tests/region-editor.test.tsx`, `frontend/tests/object-review.test.tsx`

## Acceptance criteria
1. Ca của GR-02 (pose nguồn quay 90°, mở rộng một phía, 600 hàng): fit → preview với box đó cho `removed_count == 0`.
   `added_count` được phép > 0 nhưng phải hiện trên panel (hàng nền trong dải 0,1 mm).
2. Cùng ca trên Draft và Ready; vật donor đã bị claim; vật có `transform` khác `source_transform` (đã Move) — fit không đổi theo Move.
3. 409 khi revision lệch; 422 khi vật dưới 50 hàng.
4. Frontend: mở panel gọi fit đúng một lần cho mỗi lần mở; đang chờ không cho Apply; lỗi không tạo box.
5. Không còn đường tạo box ban đầu từ `primitive_dimensions_xyz_m` cho scene có membership.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_api/test_scene_v2_routes.py \
  tests/test_api/test_role_matrix.py -q -k 'not three_hundred_thousand'
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
cd frontend && ./node_modules/.bin/vitest run tests/region-editor.test.tsx tests/object-review.test.tsx tests/region-box-model.test.ts \
  && npm run typecheck
```

## Commit
(a) service + test 1–3; (b) route + role matrix; (c) frontend + test 4–5. Đúng path. Không Co-Authored-By.
`graphify update .`, `report.md`, `status.md`.

## Out of scope
Lưu lại box của lần Apply trước; box có yaw ≠ 0 (fit trục theo khung nguồn).
