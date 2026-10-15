# T-007: Build hình học từ vỏ (Draft → Ready)

## Goal
Hàm service `build_object_geometry(...)`: nhận Draft SceneIR, dựng **vỏ mịn** cho từng vật → QA → CoACD →
vá nền + SOG → collision môi trường → publish SceneIR `object_geometry = "ready"` qua `publish_next` có fence.
Thất bại hoặc huỷ ở bất kỳ bước nào → scene đang hoạt động **không đổi**.

## Context
`architecture.md` §5, §7.1 (Ready), §7.2, §8. Dùng lại:
- `build_gaussian_shell` (T-002), `ObjectShellManifest` (T-003), helper T-006
  (`run_surface_colliders`, `run_inpaint_and_package`, `build_environment_collision`).
- Cách publish revision có fence: `membership_regeneration.regenerate_membership` gọi
  `registry.scene.publish_next(job_id, expected_revision, updated, reason, commit_guard=commit_guard)`.
- Đọc PLY nguồn + nhãn: `prepare_correction` trong `membership_regeneration.py` (đọc `source_visual_ref`,
  `decode_gaussian_membership_labels`).
- `bind_source_collision_ownership` (`extraction.py`) cho vật sau khi có collider.

## Files
- Tạo: `src/services/orchestration/scene/object_geometry_build.py`
- Tạo: `tests/test_scene/test_object_geometry_build.py`

## Interfaces
```python
class ObjectGeometryBuildError(RuntimeError):
    def __init__(self, message: str, *, object_id: str | None = None, retryable: bool = False): ...

def build_object_geometry(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    *,
    expected_revision: str,
    workspace: Path,
    object_ids: set[str] | None = None,      # None = tất cả vật active/candidate; T-011 truyền tập bị ảnh hưởng
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:                                    # scene_revision mới
```

## Steps
1. Đọc scene hiện tại; `scene.scene_revision != expected_revision` → `StaleObjectMembershipRevisionError`.
   Yêu cầu `environment.membership` có. `object_ids is None` yêu cầu `object_geometry_state(scene) == "awaiting_review"`.
2. Đọc PLY nguồn + nhãn, kiểm checksum như `prepare_correction`. Lấy config job (`load_job_config`) để có
   `coacd`, `inpaint`, `objectgs_background_voxel_m`, `geometry_method`.
3. Tập vật cần dựng: vật có nhãn trong membership, `review` không thuộc `DELETED/IGNORED/MERGED`, giao với `object_ids` nếu có.
   Vật có `provenance.shell_error` mà membership chưa đổi → lỗi `ObjectGeometryBuildError(object_id=…)`:
   "Vỏ của <tên> không dựng được: <lý do>. Sửa vùng vật rồi thử lại."
4. `progress("shell")`. Với từng vật: lấy hàng có nhãn của vật; `source_transform` từ `provenance.source_transform`
   (thiếu → lỗi); `positions_local = R^T (p − t)`; `build_gaussian_shell(..., ShellParams())` (0.02 m, smoothing bật).
   `GaussianShellError` → `ObjectGeometryBuildError(object_id=…)`. Ghi GLB vào workspace.
5. `progress("quality")`: lưu `quality` từ shell (đã QA trong T-002). Publish `ObjectShellMesh` + `ObjectShellManifest`
   (`objects/shells/{digest}.glb`, `objects/shells/{digest}.json`, stage `SCENE_DECOMPOSE`).
6. `progress("collider")`: `run_surface_colliders` với `surface_path` = GLB vỏ, `coordinate_frame=object_local`.
   Publish collider `ObjectCollider` (`colliders/{digest}.glb`, stage `COLLIDER`). `ColliderSpec(type=CONVEX_DECOMPOSITION,
   provenance={"generator": "coacd", "surface_origin": "gaussian_shell_v1", "surface_mesh_ref": …,
   "coacd_config": …, "strict_surface_input": True})`.
