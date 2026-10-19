# Restore root: obsolete region failure notice — 2026-10-18

## Outcome

Fixed Studio's build-outcome notice so a failed/cancelled geometry, region, or membership operation is shown only for its base revision. Both the displayed revision and the API's current scene revision must match that base. Existing legacy responses with a null base revision retain their previous behavior. Queued/running work still exposes cancellation, including after the scene changes.

Changed in this task:

- `frontend/src/features/studio/ObjectifyNotice.tsx`: six-line revision guard after the pending-work branch.
- `frontend/tests/progress-objectify.test.tsx`: regression cases for all three build modes and both terminal outcomes, restore before the next status response, fresh page loads, scene/status synchronization, and operation-bound cancellation.
- This report.

Uncommitted changes from the earlier demo-orientation task were preserved. No commit, push, Cloudflare deployment, job retry, reconstruction, or scene edit was performed for this task.

## Confirmed cause on job-f9f14e7fbfb1

Evidence was read from SQLite in read-only mode, immutable SceneIR files, and the existing API log. Times below are Asia/Ho_Chi_Minh on 2026-10-18.

| Time | Event |
| --- | --- |
| 20:25:55.299 | Region request for `candidate-014` accepted against `rev-121`; operation `141dcb72896a445f999423537920de1e`. |
| 20:26:10.108 | Restore published `rev-122` from `rev-121`; endpoint `/demo/restore-root` returned HTTP 200. |
| 20:26:12.969 | Worker claimed the earlier region request. |
| 20:26:13.007 | Worker rejected that request because the current scene was already `rev-122`, preserving the restored scene. |
| 20:36:45.969 | A subsequent confirm action published `rev-123`. |

The environment and all 60 object records in `rev-122` equal those in `rev-001`. Restore succeeded. The message quoted by the user is the durable failure of the obsolete region request, not a restore failure. `ObjectifyNotice` displayed that terminal result on subsequent revisions without checking `base_revision`; `geometryReviewStep` already had a revision check.

The backend revision fence remains intact. Automatically retrying the old region command on restored data would apply an earlier user operation to a different scene and is not part of the fix.

## Verification

| Check | Actual result |
| --- | --- |
| Regression tests before source fix: `vitest run tests/progress-objectify.test.tsx --reporter=dot` | **13 failed, 21 passed**; obsolete notices reproduced. Log `/tmp/p087-restore-notice-red.log`. |
| `vitest run tests/progress-objectify.test.tsx tests/demo-controls.test.tsx tests/geometry-review-step.test.tsx tests/region-editor.test.tsx tests/object-review.test.tsx --reporter=dot` | **200 passed**, 5 files. Log `/tmp/p087-restore-notice-green.log`. |
| `.venv/bin/pytest tests/test_api/test_demo_routes.py tests/test_orchestration/test_scene_objectify_queue.py -q --tb=short` | **85 passed**. Restore/revision/queue regression coverage; log `/tmp/p087-restore-notice-backend.log`. |
| `tsc --noEmit --incremental false` in frontend | Passed. |
| `eslint src/features/studio/ObjectifyNotice.tsx tests/progress-objectify.test.tsx --max-warnings=0` in frontend | Passed. |
| HTTP requests to the exact scene route on ports 3012 and 3010, and API `/docs` on 8010 | All HTTP 200. This verifies serving, not logged-in browser rendering. |
| Production `npm run build` and `npm run start -- --port 3010` after idle-queue restart | Passed; original scene URL and API `/docs` both HTTP 200 after restart, temporary port 3012 closed. |
| `git diff --check` | Passed before report; checked again at handoff. |

## Local runtime

The original production stack on 3010 contained API PID `662402` and worker PID `662403`, supervised by stack PID `662396`. During the initial update check another job, `job-35a614b47ac9`, was RUNNING at `ST-CAMERA-POSE`. The supervisor exits and terminates its worker if its frontend exits, so that stack was initially left running.

Started an independent development frontend on **3012**, forwarding to the same API on 8010. Installed Next.js source confirms development output is isolated in `.next/dev`; the production output on 3010 was not replaced. PID: `/tmp/p087-restore-notice-frontend.pid`; log: `/tmp/p087-restore-notice-frontend.log`.

Before handoff, another read-only inventory found **zero RUNNING/QUEUED jobs and zero queued/running scene requests**. The target scene had independently advanced through human region edits to `rev-126`. Rechecked the empty queues immediately before a managed stack restart. Stopped the temporary 3012 frontend and restarted the original production stack with the same environment file. No active job was cancelled.

The first restart attempt timed out waiting for port 3010: the old npm process had exited while its Next.js grandchild remained alive. Verified that exact process's PID, command, working directory, and listening port, then sent SIGTERM to it and started the replacement stack. Replacement supervisor PID: `710496`; API PID: `710501`; log: `/tmp/p087-restore-notice-stack.log`; PID file: `/tmp/p087-restore-notice-stack.pid`.

The fixed UI is served on the original URL `http://localhost:3010/scenes/job-f9f14e7fbfb1?tab=studio&mode=scene` after the production build. Port 3012 was temporary and has been stopped. Scene head remained `rev-126`, with head checksum `sha256:fe49a30208e3d4ec258ff196b98ae177df77a4decad37fa92d1fd6df14a9c718`, across the restart.

## Pre-flight (GUIDE.md Rule 13)

- **codegraph:** Graphify query, CodeGraph exploration of `RegionEditor`, `useObjectifyState`, `ObjectifyNotice`, `DemoControls`, `restore_root`, `objectify_queue`, and SceneEditor; inspected the actual persisted request and revision lineage.
- **impact:** `codegraph callers ObjectifyNotice` identifies `ObjectReviewView` and the shared-page test; exported caller chain traced through `StudioTab` to `ScenePage`. Guard applies to three build modes in this shared notice; API/contracts are unchanged.
- **understand:** Read restore and region lifecycle source plus `STUDIO_UX_SPEC.md` revision/recovery guidance. UNVERIFIED: understand-anything tool unavailable in this session.
- **minimal-code:** Rung 2: reuse existing `base_revision`, `scene_revision`, and component revision; follow the revision-bound reporting rule already used by `geometryReviewStep`.
- **checks:** TypeScript and scoped ESLint passed; frontend 200 passed; backend 85 passed. No Python source changed in this task, so no new Python formatting check was needed.
- **DevTools:** UNVERIFIED per the user's instruction to inspect code without DevTools. Tests use simulated UI state; HTTP checks do not establish live browser/GPU acceptance.
- **graphify:** `graphify update .` completed: 27,906 nodes, 87,119 edges, 880 communities; generated outputs remain ignored.
