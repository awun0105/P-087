# Review T-025

Verdict: ACCEPTED

Đọc diff `region_box._box_contains`, `resolve_region(points_local=…)`, `object_region._resolve`, cache trong
`membership_regeneration.py`, `Settings.product_region_source_cache_mib`.

## Acceptance criteria
1. Pass. Benchmark `scripts/scene/bench_region_preview.py`; warm 16 box 2M hàng có SH 1,48 → 1,19 s (máy dev). Cold ~4 s, ngoài mục tiêu (đúng tiêu chí).
2. Pass. Test budget 300k 5/5 (0,50–0,76 s).
3. Pass. Kết quả preview giống hệt (hash) trước/sau. Lọc sơ bộ dùng hình vuông bán kính `hypot(half_x, half_y)+tol`, là tập cha
   của mọi điểm trong box ở mọi yaw; sai số làm tròn ≪ `_NEAR_SLACK_M`.
4. Pass. Khoá chỉ bảo vệ bảng; một lần đọc mỗi khoá qua `Future`, lỗi được truyền cho người chờ; khoá cache theo PLY nguồn nên
   Apply đổi nhãn không đọc lại PLY; nhãn vẫn đọc và kiểm checksum mỗi lần.

## Lệch plan
Làm tối ưu box trước vì profile cho thấy đó là chỗ nghẽn; bỏ bước 4 vì đã đạt mục tiêu: chấp nhận.
