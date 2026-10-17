# T-005: Tách vật dừng ở Draft SceneIR

## Goal
Khi job có `geometry_review = "required"` và `geometry_method ∈ {"shell", "objectgs"}`, stage
`OBJECT_EXTRACT` chỉ chạy phần rẻ (SAM2 + lift + membership + vỏ thô) rồi publish **Draft SceneIR**.
Không train ObjectGS, không CoACD, không vá nền, không nén SOG nền.

## Context
`architecture.md` §5, §7.1 (Draft), §9 (màn duyệt). Code:
- `src/services/orchestration/scene/objectify.py`: `objectify()` (dòng ~317–1011). Mốc quan trọng:
  kiểm runtime ObjectGS ở đầu hàm (~dòng 337); `lift = _run(...)` (~416); `parts` + ghi `object_###.ply` (~520);
  `membership_payload` + `publish_membership()` (~546–574); nhánh ObjectGS (~576); CoACD + inpaint song song (~637).
- `src/services/orchestration/scene/extraction.py`: `extract_scene()` gọi `objectify_with_retry` rồi
  `bind_source_collision_ownership` và `scene_from_bundle(...)`.
- `src/services/scene/builder.py`: `scene_from_bundle` (môi trường mặc định = `bundle.visual_artifact_ref` + canonical geometry).
- Vỏ: `build_gaussian_shell` (T-002), `ShellParams(voxel_m=0.05, smooth_iterations=0)` cho vỏ thô.

## Files
- Sửa: `src/services/orchestration/scene/objectify.py`
- Sửa (nếu cần): `src/services/orchestration/scene/extraction.py`
- Tạo: `tests/test_scene/test_objectify_draft.py`

## Steps
1. Đọc kỹ `objectify()` và `extract_scene()`; dùng `codegraph_explore` cho `objectify extract_scene bind_source_collision_ownership`.
2. Tính cờ ngay sau khi validate config:
   ```python
   draft = (config.scene.geometry_review == "required"
            and config.scene.geometry_method in {"shell", "objectgs"}
            and correction is None)
   ```
   Khi `draft`: **bỏ qua** kiểm runtime ObjectGS ở đầu hàm (runtime chỉ cần lúc build). SAM2 runtime vẫn bắt buộc.
3. Chạy bình thường tới khi có `parts`, `labels`, `membership_payload`. Khi `draft`, rẽ sang hàm mới
   `_publish_draft(...)` và `return` ngay, trước nhánh ObjectGS.
4. `_publish_draft(...)` làm, theo thứ tự:
   1. `membership = publish_membership()`.
   2. Với từng `part` (thứ tự `enumerate(parts, start=1)` như code cũ, giữ `object_id` từ `label_to_object_id`):
      - Publish Gaussian của vật: `ObjectGaussians` (giống code cũ dòng ~818).
      - `positions_local = positions(part.rows) - part.center`; `opacity_logit = part.rows["opacity"]`.
      - `shell = build_gaussian_shell(positions_local, opacity_logit, ShellParams(voxel_m=0.05, smooth_iterations=0))`.
        Nếu `GaussianShellError`: **không bỏ vật**. Dùng GLB hộp bao (`trimesh.creation.box(extents=part.dimensions)`)
        **chỉ để hiển thị**, ghi `provenance.shell_error = <lý do>` và `provenance.shell_display = "bounding_box_placeholder"`.
        Collider vẫn `None`. Build (T-007) phải từ chối vật này với lỗi rõ ràng cho tới khi người dùng sửa vùng;
        hộp này không bao giờ được dùng làm collider.
      - Publish GLB vỏ: artifact_type `ObjectShellMesh`, đường dẫn `objects/shells/{digest}.glb`, stage `SCENE_DECOMPOSE`.
      - `SceneObject(... state=CANDIDATE, active=False, transform=Transform(world→object, translation=part.center),
        visual_ref=<Gaussian vật>, geometry_ref=<vỏ thô>, surface_mesh_ref=None, collider=None,
        primitive_dimensions_xyz_m=part.dimensions,
        provenance={method, gaussians, seed_gaussians, masks, note, "source_transform": <transform dạng json>,
                    "shell_preview": {"voxel_m": 0.05, "checksum": shell.checksum, "statistics": …}})`.
   3. Environment: `SceneEnvironment(visual_ref=bundle.visual_artifact_ref, geometry_ref=bundle.canonical_geometry_ref,
      membership=membership)` (không `collider_ref`, không `object_aware_collision_ref`, không `visual_master_ref`).
   4. Provenance scene: như code cũ phần không phụ thuộc inpaint/CoACD, thêm
      `"object_geometry": "awaiting_review"`, `"geometry_method": config.scene.geometry_method`,
      `"geometry_review": "required"`, `"segmentation_refinement": config.scene.refinement`, `floor_fit`.
   5. `return ObjectifyResult(environment=environment, objects=objects, provenance=provenance)`.
