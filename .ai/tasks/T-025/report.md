# Report T-025

## Done
- **Benchmark (acceptance 1):** `scripts/scene/bench_region_preview.py` dựng scene 2M Gaussian đủ SH (degree 3, 59 trường) có
  sàn, một vật và nền, qua đường đi thật của membership (PLY, nhãn, floor fit, vỏ). Đo cold/warm cho 1 và 16 box, p50/p95,
  RSS, và tuỳ chọn cProfile. Không đo HTTP hay trình duyệt.
- **Tối ưu hoá box (chiếm phần lớn thời gian):** `_box_contains` lọc trước các hàng trong hình vuông bao quanh box, rồi
  công thức gốc chỉ chạy trên ứng viên khi chúng là phần nhỏ; khi ứng viên nhiều thì chạy trên cả đám mây như trước.
  Kết quả giống hệt công thức gốc (test tương đương trên mặt box, box xoay, điểm NaN/inf).
- **Một phép đổi world → object-local mỗi preview:** `_resolve` đổi một lần và truyền xuống `resolve_region`.
- **Khoá chỉ bảo vệ bảng cache:** PLY được đọc và fit sàn ngoài khoá; yêu cầu đồng thời cùng nguồn chờ một lần đọc chung.
- **Cache theo PLY, có ngân sách byte:** khoá là (job, checksum PLY), không theo nhãn, nên Apply không đọc lại PLY. Mục cũ nhất
  bị bỏ khi vượt `product_region_source_cache_mib` (mặc định 1024 MiB); mục mới nhất luôn được giữ. Nhãn vẫn được giải mã và
  kiểm checksum mỗi lần.
- **Không làm bước 4 (lọc kNN của vỏ):** sau các bước trên, warm 16 box còn 1,15–1,19 s, dưới giới hạn 1,5 s; `_filter_gaussians`
  chỉ còn ~0,3 s trên ≤100 000 hàng đã chọn. Không có lý do đụng vào thuật toán vỏ.

## Files changed
- `scripts/scene/bench_region_preview.py` (mới): benchmark.
- `src/services/scene/editing/region_box.py`: `_box_contains` lọc ứng viên; `resolve_region` nhận `points_local`.
- `src/services/orchestration/scene/object_region.py`: `_resolve` đổi một lần và truyền `points_local`.
- `src/services/orchestration/scene/membership_regeneration.py`: cache theo PLY, ngân sách byte, khoá chỉ bảo vệ bảng, in-flight.
- `src/config.py`: `product_region_source_cache_mib`.
- Test: `tests/test_scene/test_region_box.py` (tương đương, 10 trường hợp), `tests/test_scene/test_membership_regeneration.py`
  (ngân sách, hai job không chặn nhau, đọc một lần cho yêu cầu đồng thời; test "bounded" đổi sang ngân sách byte).
- Evidence: `.ai/tasks/T-025/evidence/` (JSON lines của benchmark, cProfile dạng text, hai file so sánh kết quả).

## Commits
- `de6bba6f` Add a region preview benchmark with cold and warm timings (benchmark + số liệu gốc)
- `d2f2ffd2` Test only candidate rows against each box and reuse object-local points (bước 1 và 2 của plan: box, transform)
- `a50ec684` Read source PLY outside the cache lock, keyed by PLY, within a byte budget (bước 3 và 4 của plan: lock, cache)
- `3f964a2a` Apply ruff formatting to the preview benchmark and cache tests
- Báo cáo và trạng thái: commit riêng ở cuối task.

## Measurements
Máy: Linux 7.0.0, 12 nhân, 30 GB RAM. Scene: 2 000 000 Gaussian, SH bậc 3 (59 trường), 25% sàn, 60% hàng thuộc vật
(1 200 000 hàng), phần còn lại nền. Mỗi số là lần đo khi không có việc nặng khác chạy cùng (trừ lần đo đầu, xem Known issues).
Warm p50 là trung vị của 3–5 lần gọi liên tiếp sau lần cold.

| Cấu hình | Trước (`de6bba6f`) | Sau box (`d2f2ffd2`, adaptive) | Sau cache (`a50ec684`) |
| --- | --- | --- | --- |
| 1 box, cold | 4,56 s | 4,45 s | 4,20 s |
| 1 box, warm p50 / p95 | 0,649 / 0,692 s | 0,628 / 0,695 s | 0,566 / 0,581 s |
| 16 box, cold | 4,10 s | 4,87 s | 3,85 s |
| 16 box, warm p50 / p95 | 1,483 / 1,531 s | 1,184 / 1,205 s | 1,195 / 1,218 s |
| RSS đỉnh | ~1,14 GB | ~1,15 GB | ~1,14 GB |

