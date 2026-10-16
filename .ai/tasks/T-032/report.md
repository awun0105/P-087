# Report T-032: Bảng metric giá trị + xuất JSON / CSV / Markdown

## Done
- **Step 1 (model, NorthStar):** `value/scorecard.py` có `Figure`, `NorthStar`, `P2`, `P3`, `P4`, `ValueScorecard`, `BenchmarkSummary`.
  Công người tổng / trước / sau ready theo `ended_at` của lô; `machine_minutes` theo `processing_seconds` (đã có `scene.*`);
  `hardware_and_cost` gồm đỉnh VRAM/RAM của mọi lượt `completed` (kể cả `scene.*`) và chi phí = giờ GPU × đơn giá khai báo.
  Can thiệp = `scene_edit` origin human + `scene_request` origin human (key `request:<mode>`); origin system không đếm.
- **Step 2 (P2, P3):** `compute_p2` đo mỗi khe trên collision của revision layout của nó (`collision_world` → `gap_width`),
  sai số đoạn đo qua `distance_error`. `compute_p3` lấy phút đổi→thử từ `scene_edit` human sau `layouts.A.tagged_at` tới
  `walk_session` completed trên `layouts.B`, và `move_consistency` cho vật dời.
- **Step 3 (P4):** `level_from_checks` lấy bậc cao nhất mà mọi điều kiện của các bậc trước đều đạt; `reasons` là điều kiện còn thiếu
  của bậc kế tiếp. L1: xác nhận mét của revision hiện tại (`metric_scale` CONFIRMED) và `object_geometry` ready. L2: mọi vật cản
  chính có collider, ≥1 walk completed trên revision hiện tại, khe layout A không có `missed_obstacle`. L3: gói có candidate, lần
  validation được chọn cho candidate đó thuộc revision hiện tại, COMPLETED, `overall_result == PASS`. L4: cả ba ô khai báo True.
- **Step 4 (benchmark, xuất, route):** `benchmark_rows` (job mới nhất có `include_in_benchmark` mỗi project), `benchmark_summary`,
  CSV (BOM UTF-8, 14 cột theo Playbook, ô thiếu để trống), Markdown (bảng 5 dòng ở đầu). Sáu route trong
  `src/api/studio/value.py`, khai báo trong `test_role_matrix.py` (nhóm AUTHENTICATED).

## Files changed
- `src/services/orchestration/value/scorecard.py`: tạo mới (toàn bộ tính toán, ghép registry, xuất).
- `src/api/studio/value.py`: thêm 6 route GET + helper `_scorecard`, `_download`.
- `tests/test_orchestration/test_value_scorecard.py`: tạo mới.
- `tests/test_api/test_value_routes.py`: thêm 5 test route; thêm `benchmark_gpu_hourly_usd` vào SimpleNamespace settings của fixture `world`.
- `tests/test_api/test_role_matrix.py`: khai báo 6 route GET.
- `.ai/tasks/T-032/report.md`, `.ai/status.md`.

## Tests
Lệnh trong plan (kết quả thật):
```
.venv/bin/python -m pytest tests/test_orchestration/test_value_scorecard.py tests/test_api/test_value_routes.py tests/test_api/test_role_matrix.py -q
→ 63 passed (28 scorecard, 29 routes, 6 role matrix)

.venv/bin/ruff check src tests                 → All checks passed!
.venv/bin/ruff format --check src tests        → 684 files already formatted
.venv/bin/python scripts/check_contract_mirror.py → PASS
```
Test chính: công người trước/sau ready; can thiệp chỉ đếm human; phút máy cộng `scene.*` và chỉ giữ lượt mới nhất của pipeline;
chi phí declared và unavailable khi thiếu đơn giá; CPU-only không có giờ GPU; L0–L4 và reasons; P2 với world giả (khe đạt,
bỏ sót, vật giả), sai số `declared`; P3 (có, thiếu layout B, thiếu walk); **50k tam giác dưới 3 s** (đo thật, ~0.3 s cho cả file);
CSV BOM/14 cột/ô trống; Markdown 5 dòng + nhãn "đo, so với số thước" chỉ khi P2 đo được; summary; route 200/404, unavailable
khi chưa có truth, benchmark chỉ lấy job có cờ và job mới nhất mỗi project.

## Commits
- `f3722779` Start T-032 value scorecard (status: in-progress)
- `e2685452` Compute the value scorecard from events, usages and ground truth (Steps 1–3 và phần benchmark/xuất trong `scorecard.py`)
- `3df990cc` Serve value metrics as JSON, Markdown and CSV for jobs and the benchmark (Step 4: route, role matrix, route test)
- (commit báo cáo và trạng thái, xem git log sau khi ghi)

