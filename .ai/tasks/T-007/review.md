# Review T-007

Verdict: CHANGES REQUESTED (một lỗi do plan của Architect; phần còn lại đạt)

Đã đọc `report.md` và toàn bộ `src/services/orchestration/scene/object_geometry_build.py`. Chạy lại
`test_object_geometry_build.py`, `test_object_geometry_steps.py`, `test_gaussian_shell.py`: 68 passed (gồm CoACD thật, không skip).

## Đạt
- Kiểm revision, Draft, membership/nguồn, checksum PLY nguồn trước khi làm gì.
- Hàng lấy từ PLY nguồn world; đổi local bằng `(p − t) @ R` của `source_transform` (≡ Rᵀ(p − t), scipy dùng xyzw): đúng quy tắc khung.
- `shell_error` chặn build với thông điệp có tên vật; không tạo collider OBB nào.
- Publish idempotent kiểm bytes; huỷ kiểm ở mọi phase và trong `publish`; một revision duy nhất qua `publish_next` + `commit_guard`.
- Vỏ rỗng qua CoACD thật: 8/8 mảnh (bằng `max_convex_hull`), bounds lệch ≤ 0,04 m, ~20 s. Không có mass/inertia từ volume.
- `surface_label="Gaussian shell"` cho thông điệp lỗi: đúng.
- Bind `source_collision` bằng pose nguồn khi thiếu, giữ transform hiện tại: đúng.

## Lỗi phải sửa (do plan)
Plan tiêu chí 7 bảo "vật Ignored/Deleted không được dựng". **Sai.** Compositor Walk/USD
(`src/services/scene/effective_collision.py::_object_aware_environment`) duyệt **mọi** vật trong `removed_object_ids` (= mọi vật
trong membership). Vật nào không bị loại khỏi nền (IGNORED, CANDIDATE chưa xác nhận, MERGED vào vật đang giữ) sẽ được **khôi phục
collider tại pose nguồn**, và raise `source collider is required by object-aware composition` nếu `collider is None`.
Hệ quả hiện tại: scene Ready có một vật IGNORED → Walk/USD lỗi; vật DELETED được Restore sau đó → lỗi.

## Required changes
1. `build_object_geometry`: khi `object_ids is None`, dựng vỏ + collider cho **mọi** vật có trong `membership.label_to_object_id`,
   bất kể `review` (IGNORED, DELETED, MERGED đều dựng). Khi `object_ids` được truyền (T-011), dựng đúng tập đó.
   Vật có `shell_error` vẫn chặn build như hiện tại (không đổi).
2. Sửa test `@pytest.mark.parametrize("review", ["IGNORED", "DELETED", "MERGED"])` (dòng ~389): khẳng định các vật đó **có** collider
   sau build.
3. Thêm test tích hợp: sau build, gọi `effective_environment(...)` (hoặc `compose_effective_collision`) trên scene Ready có
   - một vật IGNORED → thành công, collider của nó xuất hiện tại pose nguồn trong mesh kết quả;
   - một vật DELETED → thành công, không có collider của nó;
   - Restore vật DELETED (`apply_object_action(..., "restore")`) rồi compose lại → thành công.
4. Chạy lại: `test_object_geometry_build.py`, `test_object_geometry_steps.py`, `tests/test_scene/test_effective_collision.py`,
   `tests/test_scene/test_object_aware_composition.py`; ruff. Thêm "Round 2" vào report, đặt `implemented`.

Architect đã sửa tiêu chí 7 trong `plan.md` và ghi chú vào T-011 (rebuild một phần cũng phải giữ quy tắc này).

## Suggestions (không chặn)
- Đoạn gom `processing.scene` thành nhóm `scene/coacd/inpaint` lặp lại logic trong `objectify_with_retry`. Khi có dịp, tách thành một hàm
  dùng chung (ví dụ `objectify_config_for_job(registry, job)`).
- `fit_canonical_floor_model` được tính lại từ PLY nguồn; kết quả xác định nên trùng với lúc tách. Chấp nhận.

---

# Review T-007 — Round 2

Verdict: ACCEPTED

Đã đọc diff `dc7d547c`: bỏ lọc theo `review`, giờ dựng cho mọi vật trong membership (hoặc đúng `object_ids` nếu được truyền).
Chạy lại `test_object_geometry_build.py`, `test_object_geometry_steps.py`, `test_effective_collision.py`,
`test_object_aware_composition.py`: 58 passed. Ruff sạch.

## Required changes Round 1
1. Dựng collider cho mọi vật trong membership, giữ nguyên review/state: **pass**.
2. Test cũ đổi thành khẳng định IGNORED/DELETED/MERGED **có** collider: **pass** (`test_review_tombstones_keep_review_and_receive_colliders`).
3. Test tích hợp với compositor thật (`compose_effective_collision`): IGNORED → collider khôi phục đúng bounds tại pose nguồn; DELETED → không
   có; Restore vật DELETED → compose lại thành công với cùng collider: **pass**.
4. `object_ids` tường minh chỉ dựng đúng tập đó: có test riêng, **pass**.

## Ghi chú
- Mục "Verification" trong report vẫn ghi số của vòng 1 (68 passed); số đo vòng này là của Architect ở trên. Lần sau cập nhật số trong mục Round.
