# Review T-002

Verdict: CHANGES REQUESTED (theo các quyết định dưới đây; phần đã làm đạt)

Đã đọc `report.md`, phần chính của `src/services/scene/gaussian_shell.py`, hàm `assess_surface`/`_intersections`.
Chạy lại: `test_gaussian_shell.py` + `test_object_aware_geometry.py` → 27 passed, 1 xfailed.

## Phần đã làm (đạt)
- Tiêu chí 1, 3–8 PASS, mỗi tiêu chí có test. Digest T-001 giữ nguyên.
- Lệch plan đều chấp nhận:
  - Thêm luật vá chéo thân (body diagonal) sau khi duyệt đủ 256 mẫu 2×2×2: đúng và tốt hơn plan.
  - Kiểm điểm trong mesh bằng ray parity (không có rtree): được.
  - Taubin λ=ν=0.5 mặc định trimesh: được, giữ.
- Đánh dấu tiêu chí 2 `xfail(strict=True)` và dừng thay vì tự chế luật: đúng cách.

## Quyết định cho câu hỏi

### Q1: khép mặt không quan sát được → luật "nắp vành" (rim cap) trên 6 hướng trục
Lý do: Gaussian nằm trên bề mặt, nên vật quét thiếu một mặt cho ra vỏ rỗng hình cốc. Không có bằng chứng không gian trống
thì không phân biệt được "gầm bàn trống" với "đáy hộp không thấy". Luật dưới đây chỉ đóng khi phần biên tạo thành **vòng kín**,
nên gầm bàn (4 chân rời) và hông bàn (hình chữ Π hở dưới) không bị lấp.

Thêm vào `_close_shell`, sau `binary_closing`, trước `binary_fill_holes`:
```
cap_band = dilate_voxels + close_iterations + 1          # số lớp tính từ lớp chiếm cực trị
với mỗi trục a ∈ {x, y, z}, mỗi chiều s ∈ {−, +}:
    extreme = lớp chiếm ngoài cùng theo (a, s)
    band    = các lớp trong khoảng cap_band lớp tính từ extreme vào trong
    proj    = OR(band) chiếu lên mặt phẳng vuông góc a          (2D)
    cap     = binary_fill_holes(proj, cấu trúc 4-láng giềng) & ~proj
    nếu cap có ô: bật grid[ô cap] tại lớp extreme
grid = binary_fill_holes(grid)   (3D, như cũ)
```
- Thêm `ShellParams.cap_open_faces: bool = True` (để tắt khi cần đối chiếu).
- `statistics`: `capped_cells` (tổng) và `capped_directions` (danh sách như `["-z", "+y"]`). Manifest T-007 sẽ ghi
  `inferred_regions` dựa trên trường này.
- Chấp nhận hệ quả: vật có lỗ xuyên song song trục (khung tranh, vòng tròn nằm phẳng) sẽ bị lấp lỗ. Với va chạm thì đây là xấp xỉ
  bảo thủ, được phép. Ghi vào docstring.

### Q2: ngân sách kiểm giao cắt → voxel thích ứng + ngân sách riêng cho vỏ
- `assess_surface(..., intersection_budget: int = 250_000)`: thêm tham số keyword, mặc định giữ nguyên → `convex_runner`,
  `objectgs` không đổi hành vi. `_intersections` nhận budget từ đây.
- `build_gaussian_shell` gọi với `intersection_budget=2_000_000`.
- Voxel thích ứng: `voxel_eff = max(params.voxel_m, longest_extent_m / params.max_cells_per_axis)`,
  `ShellParams.max_cells_per_axis: int = 96`. `longest_extent_m` tính sau khi lọc điểm. Ghi `voxel_m_effective` vào `statistics`;
  checksum dùng `voxel_eff`.
- Mục tiêu: vật 2 m (ví dụ sofa 2,0×0,9×0,8) dựng xong và qua QA trong ≤ 15 s. Nếu đo thấy vượt, giảm `max_cells_per_axis`
  và ghi số đo vào report; không tắt kiểm giao cắt.

### Q3: QA chấp nhận vỏ kín có Euler ≠ 2 → không đổi gate dùng chung
`assess_surface` dùng chung với ObjectGS và CoACD, và vật thật có thể có genus > 0 hợp lệ (quai cốc, thanh ngang ghế). Không đổi.
Luật nắp (Q1) xử lý trường hợp rỗng hình cốc. Trong `statistics` của vỏ ghi thêm `component_genus` (lấy từ metrics QA) để
truy vết.

## Required changes
1. Luật nắp vành theo Q1 + test:
   - Bỏ `xfail` ở `test_open_bottom_scan_is_closed_watertight`; phải PASS (volume ≥ 80% hộp, watertight, `"-z" in capped_directions`).
   - `test_table_underside_stays_open`: mặt bàn + 4 chân (như ghế, chân cao 0,7 m) → điểm giữa gầm bàn ở z = 0,3 m nằm **ngoài** mesh;
     `"-z" not in capped_directions`.
   - `test_box_missing_back_face_is_capped`: hộp thiếu mặt +y (sát tường) → watertight, volume ≥ 80%, `"+y" in capped_directions`.
   - `test_chair_leg_gaps_stay_open` (đã có) vẫn PASS.
   - `test_cap_can_be_disabled`: `cap_open_faces=False` → hành vi cũ (volume ~50% cho hộp hở đáy).
