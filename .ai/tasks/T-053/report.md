# T-053 report
- `artifacts/parsed_cache.py` (mới): `ParsedArtifactCache` LRU theo (URI, checksum), nạp một lần khi gọi đồng thời, lỗi không lưu.
- `persistence._job`: JobManifest đã kiểm được giữ theo con trỏ (URI, checksum) đọc từ DB mỗi lần (256 mục).
- `SceneEditor._load_head_revision`: revision head đã kiểm giữ theo (URI, checksum) khi phiên bản file trên đĩa không đổi; file bị sửa → đọc lại và bị từ chối như cũ (64 mục).
- `/jobs/{id}/scene`: ETag = scene_ir_checksum, `If-None-Match` → 304, `private, no-cache`.
- `main.py`: GZipMiddleware (≥1 KB, mức 5, loại trừ octet-stream/ảnh/video/zip); CORS `max_age=86400`.
- Sửa kèm (lỗi do T-052): đọc `If-None-Match` bằng `Annotated[str | None, Header()] = None` để các route vẫn gọi thẳng được trong test.
- Đo (job-a14981f78f85 rev-106): băm + parse SceneIR mỗi lần trước đây 17,3 ms → trúng đệm ~0; JSON 550 KB → gzip 25 KB.
- Lệch plan: giữ `allow_headers=["*"]` (liệt kê từng header có nguy cơ chặn request của viewer nhúng); cập nhật khẳng định `no-cache` → `immutable` trong test_effective_collision theo thiết kế T-052.
- Test đỏ có sẵn từ trước Sprint 8 (đã kiểm ở bf260701): test_runtime_migrations v11/v12, test_role_matrix route classification, test_sample_routes (7).
