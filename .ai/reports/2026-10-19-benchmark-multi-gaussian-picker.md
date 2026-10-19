# Benchmark point picking with multiple Gaussian assets — 2026-10-19

## Outcome

Removed the single-visible-Gaussian restriction from `SplatInspection`. Picking and marker rendering now use the viewer content entity (`gsplat`) as the common source-frame reference. The PlayCanvas Picker still reads the visible scene's world point, including object translation and rotation; converting that point through the environment's inverse transform preserves its current scene position rather than converting it into an individual object's local coordinates.

The reference entity can remain a coordinate reference while hidden. A missing reference still raises an explicit error, and the existing non-invertible-transform and non-finite-point checks remain. Queue ordering, history, input gating, GPU readback teardown and metric-calibration source coordinates are preserved.

## Changed files

- `frontend/src/features/viewer/splat-inspection.ts`: replace global Gaussian component counting with the named viewer content entity's transform, shared by point acquisition and marker rendering. Narrow the graph node to `Entity` before accessing its Gaussian component.
- This report.

Existing uncommitted collision-responsiveness changes from the preceding task were preserved. No scene data, geometry artifact, reconstruction operation, commit, push or cloud deployment was performed for this fix.

## Verification

- `cd frontend && ./node_modules/.bin/tsc --noEmit --incremental false`: passed after fixing a newly introduced `GraphNode.gsplat` type error with an `Entity` guard.
- `cd frontend && ./node_modules/.bin/eslint src/features/viewer/splat-inspection.ts --max-warnings=0`: passed.
- Production build through `scripts/gpu/run_stack.sh scripts/gpu/studio.env`: passed; compilation 4.9 s, TypeScript 4.0 s, 19 static pages generated. Next.js started on port 3010.
- Local scene URL and API `/docs`: HTTP 200. All persisted scene-head checksums match those captured before restarting. Receipt: `/tmp/p087-benchmark-picker/verification.json`.
- `git diff --check`: passed.
- `graphify update .`: completed after the final source edit; 27,945 nodes, 87,202 edges, 898 communities. Generated graph files remain ignored.
- Automated tests: not added or run in this task. Static checks and HTTP serving do not establish GPU picking correctness.
- Browser/GPU interaction: unverified; no DevTools used, per the user's instruction. Multiple overlapping splats, moved/rotated objects and marker placement need direct browser confirmation.

The initial production build failed on the same newly introduced TypeScript error; it was corrected before the successful rebuild. Both attempts are retained in `/tmp/p087-benchmark-picker/local-stack.log`.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: `SplatInspection` methods and callers; `ObjectReviewView` → `MetricSceneView` → `PlayCanvasScene`; source-frame utilities and `SceneOverlay.setObjects`. Graphify query also inspected these relationships.
- impact: shared inspection controller used by Benchmark and metric calibration. Public constructor and source-coordinate contract unchanged.
- understand: existing source read in this task establishes the measurement flow; no product or schema change.
- minimal-code: rung 2 — reuse the viewer's existing named content entity and the installed Picker's world-point result. No new selector, dependency or picker implementation.
- checks: TypeScript clean; scoped ESLint clean; production build passed; tests not run.
- DevTools: UNVERIFIED — user requested source inspection without DevTools; browser/GPU interaction not claimed.
