# AUD-28 — Khoảng tham chiếu chất lượng, khuyến nghị theo quy tắc và số đo tài nguyên trong bảng đánh giá

## Metadata và goal

- IMPLEMENTED (code, 2026-10-09; kiểm bằng mắt và lệnh gọi API thật còn mở); P2; EX-PRODUCT evaluation + Studio UI.
- Canonical PRODUCT-02/08/09, REC-04/06.
- Goal: bảng đánh giá cho người dùng biết điểm PSNR/SSIM/LPIPS của scene nằm ở đâu so
  với các scene đã chạy, nêu việc cần làm khi có chỉ số dưới ngưỡng, và hiện RAM/VRAM
  đã dùng. Không đặt ngưỡng Đạt/Không đạt mới khi chưa có đủ dữ liệu.
- [Agent guide](../AGENT_GUIDE.md), [ADR 0028](../../../../decisions/0028-benchmark-derived-verdicts-and-rule-based-insights.md).

## Baseline và scope

Điểm bắt đầu trong source (kiểm lại bằng CodeGraph trước khi sửa):

- `src/services/orchestration/evaluation/models.py`: `Metric`, `StageEvaluation`, `JobEvaluation`.
- `src/services/orchestration/evaluation/scorecard.py`: `_held_out_metrics` (dòng 195),
  `_pose_metrics` (dòng 139), `_system_metrics` (dòng 669), `evaluate_job` (dòng 708).
- `src/services/orchestration/evaluation/report.py`: báo cáo Markdown.
- `src/api/studio/evaluation.py`: hai route đánh giá.
- `frontend/src/features/studio/evaluation/EvaluationCard.tsx`, `frontend/src/lib/api/studio.ts`
  (kiểu `JobEvaluation`, `EvaluationMetric`), `frontend/tests/evaluation-card.test.tsx`.
- `src/services/orchestration/processing/observed.py`: `load_usages`, `_vram`.

Hiện trạng đã kiểm trong source:

1. Bốn chỉ số có `verdict`: `input.warnings`, `pose.registered_ratio`,
   `visual.nonfinite_values`, `metric.check_error`. Các chỉ số khác để trống theo quy
   tắc ở `models.py:10`: chỉ gán khi có ngưỡng đã được chấp nhận trong repo.
2. Điểm held-out đã có sẵn cho job sản phẩm: `fixed.brush.eval_split_every = 8` trong
   file preset, nên Brush giữ lại một phần tám số ảnh để chấm.
3. `pose.registered_ratio` đã có verdict theo `min_registered_ratio` trong cấu hình COLMAP
   của chính job (`scorecard.py:146`).
4. `_system_metrics` chỉ có thời gian xử lý, bước lâu nhất và số lượt chạy.
5. `Metric.threshold` là chuỗi mô tả, không phải số.

### Điểm held-out thật đang có (bằng chứng)

| Job | Nguồn | PSNR (dB) | SSIM | LPIPS |
|---|---|---|---|---|
| `job-cb8815e2a770` | `eval/protocols/recon_visual_quality.md` | 25,35 | 0,888 | 0,308 |
| `job-9b9aa3dac9f1` | artifact trong `data/studio_local` | 25,49 | 0,889 | 0,344 |
| `job-6bc02e5de4ed` | artifact trong `data/studio_local` | 26,36 | 0,899 | 0,277 |
| `job-a713242a38be` | artifact trong `data/studio_local` | 28,45 | 0,922 | 0,277 |
| `job-13a0fda27f9f` | `eval/protocols/recon_visual_quality.md` | 28,80 | 0,927 | 0,268 |
| `job-ed9cf7739a70` | artifact trong `data/studio_local` | 30,00 | 0,939 | chưa đo |

Kết luận: chỉ có sáu scene, và không scene nào được ghi nhận là hỏng. Dữ liệu này cho
biết khoảng giá trị đã thấy (PSNR 25,35–30,00; SSIM 0,888–0,939; LPIPS 0,268–0,344),
không cho biết ngưỡng nào tách scene tốt khỏi scene xấu.

### Owned

`src/services/orchestration/evaluation/models.py`, `scorecard.py`, `report.py`,
`src/services/orchestration/evaluation/reference.py` (mới),
`src/services/orchestration/evaluation/advice.py` (mới),
`configs/product/evaluation_reference_v1.json` (mới), `src/config.py` (một setting mới),
`src/api/studio/evaluation.py`, `src/services/orchestration/processing/observed.py`
(chỉ đổi tên `_vram` thành hàm công khai),
`frontend/src/lib/api/studio.ts`, `frontend/src/features/studio/evaluation/EvaluationCard.tsx`,
`tests/test_orchestration/test_evaluation.py`, `frontend/tests/evaluation-card.test.tsx`.

