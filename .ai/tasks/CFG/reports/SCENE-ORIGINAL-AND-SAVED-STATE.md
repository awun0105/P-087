# Scene original and saved state — 2026-10-13

## Behavior

- **Lưu trạng thái** saves the current scene revision, replacing the previous user snapshot. The button remains available after a snapshot exists.
- **Quay lại trạng thái đã lưu** retains the existing baseline reset operation. Returning to the original does not remove or replace the saved snapshot.
- **Về bản gốc**, adjacent to the save button, restores the first immutable SceneIR revision (`rev-001`). The existing editor enforces immutable artifacts and publishes restored content as a new revision. No pipeline stage runs again.
- A scene already at the original does not produce redundant revisions. Stale restore requests return 409 even in this case. The original button is available to contributors without requiring a saved snapshot; ScenePage and the API retain their job mutation authorization checks.
- Reviewer save/clear permissions and the existing API baseline field names remain compatible. UI badges and clear/restore wording consistently use saved-state terminology.

## Room recovery

Target confirmed by the user: `job-a14981f78f85`. Its current `rev-023` has the same environment and object content as `rev-001`: 60 original objects. The original SHA256 is `e2fe532223ac4798ae1cea05e9535e566652951af8f9aac2349650f245e5a914`.

The authenticated live original-restore API returned 200 with `at_root=true`, keeping `rev-023` because it already matched the original. Its saved snapshot is currently absent. Historical edited revisions remain available. No snapshot was automatically created or overwritten during recovery.

The API was restarted with its existing environment to load the repair. The frontend and worker continued running. Chrome shows **Lưu trạng thái** immediately followed by **Về bản gốc**, with the latter disabled while viewing the original. A deliberately stale live request returned the expected 409.

## Changed paths

`src/services/orchestration/scene/demo.py`, `src/api/studio/demo.py`, `frontend/src/lib/api/studio.ts`, `frontend/src/lib/contracts/studio.ts`, `frontend/src/features/studio/scene/DemoControls.tsx`, `frontend/src/features/studio/ScenesHome.tsx`, `tests/test_api/test_demo_routes.py`, `tests/test_api/test_role_matrix.py`, and `frontend/tests/demo-controls.test.tsx`.

The workspace contained an unfinished original-restore implementation before this task. This change completes its saved-state UI semantics, editor availability, concurrency guard and regression coverage.

## Verification and gates

- Backend: `.venv/bin/pytest tests/test_api/test_demo_routes.py tests/test_api/test_role_matrix.py tests/test_orchestration/test_scene_editor.py -q`: **56 passed**.
- Frontend: `pnpm exec vitest run tests/demo-controls.test.tsx tests/studio-overview.test.tsx tests/ux-scene-flow.test.tsx`: **47 passed**.
- Regression covers original → edit → save → original → saved state → replace saved state → original → saved state. The original artifact remains byte-for-byte unchanged. Separate coverage checks stale requests and saving while already at the original.
- `pnpm typecheck`: clean. ESLint on changed frontend files: clean. Ruff check/format on changed Python files: clean. `git diff --check`: clean.
- CodeGraph inspected the shared demo API/service callers, immutable SceneEditor revision handling, restore command and ScenePage controls. Graphify query and AST update completed.
- Impact: scene header controls, library saved-state badge and original restore endpoint. Minimal code reuses the existing baseline persistence and revision restore command.
- UNVERIFIED: understand-anything plugin unavailable; current source and artifact lineage supplied the flow evidence.
- DevTools: authenticated local Room state, button labels/order and original-restore API verified. The console's 409 message came from the deliberate stale-request check. No cloud deployment claim.
