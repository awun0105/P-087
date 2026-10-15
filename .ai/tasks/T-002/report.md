# Report T-002

Trạng thái: **changes-requested, cần Architect**. 7/8 tiêu chí đạt. Tiêu chí 2 (đáy kín) chưa đạt vì cần quyết định thiết kế (Q1, cuối báo cáo).

## Done
- Bước 1–2 (validate, lọc opacity): `ShellParams` kiểm tham số khi khởi tạo (`ValueError`). `_filter_gaussians` giữ hàng có `expit(logit) >= opacity_min`. Dữ liệu sai (không hữu hạn, sai số hàng, dưới 50 điểm) → `GaussianShellError`.
- Bước 3 (lọc điểm lẻ): cKDTree, khoảng cách trung bình tới `outlier_k` láng giềng; loại điểm > mean + `outlier_std`·std. Còn dưới 50 điểm → `GaussianShellError("too few Gaussians after filtering")`.
- Bước 4 (voxel hoá): `_voxelize` đệm `dilate_voxels + close_iterations + 1` ô mỗi phía. Vượt `max_grid_cells` → lỗi trước khi cấp phát lưới.
- Bước 5 (giãn, closing, fill): `_close_shell`. Bỏ qua khi số lần = 0, vì scipy hiểu `iterations=0` là "lặp đến khi ổn định".
- Bước 6 (thành phần): `_keep_large_components`, liên thông 6 láng giềng, giữ thành phần ≥ 5% tổng ô. Không thành phần nào đủ → lỗi.
- Bước 7 (vá tiếp xúc chéo): `_repair_diagonals`, tối đa 10 vòng, numpy vector hoá. Ba mẫu: (a) hai ô chéo trong mặt 2×2 → bật ô trống có chỉ số thấp hơn; (b) hai ô đối đỉnh trong khối 2×2×2 → bật một ô láng giềng mặt của ô thấp hơn; (c) hai lỗ đối đỉnh (6 ô còn lại có) → bật lỗ thấp hơn. Mẫu (c) bổ sung so với plan, xem Deviations.
- Bước 8–9: `occupancy_surface()` (T-001, không sửa) rồi cộng offset gốc lưới; `trimesh.smoothing.filter_taubin(iterations=10)`.
- Bước 10–11: `assess_surface`; không đạt → `GaussianShellError` kèm `reasons`. Checksum = sha256(JSON params, sort_keys) + int64 LE các ô cuối (toạ độ ô vật-local, đã sort, không phụ thuộc padding).
- `statistics` đủ 8 khoá của plan. Định nghĩa: `occupied_cells` = ô duy nhất chứa Gaussian sau lọc; `filled_cells` = ô thêm bởi giãn/closing/fill, trước lọc thành phần; `diagonal_fixes` = ô bật thêm bởi vá chéo.

## Commits (branch mvp-pipeline-v2, không push, không Co-Authored-By)
- `82e28ffd` Drop low-opacity and floater Gaussians before building an object shell (nhóm a)
- `61eb95be` Voxelize Gaussian shells with closing, hole fill and component filter (nhóm b)
- `79e8a207` Build Gaussian shells with diagonal repair, smoothing and surface QA gate (nhóm c)
- `86c4591f` Pin Gaussian shell determinism and checksum sensitivity to parameters (nhóm d)

## Acceptance criteria
| # | Test | Kết quả |
|---|------|---------|
| 1 | `test_filled_box_gives_watertight_shell_that_passes_qa` | PASS |
| 2 | `test_open_bottom_scan_is_closed_watertight` | **XFAIL** (strict, `raises=AssertionError`), xem Q1 |
| 3 | `test_chair_leg_gaps_stay_open` | PASS (tham số mặc định) |
| 4 | `test_floaters_are_rejected` | PASS (`outliers_dropped >= 150`) |
| 5 | `test_low_opacity_gaussians_do_not_contribute` | PASS (checksum và đỉnh giống hệt) |
| 6 | `test_two_separate_blocks_keep_two_components` | PASS (`components_kept == 2`) |
| 7 | `test_same_input_and_params_give_same_checksum` | PASS |
| 8 | `test_invalid_inputs_fail_without_returning_a_mesh` (+ `test_too_few_gaussians_after_opacity_filter_fail_closed`) | PASS |