Ghi chú: lần đo "sau box" đầu tiên (`bench-step1-boxfilter.jsonl`, lọc không thích nghi) làm 1 box chậm lên 0,88 s vì sao
chép ứng viên tốn hơn; đã sửa bằng ngưỡng tỉ lệ ứng viên (xem `_CANDIDATE_SHARE_LIMIT`). Lần đo đó được giữ làm bằng chứng.

Cold không giảm nhiều: thời gian cold chủ yếu là đọc PLY 472 MB, băm checksum và fit sàn, và các bước đó vẫn chạy một lần
cho mỗi nguồn. Phần khoá thu hẹp chỉ tác động khi có nhiều yêu cầu đồng thời hoặc nhiều job.

Profile warm 16 box sau mọi thay đổi (`profile-warm-16box-after-cache.txt`): tổng 1,19 s; `_box_contains` 0,68 s (16 lần, ~42 ms
mỗi lần, quét cả đám mây mỗi box); `_shell` 0,36 s (`_filter_gaussians` 0,30 s); `_local` 0,045 s; giải mã nhãn 0,045 s.
Trước đó (`bench-profile-baseline.jsonl`): tổng 1,50 s với `_box_contains` 0,91 s.

Budget test 300k (`test_preview_three_hundred_thousand_rows_budget`), chạy riêng 5 lần: 0,539 · 0,504 · 0,755 · 0,539 · 0,564 s,
đều PASS (giới hạn 1,5 s).

Tương đương kết quả (acceptance 3): `equivalence-pre.json` và `equivalence-post.json` có cùng hash SHA-256 của toàn bộ kết quả
preview (đếm, mẫu, GLB vỏ, cả hai lần gọi giống nhau) cho ba cấu hình trên fixture 20 000 hàng: 1 box, 16 box, và một box
nhỏ lệch tâm (10 195 hàng bị lấy đi, 1 805 còn lại). Trong fixture này không có hàng nào được thêm (`added_count` = 0) nên
đường thêm hàng được kiểm bằng các test hiện có.

## Tests
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_scene/test_membership_regeneration.py -q
→ 40 passed
.venv/bin/python -m pytest tests/test_scene/test_region_box.py tests/test_scene/test_object_region.py -q -k "not three_hundred_thousand"
→ 80 passed, 2 deselected (chạy sau thay đổi box, trước thay đổi cache)
.venv/bin/ruff check src tests scripts    → All checks passed!
.venv/bin/ruff format --check src tests scripts → 747 files already formatted
```
Test đồng thời (acceptance 4): `test_cold_read_of_one_job_does_not_block_another_job` (job khác không bị chặn khi một job đang đọc
PLY) và `test_concurrent_requests_for_one_source_read_the_ply_once` (yêu cầu cùng nguồn đọc PLY đúng một lần).

## Deviations from plan
- **Thứ tự và trọng tâm:** plan xếp "một phép đổi world → local" đầu tiên. Profile cho thấy đó chỉ là ~0,05 s; phần lớn là
  `_box_contains`, nên bước đó được làm trước. Bước đổi world→local vẫn làm (trong cùng commit với box).
- **Commit:** bước box và bước world→local nằm chung commit `d2f2ffd2` vì cùng sửa `region_box.py`; bước khoá và cache
  nằm chung `a50ec684` vì cùng sửa `membership_regeneration.py`. Không tách hunk bằng `git add -p` (không tương tác).
- **Bước 4 (kNN của vỏ):** không làm; không vượt ngưỡng sau các bước trước.
- **Cấu hình:** `product_region_source_cache_mib` đọc qua `get_settings()` mỗi lần gọi vì `load_membership_source` không nhận
  settings; điều này đọc lại biến môi trường mỗi preview.
- **Fixture benchmark:** dùng `_fixture` của test thay vì dựng pipeline thật; object chiếm 60% hàng (nặng hơn một vật thường)
  để đo trường hợp xấu. Sàn được fit thật (không stub như test budget).

## Known issues / TODO
- Lần đo cold đầu tiên (`bench-baseline.jsonl`, `bench-step1…`) chạy lúc có tiến trình nền khác; số warm lặp lại ổn định trong
  ±0,03 s giữa các lần chạy trong cùng một phiên, nhưng chưa đo nhiều phiên.
- Preview cold vẫn ~4 s trên 2M hàng; nếu cần dưới 1,5 s cả khi cold, phải đổi cách đọc PLY (chưa làm, ngoài phạm vi).
- Chưa đo HTTP và trình duyệt (theo plan).
- Chưa chạy full suite (T-019 lo).
