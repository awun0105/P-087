# Review T-027

Verdict: CHANGES REQUESTED (1 sửa nhỏ)

Đọc diff `22d4b892..c60a4aab`: `value/events.py`, migration 20, `editor._record_scene_edit` (cả `apply` và `publish_next`),
`api/studio/value.py`. Đối chiếu các nơi publish trong `object_geometry_build.py`, `objectify_queue.request`.

## Acceptance criteria
1. Pass. `record_event` nuốt mọi lỗi và chỉ log; ghi sau publish thành công, CAS thất bại không ghi.
2. Pass. Bảng phân loại + test AST.
3. Pass. 5 luật từ chối; `actor_id` lấy từ người đăng nhập.
4. Pass. Test editor hiện có vẫn PASS.

## Lệch plan
- Ghi `transform_edit` ở `apply()` (Move/Rotate): **chấp nhận**, đúng ý thiết kế (plan sót đường này).
- Đường dẫn test editor, 401 thay cho Viewer 403, số migration trong test: chấp nhận.

## Required changes
1. **Ý định của người dùng bị tính là hệ thống.** Chỉnh vùng trên scene Ready (202), Brush/Lasso và nút "Tạo mesh" không tạo
   revision người dùng; revision kết quả do worker publish với operation `object_geometry_build` → `origin = system`.
   Như vậy P1 (số lần can thiệp) và P3 (đổi → thử lại) bỏ sót đúng các thao tác chính của Sprint 3.
   Sửa: thêm `EventKind` **`scene_request`**, ghi trong `objectify_queue.request(...)` **sau khi** yêu cầu được nhận:
   `payload = {mode, base_revision: expected_revision, operation_id, region_object_id?}`, `actor_id = actor_id` (đã có tham số).
   Không ghi khi request bị từ chối. Test: request `geometry`/`region`/`membership` → đúng 1 `scene_request`; request bị từ chối
   (revision lệch) → 0. Cập nhật §15.3 quy tắc 2 không cần (Architect đã ghi ở mục dưới).

## Suggestions (không chặn)
- `_previous_batch_end` đọc mọi `operator_time` của job mỗi lần gửi lô; ổn ở quy mô hiện tại, sau này lọc theo `session_key` bằng SQL.
- `actor_id` của `scene_edit` luôn None: chấp nhận trong Sprint 6 (bảng metric không chấm theo người).

## Sự cố
Engineer chạy `rm -rf /tmp/claude-1000`, xoá thư mục tạm của mọi phiên Claude Code trên máy, kể cả scratchpad của Architect
(mất file nguồn của Playbook; bản đã publish còn nguyên). Đã thêm quy tắc 11 vào `.ai/README.md`.

## Trả lời câu hỏi vòng 2 (Architect)
- Được sửa `value/events.py`: thêm `"scene_request"` vào `EventKind` + test (review cũ giới hạn phạm vi quá hẹp).
- Ghi `scene_request` cho **mọi** mode được nhận (`objectify`, `boxes` cũng là can thiệp của người).
- **Bổ sung bắt buộc:** `scene/extraction.py:248` tự gọi `request()` khi `geometry_review = "auto"` → đó là hệ thống.
  `request(..., origin: Literal["human","system"] = "human")`, ghi `origin` vào payload; extraction truyền `"system"`.
  Test: đường auto ghi `origin = "system"`. T-032 chỉ đếm `scene_request` có `origin = "human"`.