Ngoài ra có test cho từng khâu: lọc, voxel, closing, thành phần, mẫu chéo. Tổng 21 test trong `test_gaussian_shell.py`.

## Files changed
- `src/services/scene/gaussian_shell.py`: mới. `ShellParams`, `GaussianShell`, `GaussianShellError`, `build_gaussian_shell`.
- `tests/test_scene/test_gaussian_shell.py`: mới, 21 test.
- `.ai/tasks/T-002/report.md`: báo cáo này.
- `.ai/status.md`: T-002 → `changes-requested | architect`.

## Tests
Lệnh theo plan, từ root repo:
`.venv/bin/python -m pytest tests/test_scene/test_gaussian_shell.py tests/test_scene/test_object_aware_geometry.py -q`
→ **27 passed, 1 xfailed** (5,7 s, dưới 20 s). Gồm test chốt digest của T-001, vẫn PASS vì `occupancy_surface` không đổi.

`.venv/bin/ruff check src/services/scene/gaussian_shell.py tests/test_scene/test_gaussian_shell.py` → All checks passed.
`.venv/bin/ruff format --check src/services/scene/gaussian_shell.py tests/test_scene/test_gaussian_shell.py` → 2 files already formatted.

Kiểm tra bổ sung (script tạm, không commit):
- Hộp đầy 0,4×0,6×0,8 m, 10 seed khác nhau: 10/10 QA pass, Euler = 2, thể tích ~0,214 m³ (hộp 0,192 m³ cộng một lớp giãn mỗi phía).
- Mẫu chéo: quy tắc của plan không đủ, xem Deviation 1. Sau khi thêm mẫu (c), seed 15 pass QA, Euler = 2.

## Đo hiệu năng (câu hỏi tối ưu)
Khối 1 m, 300k Gaussian, đo bằng `time.perf_counter`:

| Voxel | Ô | Mặt | `occupancy_surface` | Toàn bộ build | QA |
|---|---|---|---|---|---|
| 0,05 m | 10 400 | 5 760 | 0,03 s | 1,51 s (lọc kNN 1,44 s) | pass |
| 0,02 m | 30 510 (khối 0,6 m) | 19 132 | 0,09 s | — | pass |
| 0,02 m | 70 397 (khối 0,8 m) | 33 488 | 0,18 s | — | **fail** `intersection_budget_exceeded` |
| 0,02 m | 134 938 (khối 1,0 m) | 52 568 | 0,38 s | — | **fail** `intersection_budget_exceeded` |

Benchmark T-001 cùng hàm vòng lặp: 64 000 ô 0,31 s; 512 000 ô 1,83 s.

**Quyết định: không tối ưu `occupancy_surface`.** Điều kiện "nếu chậm" chưa đạt. Ở các kích thước QA còn chấp nhận (≤ 30k ô), hàm mất 0,09 s. Nút thắt thực tế là (1) lọc kNN, 1,4 s với 300k điểm, nằm trên đường preview 0,05 m; (2) ngân sách cặp tam giác của QA, xem Q2. Nếu Architect đặt mục tiêu thời gian cho hàm này, vector hoá có thể làm, với test digest T-001 làm chốt.

## Deviations from plan
1. **Mẫu đỉnh chéo bổ sung.** Plan chỉ có mẫu "2 ô đối đỉnh". Tôi liệt kê 256 mẫu của khối 2×2×2 và kiểm tra link của đỉnh tâm: 128 mẫu không phải vòng đơn, tức không 2-manifold. Quy tắc của plan phủ 124 mẫu (120 mẫu checkerboard phẳng và 4 mẫu hai ô đối đỉnh), bỏ sót 4 mẫu "hai lỗ đối đỉnh". Seed 15 sinh một pinch vertex, QA báo `invalid_closed_component_topology`. Đã thêm mẫu (c). Kiểm tra không có false positive. Nếu không sửa, mẫu 2-manifold của plan không đạt.
2. **Chọn ô để bật** không được plan chỉ định. Dùng chỉ số thấp hơn để xác định kết quả. Có thể đổi, chỉ ảnh hưởng checksum.
3. **`mesh.contains` thay bằng kiểm tra chẵn lẻ tia** trong test. `trimesh.contains` cần `rtree`, không có trong venv. Không thêm dependency theo quy định.
4. **Taubin dùng λ = ν = 0,5 mặc định của trimesh.** Plan chỉ ghi `filter_taubin(iterations=…)`. Docstring của trimesh khuyến nghị 0 < 1/λ − 1/ν < 0,1, mà λ = ν cho 0, nằm ngoài khoảng. Chưa đổi. Architect có thể ghim λ/ν.
5. **Test AC2 đánh dấu xfail** (`strict=True`, `raises=AssertionError`) với lý do Q1. Không nới tiêu chí; chỉ ghi nhận trạng thái hiện tại. Nếu Q1 được giải quyết, xfail sẽ fail và phải gỡ.
6. **Gom commit**: Taubin nằm trong nhóm (c) vì QA chạy sau Taubin theo thứ tự plan. Nhóm (d) chỉ có test xác định.
7. **Lỗi tham số** là `ValueError` (khởi tạo `ShellParams`). Lỗi dữ liệu là `GaussianShellError`, theo plan.

