# T-010: API region preview/apply trên Draft

## Goal
Hai route cho Region Editor:
- **Preview** (không ghi gì): trả bộ đếm, mẫu điểm thêm/bớt, vỏ thô của kết quả.
- **Apply** trên Draft: đồng bộ, vài giây, publish revision mới (membership mới + Gaussian vật + vỏ thô).
  Không train, không CoACD.

## Context
`architecture.md` §7.3, §9 (Region Editor), §10, §11. Dùng:
- `resolve_region`, `apply_resolution`, `preview_payload` (T-004).
- `build_gaussian_shell` với `ShellParams(voxel_m=0.05, smooth_iterations=0)` (T-002).
- Đọc PLY nguồn + nhãn + bảo vệ sàn: tách phần đọc trong `membership_regeneration.prepare_correction` thành hàm dùng chung
  `load_membership_source(registry, job_id, scene) -> MembershipSource(positions, rows, labels, manifest, floor_protected)`.
- Publish revision: `registry.scene.publish_next(job_id, expected_revision, updated, "object_region_edit")`.

## Files
- Tạo: `src/services/orchestration/scene/object_region.py`
- Sửa: `src/services/orchestration/scene/membership_regeneration.py` (tách `load_membership_source`, giữ hành vi)
- Sửa: `src/api/product/scene.py`
- Sửa: `tests/test_api/test_role_matrix.py`
- Tạo: `tests/test_scene/test_object_region.py`; sửa `tests/test_api/test_scene_v2_routes.py`

## Interfaces
```
POST /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/preview   body: ObjectRegionCommand
200 → {
  "scene_revision", "membership_checksum", "object_id",
  "added_count", "removed_count", "object_gaussian_count", "protected_floor_count",
  "overlaps": {"<id>": n}, "claimed": {"<id>": n},
  "added_sample_m": [[x,y,z], …], "removed_sample_m": [[x,y,z], …],   // object-local, ≤ 20 000 mỗi loại
  "shell_glb_base64": "…" | null, "shell_error": "…" | null
}
POST /api/v1/jobs/{job_id}/scene/objects/{object_id}/region/apply     body: ObjectRegionCommand
201 (Draft) → SceneEditResponse (revision mới)
202 (Ready) → ObjectifyState  (T-011 làm; task này trả 422 với `detail` "Scene đã có hình học; tính năng dựng lại vật sẽ có ở bước sau." cho Ready)
409 → revision/membership checksum lệch
422 → command không hợp lệ, vật < 50 Gaussian, vật không thuộc membership, vật DELETED/IGNORED/MERGED
```
Guard như route membership hiện có (`require_contributor` + `authorize_job_mutation`).

```python
# object_region.py
def preview_region(registry, job_id, object_id, command) -> dict
def apply_region_draft(registry, job_id, object_id, command, *, actor_id: str) -> SceneEditResult
```
Cache: `functools.lru_cache`-kiểu thủ công, khoá `(job_id, labels_ref.artifact_checksum, source_visual_checksum)`,
tối đa 2 mục, lưu `positions` + `rows` + `floor_protected` (không lưu labels đã sửa). Thread-safe bằng `threading.Lock`.

## Steps
1. Tách `load_membership_source` khỏi `prepare_correction`; test cũ của membership regeneration PASS. Commit.
2. `preview_region`: kiểm revision + checksum (lệch → `StaleObjectMembershipRevisionError` → 409); `resolve_region`;
   vỏ thô của hàng mới (object-local theo `source_transform`); `GaussianShellError` → `shell_glb_base64=null`,
   `shell_error=<lý do>` (preview vẫn 200 để người dùng thấy lý do). Test. Commit.
3. `apply_region_draft`: yêu cầu `awaiting_review`. `apply_resolution` → labels mới → encode + publish
   `ObjectMembershipLabels` + `ObjectMembershipArtifact` mới (giữ `source_visual_ref`, `source_geometry_ref`,
   `extraction_revision`). Vật bị ảnh hưởng = `object_id` + các vật trong `claimed`: publish lại `ObjectGaussians`,
   vỏ thô (`ObjectShellMesh`), cập nhật `primitive_dimensions_xyz_m` từ bounds hàng mới, `provenance.shell_preview`,
   xoá `provenance.shell_error` nếu vỏ dựng được (hoặc ghi lỗi mới). Vật bị lấy hết còn < 50 hàng → 422 trước khi publish.
   Ghi evidence `ObjectRegionEdit` JSON (command, preview không gồm mẫu điểm, actor, membership cũ/mới). `publish_next`. Commit.
4. Routes + role matrix + test HTTP. Commit.
5. Hiệu năng: lọc kNN của vỏ mất ~1,4 s trên 300k điểm (đo ở T-002). Nếu preview vượt 1,5 s, lấy mẫu đều (stride,
   deterministic) tối đa 100k hàng trước khi dựng vỏ thô; ghi số hàng đã lấy mẫu vào payload (`shell_sample_rows`).
   Đo thời gian preview trên 300.000 Gaussian tổng hợp trong test (≤ 1,5 s; nếu CI chậm, ghi số đo vào report). Commit.

## Acceptance criteria
1. Preview không tạo artifact nào (đếm file trong artifact store trước/sau) và không đổi revision.
2. Preview trả bộ đếm khớp `resolve_region`, mẫu điểm ≤ 20.000, vỏ GLB base64 giải mã được và watertight.
3. Apply trên Draft → revision mới; `environment.membership.labels_ref` mới; vật có `visual_ref`, `geometry_ref` (vỏ) mới;
   vật khác không bị ảnh hưởng giữ nguyên ref.
4. Claim từ vật B → B có Gaussian/vỏ mới; B còn < 50 → 422, không publish gì.
5. Revision hoặc membership checksum cũ → 409, không publish.
6. Apply trên scene Ready → 422 (envelope `{detail}`) (T-011 đổi thành 202).
7. Vật đã Move (transform khác source_transform) → kết quả giống khi chưa Move (dùng source_transform).
8. Route có trong role matrix.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_region.py tests/test_scene/test_region_box.py \
  tests/test_scene/test_membership_regeneration.py tests/test_scene/test_membership_selection.py \
  tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Ready → rebuild (T-011). UI (T-016).
