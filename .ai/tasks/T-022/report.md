# Report T-022

## Done
- Step 1: `_build_environment` trả `(environment, inpainted_gaussians)`; số đếm lấy từ kết quả `run_inpaint_and_package`
  (`inpaint_result["inpainted_gaussians"]`). Sai kiểu (bool, str, số âm, float) → `ObjectGeometryBuildError` trước khi publish.
- Step 2: `build_object_geometry` ghi `provenance["inpainted_gaussians"]` ở revision mới cho cả build toàn bộ và dựng lại một
  phần, luôn ghi đè (kể cả từ dương về 0). Validator không đổi.
- Step 3: scene có `membership_correction.operation == "reassign"` và build không có override → cập nhật
  `inpainted_gaussians` ngay trong correction đó (giữ nguyên các trường audit). Với override, `membership_correction` vẫn
  bị thay bằng `{evidence_ref}` như cũ, nên validator đọc số ở provenance scene.
- Tests (acceptance 1–4 của plan):
  - Full build với inpaint thêm 3 hàng: số hàng background = số hàng nền + 3, `representation_issues == []`.
  - Partial rebuild (region/override trên Ready) với count 3 → 0 → 5: count trong scene theo đúng từng lần, `representation_issues == []`.
  - Reassign correction cũ (count 0) → sau build count 3 trong correction, validator PASS.
  - Đặt count sai trong provenance → vẫn `SOURCE_BACKGROUND_INVALID`.
  - Inpaint trả count sai kiểu (True, "3", -1, 2.0) → lỗi, scene head không đổi.
  - E2E có CoACD thật: Draft → build (inpaint +3) → Confirm candidate-001, giữ candidate-002 → `representation_issues == []`
    → `build_simulation_package` PASS, `confirmed_objects == 1`.

## Files changed
- `src/services/orchestration/scene/object_geometry_build.py`: trả count từ `_build_environment`; kiểm kiểu; ghi provenance; cập nhật correction reassign.
- `tests/test_scene/test_object_geometry_build.py`: helper `install_background_fill`, helper `_shrink_override` (tách từ `_ready_override`, hành vi giữ nguyên), 7 test mới, sửa một call site unpack tuple.
- `tests/test_scene/test_shell_geometry_walk_usd.py`: import helper, 1 test e2e (skip nếu thiếu runtime như các test khác).
- `.ai/status.md`: T-022 → in-progress → implemented.
- `.ai/tasks/T-022/report.md`: file này.

## Tests
Lệnh trong plan (trước thay đổi: 82 passed, 1 deselected):
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_object_region.py \
  tests/test_scene/test_shell_geometry_walk_usd.py tests/test_scene/test_membership_regeneration.py -q -k 'not three_hundred_thousand'
→ 91 passed, 1 deselected (148 s)
.venv/bin/ruff check src tests  → (chạy trên 3 file đã sửa) All checks passed!
.venv/bin/ruff format --check   → 3 files already formatted
```
Thêm:
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_object_geometry_steps.py \
  tests/test_simulation/test_representation_conservation.py -q → 50 passed
```
Kiểm tra test bắt được lỗi: đưa tạm `object_geometry_build.py` của HEAD vào, chạy các test mới → 8 FAIL
(full, partial, reassign, 4 case count sai kiểu, e2e); test "tampered count" PASS như kỳ vọng (validator không đổi).
Đã khôi phục bản sửa, xác nhận bằng `cmp`.

Không chạy full suite (README mục 4).

## Deviations from plan
- **Phụ thuộc chưa thoả:** `roadmap.md` ghi T-022 cần T-019 `accepted`, nhưng `status.md` ghi T-019 là `changes-requested`.
  Làm theo yêu cầu trực tiếp của người dùng; cần Architect xác nhận.
- **Commit:** plan đề xuất (a) count + provenance + test 1, (b) partial + test 2, 3. Thực tế: commit 1
  `22181667` gồm source + toàn bộ test trong `test_object_geometry_build.py` (cả partial/reassign/tamper/invalid vì cùng file, không
  stage từng hunk được); commit 2 `9e903dbe` là test e2e trong `test_shell_geometry_walk_usd.py`.
- **Step 3:** chọn "cập nhật count trong correction reassign" thay vì ghi đè bằng bản không có `operation`, để giữ audit.
- **Helper test:** `_ready_override` không đổi hành vi; phần cuối được tách thành `_shrink_override` để test partial
  build trên scene đã build đầy đủ. Lý do: `_ready_override` relabel hàng giữa hai vật bằng một full build không đi qua
  nhánh override nên không dựng lại visual, gây `SOURCE_VISUAL_INVALID` không liên quan GR-01. Helper cũng bỏ qua publish
  lại artifact bất biến đã tồn tại (cùng nội dung).

## Known issues / TODO
- Chưa chạy full suite; chưa kiểm GPU ObjectGS hay Isaac thật (ngoài phạm vi task).
- Đường legacy `objectify.py:1055` và `object_correction.py` vẫn ghi `inpainted_gaussians` như cũ; không đụng vì ngoài plan.
- Không có câu hỏi thiết kế mở.
