# T-004: Box → membership (`ObjectRegionCommand` + `resolve_region`)

## Goal
Hàm thuần: nhận danh sách box (cộng/trừ, toạ độ object-local), trả mask source row mới của vật và
thống kê preview. Đây là lõi tính toán cho preview/apply ở T-009 và T-010.

## Context
`architecture.md` §7.3 (quy tắc tính), §11 (hiệu năng). Code liên quan:
- `src/services/scene/editing/membership.py` (`decode_gaussian_membership_labels`, `select_source_gaussians`,
  `ObjectMembershipValidationError`, `StaleObjectMembershipRevisionError`)
- `src/models/contracts/object_membership.py` (`MembershipCommandBase`, `ObjectMembershipReassignCommand`)
- Bảo vệ sàn: `membership_regeneration.prepare_correction` dùng `fit_canonical_floor_model` + `above_floor_mask`.

## Files
- Sửa: `src/models/contracts/object_membership.py` (thêm `RegionBox`, `ObjectRegionCommand`)
- Tạo: `src/services/scene/editing/region_box.py`
- Sửa: `frontend/src/lib/contracts/api.ts` (mirror hai kiểu mới)
- Tạo: `tests/test_scene/test_region_box.py`
- Sửa: `tests/test_contracts/…` (test validate command)

## Interfaces
```python
class RegionBox(ContractModel):
    op: Literal["add", "subtract"]
    center_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    half_extents_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]   # mỗi giá trị 0.005 ≤ x ≤ 20
    yaw_rad: FiniteFloat = 0.0                                       # quanh trục Z (Z-up), |yaw| ≤ 2π

class ObjectRegionCommand(MembershipCommandBase):     # có expected_scene_revision, membership_checksum
    boxes: list[RegionBox] = Field(min_length=1, max_length=16)
    claim_from: list[Identifier] = Field(default_factory=list, max_length=32)
    # validator: ít nhất một box op="add"; claim_from không trùng lặp
```

```python
@dataclass(frozen=True)
class RegionResolution:
    object_mask: np.ndarray          # bool (gaussian_count,), hàng thuộc vật sau khi áp box
    added: np.ndarray                # int64 chỉ số source row được thêm
    removed: np.ndarray              # int64 chỉ số source row bị trả về nền
    claimed: dict[str, int]          # object_id → số hàng lấy từ vật đó
    overlaps: dict[str, int]         # object_id → số hàng của vật khác nằm trong box nhưng KHÔNG lấy
    protected_floor_count: int

def boxes_contain(points_local: np.ndarray, boxes: list[RegionBox]) -> np.ndarray:
    """inside = ∪ add \\ ∪ subtract; điểm trên mặt box tính là bên trong (dung sai 1e-6)."""

def resolve_region(
    *,
    positions_world: np.ndarray,       # (n,3) toạ độ source world
    labels: np.ndarray,                # int32 (n,)
    manifest: ObjectMembershipArtifact,
    object_id: str,
    source_world_from_object: Transform,
    command: ObjectRegionCommand,
    floor_protected: np.ndarray | None,   # bool (n,), True = hàng sàn
) -> RegionResolution

def apply_resolution(labels: np.ndarray, manifest, object_id: str, resolution: RegionResolution) -> np.ndarray:
    """Trả mảng nhãn mới: added → nhãn nhỏ nhất của object_id; removed → -1. Không sửa mảng đầu vào."""

def preview_payload(resolution, positions_local, sample_limit=20_000) -> dict:
    """added_count, removed_count, object_gaussian_count, protected_floor_count, overlaps, claimed,
    added_sample_m, removed_sample_m (list[list[float]], lấy mẫu đều, deterministic)."""
```

Đổi toạ độ: `points_local = R(q)^T · (p_world − t)` với `Transform` (translation_xyz, rotation_quaternion_xyzw).
Box: `d = R_z(-yaw) · (p_local − center)`, tức `d_x = (p−c)·(cos yaw, sin yaw, 0)`, `d_y = (p−c)·(−sin yaw, cos yaw, 0)`,
`d_z = p_z − c_z`; bên trong khi `|d_i| ≤ half_i + 1e-6` mọi trục. Quy ước này **phải khớp** `contains()` của frontend
(`frontend/src/features/studio/region/box-model.ts`, đã accepted ở T-014). Vector hoá numpy, không vòng lặp Python theo điểm.

