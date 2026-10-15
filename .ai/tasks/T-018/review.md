# Review T-018

Verdict: ACCEPTED

Chỉ thêm test (`tests/test_scene/test_shell_geometry_walk_usd.py`), không sửa `src`. Chạy lại cùng
`test_effective_collision.py`, `test_object_aware_composition.py`, `test_object_aware_usd.py`, `test_simulation_package.py`:
40 passed, không skip (CoACD thật + pxr từ `data/scene_runtime`).

## Acceptance criteria
1. Mọi nơi đọc surface chấp nhận vỏ lẫn ObjectGS: **pass** (rà USD inventory, retention, shell manifest; không có chỗ giả định chỉ ObjectGS).
2. E2E vỏ: Confirm → Move +1 m x + xoay 90° → không ghost (0 tam giác trên sàn ở dấu chân cũ, sàn còn 354 tam giác), Walk và USD đúng pose,
   scale 1, không carve hai lần; Move/Rotate thuần pose không xếp việc: **pass**.
3. Scene legacy và ObjectGS cũ (không có khóa `object_geometry`) giữ Walk/sửa/đóng gói: **pass**.

## Quyết định Engineer (chấp nhận)
- Dung sai kích thước collider 0,12 m (vỏ + CoACD nở ~0,09 m mỗi trục); kiểm xoay bằng thứ tự x > y: hợp lý.

## Trả lời câu hỏi
- `object_centric` cho scene vỏ: **đúng như ý**. `objectify_queue.py:270` trả true khi `object_extraction == METHOD`, mà Draft (T-005) ghi đúng
  giá trị đó; điều kiện `geometry_method == "objectgs"` chỉ là nhánh phụ. Studio ẩn thông báo "tách lại" cho scene vỏ.

## Chuyển sang T-019
1. Collider của vật vỏ xuất hiện ở cả `geometry` và `colliders` trong USD inventory: thừa, không lỗi. Ghi vào handoff, chưa sửa.
2. Chưa có test `build_simulation_package` cho scene vỏ: T-019 thêm một test (Draft → build → Confirm → package → kiểm inventory).
