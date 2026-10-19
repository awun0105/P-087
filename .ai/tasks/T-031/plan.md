# T-031: Máy đo — sai số đoạn đo, bề rộng khe, nhất quán sau khi dời

## Goal
Hàm thuần tính các số P2/P3 từ ground truth (T-030) và collision tổng hợp của một revision.

## Context
§15.3 quy tắc 3 và 4. Collision môi trường hiệu lực của một revision: `effective_collision_for_revision(registry, job_id,
scene_revision, preview_pending=False)` (`scene/physics_collision.py:20`) — cùng nguồn với Walk và xuất USD. Collider vật:
`collider.geometry_ref` (GLB, khung object-local) đặt theo `transform` của vật. Đọc GLB: `collision_glb.read_collision_glb`
hoặc trimesh. Ray cast: `trimesh.ray` (có sẵn trong venv; nếu thiếu `embree` thì dùng triangle intersector mặc định).

## Files
- Tạo: `src/services/orchestration/value/measure.py`
- Test: `tests/test_orchestration/test_value_measure.py` (lưới/hộp tổng hợp, không cần scene thật)

## Interfaces
```python
@dataclass(frozen=True) class CollisionWorld: mesh: trimesh.Trimesh      # canonical, đã gộp môi trường + collider vật
def collision_world(registry, job_id, scene_revision) -> CollisionWorld
def distance_error(d: MeasuredDistance) -> DistanceResult   # sim_m = |b−a|, error_m, error_pct
def gap_width(world, gap: GapCheck, robot: RobotProfile) -> GapResult
    # GapResult: sim_width_m, sim_passable, real_passable, agree, kind: "ok"|"missed_obstacle"|"false_obstacle", heights_checked
def move_consistency(world_a, world_b, scene_a, scene_b, robot) -> list[MoveResult]
    # MoveResult: object_id, old_cleared: bool, new_present: bool, passed
```
- `gap_width`: các độ cao `z = h_min, h_min+0.05, …, ≤ h_max`; tại mỗi z, tia từ trung điểm `(a+b)/2` (z thay bằng giá trị đang xét)
  theo `±normalize(b−a)` (chiếu xuống mặt phẳng ngang), khoảng cách tới va chạm đầu tiên, chặn ở `|b−a|/2`; bề rộng tại z = tổng
  hai phía; `sim_width_m` = nhỏ nhất theo z. Trung điểm nằm **trong** vật (tia xuất phát trong khối) → bề rộng 0.
- `move_consistency`: vật được coi là dời khi `transform` khác nhau (dịch > 1 cm hoặc quay > 1°). `old_cleared`: không tam giác nào
  của `world_b` giao hộp bao (collider) của vật tại pose A thu 2 cm mỗi mặt, trong dải z robot. `new_present`: có tam giác của
  collider vật trong hộp bao tại pose B.

## Steps
1. `distance_error`, `gap_width` + test số học: hai hộp cách nhau 0,80 m → bề rộng 0,80 ± 0,01; robot 0,6 + 2·0,05 → qua; đặt
   một hộp thấp hơn `h_min` → không chặn; hộp chỉ chắn ở z cao trong dải → chặn. Phân loại missed/false đúng. Commit.
2. `collision_world`: gộp môi trường hiệu lực + collider vật (bỏ vật DELETED/MERGED/IGNORED theo đúng quy tắc của compositor Walk/USD
   — tái dùng hàm hiện có, không viết quy tắc mới). Test với scene tổng hợp. Commit.
3. `move_consistency` + test: dời hộp A→B, collision môi trường đã khoét nguồn → old_cleared True; không khoét → False. Commit.

## Acceptance criteria
1. Mọi hàm thuần, xác định (cùng đầu vào cùng kết quả).
2. Không đọc ground truth hay ghi gì; chỉ tính.
3. Sai số số học bề rộng ≤ 1 cm trên test hộp.
4. `collision_world` dùng đúng quy tắc vật bị loại như Walk/USD (test đối chiếu với compositor hiện có).

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_value_measure.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
