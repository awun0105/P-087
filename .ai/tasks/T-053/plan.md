# T-053: Đệm SceneIR và JobManifest đã parse; nén gzip; preflight CORS

Đọc trước: `.ai/plans/2026-10-20-pipeline-stability-and-progress.md`.

## Goal
Các request poll và mở scene không băm, không parse lại cùng một SceneIR (~650 KB) hay JobManifest nhiều lần. Phản hồi JSON
lớn được nén. Trình duyệt không gửi preflight CORS lặp lại.

## Context (đã kiểm trong code)
- `GET /jobs/{id}/scene` (`src/api/product/scene.py:71-84`) → `registry.scene.current(job_id)` →
  `_load_head_revision(head)` (`scene/editor.py:550`) → `_load_revision(..., fresh=True)` (`editor.py:510-520`): `locate`,
  `sha256_file` cả file, `SceneIR.model_validate_json`, `_require_consistent` (tính lại canonical checksum). 35–45 ms mỗi lần.
- `GET /jobs/{id}/scene/objectify` (`objectify_queue.state`, `objectify_queue.py:298-330`) gọi cùng đường đó chỉ để đọc
  vài trường provenance: 34–42 ms, poll mỗi 5 s.
- `persistence.get_job` (`projects/persistence.py:691-713`): một truy vấn + `load_model` (băm file) + parse + tính lại
  canonical checksum. Handler gọi nhiều lần mỗi request.
- Head đã commit trong DB chứa `scene_reference` (checksum file) và `scene_ir_checksum` (`editor.py:552-558`); manifest ref
  trong `r2s_jobs.manifest_ref` chứa `artifact_checksum`. Cả hai bất biến theo checksum → đệm an toàn theo checksum.
- `src/main.py` chỉ có CORS: `allow_headers=["*"]`, không `max_age` (dòng 67-73); không có middleware nén.

## Thiết kế
1. Module mới `src/services/orchestration/artifacts/parsed_cache.py`:
   ```python
   class ParsedArtifactCache(Generic[T]):
       def __init__(self, max_entries: int) -> None: ...
       def get_or_load(self, key: tuple[str, str], load: Callable[[], T]) -> T: ...
   ```
   LRU trong tiến trình, khoá `(artifact_uri, artifact_checksum)`, có khoá luồng. Đối tượng trả ra là model Pydantic
   **bất biến theo quy ước**: người gọi không được sửa tại chỗ (mọi chỗ sửa đã dùng `model_copy`; nếu tìm thấy chỗ sửa tại
   chỗ, sửa nó sang `model_copy` trong task này và ghi vào report).
2. `persistence._job(payload)`: khoá `(reference.artifact_uri, reference.artifact_checksum)` từ `manifest_ref` → đệm
   `JobManifest` đã kiểm (max 256). Lần đầu vẫn chạy đủ kiểm như cũ.
3. `SceneEditor._load_head_revision(head)`: khoá `(head.scene_reference.artifact_uri, head.scene_reference.artifact_checksum)`
   → đệm `SceneRevision` đã kiểm (max 32). Trúng đệm vẫn so `scene_id`, `scene_ir_checksum` với head (rẻ). File trên đĩa
   bị đổi mà giữ URI: dùng `require_unchanged`-kiểu kiểm `(size, mtime)` của file trước khi trả đệm; đổi thì nạp lại và
   sẽ lỗi checksum như cũ.
4. `objectify_queue.state()` không đổi code: nó tự hưởng đệm qua `registry.scene.current`.
5. `GET /jobs/{id}/scene`: thêm `ETag: "<scene_ir_checksum>"`, `Cache-Control: private, no-cache` (phải hỏi lại vì head
   có thể đổi), `If-None-Match` khớp → 304.
6. `src/main.py`: `app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)`; CORS thêm `max_age=86400` và
   liệt kê header thật sự dùng thay `"*"` (đọc frontend `lib/api/client.ts` để lấy danh sách: `Content-Type`,
   `Authorization`, `If-None-Match`, `Idempotency-Key`… — đúng những gì code gửi). Không nén `FileResponse` nhị phân
   (SOG đã nén sẵn): GZipMiddleware của Starlette bỏ qua khi đã có `Content-Encoding`; với file, đặt
   `media_type="application/octet-stream"` và thêm danh sách loại trừ nếu middleware hỗ trợ, nếu không thì chấp nhận
   (ghi số đo kích thước SOG trước/sau vào report để chứng minh không tốn CPU vô ích; nếu tốn, chỉ áp gzip cho
   `application/json` bằng middleware tự viết 20 dòng).

## Steps
1. Test `tests/test_orchestration/test_parsed_artifact_cache.py`: `test_loads_once_per_checksum`,
   `test_new_checksum_loads_again`, `test_lru_evicts_oldest`, `test_concurrent_get_loads_once`. Cài thiết kế 1. Commit
   `perf(artifacts): add a checksum-keyed cache for parsed artifacts`.
2. Test `test_get_job_parses_manifest_once` (đếm `load_model`), `test_job_revision_change_returns_new_manifest`. Cài
   thiết kế 2. Chạy test persistence/registry hiện có. Commit `perf(registry): reuse verified job manifests by checksum`.
3. Test `test_current_scene_parses_once_per_head`, `test_new_head_is_loaded`, `test_tampered_scene_file_is_rejected`
   (ghi đè file giữ URI → lỗi như cũ). Cài thiết kế 3. Chạy `tests/test_scene` và `test_scene_v2_routes.py`. Commit
   `perf(scene): reuse the verified head revision by checksum`.
4. Test API: `test_scene_etag_304`, `test_json_response_is_gzipped`, `test_cors_preflight_has_max_age`. Cài thiết kế 5, 6.
   Commit `perf(api): gzip JSON, cache CORS preflight, 304 for unchanged scene`.
5. Đo trước/sau (in-process, bản sao DB): `/scene`, `/scene/objectify`, `/progress` warm, mỗi cái 50 lần, trung vị + p95,
   kích thước `/scene` nén. Mục tiêu: `/scene/objectify` ≤ 10 ms, `/scene` ≤ 10 ms khi trúng đệm, thân nén ≤ 1/5.

## Acceptance criteria
1. Một revision scene và một revision manifest chỉ bị băm + parse một lần mỗi tiến trình.
2. File bị sửa tay vẫn bị phát hiện.
3. JSON > 1 KB được nén khi trình duyệt hỗ trợ.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_parsed_artifact_cache.py tests/test_scene tests/test_api/test_scene_routes.py tests/test_api/test_scene_v2_routes.py tests/test_orchestration/test_job_progress.py -q
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo Steps. `graphify update .`, `report.md` (kèm số đo), `status.md`.