## Steps
1. Contract + test validate (box thiếu add, 17 box, half quá nhỏ/lớn, NaN, claim_from trùng). Commit.
2. `boxes_contain` + test (box xoay 45°, box trừ khoét giữa, điểm trên mặt). Commit.
3. `resolve_region` + test các quy tắc dưới. Commit.
4. `apply_resolution` + `preview_payload` + test. Commit.
5. Mirror TS + `scripts/check_contract_mirror.py` + typecheck. Thay khai báo `RegionBox` cục bộ trong
   `frontend/src/features/studio/region/box-model.ts` bằng import từ `@/lib/contracts/api` (giữ nguyên tên trường). Commit.
6. Ca kiểm dùng chung: tạo `tests/fixtures/region_box_cases.json` gồm ≥ 8 ca (box yaw 0, π/6, −π/3, π; điểm trong, ngoài,
   đúng trên mặt, cách mặt 2e-6; half = 0.005 và 20). Test pytest đọc file và kiểm `boxes_contain`; thêm một test vitest trong
   `frontend/tests/region-box-model.test.ts` đọc **cùng file** và kiểm `contains()` (import JSON qua đường dẫn tương đối hoặc
   `fs.readFileSync`). Hai phía phải cho cùng kết quả. Commit.

## Acceptance criteria
Dữ liệu test: lưới điểm tổng hợp gồm sàn (z≈0), vật A (id `a`), vật B (id `b`) cạnh nhau, nền rải rác.
0. Giới hạn: `half_extents_m` khoảng đóng [0.005, 20] (0.005 hợp lệ, 0.0049 bị từ chối, 20 hợp lệ, 20.0001 bị từ chối).
1. Box add bao trùm A → `added` rỗng, `removed` rỗng.
2. Box add thu nhỏ còn nửa trên A → nửa dưới A nằm trong `removed`, nhãn mới = -1.
3. Box add phình sang nền → hàng nền trong box (không phải sàn) vào `added`.
4. Hàng sàn trong box **không** vào `added`; `protected_floor_count` đúng.
5. Box chồng lên B, `claim_from=[]` → hàng B không đổi; `overlaps == {"b": k}`.
6. Cùng box, `claim_from=["b"]` → hàng B trong box vào `added`, `claimed == {"b": k}`.
7. Box trừ ở giữa → hàng A trong box trừ vào `removed`.
8. Vật đã Move: dùng `source_world_from_object` (pose lúc tách), KHÔNG dùng `transform` hiện tại → kết quả giống
   trường hợp chưa Move (test truyền hai transform khác nhau, khẳng định chỉ source được dùng).
9. Kết quả vật < 50 hàng → `ObjectMembershipValidationError` với thông điệp gợi ý dùng Delete.
10. `membership_checksum` hoặc `expected_scene_revision` không khớp → lỗi stale (kiểm ở caller T-009, test
    ở đây chỉ cho `resolve_region` nhận manifest đúng).
11. `apply_resolution` không sửa mảng đầu vào (so sánh trước/sau).
12. 2.000.000 điểm, 4 box → `resolve_region` < 1 s trên CPU (test đánh dấu `@pytest.mark.slow` nếu repo có marker,
    nếu không thì dùng 300.000 điểm và ngưỡng 0,3 s).

## Tests required
`tests/test_scene/test_region_box.py` (một test cho mỗi tiêu chí). Lệnh:
```
.venv/bin/python -m pytest tests/test_scene/test_region_box.py tests/test_contracts -q
.venv/bin/python scripts/check_contract_mirror.py
.venv/bin/ruff check … && .venv/bin/ruff format --check …
cd frontend && npm run typecheck
```

## Commit
Theo từng bước. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Không route API, không publish, không dựng vỏ (T-009).
