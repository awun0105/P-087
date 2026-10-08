# 0026 Hiệu chỉnh ước lượng tài nguyên theo số đo và tách auto-tune RAM/VRAM

Date: 2026-10-08

## Status

Proposed — chờ owner duyệt. Kế hoạch triển khai: [AUD-26](../plans/active/2026-10-07-codegraph-audit/tasks/AUD-26-decoupled-resource-tuning-and-observed-budget.md).

## Context

[`resources.py`](../../src/services/orchestration/processing/resources.py) làm hai việc:
`evaluate` cảnh báo trước khi chạy (và chặn tạo job khi vượt năng lực máy), còn
`maximum_for_machine` đề xuất bộ thông số "tối đa cho máy này". Cả hai dựa trên
`estimate_gb` với các hệ số trong `configs/product/processing_presets_v1.json`. Ghi chú
của file preset nói rõ các hệ số này là heuristic từ một lần chạy 51 frame.

Bảng `r2s_resource_usage` nay đã có số đo thật của 6 job trên hai GPU. Đối chiếu ngày
2026-10-08 cho thấy:

| Preset | Frame thật | Peak RAM đo | RAM ước lượng | Peak VRAM đo | VRAM ước lượng |
|---|---|---|---|---|---|
| tối thiểu | 50 | 1,04 GB | 7,08 | 2,03 GB | 2,22 |
| tối thiểu | 149–174 | 1,46–1,53 GB | 7,08 | 2,63 GB | 2,22 |
| tối đa | 546 | 2,83–4,20 GB | 87,59 | 4,31 GB | 10,30 |

Ba vấn đề:

1. RAM bị ước lượng cao hơn thực tế 5–20 lần, do số hạng
   `frames * decode_mp * ram_per_decode_megapixel_gb`.
2. VRAM ở preset tối thiểu bị ước lượng thấp hơn thực tế.
3. `maximum_for_machine` dùng một hệ số nội suy chung cho mọi thông số. Vì RAM bị ước
   lượng quá cao, RAM luôn là ràng buộc quyết định: máy 6 GB VRAM và máy 24 GB VRAM
   cùng 16 GB RAM nhận cùng một kết quả. Thiết kế "mọi thông số tăng cùng nhịp" là chủ ý
   ban đầu (docstring của `interpolate`); ADR này thay thế chủ ý đó.

Ngoài ra, hàng đợi admission đã dùng `observed_budget` (số đo của lượt chạy cũ) thay
cho ước lượng khi có, còn `evaluate` thì không, nên UI và admission có thể kết luận
khác nhau về cùng một cấu hình.

`_fits` đã yêu cầu `required < available * warn_ratio` với `warn_ratio = 0,75`, tức đã
có khoảng đệm 1,33 lần.

## Quyết định đề xuất

1. **Giữ nguyên dạng công thức của `estimate_gb`, chỉ đổi giá trị hệ số theo số đo.**
   `ram_base_gb = 0.9`, `ram_feature_bytes = 420`, `ram_per_decode_megapixel_gb = 0`,
   `vram_base_gb = 1.25`. Quy tắc chọn: với mọi lượt chạy hoàn tất đã đo, ước lượng tính
   theo số frame thật phải lớn hơn hoặc bằng số đo. Với các hệ số này, ước lượng cho ba
   điểm RAM ở bảng trên là 1,07 / 1,50 / 4,66 GB, và preset tối đa là 9,16 GB.
2. **Không đổi công thức RAM sang dạng "số ảnh giải mã đồng thời theo số luồng".** Đó là
   một giả thuyết về cách COLMAP dùng bộ nhớ; chưa có số đo nào chứng minh, và nó cho ra
   ước lượng không còn phụ thuộc số frame.
3. **Tách `maximum_for_machine` thành hai lần tìm kiếm nối tiếp.** Lần một tìm nhóm SFM
   (`sampling.*`, `colmap.*`) theo RAM và đĩa. Lần hai giữ kết quả đó và tìm nhóm SPLAT
   (`brush.*`) theo cả VRAM, RAM và đĩa. Kết quả cuối luôn thỏa `_fits` cho cả ba tài nguyên.
4. **`evaluate` nhận số đã đo qua tham số tùy chọn.** Lớp API tính sẵn bằng
   `observed_budget` rồi truyền vào; `resources.py` vẫn là hàm thuần. `maximum_for_machine`
   không dùng số đã đo, vì `observed_budget` chỉ có giá trị cho cấu hình không nặng hơn
   những lượt đã chạy.
5. **Giữ `warn_ratio = 0,75` và `danger_ratio = 0,92`.** Không thêm hệ số đệm nào khác.
6. **Không thêm mức sàn cho `scene_extract` vào mô hình.** Số đo của bước này đi vào
   `evaluate` qua quyết định 4 khi máy đã có lịch sử.

## Hệ quả

- Schema của `ResourceModel`, `Evaluation`, `MachineCapability`, `ResourceUsage` không
  đổi. Chỉ đổi giá trị trong file preset, chữ ký của `evaluate` (thêm tham số có mặc
  định) và nội dung chuỗi `message`.
- Điều kiện chặn tạo job (`evaluation.blocking`) sẽ chặn ít hơn vì ước lượng RAM giảm.
- `scripts/gpu/gpu_plan.py` chia worker theo `estimate_gb`; ước lượng RAM giảm sẽ cho
  phép nhiều worker song song hơn trên máy thuê.
- Máy 24 GB VRAM / 16 GB RAM nhận 6 triệu splat và 3.840 px thay vì 1,9 triệu và 1.760 px.

## Giới hạn đã biết

- Số đo chỉ tới 546 frame thật. Vùng 547–2.000 frame là ngoại suy tuyến tính; cần ít
  nhất hai lượt chạy ≥ 1.000 frame để xác nhận.
- Chưa biết số Gaussian cuối cùng của từng lượt đo, nên hai hệ số VRAM theo splat và
  theo megapixel chưa được hiệu chỉnh.
- Máy chưa có lịch sử chạy thì UI chưa cảnh báo được nhu cầu của `scene_extract`
  (một lượt đo: 5,19 GB RAM, 3,42 GB VRAM).
