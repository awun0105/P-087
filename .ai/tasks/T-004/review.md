# Review T-004

Verdict: ACCEPTED

Đã đọc `report.md`, toàn bộ `src/services/scene/editing/region_box.py`, diff contract `cfe5cd38`. Chạy lại:
pytest `test_region_box.py` + `tests/test_contracts` 299 passed; `check_contract_mirror.py` PASS; vitest
`region-box-model.test.ts` 55 passed (16 ca dùng chung từ `tests/fixtures/region_box_cases.json`).

## Acceptance criteria
0. Khoảng đóng [0.005, 20]: **pass** (biên trong/ngoài đều có test).
1–7. Bao trùm, thu nhỏ, phình sang nền, bảo vệ sàn, chồng lấn không claim, claim, box trừ: **pass**.
8. Vật đã Move: **pass**. Hàm chỉ nhận pose nguồn; test dùng pose xoay 90° quanh Z và kiểm pose sai cho kết quả sai.
   Việc truyền đúng `provenance.source_transform` là của caller (T-010, không phải T-009 như report ghi: roadmap đã đánh số lại).
9. Vật < 50 hàng → lỗi gợi ý Xoá vật: **pass**.
10. Kiểm revision/checksum: đúng là trách nhiệm caller; T-010 bước 2 đã có. **pass** cho phạm vi task.
11. `apply_resolution` không sửa đầu vào: **pass**.
12. 300.000 hàng 0,07 s (ngưỡng 0,3 s): **pass**.

## Correctness
- Đổi world → local: `(p − t) @ R` ≡ `Rᵀ(p − t)` theo vector hàng: đúng.
- Công thức box khớp `contains()` frontend; xác nhận bằng file ca dùng chung chạy cả pytest lẫn vitest.
- Hàng claim từ vật khác nằm trong `added` và nhận nhãn của vật đang sửa: đúng.
- Điểm NaN/inf luôn ở ngoài box: đúng.

## Quyết định Engineer tự đưa ra (chấp nhận)
- Từ chối vật tự claim chính nó và id lạ trong `claim_from`: hợp lý, an toàn.
- Thêm hai model vào `check_contract_mirror.py`: đúng, không có thì mirror không kiểm gì mới.
- File test contract mới `test_object_region_command.py`: được.

## Required changes
Không có.

## Suggestions (không chặn)
- `resolve_region` kiểm shape của `labels` nhưng không kiểm kiểu số nguyên. Caller (T-010) đọc nhãn qua
  `decode_gaussian_membership_labels` nên luôn là int32; nếu muốn chặt hơn, thêm `np.issubdtype(labels.dtype, np.integer)`.