## Input / output / data contract

Thay đổi schema (khai báo rõ, cả backend và frontend phải cập nhật cùng sprint S1):

- `JobEvaluation.schema_version`: `Literal["1.0"]` → `Literal["1.1"]`.
- `JobEvaluation.summary: list[str] = []` (mới). Mỗi phần tử là một câu khuyến nghị tiếng Việt.
- `Metric.reference: str | None = None` (mới). Câu mô tả khoảng tham chiếu và nguồn.
- Không đổi kiểu của `Metric.threshold`, không thêm field số cho ngưỡng.

File mới `configs/product/evaluation_reference_v1.json`:

```json
{
  "schema_version": "1.0",
  "note": "Điểm held-out của các scene đã chạy. Chỉ dùng để hiển thị khoảng tham chiếu, không phải ngưỡng đạt.",
  "scenes": [
    {"job_id": "job-cb8815e2a770", "source": "eval/protocols/recon_visual_quality.md", "psnr": 25.35, "ssim": 0.888, "lpips": 0.308}
  ]
}
```

Điền đủ sáu dòng theo bảng bằng chứng ở trên; `lpips` của `job-ed9cf7739a70` là `null`.

## Logic change và dependent updates

| Chỗ | Trước | Sau |
|---|---|---|
| PSNR/SSIM/LPIPS held-out | chỉ có giá trị | thêm `reference`; `verdict` vẫn để trống |
| `pose.registered_ratio` | verdict theo cấu hình job | giữ nguyên, không thêm ngưỡng khác |
| Kết luận tổng | không có | `summary` sinh từ các chỉ số đang có verdict `warn`/`fail` |
| Nhóm Hệ thống | thời gian, bước lâu nhất, số lượt | thêm peak RAM, peak VRAM, cấu hình đã dùng |

Consumer phải cập nhật: `report.py`, `frontend/src/lib/api/studio.ts`, `EvaluationCard.tsx`,
`src/api/studio/evaluation.py`, hai file test.

## Dependencies

- S1 độc lập. S2 cần S1 (cần field `summary`). S3 cần S1 và S2.
- Không phụ thuộc AUD-26 hay AUD-27. Dùng chung `load_usages` với AUD-26 nhưng không
  sửa logic của nó.
- Việc bật verdict cho PSNR/SSIM/LPIPS nằm ngoài task này và cần owner quyết định (xem ADR 0028).

---

## Sprint AUD-28.S1 — Schema 1.1 và khoảng tham chiếu

**Input:** `models.py`, `scorecard.py`, bảng bằng chứng ở trên.
**Output:** hai field mới; file tham chiếu; ba chỉ số held-out có `reference`.
**Contract:** không chỉ số nào nhận `verdict` mới trong sprint này. Thiếu file tham chiếu
hoặc file sai định dạng thì `reference` là `None` và bảng đánh giá vẫn trả về bình thường.

Implement:

1. `models.py`: thêm `summary` vào `JobEvaluation`, thêm `reference` vào `Metric`, đổi
   `schema_version` thành `"1.1"`.
2. Tạo `configs/product/evaluation_reference_v1.json` với sáu scene.
3. `src/config.py`: thêm setting
   `product_evaluation_reference: Path = Path("configs/product/evaluation_reference_v1.json")`,
   đặt ngay dưới `product_geometry_config` (dòng 66) và khai báo theo đúng kiểu đó.
4. Tạo `src/services/orchestration/evaluation/reference.py`:
   - Model pydantic cho file (`extra="forbid"`).
   - `load_reference(path: Path | None) -> ReferenceSet | None`: trả `None` khi `path` là
     `None`, file không tồn tại hoặc không hợp lệ; ghi một dòng warning, không ném lỗi.
   - `describe(values: list[float], unit: str, digits: int) -> str | None`: trả `None` khi
     có ít hơn 2 giá trị; ngược lại trả đúng dạng
     `"Các scene đã chạy: 25,35–30,00 dB (6 scene)"` (min–max, số scene có giá trị đó).
