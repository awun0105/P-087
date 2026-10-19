# Viewer home command and GPU help

## Outcome

The shared camera home command now selects Orbit and invokes the viewer's public `resetCamera()` rather than navigating through a hidden annotation. In the installed SuperSplat viewer, Fly/Walk reset to their mode spawn; Orbit resets to the authored initial scene camera. This avoids mode-dependent spawn reset and uses the engine's reset transition. Explicit bookmark navigation remains separate through `gotoPose`.

`EditorFrame` now explains that viewing uses WebGL2 while the Gaussian editor requires a WebGPU adapter. Removed the unsafe-WebGPU flag instruction; the WebGL viewer error now names WebGL2.

Rechecked the existing fullscreen job workspace: fixed viewport layout, hidden job tabs, and the top-left exit command returning to the same job's Progress tab. No additional fullscreen changes were needed based on source/tests. Mobile editing and large-scene performance acceptance are deferred to production verification at the owner's request.

## Changed files

- `frontend/src/features/viewer/PlayCanvasScene.tsx`
- `frontend/src/features/studio/EditorFrame.tsx`
- `frontend/tests/playcanvas-camera.test.tsx`
- This report.

## Pre-flight gates

- codegraph: explored camera reset/navigation, PreviewScene, MetricSceneView and EditorFrame. Reviewed the installed viewer's camera manager reset and annotation commands.
- impact: shared PlayCanvas bridge used by PreviewScene, MetricSceneView, MetricConfirmView, GaussianLayer and WebGlViewer; callers inspected.
- understand: camera home versus explicit bookmark and WebGL fallback versus WebGPU editor. Understand-anything tool unavailable.
- minimal-code: reuse public viewer reset; no new camera controller, renderer or endpoint.
- checks: focused camera bridge, preview, camera toolbar and scene workflow suites — **37 passed**. TypeScript and ESLint passed; `git diff --check` clean. The camera fixture was updated to explicitly click the Fly command after reset instead of assuming the old mode persisted.
- DevTools: Chrome is at the login page; no errors/warnings. **UNVERIFIED: original user-visible camera failure reproduction and live fullscreen rendering — no authenticated session.** Unit tests verify command wiring and navigation, not GPU camera motion.
- graphify: AST update run after source changes.

Pre-existing deletions of CFG verification logs/images were left untouched and excluded from the commit.
