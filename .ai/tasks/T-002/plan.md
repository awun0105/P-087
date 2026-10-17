# T-002: Dựng vỏ Gaussian kín (`build_gaussian_shell`)

## Goal
Từ các Gaussian của **một** vật (toạ độ object-local, mét), dựng mesh kín, 2-manifold, qua
`assess_surface`. Đây là nguồn collider mặc định và cũng là "vỏ phát sáng" trong UI.

## Context
`architecture.md` §4 (Vỏ), §8.1–8.3, §11. Tái dùng `occupancy_surface()` (T-001) và
`assess_surface()` trong `src/services/scene/surface_mesh.py`. Thư viện có sẵn: numpy, scipy
(`scipy.ndimage`, `scipy.spatial.cKDTree`), trimesh. **Không** thêm dependency mới.

## Files
- Tạo: `src/services/scene/gaussian_shell.py`
- Tạo: `tests/test_scene/test_gaussian_shell.py`

## Interfaces
```python
@dataclass(frozen=True)
class ShellParams:
    voxel_m: float = 0.02          # preview dùng 0.05
    opacity_min: float = 0.1       # sau sigmoid
    outlier_k: int = 8
    outlier_std: float = 2.0
    dilate_voxels: int = 1
    close_iterations: int = 2
    min_component_fraction: float = 0.05
    smooth_iterations: int = 10    # Taubin; 0 = tắt
    max_grid_cells: int = 32_000_000

@dataclass(frozen=True)
class GaussianShell:
    vertices: np.ndarray           # (N,3) float64, object-local, mét
    faces: np.ndarray              # (M,3) int64
    checksum: str                  # "sha256:" của params + ô occupancy cuối
    statistics: dict[str, int | float]   # input_rows, opacity_dropped, outliers_dropped,
                                         # occupied_cells, filled_cells, components_kept,
                                         # components_dropped, diagonal_fixes
    quality: dict                  # kết quả assess_surface

class GaussianShellError(ValueError): ...

def build_gaussian_shell(
    positions: np.ndarray,         # (n,3) object-local
    opacity_logit: np.ndarray | None,  # (n,), None = không lọc opacity
    params: ShellParams = ShellParams(),
) -> GaussianShell
```

## Steps
1. Validate: `positions` (n,3) hữu hạn, n ≥ 50; `opacity_logit` cùng độ dài nếu có. Sai → `GaussianShellError`.
2. Lọc opacity: giữ `1/(1+exp(-logit)) >= opacity_min`.
3. Lọc điểm lẻ: `cKDTree`, khoảng cách trung bình tới `outlier_k` láng giềng; loại điểm > mean + outlier_std·std.
   Còn < 50 điểm → `GaussianShellError("too few Gaussians after filtering")`.
4. Voxel hoá: `cells = floor(p / voxel_m)`. Dựng lưới bool có viền đệm `dilate_voxels + close_iterations + 1`.
   Kích thước lưới > `max_grid_cells` → lỗi.
5. `binary_dilation` (`dilate_voxels` lần, cấu trúc 6-láng giềng), `binary_closing` (`close_iterations`),
   `binary_fill_holes`.
6. Thành phần liên thông (`scipy.ndimage.label`, 6-connectivity): giữ thành phần ≥ `min_component_fraction`
   tổng ô; ghi số giữ/bỏ.
7. Vá tiếp xúc chéo (để mesh 2-manifold): lặp tới khi không còn mẫu nào:
   - Cạnh chéo: trong mỗi khối 2×2 trên một mặt phẳng trục, nếu đúng 2 ô chéo nhau có và 2 ô còn lại trống → bật một ô trống.
   - Đỉnh chéo: trong khối 2×2×2, nếu chỉ 2 ô đối đỉnh có → bật thêm ô để nối mặt.
   Đếm vào `diagonal_fixes`. Giới hạn 10 vòng; còn mẫu → lỗi.
8. `vertices, faces = occupancy_surface(set_of_cells, voxel_m)` rồi cộng offset gốc lưới.
9. Nếu `smooth_iterations > 0`: `trimesh.smoothing.filter_taubin(mesh, iterations=…)` (không đổi topology).
10. `quality = assess_surface(mesh)`. `quality["passed"]` False → **không** trả về mesh mà raise
    `GaussianShellError` kèm `quality["reasons"]`.
11. `checksum` = sha256 của JSON params (sort_keys) + bytes ô cuối (int64 LE, đã sort).

## Acceptance criteria
1. Mây điểm lấp đầy hình hộp 0,4×0,6×0,8 m (20.000 điểm ngẫu nhiên, seed cố định) → mesh watertight,
   `assess_surface.passed`, bounds lệch ≤ 2·voxel_m mỗi phía.
2. Mây điểm chỉ trên **bề mặt** hình hộp, thiếu hẳn mặt đáy (mô phỏng camera không nhìn đáy) →
   vẫn watertight (đáy được khép), volume ≥ 80% hộp thật.
3. Hình "ghế": mặt ngồi + 4 chân 4×4 cm cách nhau 40 cm → khe giữa các chân **không** bị lấp
   (một điểm giữa hai chân, độ cao 0,2 m, nằm ngoài mesh: `mesh.contains`), chân không bị mất.
4. Thêm 200 điểm lơ lửng cách vật 1 m → bị loại (statistics.outliers_dropped ≥ 150), bounds không phình.
5. Điểm opacity thấp (logit −5) không góp vào vỏ.
6. Hai khối rời cách 0,5 m → `components_kept = 2`, mesh vẫn watertight.
7. Cùng input + params → cùng `checksum` (deterministic).
8. Input < 50 điểm, NaN, lưới quá ngân sách → `GaussianShellError`, không trả mesh.

## Tests required
`tests/test_scene/test_gaussian_shell.py`, một test cho mỗi tiêu chí trên (tạo dữ liệu tổng hợp trong test,
seed `np.random.default_rng(…)`). Đặt tên rõ: `test_open_bottom_scan_is_closed_watertight`,
`test_chair_leg_gaps_stay_open`, `test_floaters_are_rejected`, …

Lệnh kiểm tra:
```
.venv/bin/python -m pytest tests/test_scene/test_gaussian_shell.py tests/test_scene/test_object_aware_geometry.py -q
.venv/bin/ruff check src/services/scene/gaussian_shell.py tests/test_scene/test_gaussian_shell.py
.venv/bin/ruff format --check src/services/scene/gaussian_shell.py tests/test_scene/test_gaussian_shell.py
```
Test phải chạy < 20 s tổng; nếu chậm, giảm số điểm, không tắt kiểm tra.

## Commit
Commit sau mỗi nhóm nhỏ: (a) validate + lọc + test; (b) voxel/closing/components + test;
(c) vá chéo + occupancy_surface + QA + test; (d) smoothing + determinism. Không Co-Authored-By.
`graphify update .`, `report.md`, `status.md`.

## Out of scope
Không publish artifact, không gọi CoACD, không đụng objectify/API.
Nếu tiêu chí 3 (khe chân ghế) không đạt với tham số mặc định, ghi rõ trong `report.md` giá trị thử và
kết quả; **không** nới tiêu chí.
