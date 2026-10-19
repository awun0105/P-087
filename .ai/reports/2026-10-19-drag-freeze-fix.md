# Object movement: collision preparation responsiveness — 2026-10-19

## Outcome

Changed the work triggered after releasing a moved object:

- Viewer and physics share one active display-collision request and GLB decode.
- Every new revision URL still reaches the API. Decoded geometry is reused only after a successful authorized response with the same scoped ETag. Revision conflicts remain errors; job, frame, source URL, and mode boundaries remain in the cache key. The decoded cache retains at most two entries.
- The viewer retains one prepared environment BVH. A validated unchanged geometry read reuses it; a changed removal mask produces a new preparation.
- Large GLB decoding and BVH construction run in cooperative slices. Aborted/replaced loads cannot install their results. The pinned collision algorithm and synchronous object-query API retain their existing geometry semantics.
- Hidden collision overlays and inactive third-person occupancy are deferred. The upstream debug mesh is allocated only when its overlay is visible.

The source mesh, membership, object poses, revision contracts, backend authorization, and reconstruction pipeline were not changed. This task addresses the interaction stall; the separate upstream replacement of smooth geometry by a voxel background remains unchanged.

## Changed files

| File | Change |
| --- | --- |
| `frontend/src/features/viewer/cooperative.ts` | Abortable generator runner with an 8 ms scheduling budget. |
| `frontend/src/features/viewer/glb-mesh.ts` | Reuse the validated decoder in synchronous/cooperative forms; yield during large vertex/index loops; omit unused part copies for the flattened environment reader. |
| `frontend/src/features/viewer/collision-mesh.ts` | Reference-counted active loads, cancellation, bounded decoded reuse after fresh HTTP validation. |
| `frontend/src/features/viewer/PlayCanvasScene.tsx` | Use the shared loader and abortable asynchronous viewer collision bridge. |
| `frontend/src/features/viewer/usePhysicsPlay.ts` | Use the shared display geometry and weakly cache its canonical conversion. |
| `frontend/src/features/studio/MetricSceneView.tsx` | Load the overlay only when needed; prepare third-person occupancy only while active. |
| `frontend/scripts/patch-viewer-collision.mjs` | Extend the existing version-pinned postinstall patch with cooperative preparation, one prepared environment, and lazy debug geometry. |
| `frontend/tests/collision-mesh.test.ts` | Shared loads, scoped identity, changed geometry, fresh-revision rejection, cancellation and corrupt input recovery. |
| `frontend/tests/cooperative-collision.test.ts` | Decoder parity/validation, BVH query parity, event-loop yielding and aborts. |
| `frontend/tests/playcanvas-camera.test.tsx` | Assert asynchronous installation without recreating the viewer; retain stale-response/error checks. |
| `frontend/tests/viewer-collision-patch.test.ts` | Execute installed bridge callbacks; verify lazy allocation, prepared reuse and aborted-result rejection. |
| `frontend/tests/metric-effective-collision.test.tsx` | Hidden overlay stays unloaded across pose saves; enabling uses the current revision; preserve interaction/layer checks. |

## Verification

Executed in `frontend/` unless otherwise noted:

| Check | Actual result |
| --- | --- |
| `vitest run tests/collision-mesh.test.ts tests/cooperative-collision.test.ts tests/playcanvas-camera.test.tsx tests/viewer-collision-patch.test.ts tests/glb-mesh.test.ts tests/glb-collider-parts.test.ts tests/collider-loading.test.ts tests/metric-effective-collision.test.tsx tests/object-camera-collision.test.ts tests/region-editor.test.tsx tests/object-review.test.tsx tests/scene-overlay-gizmo.test.ts tests/scene-physics.test.ts tests/third-person.test.ts --reporter=dot` | **234 passed**, 14 files; `/tmp/p087-drag-audit/final-tests.log`. |
| `tsc --noEmit --incremental false` | Passed. |
| Scoped ESLint over changed script, source and tests, `--max-warnings=0` | Passed after removing unused parameter warnings in a test mock. |
| `node scripts/patch-viewer-collision.mjs` | Installed the generated patch successfully. |
| Fresh postinstall replay and second-run idempotency | Passed: reconstructed pristine pre-patch files in an isolated temporary package, replayed all eight patch stages, compared exact output to the installed files, then repeated. Script `/tmp/p087-drag-audit/check-postinstall.mjs`. |
| Production `npm run build` through the normal local stack | Compiled, TypeScript, and static page generation passed; `next start --port 3010` ready. |
| Exact local scene URL and API `/docs` | HTTP 200 after restart. This verifies serving, not authenticated browser interaction. |
| `graphify update .` | Completed: 27,939 nodes, 87,195 edges, 856 communities; generated files remain ignored. |
| `git diff --check` | Passed; checked again at handoff. |

