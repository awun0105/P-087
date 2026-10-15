# T-003: Contract vỏ Gaussian, trạng thái hình học và presets

## Goal
Khai báo dữ liệu mới, chưa đổi luồng chạy:
- Artifact vỏ: `ObjectShellMesh` + `ObjectShellManifest`.
- `SceneObject.surface_mesh_ref` chấp nhận cả `ObjectShellMesh`.
- Lựa chọn `geometry_method = "shell"` và `geometry_review = "required" | "auto"`.
- Presets mặc định cho job mới: `shell` + `required` + `multiview_v1`.
- Helper đọc trạng thái hình học của scene.

## Context
`architecture.md` §5, §7.1, §7.2. Preset đang đặt `scene.geometry_method = "objectgs"` (commit `3d487da1`);
task này đổi sang `shell` theo quyết định mới của chủ dự án (vỏ làm nguồn collider mặc định, ObjectGS là tuỳ chọn).

## Files
- Sửa: `src/models/contracts/object_geometry.py` (thêm `ObjectShellManifest`)
- Sửa: `src/models/contracts/scene.py` (validator `surface_mesh_ref`, khoảng dòng 174–176)
- Sửa: `src/models/contracts/__init__.py` (export nếu file này re-export contract)
- Sửa: `src/services/orchestration/scene/objectify.py`:
  - `SceneObjectifyConfig.geometry_method: Literal["legacy", "shell", "objectgs"] = "legacy"`
  - thêm `geometry_review: Literal["legacy", "required", "auto"] = "legacy"`
  - `job_requires_objectgs` → đổi tên `job_requires_strict_geometry`, trả True khi `geometry_method in {"shell", "objectgs"}`
    (giữ alias `job_requires_objectgs = job_requires_strict_geometry` để không vỡ import; cập nhật nơi gọi trong
    `src/services/orchestration/scene/extraction.py`).
  - loại `geometry_review` khỏi config gửi cho lift runner (thêm vào tập `exclude` cạnh `geometry_method`).
- Tạo: `src/services/scene/geometry_state.py`
- Sửa: `configs/product/processing_presets_v1.json`
- Sửa: `frontend/src/lib/contracts/api.ts` (mirror `ObjectShellManifest` nếu mirror yêu cầu; kiểm bằng script)
- Test: `tests/test_contracts/test_object_geometry.py` (tạo nếu chưa có), `tests/test_orchestration/test_processing_config.py`,
  `tests/test_scene/test_objectify_config_override.py`, `tests/test_scene/test_geometry_state.py` (mới)

## Interfaces
```python
class ObjectShellManifest(ContractModel):
    artifact_type: Literal["ObjectShellManifest"] = "ObjectShellManifest"
    schema_version: Literal["1.0"] = "1.0"
    object_id: Identifier
    shell_mesh_ref: ProductArtifactRef          # artifact_type == "ObjectShellMesh"
    source_membership: ObjectMembershipArtifact
    source_world_from_object: Transform          # pose lúc tách, dùng để đổi toạ độ
    coordinate_frame: Literal["object_local"] = "object_local"
    distance_unit: Literal["m"] = "m"
    voxel_m: FiniteFloat = Field(gt=0)
    params: JsonObject
    statistics: JsonObject
    quality: JsonObject                          # phải có "passed": True
    vertex_count: int = Field(ge=4, strict=True)
    triangle_count: int = Field(ge=4, strict=True)
    provenance: JsonObject = Field(default_factory=dict)
    # validator: shell_mesh_ref type đúng; object_id thuộc source_membership; quality["passed"] is True;
    # shell_mesh_ref.job_id == source_membership.labels_ref.job_id
```

```python
# src/services/scene/geometry_state.py
ObjectGeometryState = Literal["awaiting_review", "ready"]
def object_geometry_state(scene: SceneIR) -> ObjectGeometryState:
    """Thiếu khóa (scene cũ) → "ready"; giá trị lạ → ValueError."""
def require_geometry_ready(scene: SceneIR, action: str) -> None:
    """Raise SceneEditRejectedError(code="OBJECT_GEOMETRY_NOT_READY", message=f"… {action} …") khi awaiting_review."""
```
Xem `src/services/orchestration/scene/errors.py` để dùng đúng lớp lỗi và cách gắn code.

Presets (`configs/product/processing_presets_v1.json`):
- Param `scene.geometry_method`: thêm choice `{"value": "shell", "label": "Vỏ Gaussian (mặc định)"}`;
  mô tả: "Vỏ Gaussian: nhanh, luôn kín. ObjectGS: chi tiết hơn, cần GPU; vật không đạt chất lượng giữ collider từ vỏ."
- Param mới `scene.geometry_review` (choice `required` "Dừng để duyệt tách vật" / `auto` "Tạo mesh ngay").
- Mọi preset: `"scene.geometry_method": "shell"`, thêm `"scene.geometry_review": "required"`. Giữ `scene.refinement: "multiview_v1"`.
Sửa văn bản bằng thay thế chuỗi để giữ định dạng file; kiểm `python3 -m json.tool`.

## Steps
1. Viết test contract trước (fail), rồi thêm `ObjectShellManifest`. Commit.
2. Nới validator `SceneObject.surface_mesh_ref` cho phép `{"ObjectSurfaceMesh", "ObjectShellMesh"}`. Test. Commit.
3. `geometry_state.py` + test. Commit.
4. Config Literal + `job_requires_strict_geometry` + test. Commit.
5. Presets + sửa test `test_every_preset_seals_objectgs_geometry_and_multiview_refinement` thành
   `test_every_preset_seals_shell_geometry_review_and_multiview` (khẳng định 3 giá trị). Commit.
6. Chạy `scripts/check_contract_mirror.py`; nếu báo thiếu, cập nhật `frontend/src/lib/contracts/api.ts`. Commit.

## Acceptance criteria
1. `ObjectShellManifest` từ chối: sai artifact_type, object_id không trong membership, `quality.passed` không phải True.
2. `SceneObject` chấp nhận `surface_mesh_ref` loại `ObjectShellMesh`; vẫn từ chối loại khác (ví dụ collider GLB).
3. `object_geometry_state`: thiếu khóa → `ready`; `awaiting_review` → `awaiting_review`; giá trị khác → lỗi.
4. Job có `geometry_method` `shell` hoặc `objectgs` → `job_requires_strict_geometry` True; `legacy`/không có → False.
5. Mọi preset tạo job config có `geometry_method=shell`, `geometry_review=required`, `refinement=multiview_v1`.
6. `SceneObjectifyConfig()` mặc định vẫn `legacy` cho cả ba khóa (job cũ không đổi hành vi).
7. Lift runner không nhận khóa `geometry_review` trong `config`.

## Tests required
Lệnh (không chạy full suite):
```
.venv/bin/python -m pytest tests/test_contracts tests/test_scene/test_geometry_state.py \
  tests/test_scene/test_objectify_config_override.py tests/test_orchestration/test_processing_config.py \
  tests/test_orchestration/test_processing_presets_schema.py tests/test_orchestration/test_scene_objectify_queue.py -q
.venv/bin/python scripts/check_contract_mirror.py
.venv/bin/ruff check <các file đã sửa> && .venv/bin/ruff format --check <các file đã sửa>
cd frontend && npm run typecheck   # chỉ khi sửa api.ts
```

## Commit
Mỗi bước trong Steps là một commit. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Chưa đổi `objectify()` để dừng ở Draft (T-005). Chưa dùng `shell` trong luồng chạy.