5. Kiểm `extract_scene()`: `bind_source_collision_ownership` có chạy được với vật không có collider không.
   Nếu nó yêu cầu collider, bỏ qua bước này khi `provenance["object_geometry"] == "awaiting_review"` (build ở T-007 sẽ gọi lại).
   Ghi rõ quyết định trong `report.md`.
6. `objectify_with_retry` không cần đổi (config đến từ job). Kiểm job có `geometry_review` trong config niêm phong
   được truyền vào `scene_config` (nhóm `scene`).

7. Dọn từ review T-003: trong `extract_scene` đổi tên biến `objectgs_required` → `strict_geometry_required` và thông điệp
   "ObjectGS job requires …" → "Job hình học nghiêm ngặt (shell/ObjectGS) cần runtime SAM2/objectify; không được lùi về legacy";
   xoá alias `job_requires_objectgs` trong `objectify.py` (không còn nơi dùng). Nới `geometry_method` của `objectify_with_retry`
   và `reobjectify` thành `Literal["legacy", "shell", "objectgs"]`. Commit riêng.

## Interfaces
Không đổi chữ ký public. `ObjectifyResult` giữ nguyên.

## Acceptance criteria
1. Job config `geometry_method=shell, geometry_review=required`: `objectify()` **không** gọi ObjectGS runner,
   convex runner, inpaint runner, `package_splat` (test bằng monkeypatch các hàm đó raise nếu bị gọi).
2. Scene publish có `provenance.object_geometry == "awaiting_review"`, mọi vật `collider is None`,
   `geometry_ref.artifact_type == "ObjectShellMesh"`, `provenance.source_transform` có mặt.
3. `environment.membership` khớp membership publish; `environment.object_aware_collision_ref is None`;
   `environment.visual_ref == bundle.visual_artifact_ref`.
4. Vỏ thô mỗi vật là GLB đọc lại được bằng trimesh, watertight.
5. Vật mà vỏ lỗi → vẫn có trong scene, có `provenance.shell_error`, `collider is None`.
6. Job `geometry_method=objectgs, geometry_review=required` mà **không** cấu hình runtime ObjectGS → vẫn publish Draft (không lỗi).
7. Job `geometry_review=legacy` hoặc `auto` hoặc `geometry_method=legacy` → hành vi cũ không đổi
   (các test hiện có trong `tests/test_scene/test_objectgs_objectify_flow.py`, `tests/test_scene/test_objectify_config_override.py` PASS).

## Tests required
`tests/test_scene/test_objectify_draft.py`: dựng fixture như `test_provider_requests_receive_overrides`
(monkeypatch `_run` cho lift, `camera_views`, `metric_visual_master`, floor…), tạo 2 vật tổng hợp đủ ≥ 200 Gaussian mỗi vật.
Một test cho mỗi tiêu chí 1–6. Lệnh:
```
.venv/bin/python -m pytest tests/test_scene/test_objectify_draft.py tests/test_scene/test_objectify_config_override.py \
  tests/test_scene/test_objectgs_objectify_flow.py tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_orchestration/test_scene_extraction.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
(a) cờ `draft` + bỏ kiểm runtime ObjectGS khi draft + test 6; (b) `_publish_draft` vật + vỏ + test 2,4,5;
(c) environment/provenance + test 1,3; (d) chỉnh `extract_scene` nếu cần. Không Co-Authored-By.
`graphify update .`, `report.md`, `status.md`.

## Out of scope
Build hình học (T-007), API (T-009/T-010), UI.