2. Ngân sách + voxel thích ứng theo Q2 + test:
   - `assess_surface` tham số mới, mặc định không đổi (test `tests/test_scene/test_surface_mesh.py` vẫn PASS).
   - `test_large_object_uses_adaptive_voxel_and_passes_qa`: hộp 2,0×0,9×0,8 m → `voxel_m_effective > 0.02`, QA pass, đo thời gian và ghi vào report.
3. `statistics.component_genus` theo Q3.
4. Cập nhật docstring module về luật nắp và giới hạn (lỗ xuyên bị lấp).
5. Lệnh kiểm tra:
   ```
   .venv/bin/python -m pytest tests/test_scene/test_gaussian_shell.py tests/test_scene/test_object_aware_geometry.py \
     tests/test_scene/test_surface_mesh.py tests/test_simulation/test_surface_convex_runner.py -q
   .venv/bin/ruff check … && .venv/bin/ruff format --check …
   ```
6. Commit theo nhóm: (a) assess_surface budget, (b) voxel thích ứng, (c) luật nắp + test, (d) genus + docstring.
   Thêm mục "Round 2" vào `report.md`, đặt `status.md` → `implemented`.

## Ghi chú cho task sau
- Lọc kNN 1,44 s trên 300k điểm ở đường preview: vượt mục tiêu preview 1,5 s (architecture §11). Đã thêm ghi chú vào T-010:
  preview phải đo và, nếu cần, lấy mẫu đều (stride, deterministic) trước khi lọc kNN.

---

# Review T-002 — Round 2

Verdict: CHANGES REQUESTED (nhỏ; chốt hướng Q4)

Chạy lại 4 file test của review: 57 passed, 2 xfailed. Đã đọc diff `ce627ea9` (budget mặc định giữ 250k → ObjectGS/CoACD
không đổi). Required change 2, 3, 4: **pass**. Vật 2,0×0,9×0,8 m dựng 3,5–4,9 s, QA pass.

## Quyết định Q4: chọn (a), bỏ luật nắp vành

Luật nắp vành do Architect đặt ở Round 1 đã được thực nghiệm bác bỏ: tường vỏ có lỗ xuyên nên phần rỗng rò ra, các biến thể khác
lấp quá tay (1,33–1,36×), và phép kiểm lỗ báo sai cả trên hình cầu kín. Không đặt thêm luật mới, vì:
- **Mesh vỏ chỉ dùng cho va chạm.** Vỏ thiếu đáy vẫn **kín (watertight)** và qua QA. Đáy không thấy nằm sát sàn, mặt sau không thấy
  nằm sát tường, nên không có vật nào đi vào phần rỗng đó. Về va chạm, vỏ rỗng hình cốc úp tương đương khối đặc.
- Mọi luật lấp tự động đều phải đoán, và đoán sai thì lấp cả gầm bàn (tệ hơn nhiều cho Walk).

Vì vậy:
1. **Xoá** `_cap_open_faces`, `ShellParams.cap_open_faces`, `capped_cells`, `capped_directions` và phần docstring tương ứng.
   Không giữ (c): tín hiệu hướng bị đóng không đáng tin (báo 5 hướng trên hình cầu kín) thì không nên đưa vào manifest.
2. Thêm thống kê **chỉ để truy vết**, không chặn: `solidity = volume(vỏ) / volume(bao lồi của vỏ)`, ghi vào `statistics`.
   Giá trị thấp gợi ý vỏ rỗng hoặc vật lõm; T-007 ghi nó vào `ObjectShellManifest.statistics`, Studio có thể hiển thị sau.
3. Test:
   - Hai test đóng mặt (`test_open_bottom_scan_is_closed_watertight`, `test_box_missing_back_face_is_capped`) đổi thành
     `test_open_bottom_scan_gives_watertight_shell_that_passes_qa` và `test_missing_back_face_gives_watertight_shell_that_passes_qa`:
     khẳng định watertight, QA pass, `0 < solidity < 1`. Bỏ xfail. Không khẳng định thể tích ≥ 80%.
   - Xoá `test_cap_can_be_disabled`.
   - Giữ `test_table_underside_stays_open`, `test_chair_leg_gaps_stay_open` (nay là kiểm tra hồi quy: không có bước nào lấp gầm).
   - Thêm `test_solidity_is_close_to_one_for_filled_box` (hộp đặc → solidity > 0,9).
   - Giữ bộ sinh dữ liệu bề mặt đều mới (sửa đúng).
4. Lệnh kiểm tra như Round 1. Commit theo nhóm (xoá nắp; solidity + test). Thêm "Round 3" vào report, `status.md` → `implemented`.

Architect đã cập nhật `architecture.md` §8.1 theo quyết định này.