5. `scorecard.py`:
   - `evaluate_job` nhận thêm `reference_config: Path | None = None` và truyền bộ tham chiếu
     xuống `_visual_metrics` → `_held_out_metrics`.
   - Trong `_held_out_metrics`, gán `reference` cho ba chỉ số `visual.novel_view_quality`,
     `visual.novel_view_ssim`, `visual.novel_view_lpips` khi chỉ số đó có giá trị.
     Không sửa `value`, `display`, `meaning`, `verdict`, `threshold`.
6. `src/api/studio/evaluation.py`: truyền `deps.settings().product_evaluation_reference`.
7. `report.py`: thêm cột "Tham chiếu" vào bảng Markdown (ô trống khi `reference` là `None`).
8. `frontend/src/lib/api/studio.ts`: thêm `summary: string[]` và `reference: string | null`
   vào kiểu; nếu có parser kiểm `schema_version` thì chấp nhận `"1.1"`.

Không làm trong sprint này:

- Không gán `ok`/`warn`/`fail` cho PSNR, SSIM, LPIPS. Không viết bất kỳ con số ngưỡng nào
  (27 dB, 24 dB, 0,88, 0,80, 0,30 đều không được xuất hiện trong code).
- Không đổi verdict của `pose.registered_ratio`.
- Không điền `summary` (để danh sách rỗng; S2 làm).

Test (`tests/test_orchestration/test_evaluation.py`):

- `describe` với sáu giá trị PSNR ở trên trả đúng chuỗi mẫu; một giá trị trả `None`.
- LPIPS chỉ đếm năm scene (bỏ `null`).
- Không có file tham chiếu → ba chỉ số có `reference is None`, không lỗi.
- File sai định dạng → `None` và có warning.
- Ba chỉ số held-out vẫn có `verdict is None` trong mọi trường hợp.
- Báo cáo Markdown có cột "Tham chiếu".

**Exit:**
- [x] Sáu nhóm test pass; test đánh giá hiện có chỉ đổi `schema_version`.
- [x] `npm run typecheck` pass sau khi sửa kiểu ở frontend.

---

## Sprint AUD-28.S2 — Khuyến nghị theo quy tắc và số đo tài nguyên

**Input:** `scorecard.py` sau S1, `observed.py`.
**Output:** `summary` có nội dung; nhóm Hệ thống có ba chỉ số mới.
**Contract:** `summary` chỉ sinh từ các chỉ số đã có `verdict` là `warn` hoặc `fail`.
Không có điểm gộp, không có trọng số.

Khuyến nghị:

1. Tạo `src/services/orchestration/evaluation/advice.py` với hàm thuần
   `summarize(groups: list[StageEvaluation]) -> list[str]`:
   - Duyệt mọi `Metric` có `verdict` là `fail` trước, rồi `warn`, giữ thứ tự nhóm.
   - Tra bảng theo `key`:

     | `key` | `verdict` | Câu sinh ra |
     |---|---|---|
     | `input.warnings` | `warn` | "Video có cảnh báo chuyển động: {display}. Lần quay sau hãy di chuyển đều tay, tránh đứng yên lâu hoặc lia máy nhanh." |
     | `pose.registered_ratio` | `fail` | "COLMAP chỉ dựng được vị trí cho {display} ảnh, dưới ngưỡng {threshold}. Quay chậm hơn và để các khung hình liên tiếp chồng lấn nhiều hơn." |
     | `visual.nonfinite_values` | `fail` | "File 3DGS có giá trị hỏng. Chạy lại bước dựng hình; không duyệt scene này." |
     | `metric.check_error` | `fail` hoặc `warn` | "Đoạn kiểm C–D lệch {display}, ngoài ngưỡng {threshold}. Đo lại hai đoạn A–B và C–D rồi xác nhận lại tỉ lệ." |

   - Chỉ số có `warn`/`fail` nhưng không có trong bảng: sinh câu chung
     "{label}: {display} (ngưỡng: {threshold})".
   - Không có chỉ số nào `warn`/`fail`: trả đúng một câu
     "Không có chỉ số tự kiểm nào dưới ngưỡng. {n} trên {total} chỉ số có ngưỡng; các chỉ số còn lại chỉ để tham khảo."
     với `n` là số chỉ số trong nhóm `measured` có `verdict` khác `None` và `total` là số chỉ số trong
     nhóm `measured` có `threshold` khác `None`. Mẫu số chỉ đếm chỉ số thực sự có ngưỡng, không tính
     các dòng tài nguyên chỉ để tham khảo.
