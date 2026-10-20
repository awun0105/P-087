# T-051: File theo checksum — trình duyệt giữ vĩnh viễn, không băm lại, URL R2 ổn định

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md` (quy tắc chung, mục "Bảo mật bộ đệm").

## Goal
Mở lại scene hoặc chuyển giữa các bước không tải lại file 10–30 MB đã có trong trình duyệt. Mỗi lần tải file, backend chỉ
kiểm quyền rồi trả file, không băm lại toàn bộ file và không dựng lại danh sách file của job.

## Context (đã kiểm trong code)
- Route `GET /jobs/{job_id}/artifacts/content` và `/content/{filename}` (`src/api/product/artifacts.py:59-113`). URL đã
  chứa `artifact_checksum`. Trả `FileResponse` với `Cache-Control: private, no-cache` (dòng 97) — trình duyệt luôn hỏi lại.
  Starlette `FileResponse` có Range nhưng không xử lý `If-None-Match`.
- Production có kho R2: `registry.presigned_artifact_url` (`projects/registry.py:2001-2011`) gọi `authorized_artifact`,
  rồi `remote.head(key)` (một lần gọi mạng), rồi `remote.presign(key, expires)` — chữ ký mới mỗi request nên URL đích luôn
  khác, bộ đệm trình duyệt không bao giờ trúng. Trả `307`.
- `resolve_artifact` (`registry.py:2013-2021`) → `runtime_resolver.require` → `verify_file_checksum` cả file mỗi lần
  (`artifacts/store.py:64-72`). Đã có `require_unchanged` (`store.py:74-97`) đệm kết quả băm theo `(kích thước, mtime)`,
  hiện chỉ đường preview dùng.
- `authorized_artifact` dựng lại toàn bộ allow-list `_product_visible_references` (`registry.py:2023-2116`) mỗi request:
  đọc manifest nhiều lần, băm + parse SceneIR, đọc frame set, bundle, báo cáo LiDAR. Đo: sàn ~60 ms, 4–5 transaction mỗi
  request; Studio Draft mở 60 vỏ GLB = 60 lần như vậy.
- Đo hiện tại: jpg/glb 58–82 ms, SOG 14 MB 88–108 ms, SOG 31 MB 138–209 ms (local, chưa tính mạng).

## Thiết kế
1. **Allow-list đệm theo revision — đã có, commit `847c3aa9` của phiên khác.** Đệm nằm **trong**
   `ProjectRegistry._product_visible_references`, khoá `(job_id, job_manifest_checksum, head_checksum)`, 16 mục, có lock;
   không có scene head thì không đệm; phần dựng thật là `_build_product_visible_references`; test
   `test_allow_list_is_cached_per_manifest_and_scene_head` trong `tests/test_orchestration/test_artifact_download_links.py`.
   **Không viết lại, không sửa test đó.** Test mới của task này đếm số lần gọi `_build_product_visible_references`.
   Chỉ bổ sung nếu đo thấy cần: (a) job chưa có scene head cũng được đệm, phần tử thứ ba của khoá là `"no-head"`
   (`test_job_without_scene_head_is_cached`); (b) khoá đọc `job_manifest_checksum` bằng truy vấn `r2s_jobs.manifest_ref`
   thay vì `get_job` nếu T-053 chưa làm `get_job` rẻ.
2. **Không băm lại.** `resolve_artifact` dùng `runtime_resolver.require_unchanged(canonical)` thay `require`. Đường đọc
   nghiêm ngặt khác giữ `require`.
3. **Trình duyệt giữ file.** Trả file thành công với
   `Cache-Control: private, max-age=31536000, immutable` và `ETag: "<checksum không tiền tố sha256:>"`. Nếu request có
   `If-None-Match` khớp ETag: kiểm quyền (allow-list) **trước**, rồi trả `304` không đọc file. Viết helper dùng chung
   `def checksum_etag(checksum: str) -> str` và `def not_modified(request: Request, etag: str) -> bool` trong
   `src/api/product/http_cache.py`.
4. **URL R2 ổn định.** Trong lớp kho remote (tìm `def presign` trong `src/services/orchestration/artifacts/`), thêm đệm
   trong tiến trình `(key) → (url, expires_at)`; tái dùng URL khi còn ≥ 1/2 thời hạn. Thời hạn mặc định giữ
   `artifact_presign_seconds`. Kết quả `head(key)` đệm cùng chỗ (object R2 bất biến theo key có checksum). Phản hồi 307 thêm
   `Cache-Control: private, max-age=<thời gian còn lại của URL − 60 s>` để trình duyệt không hỏi lại API trong lúc URL còn
   hạn. Khi upload object lên R2 (tìm `def upload`/`put` cùng module), đặt metadata
   `CacheControl="private, max-age=31536000, immutable"` để R2 trả header đó cho file mới.
5. Không đổi URL mà frontend tạo; frontend không cần sửa để hưởng lợi.

## Steps
1. Test `tests/test_api/test_artifact_http_cache.py`:
   - `test_artifact_content_is_immutable_and_has_etag`: tải một artifact fixture → `cache-control` chứa `immutable`,
     `etag` bằng checksum.
   - `test_matching_if_none_match_returns_304_without_reading_file`: monkeypatch `resolve_artifact` để ném nếu bị gọi; gửi
     `If-None-Match` đúng → 304.
   - `test_if_none_match_still_checks_permission`: URI không thuộc allow-list + `If-None-Match` → 404, không phải 304.
   - `test_range_request_still_works`: header `Range: bytes=0-9` → 206, 10 byte.
   FAIL. Cài thiết kế 3. PASS. Commit `perf(api): let browsers keep checksum-addressed artifacts`.
2. Sau khi commit allow-list của phiên khác đã có: thêm vào `tests/test_orchestration/test_artifact_download_links.py`
   - `test_resolve_artifact_does_not_rehash_unchanged_file`: đếm `verify_file_checksum` = 1 sau hai lần `resolve_artifact`.
   - `test_changed_file_is_rechecked`: ghi đè byte của file đã phục vụ (giữ URI) → `ArtifactChecksumError`.
   - Nếu làm bổ sung (a): `test_job_without_scene_head_is_cached`.
   FAIL. Cài thiết kế 2 (và bổ sung nếu cần). PASS. Commit `perf(registry): serve verified artifacts without rehashing`.
3. Test kho remote (file test hiện có của R2 store: `grep -rln "presign" tests`), thêm
   `test_presigned_url_is_reused_within_half_lifetime`, `test_presigned_url_renews_after_half_lifetime` (đồng hồ giả),
   `test_head_result_is_cached`, `test_upload_sets_immutable_cache_control`. Cài thiết kế 4. Commit
   `perf(storage): reuse presigned artifact links and mark uploads immutable`.
4. Đo trước/sau: script trong scratchpad gọi handler in-process (theo cách audit: bản sao `data/studio_local/runtime.db`,
   không ghi DB thật), 20 lần tải SOG lớn nhất và 60 lần tải vỏ GLB của `job-f9f14e7fbfb1`; ghi trung vị và p95 vào report.
   Mục tiêu: lần thứ hai trở đi ≤ 15 ms mỗi file nhỏ (không tính truyền), 304 ≤ 10 ms.

## Acceptance criteria
1. Mở lại cùng một scene không tải lại file đã có (trình duyệt dùng bộ đệm hoặc nhận 304).
2. Không còn băm toàn bộ file mỗi lần tải; allow-list dựng một lần mỗi revision.
3. Người không có quyền không bao giờ nhận 304 hay file từ bộ đệm.
4. Production: cùng một file trong nửa thời hạn ký nhận cùng URL R2.

## Tests required
```
.venv/bin/python -m pytest tests/test_api/test_artifact_http_cache.py tests/test_orchestration/test_artifact_download_links.py <test kho R2> tests/test_api/test_scene_routes.py -q
.venv/bin/python -m pytest $(grep -rln "artifacts/content" tests/test_api) -q
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm số đo), `status.md`.
