# T-006: Tách helper dùng chung khỏi `objectify()` (không đổi hành vi)

## Goal
Đưa ba khối logic trong `objectify()` thành hàm riêng để T-007 (build từ Draft) gọi lại, tránh chép code:
1. Chạy CoACD trên surface mesh object-local → kết quả collider từng vật.
2. Vá nền (inpaint) + nén SOG nền + publish `background.ply`/`background.sog`.
3. Dựng collision môi trường object-aware (support sàn suy ra + `build_background_collision` + publish manifest).

## Context
`architecture.md` §6, §8.5. Code nguồn trong `src/services/orchestration/scene/objectify.py`:
- CoACD + inpaint song song: khối từ `report_progress("collider_and_background")` (~dòng 637) tới kiểm lỗi collider (~701).
- SOG + publish nền: ~702–727.
- Collision môi trường: khối `if objectgs_receipt is not None:` sau khi tạo `SceneEnvironment` (~931–1010).

## Files
- Tạo: `src/services/orchestration/scene/object_geometry_steps.py`
- Sửa: `src/services/orchestration/scene/objectify.py` (gọi hàm mới)
- Tạo: `tests/test_scene/test_object_geometry_steps.py`

## Interfaces
```python
@dataclass(frozen=True)
class SurfaceInput:
    key: str                 # id dùng trong request convex ("1", "2", …)
    surface_path: Path       # GLB object-local, mét
    surface_checksum: str
    output_glb: Path

def run_surface_colliders(python, inputs: list[SurfaceInput], coacd_config: dict, workspace: Path,
                          timeout: float, cancel_event) -> dict[str, dict]:
    """Gọi CONVEX_RUNNER với chế độ surface_mesh strict. Trả {key: item}. Thiếu parts/lỗi → ObjectifyError
    ("…Gaussian/OBB fallback is forbidden"), giống hành vi hiện có."""

def run_inpaint_and_package(python, *, background_ply: Path, objects_ply: Path, views: list, settings,
                            inpaint_config: dict, workspace: Path, timeout: float, cancel_event,
                            publish, job_id: str) -> tuple[ProductArtifactRef, ProductArtifactRef, dict]:
    """Inpaint → package_splat → publish background.ply (GaussianPLY) + background.sog (VisualArtifact).
    Trả (master_ref, visual_ref, inpaint_result)."""

def build_environment_collision(*, source_points, membership_labels, label_to_object_id, footprints,
                                floor_model, floor_fit, voxel_m, bundle, membership, publish, job_id
                                ) -> tuple[ProductArtifactRef, ProductArtifactRef]:
    """Support sàn dưới footprints + build_background_collision + publish GLB và ObjectAwareEnvironmentManifest.
    Trả (collision_glb_ref, manifest_ref). footprints: list[(low_xyz, high_xyz)] theo toạ độ source world."""
```
Chép nguyên logic (kể cả thông điệp lỗi, provenance, đường dẫn artifact). Trong `objectify()` vẫn chạy CoACD và
inpaint **song song** như cũ: dùng `ThreadPoolExecutor` gọi `run_surface_colliders` và phần inpaint; phần package/publish
chạy sau. Nếu tách song song khó giữ nguyên, cho `run_inpaint_and_package` nhận cờ `package=False` và gọi package riêng.

## Steps
1. Viết test "chụp hành vi" trước khi refactor: chạy `tests/test_scene/test_objectgs_objectify_flow.py` và
   `test_objectify_config_override.py`, ghi lại PASS. Không cần test mới cho bước này.
2. Tách `build_environment_collision` (khối thuần CPU, dễ nhất) + test đơn vị với điểm tổng hợp: sàn + 1 vật →
   GLB không chứa ô của vật, có support dưới footprint, manifest có `removed_object_ids`. Commit.
3. Tách `run_surface_colliders` + test monkeypatch `_run` (trả parts=0 → ObjectifyError). Commit.
4. Tách `run_inpaint_and_package` + test monkeypatch `_run`/`package_splat`. Commit.
5. Chạy lại test hành vi cũ → PASS. Commit nếu có chỉnh.

## Acceptance criteria
1. Các test hiện có PASS không sửa assertion:
   `tests/test_scene/test_objectgs_objectify_flow.py`, `tests/test_scene/test_objectify_config_override.py`,
   `tests/test_orchestration/test_scene_objectify_queue.py`, `tests/test_scene/test_object_aware_composition.py`.
2. `objectify()` ngắn đi rõ rệt; không còn bản sao logic ở hai nơi.
3. Test đơn vị mới cho ba hàm PASS.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_steps.py tests/test_scene/test_objectgs_objectify_flow.py \
  tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_scene/test_object_aware_composition.py tests/test_scene/test_objectify_draft.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
```

## Commit
Mỗi hàm tách là một commit. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Không thêm hành vi mới, không đổi đường dẫn artifact hay thông điệp lỗi.