An initial focused run had 72 passes and two failures: old overlay tests assumed an invisible overlay was eagerly loaded. Tests now explicitly enable the overlay or surface tool before asserting its load. The fresh-install replay also caught an ambiguous declaration patch anchor (`createMeshCollision` matched the new async name); the anchor now includes `(` and fresh replay passes. Neither failure was reported as a pre-existing repository problem.

No Python source changed, so no Python test/lint run was needed for this frontend fix.

## Actual-mesh CPU measurement

Used the immutable drjohnson object-aware background: 795,053 vertices and **1,618,392 triangles**. The probe executes the installed pinned viewer's exact collision class/helpers in Node's ordinary realm, with a 10 ms timer running during the cooperative preparation. The original synchronous measurement came from the preceding read-only diagnosis.

| Measurement | Result |
| --- | ---: |
| Previous synchronous constructor | 3,718.89 ms in one call |
| Cooperative construction total | 5,217.45 ms |
| Timer callbacks during construction | 369 |
| Largest timer gap | 35.28 ms |
| Process RSS after cooperative construction | 618.16 MiB |

Total computation grew in this sample because scheduling yields have a cost. The fix allows input/paint tasks between slices and avoids another build when validated geometry is unchanged. The 8 ms budget is checked at bounded generator checkpoints; it is not a hard browser frame-time guarantee. RSS includes Node, source-extraction dependencies, GLB bytes and query structures; it is not a browser heap measurement. Evidence: `/tmp/p087-drag-audit/cooperative-profile.json` and `profile-cooperative.mjs`.

## Local handoff

Immediately before restarting, verified zero queued/running reconstruction jobs, zero queued/running scene requests, and zero queued/waiting/running import operations. Restarted the existing native stack with its existing environment file and explicitly terminated the identified old Next.js descendant so npm could not leave port 3010 occupied.

- New supervisor: `1382331`.
- Log: `/tmp/p087-drag-audit/local-stack.log`.
- Scene URL: `http://localhost:3010/scenes/job-f9f14e7fbfb1?tab=studio&mode=scene`.
- All persisted scene head checksums matched the before-restart snapshot. The target remains `rev-197`.
- No job or mesh rebuild was submitted. No commit, push, or Cloudflare deployment was performed.

Reload the page with Ctrl+Shift+R to load the new client bundle. DevTools and browser automation were not used, following the user's instruction. Actual browser/GPU interaction acceptance remains unverified.

## Pre-flight — GUIDE.md Rule 13

- **codegraph:** Graphify query and CodeGraph/source tracing covered `ObjectReviewView.run`, gizmo end callbacks, `MetricSceneView`, `usePhysicsPlay.fetchMesh`, `PlayCanvasScene`, the GLB reader, and the installed collision bridge.
- **impact:** Ran callers for `PlayCanvasScene`, `MetricSceneView`, `usePhysicsPlay`, `parseGlbMesh`, and `SceneOverlay`. The changed synchronous reader retains its signatures and tests for all existing consumers. New shared helpers are used by the two display-collision consumers. The pinned library's synchronous object-query path remains available.
- **understand:** Read the existing flow and collision revision/identity boundaries. UNVERIFIED: understand-anything tool is unavailable in this session.
- **minimal-code:** Reused the existing validated GLB decoder, pinned collision algorithm, postinstall mechanism, API ETag, and native timers/generators. No new dependency or background service was introduced.
- **checks:** 234 frontend tests passed; TypeScript, scoped ESLint, fresh/idempotent patch replay, production build, and HTTP health passed.
- **DevTools:** UNVERIFIED per the user's no-DevTools instruction. Unit tests and CPU timer measurements do not establish browser/GPU acceptance.
