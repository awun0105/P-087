# Walk stage preview and object review before mesh

Date: 2026-10-17. No commit, push, new job, pipeline rerun or live scene edit performed by this change.

## Outcome

- Stage reconstruction previews explicitly request the job's sealed canonical collision. Their read-only Walk is independent of the editable SceneIR's geometry readiness. The route still verifies job ownership through the existing allow-list and binds the URI/checksum to the ReconstructionBundle's canonical geometry. Revision/dynamic/preview parameters cannot be mixed with this mode.
- Studio Walk retains its existing Ready gate. Collision loading displays the backend's explanation instead of only an HTTP number.
- The Draft banner opens the object panel, shows pending/chosen/fixed counts, and disables mesh creation until candidates have a review choice. The builder independently enforces review before artifact work.
- Draft candidates can be selected for editing or kept in the fixed background, individually or through checked rows. An already confirmed Draft object can be changed back to fixed background. Every change uses the returned revision; successful earlier changes remain visible if a later batch request fails.
- A fixed background object is skipped by the full per-object shell, collider and ObjectGS work. Its immutable source visual stays represented separately; its source occupancy remains in the authored environment collision. The full membership and original source references remain intact. ObjectGS receives a separate filtered membership for the selected training objects.
- Re-selecting a previously fixed object after Ready reopens geometry review instead of silently publishing a Ready object without a collider. Existing Ready scenes with already-separated ignored objects retain their restoration/rebuild behavior.

## Existing job

`job-f9f14e7fbfb1` has source visual, source membership, canonical collision and source frames needed by geometry build. It can continue from these artifacts after reviewing the choices. No new scene, upload, COLMAP, Brush or segmentation run is required for this choice change. A geometry build still validates the selected objects and may report another geometry problem; its success on this real job has not been claimed.

The only recorded Draft shell error was `candidate-016`, `open_or_nonpositive_component`. The user identified this object as a window. Its selection has not been changed automatically.

The target remained `rev-061`, generation 61, head checksum `sha256:b28d8ab645a39dc4bbeb2c2abb409571d13ef74a03fe668ebc721acb35982c38` before and after runtime reload.

## Files changed

Backend:

- `src/api/product/artifacts.py`
- `src/services/orchestration/scene/object_geometry_build.py`
- `src/services/scene/editing/commands.py`
- `src/services/scene/effective_collision.py`

Frontend:

- `frontend/src/features/studio/GeometryReviewBanner.tsx`
- `frontend/src/features/studio/ObjectReviewView.tsx`
- `frontend/src/features/studio/MetricSceneView.tsx`
- `frontend/src/features/studio/StageViewer.tsx`
- `frontend/src/features/viewer/PlayCanvasScene.tsx`
- `frontend/src/lib/api/endpoints.ts`

Regression tests:

- `tests/test_scene/test_editing_review.py`
- `tests/test_scene/test_effective_collision.py`
- `tests/test_scene/test_object_geometry_build.py`
- `tests/test_scene/test_object_geometry_build_objectgs.py`
- `tests/test_scene/test_shell_geometry_walk_usd.py`
- `frontend/tests/geometry-review-banner.test.tsx`
- `frontend/tests/object-review.test.tsx`
- `frontend/tests/metric-effective-collision.test.tsx`
- `frontend/tests/playcanvas-camera.test.tsx`

Graphify outputs were refreshed with `graphify update .`. Pre-existing working-tree changes were preserved.

## Verification

Initial regression reproduction: 3 new tests failed on the old behavior. After the core changes, the same 3 passed.

Backend command:

```bash
.venv/bin/pytest tests/test_scene/test_editing_review.py tests/test_scene/test_object_geometry_build.py tests/test_scene/test_object_geometry_build_objectgs.py tests/test_scene/test_effective_collision.py tests/test_scene/test_shell_geometry_walk_usd.py tests/test_scene/test_object_aware_composition.py tests/test_scene/test_representation_composition.py tests/test_simulation/test_representation_conservation.py tests/test_simulation/test_object_aware_usd.py tests/test_contracts/test_object_geometry.py tests/test_orchestration/test_scene_objectify_queue.py -q --disable-warnings --maxfail=5
```

