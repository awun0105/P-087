# T-032: Bảng metric giá trị + xuất JSON / CSV / Markdown

## Goal
Gom dữ liệu của T-027..T-031 thành `ValueScorecard` cho một job và danh sách `benchmark_rows` cho nhiều scene; xuất JSON, CSV, Markdown.
Chỉ backend. Không có UI (UI là T-033, T-034).

## Context
- `.ai/architecture.md` §15.1 (bảng 5 metric và nguồn), §15.2 (`value_scorecard.py`: gom nguồn + xuất), §15.3 quy tắc 1, 2, 5, 6.
- Thứ tự cột CSV/bảng: mục 7 "Sổ kết quả" của Playbook (https://claude.ai/artifact/HxAyREwmuoxmXFXdTcsNuN). Dùng đúng 14 cột ở mục Interfaces.
- Phụ thuộc, phải có trước khi làm:
  - T-027: `record_event`, `list_events`, `operation_origin`, `value/__init__.py`, router `src/api/studio/value.py`.
  - T-028: `processing_seconds` đã gồm `scene.*`.
  - T-029: sự kiện `operator_time` và `walk_session` đã được ghi.
  - T-030: model `BenchmarkTruth` và hàm đọc truth kèm `version` trong `value/ground_truth.py`.
  - T-031: `collision_world`, `distance_error`, `gap_width`, `move_consistency` và các kiểu `DistanceResult`, `GapResult`, `MoveResult` trong `value/measure.py`.
- Có sẵn để tái dùng: `processing/observed.py` (`load_usages`, `processing_seconds`), `jobs/metric.py` (xác nhận mét, `MetricConfirmationError`), `simulation_package.current_package`, `review/validation_runs.py` (trạng thái `COMPLETED`), `Settings.benchmark_gpu_hourly_usd`, `MachineCapability` (snapshot benchmark của job).
- Mẫu xuất Markdown: `GET /jobs/{id}/evaluation/report.md` trong `src/api/studio/evaluation.py`. Làm theo cùng kiểu `Response`.
- Lưu ý tên: `src/services/orchestration/evaluation/scorecard.py` đã có sẵn và là module khác. Không sửa nó, và không gộp vào.

## Files
- Tạo: `src/services/orchestration/value/scorecard.py`
- Sửa: `src/api/studio/value.py` (thêm 6 route; router đã có từ T-027)
- Sửa: `tests/test_api/test_role_matrix.py` (khai báo 6 route mới; test này liệt kê mọi route và fail nếu thiếu)
- Test, thêm vào file đã có từ T-027 (không tạo lại, không ghi đè):
  - `tests/test_orchestration/test_value_scorecard.py` (tạo mới)
  - `tests/test_api/test_value_routes.py`
- Không sửa frontend và `frontend/src/lib/contracts/api.ts`. Việc đó thuộc T-034.

## Steps
1. Model, `Figure`, `NorthStar`, `build_scorecard` phần NorthStar, test với sự kiện và usage giả. Commit.
2. P2 và P3 qua `measure.py` và `ground_truth.py`, test với world giả (không cần Isaac). Commit.
3. P4 và `reasons`, test từng bậc L0–L4. Commit.
4. `benchmark_rows`, summary, CSV và Markdown, 6 route, khai báo trong role matrix, test route. Commit.
Sau mỗi bước: `ruff check` và `ruff format --check` trên các file vừa đổi.

## Ghi chú từ review T-027
Số lần can thiệp = `scene_edit` có `origin = human` + `scene_request` có `origin = human` (yêu cầu qua hàng đợi;
đường `geometry_review = auto` ghi `origin = system` và không được đếm).

## Interfaces
```python
Provenance = Literal["measured", "declared", "unavailable"]
class Figure(BaseModel):
    value: float | int | str | None
    unit: str | None
    provenance: Provenance
    note: str | None = None          # bắt buộc khi unavailable: lý do ngắn, tiếng Việt
class NorthStar(BaseModel):
    hands_on_minutes: Figure
    hands_on_before_ready_minutes: Figure     # trước lần đầu object_geometry = ready
    hands_on_after_ready_minutes: Figure
    machine_minutes: Figure                   # processing_seconds / 60
    hardware: dict[str, str | float | None]   # gpu_name, vram_gb, cpu_count, ram_gb, peak_vram_gb, peak_ram_gb
    # peak_* = lớn nhất trên MỌI ResourceUsage `completed` của job, gồm cả `scene.*` (T-028): Tạo mesh/ObjectGS có thể là bước
    # tốn VRAM nhất, quyết định "chạy được trên GPU nào". Thẻ kỹ thuật cũ và benchmark runtime giữ nguyên, không đọc scene.*.
    gpu_hours: Figure                         # tổng duration_seconds của usage có gpu_name / 3600
    cost_usd: Figure                          # gpu_hours × benchmark_gpu_hourly_usd; None → unavailable
    interventions: dict[str, int]             # operation → số lần, chỉ origin = human; thêm "unknown" nếu có
class P2(BaseModel):
    gaps_checked: int
    gaps_agree: int
    missed_obstacles: int                     # GapResult.kind == "missed_obstacle"
    false_obstacles: int                      # GapResult.kind == "false_obstacle"
    gap_results: list[GapResult]
    max_distance_error_cm: Figure
    distance_results: list[DistanceResult]
    key_obstacles_with_collider: str          # "k/n"
class P3(BaseModel):
    edit_to_retest_minutes: Figure
    moves: list[MoveResult]
    consistent: bool | None                   # None khi không có vật dời hoặc thiếu layout B
class P4(BaseModel):
    level: Literal[0, 1, 2, 3, 4]             # 0 = chưa đạt L1
    reasons: list[str]                        # điều kiện còn thiếu để lên bậc kế tiếp; rỗng khi L4
class ValueScorecard(BaseModel):
    job_id: str
    scene_name: str
    generated_at: datetime                    # UTC
    scene_revision: str | None
    data_source: str                          # truth.data_source; "unavailable" khi chưa có truth
    notes: str                                # truth.notes, "" khi chưa có truth
    north_star: NorthStar
    p2: P2
    p3: P3
    p4: P4
    manual_baseline_minutes: Figure           # declared, từ truth.manual_baseline_minutes
def build_scorecard(registry, settings, job_id) -> ValueScorecard
def benchmark_rows(registry, settings) -> list[ValueScorecard]
    # mỗi project: job mới nhất có truth.include_in_benchmark = True
```

### Quy tắc provenance
Một `Figure` là `measured` chỉ khi mọi đầu vào do máy tạo ra (sự kiện trình duyệt, usage, collision, transform). Có bất kỳ
đầu vào nào do người nhập thì là `declared`. Không có dữ liệu thì `unavailable` với `note`.

| Số | Provenance |
| --- | --- |
| phút công người, phút trước/sau ready | measured (lô `operator_time`) |
| số lần can thiệp | measured (đếm `scene_edit`) |
| phút máy, gpu_hours, hardware | measured (`ResourceUsage`, `MachineCapability`) |
| cost_usd | declared (giờ đo × đơn giá khai báo) |
| edit → thử lại | measured (timestamp sự kiện) |
| nhất quán sau khi dời | measured (geometry từ transform) |
| sai số kích thước, số khe khớp, bỏ sót, giả | declared (có điểm và `real_m` / `real_passable` do người nhập) |
| k/n vật cản có collider | declared (n từ truth) |
| mốc làm tay | declared |
| bậc L4 | declared (ghi "khai báo" trong `reasons` khi L4) |

### Quy tắc bậc (§15.3 quy tắc 5)
- L1: có xác nhận mét cho revision hiện tại (hoặc scene cũ không có khoá xác nhận) và `object_geometry` đã ready.
- L2: L1 + mọi `key_obstacle_ids` có collider + ≥ 1 `walk_session` completed trên revision hiện tại + khe kiểm của layout A
  không có `missed_obstacle`.
- L3: L2 + có gói mô phỏng `current_package` cho revision hiện tại + có lần validation Isaac `COMPLETED` cho gói đó **và**
  `ValidationReport.overall_result == PASS` (Architect chốt, §15.3). COMPLETED nhưng FAIL/ERROR → chưa L3, `reasons` nêu kết quả.
- Khe kiểm của L2 đo trên đúng collision tổng hợp mà Walk dùng (T-031 `collision_world`); không cần mô phỏng Walk riêng.
- L4: L3 + `truth.l4` có `layout_a_passed`, `layout_b_passed` và `matches_reality` đều `True`.
- `reasons` là danh sách tiếng Việt các điều kiện chưa đạt của bậc **kế tiếp**. Thiếu truth thì ghi "chưa có ground truth".

### Quy tắc đo
- Edit → thử lại: từ `scene_edit` có `origin = human` đầu tiên sau `layouts.A.tagged_at`, tới `walk_session` completed đầu tiên
  có `scene_revision = layouts.B.scene_revision` và `at` sau thời điểm sửa. Thiếu một đầu thì `unavailable` kèm lý do.
- P2: mỗi `GapCheck` được đo trên revision của layout của nó (`gap.layout` → `layouts[X].scene_revision`).
  `max_distance_error_cm` lấy từ mọi `MeasuredDistance`.
- P3: `move_consistency(world_A, world_B, ...)` chạy trên các vật có transform khác giữa hai revision.

### Routes
```
GET /api/v1/jobs/{job_id}/value-metrics            → ValueScorecard (JSON)
GET /api/v1/jobs/{job_id}/value-metrics.md         → text/markdown; charset=utf-8
GET /api/v1/jobs/{job_id}/value-metrics.csv        → text/csv; charset=utf-8
GET /api/v1/value-metrics/benchmark                → {rows: [ValueScorecard], summary}
GET /api/v1/value-metrics/benchmark.md | .csv
```
- Tất cả là đọc. Gắn vào router studio nên có `require_contributor`. Benchmark chỉ liệt kê các job mà job list hiện tại cho
  người gọi thấy; nếu job list có lọc theo chủ sở hữu thì áp cùng bộ lọc.
- Job không tồn tại → 404 với `ApiErrorResponse`, như `evaluation`.

### Định dạng xuất
- CSV: UTF-8 có BOM (`﻿`), dấu phẩy, số dùng `.`, làm tròn 1 chữ số thập phân. Ô `unavailable` để **trống** (không ghi 0).
  Một dòng một scene, đúng 14 cột theo thứ tự sau:
  `Scene | Nguồn | Phần cứng | Máy (ph) | Người (ph) | Can thiệp | Khe khớp | Bỏ sót / Giả | Sai số KT | Đổi→thử (ph) | Nhất quán | Bậc | Làm tay (ph) | Ghi chú`
  - Nguồn: `self_capture` → "Tự quay", `hf_room` → "HF room", `synthetic` → "Tổng hợp".
  - Phần cứng: `GPU · VRAM`. Khe khớp: `agree/checked`. Bỏ sót / Giả: `missed / false`. Nhất quán: "Đạt" / "Không" / trống.
  - Bậc: `L0`…`L4`.
- Markdown: đầu tài liệu là bảng 5 dòng: **Chính** (phút công · phút máy · chi phí trên một dòng), **P2**, **P3**, **P4**,
  **Làm tay** (mốc so sánh cho P1). Sau đó là chi tiết từng khe và từng vật dời. Ô thiếu dữ liệu ghi "—".
- Summary của benchmark: `scenes`, trung vị phút công người, trung vị phút máy theo `gpu_name`, tổng khe khớp / tổng khe,
  tổng bỏ sót, tổng giả, số scene đạt ≥ L2 và ≥ L3, trung vị mốc làm tay. Trung vị chỉ tính trên giá trị có số, và kèm số mẫu `n`.

## UI/UX
Không có. Bảng và thẻ hiển thị thuộc T-033, T-034.

## Acceptance criteria
1. Scene không có ground truth: `build_scorecard` trả đủ mọi khung, không ném lỗi. P2 và P3 là `unavailable` với note
   "chưa có ground truth". P4 tính theo dữ liệu có sẵn (L1 nếu đủ điều kiện, không vượt quá điều kiện đã đạt).
2. CSV mở được trong bảng tính: có BOM, đúng 14 cột theo thứ tự trên, số dạng `.`. Markdown có bảng 5 dòng ở đầu.
3. Không có số nào ghi `measured` khi thực ra do người nhập. Test kiểm từng trường: `distances`, `gaps`, `real_passable`,
   `layouts`, `manual_baseline_minutes`, `l4`, `cost_usd` đều là `declared`.
4. `build_scorecard` cho một job < 3 s trên fixture lưới trong test (cỡ 50k tam giác).
5. `benchmark_rows` chỉ lấy job mới nhất có `include_in_benchmark` mỗi project. Job không đưa vào benchmark không xuất hiện trong
   `rows` và không vào `summary`.
6. Mọi số thiếu dữ liệu là `unavailable` hoặc ô trống, không bao giờ là 0.
7. Sáu route mới chỉ đọc, đi qua router studio có `require_contributor`, và được khai báo trong `test_role_matrix.py`.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_value_scorecard.py tests/test_api/test_value_routes.py tests/test_api/test_role_matrix.py -q
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/python scripts/check_contract_mirror.py
```
Các ca cần có:
- NorthStar với sự kiện và usage giả: phút trước/sau ready, can thiệp theo origin, `cost_usd` có và không có đơn giá.
- P2 và P3 với world giả: một khe đạt, một khe bỏ sót, một vật giả, một vật dời đạt và một vật dời không đạt.
- P4: một ca cho mỗi bậc L0–L4, kiểm `reasons` của bậc kế tiếp.
- `benchmark_rows`: nhiều project, job cũ và job mới, job không include.
- CSV: BOM, số cột, thứ tự cột, ô trống cho unavailable.
- Route: 200 và 404, và 403 hoặc 401 khi không có quyền (theo mẫu của `test_evaluation.py`).

## Commit
Theo Steps. Stage đúng path, không dùng `git add -A`. Không thêm Co-Authored-By. Sau khi xong chạy `graphify update .`, cập nhật `report.md` và `status.md`.

## Out of scope
- UI, thẻ "Giá trị", trang `/benchmark`, panel nhập ground truth (T-033, T-034).
- Gương TypeScript và thay đổi `frontend/src/lib/contracts/api.ts`.
- Đổi định nghĩa bậc hoặc quy tắc đo. Nếu cần đổi, sửa `architecture.md` §15.3 trước.
- Xuất PDF, cache kết quả, phân quyền theo người dùng mới.
- Gửi dữ liệu ra dịch vụ ngoài.