7. `progress("environment")`: viết `background.ply` (hàng nhãn −1) và `objects_world.ply` (hàng của mọi vật) như objectify,
   gọi `run_inpaint_and_package` → `visual_ref`, `visual_master_ref`. Gọi `build_environment_collision` với footprints =
   AABB (source world) của hàng mỗi vật. Kết quả gán `environment.collider_ref`, `environment.object_aware_collision_ref`.
8. Cập nhật vật: `geometry_ref` = collider GLB, `surface_mesh_ref` = vỏ mịn, `collider` mới,
   `provenance.shell_manifest_ref`, `provenance.surface_selection = {"chosen": "gaussian_shell"}`. Giữ `transform`,
   tên, state, review của vật (không reset lựa chọn người dùng).
9. `bind_source_collision_ownership(objects, source_geometry_ref, new_revision_hint)` nếu cần (giống `extract_scene`).
10. Provenance scene: `object_geometry = "ready"`, `geometry_build = {input_scene_revision, built_object_ids, at}`.
11. `_ensure_not_cancelled` trước mỗi bước; `progress("publish")`; `registry.scene.publish_next(..., "object_geometry_build",
    commit_guard=commit_guard)`.

## Acceptance criteria
1. Draft 2 vật tổng hợp → revision mới, `object_geometry == "ready"`, mỗi vật có `collider.collider_type == CONVEX_DECOMPOSITION`,
   `surface_mesh_ref.artifact_type == "ObjectShellMesh"`, manifest vỏ `quality.passed is True`.
2. Môi trường có `object_aware_collision_ref`; mesh nền không chứa ô bên trong vật (kiểm điểm giữa vật nằm ngoài mesh nền).
3. Revision kỳ vọng sai → lỗi stale, scene không đổi.
4. Huỷ (`cancel_event.set()` sau bước shell) → `ProcessCancelledError`/lỗi huỷ, scene không đổi, không có revision mới.
5. Một vật vỏ lỗi → `ObjectGeometryBuildError(object_id=…)`, scene không đổi, **không** có collider OBB nào được tạo.
6. CoACD trả 0 part → lỗi, scene không đổi.
7. Vật đã Ignored/Deleted không được dựng; vật khác vẫn dựng.
8. Dùng `source_transform`, không dùng `transform`: vật có `transform` khác `source_transform` vẫn cho collider khớp hình dạng
   (bounds object-local giống trường hợp chưa Move).
9. Khi runtime CoACD thật có sẵn (`data/scene_runtime`), test tích hợp chạy CoACD thật; không có → `pytest.skip` kèm lý do rõ.
10. Vỏ rỗng (quét thiếu đáy, dữ liệu `open_face_points` của `tests/test_scene/test_gaussian_shell.py`) qua CoACD thật cho số mảnh
   ≤ `max_convex_hull` của config và collider bao phủ vật (bounds collider lệch bounds vỏ ≤ 2·voxel). Ghi số mảnh và thời gian
   vào report. Nếu vượt ngân sách mảnh: báo Architect, không tự lấp vỏ.
11. Không có trường khối lượng/quán tính nào tính từ `mesh.volume` của vỏ hay collider (grep trong code mới).

## Tests required
`tests/test_scene/test_object_geometry_build.py`: fixture registry + Draft scene giống `tests/test_scene/test_membership_regeneration.py`
và `tests/test_scene/test_objectgs_objectify_flow.py` (tận dụng helper sẵn có). Monkeypatch inpaint/package để chạy CPU.
Một test cho mỗi tiêu chí. Lệnh:
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_object_geometry_steps.py \
  tests/test_scene/test_gaussian_shell.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
(a) khung hàm + kiểm revision/state + test 3; (b) vỏ + manifest + test 1 phần vỏ; (c) collider + test 6;
(d) môi trường + test 2; (e) publish + huỷ + test 4,5,7,8; (f) test CoACD thật. Không Co-Authored-By.
`graphify update .`, `report.md`, `status.md`.

## Out of scope
ObjectGS (T-008), hàng đợi/API (T-009), rebuild một phần (T-011 sẽ dùng `object_ids`).
