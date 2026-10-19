# Separate collision geometry, selection frames, and triangle edges

Date: 2026-10-14
Branch: codex/pr04-browser-physics. Changes remain uncommitted; no push or PR creation.

## Outcome

- Collision mesh toggles the effective environment mesh and all active physics object collider previews.
- Khung vật thể preserves the original shape-following GLB surface and selected-object edge highlight. Box geometry is used only when no GLB is available or while loading/failed. Its visibility is independent of the collision layer.
- Cạnh tam giác mesh switches both environment and object collider previews between triangle surfaces and triangle-edge wireframe. Enable Collision mesh first. This is a wireframe mode, not edges over filled surfaces.
- Object collider previews derive from physicsObjects, independent of the viewport Gaussian hidden set. They include confirmed active colliders, not pending/inactive candidates.
- Gizmo and physics poses update both object selection shapes and collider previews, including collider child transforms. GLB node transforms remain in the instantiated hierarchy.
- Display toggles reuse collider entities and retain the current simulated pose. Wireframe buffers are generated only when absent. Deletion/revision replaces inputs; stale asset callbacks cannot reattach discarded previews.
- Collider GLB loading does not draw an invented box substitute. Authored box colliders still draw their box geometry.
- Physics, carving, activation, producer, and persistence behavior are unchanged.

## Changed files

- frontend/src/features/studio/MetricSceneView.tsx
- frontend/src/features/viewer/scene-overlay.ts
- frontend/tests/metric-effective-collision.test.tsx
- frontend/tests/scene-overlay-gizmo.test.ts
- This report.

## Verification

- PASS: npx vitest related src/features/viewer/scene-overlay.ts --run --maxWorkers=2 — 119 tests, 10 files, 15.64 s.
- PASS: npx tsc --noEmit.
- PASS: npx eslint on the four changed source/test files.
- PASS: .venv/bin/ruff check src/ tests/.
- PASS: .venv/bin/ruff format --check src/ tests/ — 619 files.
- PASS: git diff --check.
- graphify update .: AST graph refreshed; community relabel warnings do not indicate a source check failure.

The first added graphics fixture test failed because its stub lacked PlayCanvas onPostStateChange. The fixture was corrected and the final related suite passed. These tests use real PlayCanvas entity transforms with stub graphics systems, not a live GPU browser scene.

## UI check

Reload the updated frontend. Enable Collision mesh, disable Khung vật thể: environment and active object colliders should remain visible. Enable Cạnh tam giác mesh to inspect triangle topology; disabling it restores surfaces. Disable 3DGS màu for a clearer geometry view. Move/rotate an object and check the collider follows it. Display toggles must not change Walk collision or activate/deactivate an object.

Browser inspection reached authenticated Room rev-092. Its canonical collision endpoint returned 200 with matching X-Scene-Revision and a composition checksum. Before reload the audit tab requested obsolete rev-090 while the scene head advanced, producing 409 as expected.

PASS: actual browser PlayCanvas entities for candidate-002 were temporarily moved through setObjectPose. Gaussian, selection GLB, and independent collider had equal moved positions. Rebuilding collider entities retained the live pose. The original pose and display state were restored in finally; no persistent object command or SceneIR revision was written. Console contained no warnings/errors after reload and this probe.

UNVERIFIED: complete physical mouse drag -> release -> API save -> Walk contact sequence and dense wireframe performance. No server was started/stopped. Isaac Sim was not tested.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: SceneOverlay, setBoxes, paint, shapeGeometry, MetricSceneView source and callers inspected.
- impact: ObjectReviewView and StageLayer rendering; usePhysicsPlay updates object poses. No physics API changes.
- understand: existing local rendering flow inspected; separate geometry display from selection and physics state.
- minimal-code: reused PlayCanvas wireframe/material/entity rendering and existing quaternion helpers.
- checks: TypeScript and scoped ESLint clean; related Vitest 119 passed / 0 failed; Ruff clean.
- DevTools: authenticated Room inspected; programmatic pose/rebuild probe passed with clean console. Physical mouse/Walk sequence remains UNVERIFIED.

## Pose regression correction

Environment-load completion and display changes shared an effect that rebuilt object frames from authored inputs during a drag. The effects are now independent. Rebuilt object layers use the current Gaussian entity pose with the collider child transform. setObjects restores all representations together, including Reset/Exit Walk.

New regression assertions failed before the fix (3 failures in 10 focused tests) and passed afterward (10/10). Additional native/camera/loading physics suite: 35 tests across 4 files passed. Effective collision and Scene API suite: 65 tests passed in 3.19 s. Source carving policy and collision ownership were not changed.

Historical live evidence: Room rev-090 had 60 CANDIDATE objects, none active; candidate-002 moved between rev-089 and rev-090. Room later advanced to rev-092 with candidate-002 CONFIRMED and active. These are distinct snapshots, not a change made by this audit.
