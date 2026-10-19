# Review T-032

Verdict: ACCEPTED (trả lời 4 câu hỏi; Architect tự sửa 4 lỗi, commit `8e71c6a2`)

Đọc trọn `value/scorecard.py` (850 dòng) và route mới trong `api/studio/value.py`. Chạy value_scorecard, observed_budget,
value_routes, evaluation: 95 PASS.

## Trả lời câu hỏi
1. **Phần cứng theo job: không cần đổi schema.** Runner đã ghi snapshot `machine` (MachineCapability) vào benchmark runtime của
   từng attempt: `artifact://jobs/{job}/benchmark/pipeline_runtime/attempt-{n}-{terminal|partial}.json`. Bảng đọc snapshot của
   attempt mới nhất có `machine` (terminal trước). Đã sửa. Ghi chú: đó là máy worker lúc job pipeline kết thúc; Tạo mesh chạy ở
   worker khác thì `gpu_name` của lượt đo vẫn đúng, còn VRAM/CPU/RAM tổng là của máy pipeline.
2. **L3 dùng run được chọn cho candidate** (cùng cổng xuất `validation_gate`): chấp nhận. Lý do: bảng phải khớp với điều kiện
   phát hành thật; "một run PASS bất kỳ" có thể che một run FAIL mới hơn đã được chọn.
3. **L4**: `reasons` rỗng + "(khai báo tay)" trên dòng P4 của Markdown: chấp nhận. T-034 hiển thị nhãn "khai báo" khi level = 4.
4. `interventions_total`, `unavailable_reason` cho P2/P3, `gpu_hours` theo tập lượt tính tiền, khe thiếu layout không đếm:
   chấp nhận.

## Lỗi tìm ra khi audit và đã sửa
1. **P3 bỏ sót thay đổi qua hàng đợi.** Mốc "đổi bố trí" chỉ xét `scene_edit` human; chỉnh vùng trên Ready và Brush/Lasso chỉ có
   `scene_request` human (revision kết quả là system) → P3 "unavailable" dù người dùng đã đổi. Sửa: `first_human_change_after`
   tính cả `scene_request` human, có test.
2. **Phần cứng để null** dù có snapshot (câu hỏi 1). Sửa + test đọc attempt mới nhất có snapshot.
3. **Quy tắc tính tiền bị chép hai nơi** (`_billed` và `processing_seconds`). Sửa: `observed.billed_usages` là nguồn duy nhất.
4. **Markdown vỡ bảng** khi tên scene có `|` hoặc xuống dòng. Sửa: `_md` escape.

## Suggestions (không chặn)
- `build_scorecard` đọc toàn bảng usage; `benchmark_rows` gọi cho từng project. Đo khi bộ benchmark > vài chục scene.
- Route benchmark liệt kê mọi project cho mọi contributor (giống danh sách scene hiện có); xem lại khi có nhiều tổ chức.
