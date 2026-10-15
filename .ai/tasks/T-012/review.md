# Review T-012

Verdict: CHANGES REQUESTED (nhỏ; chốt các thao tác ngoài bảng)

Đã đọc `report.md`, diff `1cd7a859`, `00404b8b`, `3f417bd3`, và `restore_revision`. Chạy lại 8 file test liên quan
(gồm `test_object_restore.py`): 161 passed.

## Acceptance criteria
1. Draft: Move/Rotate/sửa collider bị từ chối, scene không đổi: **pass** (422 theo mapping sẵn có của `SceneEditRejectedError`).
2. Draft: Confirm/Ignore/Hide/Delete/Restore thành công: **pass**.
3. Draft: Walk và simulation-package → 409 với "Cần tạo mesh…": **pass**.
4. Scene ready/cũ không đổi hành vi: **pass**.

## Lệch plan (chấp nhận)
- Chặn USD trong `build_simulation_package()` thay vì route: tốt hơn, mọi đường gọi đều bị chặn.
- Chặn Walk không phụ thuộc `scene_revision`: đúng, vì preview của Studio không gửi revision.
- Head không đọc được → 409 thay vì phục vụ preview thô: fail-closed, đúng hướng.

## Quyết định cho các thao tác ngoài bảng
| Thao tác | Draft | Lý do |
| --- | --- | --- |
| `restore_revision` | **Cho phép** | Chép trọn environment + objects + provenance của revision đích, nên luôn nhất quán: về revision Ready thì collider khớp membership của chính nó; về revision Draft thì quay lại duyệt. Một build đang chạy sẽ tự thất bại vì fence revision. |
| Thêm box, thêm vật từ catalog, nhân bản | **Chặn** | Vật người dùng thêm cần Move để đặt chỗ, mà Move đã khoá trong Draft; đặt vật mới là việc của bước sau khi có hình học. |
| Sửa collision surfaces (môi trường) | **Chặn** | Draft chưa có collision môi trường object-aware; sửa trên mesh canonical rồi sẽ bị build thay thế. |
| Gán nhãn (label) | **Cho phép** | Chỉ là ngữ nghĩa, không đụng hình học. |

## Required changes
1. Gọi `require_geometry_ready(scene, action)` ở:
   - `add_box_object` (`"thêm vật"`), `add_catalog_object` (`"thêm vật từ thư viện"`), nhân bản (`"nhân bản vật"`; nếu nhân bản đi qua
     `apply_object_action` thì chặn đúng action đó, không chặn cả hàm),
   - `edit_collision_surfaces` (`"sửa bề mặt va chạm"`).
2. Test cho từng chỗ: Draft → `ObjectGeometryNotReadyError`/HTTP 422 qua route tương ứng, không publish revision; scene ready → như cũ.
3. Test `restore_revision`: từ revision Ready khôi phục về revision Draft → `object_geometry == "awaiting_review"`; từ Draft khôi phục về
   Ready → `"ready"` và collider/`object_aware_collision_ref` đúng của revision đích.
4. Chạy lại đúng nhóm test đã chạy + file test của các hàm trên; ruff. Thêm "Round 2" vào report, đặt `implemented`.

## Ghi chú
- Studio vẫn gửi Walk/USD khi Draft cho tới T-013 (khoá nút). Chấp nhận trong khoảng giữa hai task.
- Về câu "answer with text only, no tool calls": không có yêu cầu đó. Agent làm đúng khi tiếp tục làm task.
