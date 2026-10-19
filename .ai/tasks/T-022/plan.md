# T-022: Giữ số Gaussian vá nền khi Tạo mesh (GR-01, P1)

## Goal
Tạo mesh và dựng lại một phần phải ghi đúng `inpainted_gaussians` của lần vá nền **mới** vào cùng revision với
`environment.visual_master_ref`. Hiện builder bỏ số đếm (`object_geometry_build.py:545`: `master, visual, _ = run_inpaint_and_package(...)`),
nên `representation_integrity` (dòng 52–73) đọc 0 → `SOURCE_BACKGROUND_INVALID` → preflight FAIL, không tạo được gói, trên mọi
scene thật có vá nền > 0 và còn vật cần SOURCE (ứng viên chưa Confirm, vật Ignore).

## Context
- Phát hiện và probe: `.ai/tasks/T-019/review.md` §GR-01, `evidence/inpaint-valid-probe.txt`.
- Đường cũ đúng: `objectify.py:859, 1055` lấy `inpaint["inpainted_gaussians"]`; `object_correction.py:567, 780` cũng vậy.
- Validator chọn `membership_correction` khi `operation == "reassign"`, ngược lại đọc provenance scene. Builder hiện thay
  `membership_correction` bằng `{evidence_ref}` (không có `operation`) khi có override → validator đọc provenance scene.

## Files
- Sửa: `src/services/orchestration/scene/object_geometry_build.py` (`_build_environment` trả thêm số đếm; ghi provenance)
- Test: `tests/test_scene/test_object_geometry_build.py`, `tests/test_scene/test_shell_geometry_walk_usd.py` (hoặc file của T-019)

## Steps
1. `_build_environment` trả `(environment, inpainted_gaussians: int)` lấy từ kết quả `run_inpaint_and_package`
   (kiểu int ≥ 0, không phải bool; sai kiểu → `ObjectGeometryBuildError`).
2. Provenance revision mới: `"inpainted_gaussians": <số mới>` ở **cả** build toàn bộ và dựng lại một phần; luôn ghi đè,
   kể cả từ dương về 0. Không đổi validator.
3. Nếu `membership_correction` cũ có `operation == "reassign"` mà build không có override (scene cũ đi đường legacy rồi Tạo mesh):
   ghi đè `membership_correction` bằng bản không có `operation` như nhánh override, hoặc cập nhật count trong đó — chọn một,
   ghi lý do trong report. Mục tiêu: validator luôn đọc đúng số của lần build mới.

## Acceptance criteria
1. Fixture PLY đủ field (dùng fixture của T-019), provider inpaint giữ prefix nền + thêm k>0 hàng, trả `inpainted_gaussians=k`:
   Draft → build → Confirm một vật, giữ một ứng viên → `representation_integrity` không có issue → preflight PASS → package PASS.
2. Dựng lại một phần (region trên Ready) với k' ≠ k (gồm k'=0): count trong scene = k', preflight PASS.
3. Count sai cố ý (sửa provenance trong test) → vẫn `SOURCE_BACKGROUND_INVALID` (validator không bị nới).
4. Lỗi/huỷ giữa chừng: scene head không đổi (test sẵn có vẫn PASS).

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_object_region.py \
  tests/test_scene/test_shell_geometry_walk_usd.py tests/test_scene/test_membership_regeneration.py -q -k 'not three_hundred_thousand'
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```

## Commit
(a) trả count + ghi provenance + test 1; (b) partial + test 2, 3. Đúng path; cây có thay đổi chưa commit của T-019. Không Co-Authored-By.
`graphify update .`, `report.md`, `status.md`.

## Out of scope
Đổi validator, đổi thuật toán inpaint.
