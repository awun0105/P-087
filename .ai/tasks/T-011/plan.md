# T-011: Sửa vùng sau khi Ready → rebuild đúng vật bị ảnh hưởng

## Goal
Khi scene đã có hình học (`ready`), chỉnh vùng (box ở T-010, hoặc Brush/Lasso qua route `membership/regenerate` có sẵn)
xếp một việc nền: cập nhật membership + dựng lại vỏ/collider **chỉ** cho vật bị ảnh hưởng + dựng lại nền/collision
môi trường, rồi publish **một** revision. Không train lại cả scene khi `geometry_method = shell`.

## Context
`architecture.md` §5 (dòng cuối luồng). Hiện trạng: `regenerate_membership` (`membership_regeneration.py`) gọi
`objectify_with_retry(... correction=CorrectedMembership(...), geometry_method="objectgs")` → train lại ObjectGS cả scene.
Task này thay đường đó bằng `build_object_geometry` (T-007/T-008) với nhãn mới.

## Files
- Sửa: `src/services/orchestration/scene/object_geometry_build.py` (thêm tham số nhãn thay thế)
- Sửa: `src/services/orchestration/scene/membership_regeneration.py`
- Sửa: `src/services/orchestration/scene/objectify_queue.py` (mode `region`)
- Sửa: `src/services/orchestration/scene/object_region.py`, `src/api/product/scene.py`
- Sửa: `frontend/src/lib/api/studio.ts` (thêm `"region"` vào `ObjectifyMode`)
- Test: `tests/test_scene/test_object_geometry_build.py`, `tests/test_scene/test_membership_regeneration.py`,
  `tests/test_orchestration/test_scene_objectify_queue.py`, `tests/test_api/test_scene_v2_routes.py`

## Interfaces
```python
@dataclass(frozen=True)
class MembershipOverride:
    labels: np.ndarray                 # int32 nhãn mới (gaussian_count,)
    manifest: ObjectMembershipArtifact # đã publish
    evidence_ref: ProductArtifactRef   # ObjectRegionEdit hoặc ObjectMembershipCorrection

def build_object_geometry(..., object_ids: set[str] | None = None,
                          membership_override: MembershipOverride | None = None, ...) -> str
```
- Khi có `membership_override`: scene phải `ready`; `object_ids` bắt buộc (vật bị ảnh hưởng). Vỏ + collider chỉ dựng cho
  `object_ids`; vật khác giữ nguyên ref. Nền (inpaint/SOG) + collision môi trường **luôn** dựng lại vì membership đổi.
  `environment.membership` = manifest mới. Provenance scene ghi `membership_correction.evidence_ref`.
- `geometry_method = objectgs`: build theo T-008 (ObjectGS train lại vì model dùng chung — ghi rõ trong provenance
  `objectgs_retrained_for = [...]`); vật không thuộc `object_ids` vẫn giữ surface/collider cũ.

Route `region/apply` trên Ready → 202 `ObjectifyState(mode="region")`. Lưu command vào bản ghi queue (như mode `membership`).

## Steps
1. `membership_override` trong build + test: chỉ vật bị ảnh hưởng có collider mới, vật khác giữ nguyên ref; nền có manifest mới. Commit.
2. `regenerate_membership`: thay `objectify_with_retry(correction=…)` bằng: tính nhãn mới (code cũ), publish membership +
   evidence (code cũ), gọi `build_object_geometry(..., object_ids=affected, membership_override=…)`. Bỏ ràng buộc
   "chỉ ObjectGS" (`queued regeneration requires an ObjectGS scene`) → thay bằng "scene phải ready". Sửa test cũ cho khớp
   hành vi mới (ghi lý do sửa từng assertion trong report). Commit.
3. Mode `region` trong queue: worker tính `resolve_region` từ command lưu, publish membership + evidence, gọi build như bước 2.
   Revision fence + huỷ như mode `membership`. Commit.
4. Route `region/apply` trên Ready → 202; frontend type. Commit.

## Acceptance criteria
0. Vật bị ảnh hưởng ở trạng thái IGNORED/DELETED/MERGED vẫn được dựng lại collider (xem review T-007).
1. Scene ready 3 vật, sửa vùng vật A (shell): chỉ A có `collider.geometry_ref` mới; B, C giữ ref cũ (so checksum);
   collision môi trường + nền có ref mới; một revision duy nhất được publish.
2. Không gọi ObjectGS khi `geometry_method = shell` (monkeypatch raise).
3. Claim từ B → A và B đều được dựng lại.
4. Huỷ giữa chừng / lỗi vỏ / revision lệch → scene giữ revision cũ, không artifact nào được gắn vào scene.
5. Route Brush/Lasso cũ (`membership/regenerate`) vẫn chạy, giờ đi qua đường build mới.
6. `ObjectifyState` có `mode = "region"`, phase hiển thị như build.

## Tests required
```
.venv/bin/python -m pytest tests/test_scene/test_object_geometry_build.py tests/test_scene/test_membership_regeneration.py \
  tests/test_scene/test_object_region.py tests/test_orchestration/test_scene_objectify_queue.py \
  tests/test_api/test_scene_v2_routes.py tests/test_api/test_role_matrix.py -q
.venv/bin/ruff check … && .venv/bin/ruff format --check …
cd frontend && npm run typecheck
```

## Commit
Theo Steps. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`.

## Out of scope
Không xoá đường `objectify(correction=…)` cũ trong task này; chỉ ngừng gọi nó. Ghi vào report để dọn sau.