2. `evaluate_job`: gán `summary=summarize(groups)` sau khi dựng xong `groups`.
3. `report.py`: in `summary` thành danh sách gạch đầu dòng ngay sau phần tiêu đề.

Câu cấm: không được sinh câu nào khẳng định scene "sẵn sàng mô phỏng", "sẵn sàng duyệt"
hay "đạt chuẩn". Phần hình học và va chạm chưa có verdict nên không có cơ sở cho các câu đó.

Số đo tài nguyên:

4. `observed.py`: đổi tên `_vram` thành `usage_vram` (hàm công khai) và sửa nơi gọi trong
   cùng file. Không đổi logic.
5. `evaluate_job` nhận thêm `usages: list[ResourceUsage] | None = None`.
   `src/api/studio/evaluation.py` truyền `load_usages(RuntimeDatabase(deps.settings().database_url))`;
   nếu đọc DB lỗi thì truyền `None` và ghi warning.
6. `_system_metrics` thêm ba chỉ số, tính trên các bản ghi có `job_id` trùng và
   `outcome == "completed"`:
   - `system.peak_ram`: giá trị `peak_ram_gb` lớn nhất, đơn vị GB;
     `display` dạng "5,2 GB (bước scene_extract)".
   - `system.peak_vram`: giá trị `usage_vram` lớn nhất, cùng dạng `display`.
   - `system.config`: lấy `params` của bản ghi `completed` mới nhất; `value` là `None`,
     `display` dạng "tối đa 1.200 frame · 6.000.000 splat · 3.840 px"
     (ba key `sampling.max_frames`, `brush.max_splats`, `brush.max_resolution`).
   - Không có bản ghi phù hợp, hoặc `usages` là `None`: vẫn trả ba chỉ số với `value=None`
     và `display="Chưa đo — job này không có bản ghi tài nguyên"`. Đây là quy ước hiện có
     của `Metric` (xem ghi chú ở `models.py` cho `value`).
   - Ba chỉ số này không có `verdict`.
   - `system.processing_time` và `system.slowest_stage` chỉ tính các stage worker thuộc attempt hiện tại;
     loại `ST-METRIC-CANONICALIZE` vì thời lượng của nó chứa thời gian chờ người dùng, đồng thời loại
     stage được tái sử dụng từ attempt trước.

Test (`tests/test_orchestration/test_evaluation.py`):

- Mỗi dòng của bảng quy tắc sinh đúng câu, có thay đúng `{display}` và `{threshold}`.
- `fail` đứng trước `warn` trong `summary`.
- Chỉ số lạ có `warn` → câu chung.
- Không có `warn`/`fail` → đúng một câu với `n` và `total` đúng.
- Không câu nào trong `summary` chứa "sẵn sàng".
- Peak RAM/VRAM: chọn đúng giá trị lớn nhất và đúng tên tool; bỏ qua lượt `failed`;
  bỏ qua bản ghi của job khác; không có bản ghi → `value is None`.
- `system.processing_time` loại thời gian chờ xác nhận metric và stage tái sử dụng khi retry;
  `system.slowest_stage` chỉ chọn trong các stage worker của attempt hiện tại.

**Exit:**
- [x] Test khuyến nghị, số đo tài nguyên, API fallback và observed budget pass.
- [ ] Gọi GET qua API đang chạy từ checkout này để xác nhận `summary` và nhóm Hệ thống mới.

**Kiểm tra runtime local (`job-6bc02e5de4ed`):**
- GET trên phiên trình duyệt đã đăng nhập trả HTTP 200 và `job_status="SUCCEEDED"`, nhưng
  không có `summary` và chỉ có ba metric hệ thống cũ (`processing_time`, `slowest_stage`,
  `attempts`). Đây là API process cũ, không phải code S2 trong checkout.
- Handler của checkout không hoàn tất: telemetry đọc báo `OperationalError`, sau đó registry
  không khởi chạy vì role PostgreSQL được cấu hình trong shell không tồn tại trong DB local.
- **UNVERIFIED:** chưa có response từ API của checkout này cho job local; Exit live GET còn mở.

---

## Sprint AUD-28.S3 — Hiển thị trên `EvaluationCard`

**Input:** `EvaluationCard.tsx`, kiểu dữ liệu đã cập nhật ở S1.
**Output:** khối khuyến nghị ở đầu bảng; dòng tham chiếu dưới các chỉ số có `reference`.
**Contract:** không thêm thư viện; dùng component và token màu đang có. Không vẽ thanh
so ngưỡng, vì `threshold` là chuỗi và chỉ bốn chỉ số có verdict.

