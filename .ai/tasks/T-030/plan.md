# T-030: Ground truth của benchmark

## Goal
Lưu mọi số đo thước và khai báo của một scene benchmark trong **một tài liệu có phiên bản** mỗi job, đọc/ghi qua API có CAS.

## Context
§15.2, §15.3. Toạ độ điểm theo khung canonical của scene (mét, Z-up, sàn z = 0), cùng khung với SceneIR.
Số migration **cố định là 21** (chủ dự án chốt). Hiện `LATEST_SCHEMA_VERSION` = 20 (T-027 đã dùng 20 trong `jobs/database.py`).
Không task nào khác được lấy 21; nếu cần migration khác trước T-030 thì phải đánh số từ 22 và báo lại.

## Files
- Tạo: `src/services/orchestration/value/ground_truth.py`
- Sửa: `src/services/orchestration/jobs/database.py` (migration 21: `r2s_benchmark_truth(job_id TEXT PK, version INTEGER NOT NULL,
  payload TEXT NOT NULL)`)
- Sửa: `tests/test_orchestration/test_runtime_migrations.py` — hai assert `LATEST_SCHEMA_VERSION == 20` (dòng ~206, ~242) thành 21
- Sửa: `src/api/studio/value.py`
- Test: `tests/test_orchestration/test_benchmark_truth.py`, `tests/test_api/test_value_routes.py`, `tests/test_api/test_role_matrix.py`

## Interfaces
```python
Vec3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
class RobotProfile(BaseModel):
    width_m: float = Field(gt=0.05, le=3); safety_margin_m: float = Field(ge=0, le=1)
    height_min_m: float = Field(ge=0, le=2); height_max_m: float = Field(gt=0, le=3)   # validator: min < max
class MeasuredDistance(BaseModel): id: Identifier; label: str(≤80); a: Vec3; b: Vec3; real_m: float = Field(gt=0, le=100)
class GapCheck(BaseModel):
    id: Identifier; label: str(≤80); layout: Literal["A","B"]; a: Vec3; b: Vec3   # |b−a| ∈ [0.1, 10] m
    real_width_m: float | None = Field(default=None, gt=0, le=10); real_passable: bool
class LayoutRef(BaseModel): scene_revision: Identifier; tagged_at: datetime
class L4Declaration(BaseModel): layout_a_passed: bool; layout_b_passed: bool; matches_reality: bool; evidence: str(1..600)
class BenchmarkTruth(BaseModel):  # extra="forbid"
    schema_version: Literal["1.0"] = "1.0"
    include_in_benchmark: bool = False
    data_source: Literal["self_capture","hf_room","synthetic"] = "self_capture"
    robot: RobotProfile | None = None
    distances: list[MeasuredDistance] = Field(max_length=32)
    gaps: list[GapCheck] = Field(max_length=32)
    key_obstacle_ids: list[Identifier] = Field(max_length=64)
    layouts: dict[Literal["A","B"], LayoutRef] = {}
    manual_baseline_minutes: float | None = Field(default=None, ge=0, le=10_000)
    l4: L4Declaration | None = None
    notes: str = Field(default="", max_length=2000)
```
```
GET  /api/v1/jobs/{job_id}/benchmark-truth            → {version, truth, updated_at}  (chưa có: version 0, truth mặc định)
PUT  /api/v1/jobs/{job_id}/benchmark-truth  {expected_version, truth} → {version, truth, updated_at}; lệch version → 409
```
Kiểm khi PUT: `layouts[X].scene_revision` phải là revision có thật của job (`registry.scene.revision`); `key_obstacle_ids` phải là
vật có trong scene hiện tại; id trong `distances`/`gaps` không trùng. Quyền như T-027; GET cho mọi người xem được job.

## Steps
1. Model + validator + test (biên, min<max, id trùng, độ dài khe). Commit.
2. Migration 21 + repository CAS (`version` tăng 1 mỗi lần ghi) + test 409. Commit.
3. Hai route + kiểm tham chiếu revision/vật + role matrix. Commit.

## Acceptance criteria
1. Ghi đồng thời: một bên thắng, bên kia 409, không mất dữ liệu.
2. Revision không tồn tại hoặc vật không có trong scene → 422 với thông điệp tiếng Việt nêu đúng mục sai.
3. Job chưa có tài liệu → GET trả version 0 và giá trị mặc định, không 404.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_benchmark_truth.py tests/test_api/test_value_routes.py tests/test_api/test_role_matrix.py \
  tests/test_orchestration/test_runtime_migrations.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/python scripts/check_contract_mirror.py
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
