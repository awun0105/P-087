# Report T-031: Máy đo khe, sai số, nhất quán sau khi dời

## Done
- **Step 1 (sai số đoạn đo, bề rộng khe):** `distance_error` và `gap_width` trong `value/measure.py`. Quét z từ h_min theo bước 0,05 m tới h_max. Mỗi phía chặn ở |b−a|/2. Bề rộng = nhỏ nhất theo z. Trung điểm nằm trong vật kín → bề rộng 0. Phân loại `ok`, `missed_obstacle`, `false_obstacle` theo quy tắc 3.
- **Step 2 (collision tổng hợp):** `collision_world(registry, job_id, revision)` và phần thuần `compose_collision_world`. Môi trường đã khoét cộng collider của mọi vật mà USD xuất (`resolve_representation(...).export_as_object`, cùng quy tắc với `scene_representations`). Pose collider = t_obj + R_obj·t_local, R = R_obj·R_local (cùng công thức với `composeColliderTransform` phía frontend).
- **Step 3 (nhất quán sau khi dời):** `move_consistency`. Vật được coi là dời khi dịch > 1 cm hoặc quay > 1°. `old_cleared`: không tam giác nào của vật khác (không tính chính vật đó) giao hộp tại pose A thu 2 cm mỗi mặt, trong dải z của robot. `new_present`: vật còn tam giác trong collision B. Giao tam giác–hộp dùng SAT vector hoá.

## Files changed
- `src/services/orchestration/value/measure.py`: tạo mới, toàn bộ máy đo.
- `tests/test_orchestration/test_value_measure.py`: tạo mới, 23 test.
- `.ai/tasks/T-031/report.md`, `.ai/status.md`: báo cáo và trạng thái.

Không sửa `objectify_queue.py`, `observed.py`, `scorecard.py`, `runner.py` (theo yêu cầu). Các file này và `events.py`, `admission.py`, `scorecard.py` đang có thay đổi chưa commit của agent khác; commit T-031 chỉ stage đúng hai file trên.

## Tests
```
.venv/bin/python -m pytest tests/test_orchestration/test_value_measure.py -q
→ 23 passed

.venv/bin/ruff check src tests                  → All checks passed!
.venv/bin/ruff format --check src tests         → 682 files already formatted
```
Kiểm tra thêm (không commit): 3000 tam giác–hộp ngẫu nhiên, SAT không bỏ sót tiếp xúc nào so với lấy mẫu điểm trên tam giác (0 false negative).

## Commits
- `7ded41fd` Start T-031 measurement functions (status: in-progress)
- `f1567f28` Measure segment error and gap width on the collision world
- `f8c70d10` Compose the collision world with the object colliders the USD export includes
- `3bce518d` Check that moved objects clear their old footprint and reappear at the new pose

## Deviations from plan
1. **`CollisionWorld` có thêm `face_owner` và `solid_owners`.** Plan chỉ ghi `mesh`. Không có nhãn chủ sở hữu từng tam giác thì không thể loại tam giác của chính vật khi kiểm vết cũ, cũng không biết vật nào kín để kiểm "bên trong".
2. **`DistanceResult` và `GapResult` có thêm `distance_id` / `gap_id`.** Scorecard cần id để tham chiếu từng khe và từng đoạn đo.
3. **Ray–tam giác viết bằng numpy (Möller–Trumbore), không dùng `trimesh.ray`.** Môi trường không có `rtree`, `trimesh.ray.RayMeshIntersector` lỗi khi gọi. Không cài thêm thư viện.
4. **`collision_world` không gọi `effective_collision_for_revision`.** Hàm đó chỉ nhận revision hiện tại, còn `world_a` là revision cũ. Thay vào đó: `registry.scene.revision(job, rev)` rồi `effective_environment(...)`. Không chạy `_recover_legacy_source_ownership` vì hàm này có thể publish. Hệ quả: revision cũ thiếu quyền sở hữu nguồn sẽ bị từ chối với `SourceCollisionOwnershipError` (fail closed).
5. **`old_cleared` không tính tam giác của chính vật đang dời.** Plan ghi "không tam giác nào của world_b". Đọc đúng chữ thì collider mới của vật (ở B) có thể làm vết cũ bị tính là chưa khoét khi hai pose chồng nhau. Tôi loại tam giác của chính vật. **Đây là quyết định Architect cần xác nhận.**
6. **Kiểm "bên trong" chỉ áp dụng cho vật kín.** Parity của tia không đúng với mesh hở. Môi trường đã khoét là mesh hở, nên không dùng để kiểm điểm giữa khe.
7. **Chưa rõ trong plan, tôi chọn:**
   - Khe có đoạn nằm dọc (không có hướng ngang) → `ValueError`.
   - Hộp thu 2 cm bị rỗng (vật quá nhỏ) → `old_cleared = False` (không kiểm được thì không coi là đạt).
   - Vết cũ nằm hoàn toàn ngoài dải z của robot → `old_cleared = True` (đúng chữ plan: không có tam giác nào trong dải để kiểm).
   - `new_present` = vật còn tam giác trong `world_b`. Tam giác của collider luôn nằm trong hộp bao của chính nó, nên kiểm trong hộp là thừa.

## Known issues / TODO
- **Đường `collision_world` đi qua registry chưa có test end-to-end.** Fixture seed có vật xuất mà không có collider (`object-floor-001`), nên `compose` từ chối đúng như USD. Test hiện có: revision không tồn tại (`SceneError`), và sự khớp chọn vật với `scene_representations` trên fixture thật. Phần ghép môi trường đã khoét + collider qua registry cần một scene có collider để kiểm.
- Hiệu năng `gap_width` (24 độ cao × 2 tia, lọc tam giác theo z) và `move_consistency` (SAT trên toàn bộ tam giác B) chưa đo trên lưới lớn.
- Chưa chạy trên scene Studio thật.