Implement:

1. Trong `EvaluationCard` (bảng tổng hợp), render `data.summary` thành một khối ở đầu,
   mỗi phần tử một dòng. Khối dùng tông `ochre` khi có ít nhất một chỉ số `warn`/`fail`
   trong `data.groups`, ngược lại dùng tông trung tính. `summary` rỗng thì không render khối.
2. Trong `MetricRow`, khi `metric.reference` khác `null`, thêm một dòng chữ nhỏ ngay dưới
   `meaning`, hiển thị nguyên chuỗi `reference`.
3. `StageMetrics` (chỉ số của từng bước) không hiển thị `summary`.
4. Không sửa cách hiển thị `verdict` và `threshold` hiện có.

Test (`frontend/tests/evaluation-card.test.tsx`):

- Có `summary` → các câu xuất hiện theo đúng thứ tự.
- `summary` rỗng → không có khối.
- Chỉ số có `reference` → chuỗi xuất hiện; `reference` là `null` → không có dòng thừa.
- Ba chỉ số hệ thống mới hiển thị `display` như mọi chỉ số khác.

**Exit:**
- [x] Test frontend pass; `npm run lint`, `npm run typecheck`, `npm run build -- --webpack` pass.
- [x] Chrome DevTools xác nhận route review và `Bảng đánh giá` render; console không có lỗi/cảnh báo.
- [ ] Owner xác nhận summary và reference rows mới trên API của checkout này; response hiện tại chưa có các field đó.

