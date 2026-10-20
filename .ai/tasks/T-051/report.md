# T-051 report
- Đệm allow-list: dùng nguyên commit 847c3aa9 của phiên deploy (không viết lại).
- `src/api/product/http_cache.py` (mới): `IMMUTABLE_PRIVATE`, `checksum_etag`, `not_modified`.
- `artifacts.py` route content: kiểm quyền → `If-None-Match` khớp thì 304 không đọc file; file trả `private, max-age=31536000, immutable` + ETag; redirect R2 kèm `private, max-age=presign/2-60`.
- `registry.resolve_artifact`: `require_unchanged` (băm một lần mỗi phiên bản file).
- `ArtifactRemote`: đệm `head` khi tìm thấy, đệm link đã ký tới nửa thời hạn; `S3ObjectStore.put_file` đặt `CacheControl` immutable cho file mới.
- Đo (SOG 31,2 MB của job-f9f14e7fbfb1, in-process): băm mỗi lần tải trước 69,7 ms trung vị → sau 0,13 ms (lần 2+).
- Test: 4 test HTTP trong test_scene_routes.py; 5 test trong test_artifact_download_links.py.
- Ghi chú: `test_role_matrix.py::test_every_route_is_classified_exactly_once` đỏ từ trước Sprint 8 (route /demo-sessions chưa khai báo) — không do task này.
- Lệch plan: không làm bổ sung (a)/(b) cho đệm allow-list; chưa đo thấy cần.
