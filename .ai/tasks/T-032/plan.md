# T-032: Bảng metric giá trị + xuất JSON / CSV / Markdown

## Goal
Gom T-027..T-031 thành `ValueScorecard` cho một job và bảng benchmark cho nhiều scene; xuất JSON, CSV, Markdown.

## Context
§15.1, §15.3 quy tắc 5–6. Nguồn: `value/events.py`, `processing/observed.py` (`load_usages`, `processing_seconds`),
`MachineCapability` (benchmark snapshot của job), `Settings.benchmark_gpu_hourly_usd`, `value/ground_truth.py`, `value/measure.py`,
`simulation_package.current_package`, `review/validation_runs.py` (run `COMPLETED` của gói), trạng thái mét của job.
Mẫu xuất markdown hiện có: `GET /jobs/{id}/evaluation/report.md` (`api/studio/evaluation.py`).

## Files
- Tạo: `src/services/orchestration/value/scorecard.py`
- Sửa: `src/api/studio/value.py`
- Test: `tests/test_orchestration/test_value_scorecard.py`, `tests/test_api/test_value_routes.py`

## Interfaces
```python
Provenance = Literal["measured", "declared", "unavailable"]
class Figure(BaseModel): value: float | int | str | None; unit: str | None; provenance: Provenance; note: str | None = None
class NorthStar(BaseModel):
    hands_on_minutes: Figure; hands_on_before_ready_minutes: Figure; hands_on_after_ready_minutes: Figure
    machine_minutes: Figure; hardware: dict[str, str | float | None]   # gpu_name, vram_gb, cpu_count, ram_gb
    gpu_hours: Figure; cost_usd: Figure; interventions: dict[str, int]  # operation → số lần (origin human)
class P2(BaseModel):
    gaps_checked: int; gaps_agree: int; missed_obstacles: int; false_obstacles: int; gap_results: list[GapResult]
    max_distance_error_cm: Figure; distance_results: list[DistanceResult]; key_obstacles_with_collider: str  # "k/n"
class P3(BaseModel): edit_to_retest_minutes: Figure; moves: list[MoveResult]; consistent: bool | None
class P4(BaseModel): level: Literal[0,1,2,3,4]; reasons: list[str]   # vì sao chưa lên bậc kế tiếp
class ValueScorecard(BaseModel):
    job_id: str; scene_name: str; generated_at: datetime; scene_revision: str | None
    data_source: str; north_star: NorthStar; p2: P2; p3: P3; p4: P4; manual_baseline_minutes: Figure
def build_scorecard(registry, settings, job_id) -> ValueScorecard
def benchmark_rows(registry, settings) -> list[ValueScorecard]   # job mới nhất của mỗi project có include_in_benchmark
```
- **Edit → thử lại**: từ `scene_edit` human đầu tiên sau `layouts.A.tagged_at` tới `walk_session` `completed` đầu tiên trên
  `layouts.B.scene_revision`. Thiếu một đầu → `unavailable` kèm lý do.
- **Phút máy**: `processing_seconds` của job (đã gồm `scene.*` từ T-028). `gpu_hours` = tổng `duration_seconds` của usage có
  `gpu_name` / 3600. `cost_usd` = `gpu_hours × benchmark_gpu_hourly_usd` (None → `unavailable`).
- **Bậc**: đúng §15.3 quy tắc 5; `reasons` liệt kê điều kiện chưa đạt của bậc kế tiếp.
- Mọi số thiếu dữ liệu → `provenance = "unavailable"`, không đoán, không 0 giả.

Routes:
```
GET /api/v1/jobs/{job_id}/value-metrics            → ValueScorecard
GET /api/v1/jobs/{job_id}/value-metrics.md | .csv
GET /api/v1/value-metrics/benchmark                → {rows: [ValueScorecard], summary}
GET /api/v1/value-metrics/benchmark.md | .csv
```
`summary`: số scene, trung vị phút công người, trung vị phút máy theo `gpu_name`, tổng khe khớp / tổng khe, tổng bỏ sót, tổng giả,
số scene đạt ≥ L2 / ≥ L3, trung vị mốc làm tay. CSV: một dòng một scene, cột đúng thứ tự bảng "Sổ kết quả" của Playbook.

## Steps
1. Model + `build_scorecard` phần NorthStar + test với sự kiện/usage giả. Commit.
2. P2/P3 qua `measure.py` + test (dùng world giả). Commit.
3. P4 + test từng bậc và `reasons`. Commit.
4. `benchmark_rows` + summary + CSV/MD + route + quyền (mọi người xem được job thì đọc được). Commit.

## Acceptance criteria
1. Scene không có ground truth: bảng vẫn trả đủ khung, P2/P3 `unavailable`, P4 tối đa theo dữ liệu có.
2. CSV mở được bằng bảng tính (UTF-8 có BOM, dấu phẩy, số dạng `.`); Markdown có bảng 5 metric ở đầu.
3. Không có số nào ghi `measured` khi thực ra là người nhập (`declared`).
4. Tính toán một job < 3 s trên scene thử (đo trong test có fixture lưới vừa).

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_value_scorecard.py tests/test_api/test_value_routes.py tests/test_api/test_role_matrix.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/python scripts/check_contract_mirror.py
```

## Commit
Theo Steps. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.