## Deviations from plan
1. **Step 1–3 gộp vào một commit.** Chúng cùng nằm trong `scorecard.py` và phụ thuộc lẫn nhau, tách commit sẽ phải dựng file
   giả. Step 4 (route) tách riêng.
2. **`NorthStar.interventions_total: Figure` (thêm).** Plan chỉ có `interventions: dict`. Không có Figure thì CSV "Can thiệp"
   không phân biệt được "chưa có sự kiện" với "0 lần" — cần để không ghi 0 giả.
3. **`P2.unavailable_reason`, `P3.unavailable_reason` (thêm).** Các trường đếm của P2/P3 là `int`, không có provenance. Khi chưa có
   ground truth, `gaps_checked = 0` sẽ trông như một phép đo. Khối unavailable thì có lý do rõ và các cột CSV để trống.
4. **`P2.gap_results` / `GapResult.gap_id` / `DistanceResult.distance_id` dùng như trong `measure.py`.** Không đổi.
5. **Đỉnh VRAM và RAM của job: `peak_vram_gb`, `peak_ram_gb`** lấy từ mọi lượt `completed`, gồm `scene.*` (đúng brief). Đỉnh
   chỉ tính trên usage đã đọc; không lọc theo `shared_gpu`.
6. **Hardware:** `vram_gb`, `cpu_count`, `ram_gb` để `null` (xem câu hỏi 1). Cột CSV "Phần cứng" chỉ có tên GPU, không có VRAM.
7. **`gpu_hours`** dùng đúng tập lượt tính tiền của `processing_seconds` (scene.* cộng dồn, pipeline chỉ lượt mới nhất theo
   tool), không cộng mọi lượt có `gpu_name`, để giờ GPU khớp với phút máy. Plan viết "tổng duration_seconds của usage có gpu_name".
8. **Hàm `_billed` là bản sao của quy tắc trong `observed.py`.** `processing_seconds` không trả về danh sách lượt đã chọn; tôi
   không sửa `observed.py` theo yêu cầu. Nếu quy tắc đổi thì phải đổi cả hai nơi.
9. **Khe không thuộc layout nào có revision** (thiếu layout) bị bỏ qua, không đếm: `gaps_checked` chỉ đếm khe đo được.
10. **L3 dùng lần validation được chọn** (`get_selection_for_candidate`), cùng đường với cổng xuất (`validation_gate.py`), không
    quét mọi run COMPLETED của candidate. Xem câu hỏi 2.

## Known issues / TODO
- **Hiệu năng benchmark:** `build_scorecard` gọi `load_usages` (toàn bảng) mỗi lần; `benchmark_rows` gọi `build_scorecard` cho
  từng project. Chưa đo trên DB lớn.
- Route GET dùng `require_contributor` nhưng không kiểm quyền sở hữu, vì đọc là chung cho workspace (giống danh sách project).
  Benchmark liệt kê mọi project (giống `list_projects`).
- Chưa chạy trên scene Studio thật (fixture `job-fixture-001` không có collider cho vật xuất nên P2/P3 là unavailable trong route test).

## Câu hỏi cho Architect (cần Architect)
1. **Phần cứng theo job.** Plan viết `hardware` lấy từ `MachineCapability` "benchmark snapshot của job". Nhưng
   `MachineCapability` lưu theo worker (`r2s_workers`, upsert, chỉ bản mới nhất) và không gắn với job. Hiện chỉ `gpu_name` và
   đỉnh VRAM/RAM của job có thể đo được; `vram_gb`, `cpu_count`, `ram_gb` để `null`. Cần quyết định: có ghi snapshot phần cứng
   vào job (manifest hoặc bảng mới) không? Nếu có, đó là thay đổi schema, tôi không tự làm.
2. **L3: "lần validation Isaac COMPLETED" là run nào?** Tôi chọn run được chọn cho candidate (cùng cổng xuất). Phương án khác:
   bất kỳ run COMPLETED nào của candidate có PASS. Hai cách khác nhau khi có run FAIL rồi PASS, hoặc PASS rồi FAIL.
3. **L4 và nhãn "khai báo".** Interface ghi `reasons` rỗng khi L4; bảng provenance ghi "ghi 'khai báo' trong reasons khi L4".
   Tôi làm theo interface (reasons rỗng), và ghi "(khai báo tay)" ngay trên dòng P4 của Markdown. Cần xác nhận.
4. **Thêm `interventions_total`, `unavailable_reason` cho P2/P3** (deviation 2–3 ở trên). Cần chấp nhận hoặc đổi.

Vì các câu hỏi này, trạng thái để `changes-requested` kèm "cần Architect". Code và test đã xong và đạt; nếu Architect chấp nhận
các lựa chọn trên, chuyển sang `implemented`.