Result: **220 passed in 199.74s**. After the final source-ownership fallback change, the 4 targeted cases covering missing ownership, all-fixed background and selective ObjectGS passed in 2.52s. Counts overlap and must not be added as unique tests. These include real CPU CoACD/OpenUSD regression paths where the isolated runtime is installed; ObjectGS training remains mocked, not real GPU acceptance.

Frontend command:

```bash
cd frontend
npx vitest run tests/geometry-review-banner.test.tsx tests/object-review.test.tsx tests/metric-effective-collision.test.tsx tests/stage-viewer.test.ts tests/stage-view-selection.test.tsx tests/playcanvas-camera.test.tsx
```

Result: **105 passed, 6 files**. After the final review-panel navigation change, the three affected suites were rerun: **81 passed, 3 files**. These counts overlap.

Broader `npx vitest related <six changed frontend source files> --run`: **288 passed, 2 failed, 21 files**. Both failures are pre-existing expectations in `studio-inspection.test.tsx`: expected `QA calibration LiDAR`, while unchanged `stages.ts` at HEAD uses `Kiểm tra căn chỉnh LiDAR`. Neither file was changed.

Static checks:

- `.venv/bin/ruff check src/ tests/`: passed.
- `.venv/bin/ruff format --check src/ tests/`: 719 files already formatted.
- `npx tsc --noEmit`: passed.
- `npx eslint <changed frontend source and test files>`: passed.
- `git diff --check`: passed.
- `graphify update .`: AST-only graph refresh; extractor warnings about 42 files with no symbols were reported.

## Live verification

Before reloading the API, the browser sent `reconstruction=true` but the old API returned 409, `Cần tạo mesh trước khi Walk.`

After confirming no RUNNING jobs or RUNNING/CLAIMED operations, `systemctl --user restart r2s-stack` reloaded the API, worker and dev frontend. A queued job remained in durable storage. Live OpenAPI includes the new `reconstruction` parameter.

Chrome DevTools on the authenticated page at `/scenes/job-f9f14e7fbfb1/stages/ST-RGB-GEOMETRY` verified:

- collision HTTP **200**, `X-Collision-Mode: reconstruction`;
- GLB **218988 bytes**, magic `glTF`;
- rendered reconstruction and collision overlay;
- no `Không thể dùng Walk` notice;
- no console errors or warnings.

A separate negative GET without `reconstruction=true` still returned 409, `Cần tạo mesh trước khi Walk.`, proving that the Studio readiness gate remains enforced.

Studio browser inspection verified the `Duyệt vật thể` entry, `Tạo mesh cho 60 vật đã chọn`, and the fixed-background action on Vật thể 16. Only navigation/selection was used; no live scene mutation or mesh request was sent. The real job's selective geometry build, interactive walking/contact behavior and Isaac validation remain unverified.

Evidence under `/tmp`:

- `p087-review-stage7-after.snapshot.txt`, `p087-review-stage7-after.png`
- `p087-review-window.snapshot.txt`, `p087-review-window.png`
- `p087-review-backend-final.log`, `p087-review-last-cases.log`
- `p087-review-frontend-final.log`, `p087-review-last-ui.log`, `p087-review-related.log`
- `p087-review-live-openapi.json`

## Pre-flight — GUIDE.md Rule 13

- codegraph: read objectify, geometry build/steps, review commands, effective collision, artifact route, stage viewer and shared scene viewer; explored their callers/tests before edits. Graphify queries supplied the scoped relationships.
- impact: shared review commands, geometry publication, Studio/Walk collision and browser viewer loading; consumers include USD export and source representation validation. Covered by the focused backend/frontend suites above.
- understand: PRD FR-07, STUDIO_UX_SPEC S08 and current source/call paths. `understand-anything` tool was unavailable; no result from that tool is claimed.
- minimal-code: reused confirm/ignore, SceneIR revisions, source ownership, immutable membership, background collision builder and existing queue. No new SceneIR fields or migration.
- checks: Ruff/format/TypeScript/ESLint passed; focused suites passed as above. Broader related frontend suite retains two unrelated failures.
- DevTools: real authenticated stage and Studio inspected; HTTP 200 collision and clean console verified. Real selective mesh run and Isaac acceptance not executed.
