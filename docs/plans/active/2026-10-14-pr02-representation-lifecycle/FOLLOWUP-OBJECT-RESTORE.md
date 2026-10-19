# Studio object lifecycle follow-up — grouping, recovery and legacy activation

## Outcome

Implemented in the original checkout on `codex/browser-collider-frame-correctness`; no new worktree. The new changes are committed locally, not pushed by this follow-up. This request supersedes the earlier PR-02 restriction against adding merge recovery.

The archive filter is now **Đã loại/xoá/gộp/ẩn**, with separate headings for **Đã loại**, **Đã xoá**, **Đã gộp**, **Ẩn trên màn hình**, and **Tắt trong mô phỏng**. Hidden and disabled objects leave the main/pending/confirmed lists, remain selectable/restorable in the archive, and retain distinct semantics. Viewport hiding remains frontend state and creates no SceneIR revision. List filtering no longer removes outlines belonging to other visible objects.

## Live error evidence

The reported `candidate-010: INVALID_OBJECT_ACTIVATION` was verified in `job-a14981f78f85` artifact `rev-073`: state CANDIDATE, active=true, operation=hide, last_scene_operation=show. History shows the old visibility action repeatedly toggled this Candidate's active flag. The representation validator is correct; Candidate activation must not be mistaken for confirmation.

The UI now explains this legacy state and offers **Khôi phục trạng thái candidate-010**, using the existing revision/CAS restore command to return to Candidate active=false without confirming or moving it.

Before an attempted narrow repair, the agent rechecked the committed DB head. It was already `rev-074`, operation=`restore_revision`, Candidate active=false with no representation blockers. The agent created **no extra revision**. A read-only comparison against rev-073 confirmed unchanged pose, Gaussian/geometry/collider refs, source ownership, physics and every other object. Receipt: `/tmp/p087-object-lifecycle/current-state-verification.json`.

## User operations

| Group | Restore behavior |
| --- | --- |
| Ignored | Remove ignored review; return to Candidate waiting for confirmation |
| Deleted | Restore the retained object and its original refs/pose; Confirmed becomes active, Candidate stays pending |
| Merged | Confirm restoring the entire group before its merge; restores sealed source refs and Gaussian/collision ownership |
| Viewport hidden | Show locally; no API write or simulation change |
| Simulation disabled | Enable Confirmed with explicit active=true and current revision/CAS; also clear its viewport hide if needed |

User-added objects are now soft-deleted like reconstructed ones, so future Delete operations are restorable. User-added objects already hard-deleted by older code have no current tombstone; recovering those still requires a suitable scene-history revision.

**Gộp** combines multiple pending proposals that represent parts of one real object. It preserves a chosen primary ID and joins their Gaussian/ownership representation; secondaries remain audit tombstones. The inspector exposes **Gộp với ứng viên khác**. The existing correction panel is labeled **Gộp ứng viên / Sửa nhóm Gaussian** and explains the operation. Existing eligibility gates (sealed membership, source pose/ownership, pending reconstructed candidates) remain in place; the segmentation/correction/CoACD algorithms were not changed.

## Merge recovery and safety

`restore_merged_group` loads checksum-verified committed snapshots before/after the merge via `SceneEditor.revision`. It restores the complete affected object group and only the corresponding owner-map entries, keeping unrelated current objects/edits. Nested merges unwind until the selected object is independent. It reuses immutable artifacts and publishes once through the existing restore endpoint and CAS.

The command rejects missing history, changed source geometry/labels/context, changed ownership, and edits to the affected group after merging. It does not silently discard later edits or roll back the entire scene. Those cases report a specific error; the existing scene-history restore remains an explicit broader choice.

## Changed files

- `src/services/scene/editing/commands.py`: soft-delete user-added objects; existing restore repairs legacy Candidate activation.
- `src/services/orchestration/scene/object_restore.py`: guarded group restoration from committed history.
- `src/services/orchestration/scene/objects.py`: route merged restore through that service.
- `frontend/src/features/studio/ObjectReviewView.tsx`: operation groups, scoped restore controls, merge discoverability, confirmation dialog and legacy-state explanation.
- `tests/test_scene/test_object_restore.py`, `test_editing_review.py`, `test_editing_v2.py`: conservation, nested merge, CAS, later edits, missing history, Candidate repair and user-added restoration.
- `frontend/tests/object-review.test.tsx`: archive groups, local visibility, restore commands, confirmation/cancel, legacy repair and merge discovery.

## Verification

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
# PASS; 615 files already formatted

.venv/bin/pytest \
 tests/test_scene/test_object_restore.py tests/test_scene/test_object_correction.py \
 tests/test_scene/test_representation_composition.py tests/test_scene/test_editing_review.py \
 tests/test_scene/test_editing_v2.py tests/test_scene/test_object_membership.py \
 tests/test_scene/test_scene_rush_pipeline.py tests/test_api/test_scene_routes.py \
 tests/test_api/test_scene_v2_routes.py tests/test_orchestration/test_scene_head.py \
 tests/test_orchestration/test_scene_editor.py tests/test_simulation/test_representation_conservation.py \
 tests/test_simulation/test_usd_capabilities.py tests/test_simulation/test_preflight.py \
 tests/test_orchestration/test_simulation_package.py tests/test_simulation/test_collision_edit_composition.py \
 tests/test_simulation/test_usd.py tests/test_simulation/test_simulation_config_override.py -q
# 295 passed; no skips/failures

cd frontend
./node_modules/.bin/vitest run
# 586 passed across 67 files; object-review suite: 44 passed
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/eslint src/features/studio/ObjectReviewView.tsx tests/object-review.test.tsx
# exit 0
```

An intermediate fixture change missed a `SceneObjectOrigin` import (one failed test); it was corrected in local commit `207e57a6` and the final full regression above passes. Existing Three.js multiple-instance warnings appear in viewer tests.

## Commits and gates

- `994d0891`: restorable deletion and guarded merge undo.
- `207e57a6`: correct origin enum fixture import.
- `0e61f45f`: operation groups and Studio restore controls.
- The documentation commit containing this report also updates stale operation comments.

Pre-flight (GUIDE.md Rule 13):

- **codegraph:** ObjectReviewView/FILTERS/Inspector, editing commands, action service, merge producer, membership validation and SceneEditor history/publication were explored before changes; consumers include StudioTab, product scene routes, export/carve tests and the new restore service. Graphify AST update completed after implementation.
- **impact:** existing restore endpoint/SceneIR CAS; user-added Delete now retains tombstones; viewport filters affect lists independently of rendering/physics.
- **understand:** merge → committed snapshots → guarded group restore → one new revision; separate local visibility and simulation state. UNVERIFIED: dedicated understand-anything tool unavailable.
- **minimal-code:** reused existing restore endpoint, snapshot API, strict activation, membership map, and AlertDialog; no new ownership artifacts, GPU producer, migration-on-read or new SceneIR fields.
- **checks:** final results above; source/ownership conservation and unrelated-edit protection are tested.
- **DevTools:** navigated actual local scene URL, which redirected to `/login?next=...`; login snapshot captured, console error/warning list empty, auth/navigation network requests returned 200. **UNVERIFIED: authenticated Studio panel/WebGL/Isaac acceptance** — no logged-in session in the connected browser. Tests use a canvas stub; no claim of browser E2E PASS.

The frontend dev server can reload these changes. Backend must restart to load the new merge-restoration service. No runtime restart or new production merge/delete was performed by this follow-up.
