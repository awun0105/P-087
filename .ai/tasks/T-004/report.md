# Report T-004

## Done

Làm theo 6 step của plan. Mỗi step là một commit, theo TDD: viết test trước, thấy đỏ đúng lý do, rồi mới sửa code.

- **Step 1** (`cfe5cd38`): `RegionBox` và `ObjectRegionCommand` trong `object_membership.py`. Nửa kích thước khoảng đóng [0,005; 20] m, yaw trong [−2π, 2π], tối đa 16 box, bắt buộc có ít nhất một box `add`, `claim_from` không trùng.
- **Step 2** (`6fa549ec`): `boxes_contain` trong `src/services/scene/editing/region_box.py`. Quy tắc `inside = ∪add \ ∪subtract`, dung sai 1e-6 cho điểm trên mặt, điểm NaN hoặc vô hạn luôn ở ngoài.
- **Step 3** (`debc16db`): `resolve_region` và `RegionResolution`. Đổi toạ độ bằng `R^T(p − t)` với pose nguồn; `rotation_matrix` dùng lại từ `reconstruction/alignment/similarity.py`. Hàng mới = `inside ∩ eligible`, với `eligible = nền không thuộc sàn ∪ hàng của vật ∪ hàng của vật trong claim_from`. Vật còn dưới 50 hàng bị từ chối với thông điệp gợi ý "Xoá vật".
- **Step 4** (`21c707ff`): `apply_resolution` (hàng thêm nhận nhãn nhỏ nhất của vật, hàng bớt nhận −1, không sửa mảng đầu vào) và `preview_payload` (thống kê và mẫu toạ độ, mẫu lấy đều theo chỉ số nên lặp lại được).
- **Step 5** (`832d6d24`): `api.ts` có `RegionBox` và `ObjectRegionCommand`. `box-model.ts` bỏ khai báo cục bộ và import `RegionBox` từ `api.ts`. `check_contract_mirror.py` kiểm hai model mới.
- **Step 6** (`a26c851b`): `tests/fixtures/region_box_cases.json` gồm 16 ca. Pytest và vitest cùng đọc file này và cho cùng kết quả.

Tiêu chí chấp nhận 0–12: mỗi tiêu chí có một test `test_criterion_N_…` trong `tests/test_scene/test_region_box.py`. Dữ liệu tổng hợp gồm sàn z = 0, vật a và b cạnh nhau, dải nền giữa hai vật và nền rải rác xa. Các tập hàng kỳ vọng được tính bằng công thức trục-song-song độc lập, không gọi lại hàm đang kiểm.

## Files changed

- `src/models/contracts/object_membership.py`: thêm `RegionBox`, `ObjectRegionCommand`, `HalfExtentM`.
- `src/services/scene/editing/region_box.py` (mới): `boxes_contain`, `RegionResolution`, `resolve_region`, `apply_resolution`, `preview_payload`.
- `frontend/src/lib/contracts/api.ts`: interface `RegionBox`, `ObjectRegionCommand`.
- `frontend/src/features/studio/region/box-model.ts`: bỏ `RegionBox` cục bộ, import từ `api.ts`.
- `scripts/check_contract_mirror.py`: thêm hai model vào `MODEL_MIRRORS`.
- `tests/test_contracts/test_object_region_command.py` (mới): kiểm contract (ngưỡng kích thước, số box, NaN, yaw, claim trùng, trường thừa).
- `tests/test_scene/test_region_box.py` (mới): tiêu chí 0–12 và test đọc ca chung.
- `tests/fixtures/region_box_cases.json` (mới): 16 ca.
- `frontend/tests/region-box-model.test.ts`: thêm test đọc cùng file ca chung.
- `.ai/tasks/T-004/report.md`, `.ai/status.md` (chỉ dòng T-004).

## Tests

- `.venv/bin/python -m pytest tests/test_scene/test_region_box.py tests/test_contracts -q`: **299 passed**. Thời gian của test hiệu năng: 0,07 s, ngưỡng 0,3 s.
- `.venv/bin/python scripts/check_contract_mirror.py`: **PASS**, 8 model.
- `ruff check` và `ruff format --check` trên 5 file Python đã sửa hoặc tạo: **passed**.
- `cd frontend && npm run typecheck`: **exit 0**. Ở một lần chạy giữa chừng, lỗi nằm ở `tests/region-overlay.test.ts`, file chưa commit của agent khác. File này sau đó được commit (`03cee461`) và typecheck qua.
- `eslint` trên `box-model.ts`, `api.ts`, `region-box-model.test.ts`: **exit 0**.
- `vitest run tests/region-box-model.test.ts`: **55 passed** (38 cũ, 17 mới).
- `graphify update .` đã chạy sau khi sửa code.

## Deviations from plan

1. **Tiêu chí 8 (pose nguồn):** hàm chỉ nhận `source_world_from_object`, không có pose hiện tại. Test khẳng định kết quả theo pose nguồn, và truyền pose sai thì báo lỗi số hàng. Việc truyền đúng pose nguồn thuộc caller (T-009).
2. **Tiêu chí 10 (checksum và revision):** `resolve_region` không kiểm `membership_checksum` và `expected_scene_revision`, đúng như plan giao cho caller T-009. Test chỉ kiểm manifest khớp số hàng và object có tồn tại.
3. **Tiêu chí 12 (hiệu năng):** repo không có marker `slow`, nên dùng 300 000 hàng và ngưỡng 0,3 s theo phương án dự phòng của plan.
4. **Test contract ở file mới** `tests/test_contracts/test_object_region_command.py`. Plan ghi "Sửa tests/test_contracts/…", nhưng chưa có file membership phù hợp trong thư mục đó.
5. **`scripts/check_contract_mirror.py` có thêm hai model** `RegionBox` và `ObjectRegionCommand`. Plan không liệt kê file này trong Files. Thêm để script thật sự kiểm mirror mới, không chỉ chạy cho có.
6. **Quyết định mới:** `resolve_region` từ chối khi `object_id` nằm trong `claim_from`, và từ chối id lạ trong `claim_from`. Plan không nói rõ. Dễ đảo nếu Architect muốn khác.
7. **Định nghĩa `protected_floor_count`:** số hàng nền thuộc sàn nằm trong box mà không được lấy. `claimed` và `overlaps` chỉ có khoá với số lớn hơn 0.
8. **TypeScript:** `yaw_rad` và `claim_from` khai là bắt buộc, trong khi Python có giá trị mặc định. Frontend luôn gửi đủ hai trường này.
9. **`BACKGROUND_LABEL`** được khai báo lại trong `region_box.py`, vì `_BACKGROUND_LABEL` của `membership.py` là tên private.
10. **Cảnh báo số học của numpy** bị tắt cục bộ trong `_box_contains`. Điểm vô hạn gây `inf × 0 = NaN`, và kết quả đúng là "ngoài box".

## Known issues / TODO

- Chưa làm, nằm ngoài phạm vi T-004: route API và preview (T-009), vỏ thô `shell_glb_base64` (T-009), kiểm `membership_checksum` và `expected_scene_revision` (T-009), tính `floor_protected` (caller).
- `apply_resolution` không kiểm dtype và độ dài của `labels`. Caller (T-009) phải truyền mảng đã đi qua `decode_gaussian_membership_labels`.
- Ngưỡng hiệu năng 0,3 s trên CPU có thể nhạy với máy chậm. Nếu flaky trên CI, nới ngưỡng.
- `RegionBox` và `ObjectRegionCommand` trong `api.ts` chỉ được kiểm tên trường bởi mirror script, không kiểm kiểu. Kiểu được kiểm bởi typecheck ở các chỗ dùng.