## Verification và DoD

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/pytest tests/test_orchestration/test_evaluation.py tests/test_orchestration/test_observed_budget.py -q
cd frontend && npm run lint && npm run typecheck && npm test -- tests/evaluation-card.test.tsx && npm run build -- --webpack
```

Phân loại evidence: test S1 và S2 là unit; lệnh gọi API trên dữ liệu local ở S2 là local
integration; S3 là unit (Vitest). Không có phần nào của task này là GPU evidence.

DONE khi cả ba sprint tick đủ Exit.

## Result / Evidence

### Sprint AUD-28.S1 — 2026-10-09

- **Commit:** `a5c30a9` (base `f33f8fb`).
- **Files:** `configs/product/evaluation_reference_v1.json`, this task file,
  `frontend/src/lib/api/studio.ts`, `frontend/tests/evaluation-card.test.tsx`,
  `src/api/studio/evaluation.py`, `src/config.py`,
  `src/services/orchestration/evaluation/models.py`,
  `src/services/orchestration/evaluation/reference.py`,
  `src/services/orchestration/evaluation/report.py`,
  `src/services/orchestration/evaluation/scorecard.py`,
  `tests/test_orchestration/test_evaluation.py`.
- **Schema:** `JobEvaluation.schema_version` is `1.1`; `summary` defaults to an empty
  list and `Metric.reference` is optional. The frontend parser remains compatible with
  responses that omit these fields.
- **Behavior:** Six configured reference scenes provide descriptive min/max intervals.
  LPIPS has five non-null samples. Held-out metrics retain `verdict=None`. Missing or
  invalid reference configuration logs a warning and leaves evaluation usable without
  reference values.
- **Verification:** `.venv/bin/pytest tests/test_orchestration/test_evaluation.py -q`
  (12 passed); `.venv/bin/ruff check src/ tests/ scripts/resources/` (passed);
  `.venv/bin/ruff format --check src/ tests/ scripts/resources/` (537 files formatted);
  `cd frontend && npm run typecheck` (passed); `npm run lint` (passed with two existing
  warnings in `src/features/studio/inspection/LidarCalibrationQAStage.tsx`);
  `npm exec -- vitest run tests/evaluation-card.test.tsx` (5 passed).
- **Graph indexes:** CodeGraph was queried for the evaluation flow and current symbols;
  Graphify was queried before the next sprint. The required post-edit Graphify refresh
  was completed for S1.
- **Limits:** Intervals describe the configured sample range; they do not define an
  acceptance threshold or establish simulation readiness. No GPU claim is part of S1.

### Sprint AUD-28.S2 — 2026-10-09

- **Commit:** `c2cb6c3` (base `a5c30a9`); message
  `feat(evaluation): rule-based advice and system telemetry metrics (AUD-28.S2)`.
- **Files:** `src/api/studio/evaluation.py`,
  `src/services/orchestration/evaluation/advice.py`,
  `src/services/orchestration/evaluation/report.py`,
  `src/services/orchestration/evaluation/scorecard.py`,
  `src/services/orchestration/processing/observed.py`,
  `tests/test_orchestration/test_evaluation.py`, this task file.
- **Contract:** `evaluate_job` accepts optional `usages`; completed same-job records supply
  peak RAM/VRAM and latest config; missing measurements return `value=None` and the defined
  no-data display. Summary orders failures before warnings and never claims simulation readiness.
- **Verification:** `.venv/bin/ruff check src/ tests/ scripts/resources/` (passed);
  `.venv/bin/ruff format --check src/ tests/ scripts/resources/` (538 files formatted);
  `.venv/bin/pytest tests/test_orchestration/test_evaluation.py tests/test_orchestration/test_observed_budget.py -q`
  (27 passed); `graphify update .` completed.
- **Runtime boundary:** the authenticated local GET returned the older response shape, while
  the current checkout could not access the configured local PostgreSQL registry. Live job
  evidence remains unverified.

### AUD-28.S2 timing correction — 2026-10-09

- **Reason:** live review exposed `system.processing_time=57,488` seconds and
  `system.slowest_stage=ST-METRIC-CANONICALIZE (874.9 minutes)`. That interval includes the
  user's metric-confirmation wait. The old scorecard also counted stage artifacts carried into
  a retry.
- **Change:** `current_attempt_stage_timings` is now shared by the benchmark and scorecard.
  The scorecard totals measured worker stages from the current attempt and chooses the slowest
  from the same set. Metric confirmation remains represented as user wait in the benchmark.
- **Regression:** before the fix, tests measured 870.7 minutes instead of 40 seconds for a
  14.5-hour confirmation wait, and 175.5 minutes instead of 30 seconds after a retry. Both
  tests pass with the shared timing rules.
- **Verification:** `.venv/bin/pytest tests/test_orchestration/test_evaluation.py
  tests/test_orchestration/test_pipeline_timing.py -q` (27 passed);
  `.venv/bin/ruff check src/ tests/` (passed);
  `.venv/bin/ruff format --check src/ tests/` (537 files formatted); CodeGraph sync reports
  up to date; `graphify update .` completed.
- **Browser:** authenticated DevTools review rendered the existing page with HTTP 200 and no
  console errors or warnings. Its evaluation endpoint still serves schema `1.0`, without
  `summary`, and the old 958.1-minute value. The running API is not serving this checkout, so
  the corrected live response remains **UNVERIFIED**.

### Sprint AUD-28.S3 — 2026-10-09

- **Commit:** `00511a4` (base `c2cb6c3`); message
  `feat(studio): display evaluation advice and reference intervals on UI (AUD-28.S3)`.
- **Files:** `frontend/src/features/studio/evaluation/EvaluationCard.tsx`,
  `frontend/tests/evaluation-card.test.tsx`, this task file.
- **Contract:** the review evaluation card renders the rule-based summary and configured
  metric reference intervals when present; `StageMetrics` remains unchanged.
- **Verification:** `npm exec -- vitest run tests/evaluation-card.test.tsx` (8 passed),
  `npm run lint` (passed with two existing warnings in `LidarCalibrationQAStage.tsx`),
  `npm run typecheck` (passed), and `npm run build -- --webpack` (passed).
- **Browser evidence:** the authenticated Studio review page rendered the EvaluationCard.
  Chrome DevTools reported no console errors or warnings. Its API response returned HTTP 200
  and `job_status="SUCCEEDED"`, but lacked `summary` and `reference`; those visual states remain
  **UNVERIFIED** until this checkout's API serves the S1/S2 contract.

S2 and S3 code and automated checks are complete. S2 live-data and S3 non-empty
summary/reference visual exits remain open until the local Studio API serves this checkout.

### Sửa sau review (2026-10-09)

- `summarize` đếm `total` là tổng số chỉ số của các nhóm `measured` (trước đó chỉ đếm chỉ số
  có `threshold`, nên câu luôn ra dạng "n trên n"). Test cập nhật: "0 trên 3", "1 trên 2".
- `summarize` trả danh sách rỗng khi chưa chỉ số nào có verdict (job chưa chạy xong bước nào); trước đó job
  đang chờ vẫn nhận câu "Không có chỉ số tự kiểm nào dưới ngưỡng".
