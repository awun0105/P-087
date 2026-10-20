# T-052 report
- `scene/collision_cache.py` (mới): `CollisionKey` (job, revision, checksum + URI nguồn, preview, khung, config checksum; `etag` tính trước khi dựng), `CollisionPayload`, `WalkCollisionCache` (bộ nhớ ≤4 mục/256 MB + đĩa, khoá theo key, `prune(7 ngày)`).
- Route `/walk-collision` nhánh có `scene_revision`: kiểm quyền + kiểm revision là head → 304 nếu `If-None-Match` khớp → đọc đệm hoặc dựng một lần; trả `private, max-age=31536000, immutable`. Thư mục đệm `ARTIFACT_ROOT/../cache/walk-collision`; dọn file cũ một lần mỗi tiến trình ở luồng nền.
- Đo (payload 29 MB): đọc từ đĩa 107 ms (gồm kiểm sha256), từ bộ nhớ 0,1 ms; lần dựng đầu giữ nguyên (~0,8–1,1 s theo khảo sát).
- Test: test_collision_cache (7), 4 test route trong test_scene_routes.py.
- Lệch plan: chỉ đệm nhánh có `scene_revision` (nhánh xem trước theo bản tái dựng rẻ và có test cố ý sửa file nguồn). Gzip để GZipMiddleware của T-053 xử lý chung.
