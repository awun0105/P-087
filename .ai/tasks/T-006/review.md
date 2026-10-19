# Review T-006

Verdict: ACCEPTED

Đã đọc `report.md`, toàn bộ `object_geometry_steps.py` và diff `objectify.py` (`8ad6c0e1..691e499c`). Chạy lại Tests required
cộng `test_membership_regeneration.py`, `test_objectgs_required_stage.py`, `test_scene_extraction.py`, `test_diagnostic_runners.py`:
107 passed.

## Acceptance criteria
1. Test cũ PASS không sửa assertion: **pass**.
2. Không còn bản sao logic: **pass**. Ba khối chuyển ra helper; `objectify()` gọi lại.
3. Test đơn vị cho ba hàm: **pass** (15 ca, gồm sàn nghiêng và huỷ).

## Kiểm hành vi được giữ nguyên
- Nhánh legacy vẫn gọi `_run` với `gaussians_ply` và **không** có kiểm tra nghiêm ngặt (cho phép OBB như cũ). Chỉ nhánh ObjectGS đi qua
  `run_surface_colliders`. Đúng.
- Thông điệp lỗi, đường dẫn artifact, artifact type, stage, thứ tự package → publish membership → kiểm huỷ → publish nền: giữ nguyên.
- CoACD và inpaint vẫn song song. Khi CoACD lỗi, `with ThreadPoolExecutor` vẫn chờ inpaint kết thúc rồi mới ném lỗi, tương đương code cũ.

## Quyết định Engineer (chấp nhận)
- Tách `run_inpaint` + tham số `inpaint_result` thay cho cờ `package=False`: gọn hơn.
- `before_publish` giữ thứ tự publish membership cũ: đúng.
- `footprint_centers` giữ phép kiểm tiếp xúc theo tâm nguồn cũ cho nhánh correction (sàn nghiêng): phát hiện tốt, có test.

## Suggestions (không chặn)
1. Helper import `_run`, `_reference`, `ObjectifyError`, … từ `objectify` ngay trong hàm để tránh vòng import. Chạy được, nhưng là
   mùi thiết kế. Khi có dịp (không bắt buộc trong chuỗi này), chuyển các primitive đó sang module nhỏ riêng
   (ví dụ `objectify_runtime.py`) và để cả hai module cùng import.
2. Thông điệp "ObjectGS surface collider generation failed…" sẽ sai ngữ cảnh khi T-007 dùng `run_surface_colliders` cho vỏ Gaussian.
   Đã ghi vào plan T-007: thêm tham số `surface_label` (mặc định "ObjectGS surface") để thông điệp nêu đúng nguồn.