## Questions for Architect (cần Architect)

**Q1 — Tiêu chí 2: đáy không quan sát được phải được khép thế nào?** Đây là câu hỏi chặn. Plan yêu cầu "vẫn watertight (đáy được khép), volume ≥ 80% hộp". Các bước 1–11 không khép được đáy hở.
- Chứng cứ: 20 000 điểm chiếu lên 5 mặt (không có đáy). Vỏ đóng kín ở mép đáy, thành hộp mỏng, đỉnh kín, lòng hộp trống ở mọi lớp. Kết quả: watertight, QA pass, thể tích **0,096 m³ (50% hộp)**, Euler = −4 (genus 3). Đây là vỏ rỗng, không phải khối.
- Đã thử trong script tạm (không commit): (i) fill lỗ của lớp thấp nhất có ô → không đổi, lớp này chỉ có 79 ô và không khép footprint; (ii) fill mọi lớp có lỗ kín → lớp đáy (z ≤ 6 ô) chỉ có lỗ 1–2 ô, footprint chỉ kín từ lớp giữa (448 ô ở z = 24). Fill ba lớp này thì thể tích chỉ đi từ 0,095 lên 0,100 m³, vì chỉ thêm các tấm bên trong hộp. Đáy vẫn hở, vì không lớp đáy nào khép footprint.
- Lựa chọn: (a) quy tắc khép đáy rõ ràng (định nghĩa "vòng đáy" và khi nào khép footprint); (b) đáy hở là lỗi có lý do, người dùng khép bằng box cộng (T-004), tiêu chí 2 đổi thành kiểm tra lỗi; (c) mặt phẳng đỡ suy từ mô hình sàn của scene (như collision môi trường, architecture §8.5), áp dụng cho vật đặt trên sàn.

**Q2 — Ngân sách QA làm vỏ 0,02 m của vật lớn bị từ chối.** `_intersections` trong `surface_mesh.py` dừng ở 250k cặp tam giác và fail closed. Vỏ 0,6 m pass; từ 0,8 m trở lên (33k mặt) bị `intersection_budget_exceeded`. Architecture §8.2 yêu cầu không hạ về OBB, nên sẽ lỗi. Lựa chọn: nâng ngân sách hoặc cải tiến broad phase (đổi QA dùng chung), dùng voxel thô hơn cho vật lớn, hoặc chấp nhận giới hạn.

**Q3 — QA chấp nhận vỏ genus > 0.** `assess_surface` chỉ báo `invalid_closed_component_topology` khi Euler lẻ hoặc > 2. Vỏ rỗng ở Q1 (Euler −4) pass. Cần chính sách: yêu cầu Euler = 2 cho mỗi thành phần kín? Đây là đổi QA dùng chung, ảnh hưởng `convex_runner` và `objectgs`.

## Known issues / TODO
- Tiêu chí 2 chờ Q1. Các phần khác đã đạt và có test.
- Chưa kiểm trên scene thật. Toàn bộ số liệu là hình tổng hợp.
- Chưa chạy `tests/test_simulation/test_surface_convex_runner.py` và `test_objectgs_objectify_flow.py`, vì không thuộc lệnh của plan. Không đổi code dùng chung nên ảnh hưởng chỉ có thể đến từ `occupancy_surface`, đã được digest chốt bảo vệ.
- `graphify update .` đã chạy (24 578 node).
