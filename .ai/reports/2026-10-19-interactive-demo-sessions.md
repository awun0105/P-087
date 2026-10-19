# Interactive sample workspaces

## Outcome

Published samples open the real Studio scene page and stage inspection components in a disposable workspace. Each visit gets a new capability token, SQLite database, artifact namespace and worker directory. Native commands execute against that workspace. Source job IDs, artifact URIs and checksums are preserved inside the isolated stores.

The iframe owns the demo document lifetime. API scope is captured once for that document, so late asynchronous work stays bound to the old session even after navigation. Reset or exit closes the session and removes the iframe. Unknown, closed or expired session requests return 410.

The published workspace is frozen beside the demo bundle. Later source edits or removal do not change it. Future exports of completed durable jobs include this baseline. `python -m scripts.demo.freeze_demo_workspace --sample <id>` upgrades an explicitly selected legacy sample; existing baselines are refused.

## Local data and service

Added workspace sidecars to these three existing samples. Their public `manifest.json` bytes were preserved.

| Sample | Job | Frozen revision | Files |
| --- | --- | --- | --- |
| drjohnson-f9f14e7f-d7be7c91-aligned | job-f9f14e7fbfb1 | rev-198 | 951 |
| mip-nerf-360-room-images-4-bfc7d73f-024f857c-aligned | job-bfc7d73f0dbf | rev-062 | 862 |
| playroom-7c9820b4-784cdd45-aligned | job-7c9820b4834f | rev-003 | 636 |

Immutable bytes use hard links on the same filesystem; cross-filesystem copies use exclusive creation. Serialized artifact envelopes can contain a content checksum different from their file checksum. Snapshot traversal verifies incoming file references and follows the envelope's dependencies without treating its own identity as another dependency. Mutable Rerun recordings use byte copies.

The local supervisor was restarted after checking there were no active source pipeline, scene, import, registration or validation operations. New supervisor: 2067082. API: 8010. Production Next.js: 3010. No Cloudflare deployment, commit or push was performed.

## Concurrent activity and cleanup

- Separate visits and tabs receive independent sessions, including visitors viewing the same sample or moving the same object.
- Within one session, native SceneIR revision/CAS and worker fencing still apply. Concurrent edits from the same base revision yield one success and one 409.
- Real shared jobs retain their existing whole-scene revision/CAS behavior. This change adds no region locks, presence indicators or collaborative transform broadcast.
- Demo requests are dispatched after normal queues. The parent reserves resources in the shared machine ledger before starting a native private worker. Demo GPU work remains exclusive until measurements qualify sharing.
- File locks prevent two dispatchers from owning the same session and prevent deleting files while an API stream or worker uses them.
- Closing marks the session unavailable immediately. The dispatcher terminates its private worker and owned descendants, releases resource reservations, then cleanup removes its files. A Linux parent-death signal prevents an orphan private worker when its dispatcher disappears.
- Browser heartbeat: 25 seconds. Orphan timeout: 180 seconds. Hard lifetime: 4 hours. Default maximum: 32 sessions. These limits are configurable through `PRODUCT_DEMO_*` settings.
- API and dispatchers require the same session filesystem with working file locks. This is implemented for the local shared-filesystem stack; independent cloud hosts without a shared volume are not validated.

## Changed files for this task

Backend and CLI:

- `src/api/demo_sessions.py`
- `src/api/auth.py`
- `src/api/product/deps.py`
- `src/api/studio/deps.py`
- `src/api/studio/demo.py`
- `src/api/routes.py`
- `src/config.py`
- `src/services/orchestration/samples/session_context.py`
- `src/services/orchestration/samples/sessions.py`
- `src/services/orchestration/samples/snapshot.py`
- `src/services/orchestration/samples/workspace.py`
- `src/services/orchestration/samples/session_worker.py`
- `src/services/orchestration/samples/export.py`
- `src/services/orchestration/jobs/admission.py`
- `src/services/orchestration/jobs/worker_cli.py`
- `scripts/demo/freeze_demo_workspace.py`

Frontend:

- `frontend/src/app/demo-workspace/[sessionId]/page.tsx`
- `frontend/src/features/studio/DemoWorkspace.tsx`
- `frontend/src/features/studio/SampleScene.tsx`
- `frontend/src/features/studio/inspection.ts`
- `frontend/src/features/studio/inspection/StageSceneWorkspace.tsx`
- `frontend/src/lib/api/demo-session.ts`
- `frontend/src/lib/api/client.ts`
- `frontend/src/lib/api/auth.ts`
- `frontend/src/lib/api/inputAssemblies.ts`
- `frontend/src/lib/api/studio.ts`
- `frontend/src/lib/api/value.ts`

Tests and report:

- `tests/test_api/test_demo_sessions.py`
- `tests/test_api/test_demo_routes.py`
- `tests/test_orchestration/test_sample_export.py`
- `frontend/tests/demo-session-scope.test.ts`
- `frontend/tests/preview-scene-camera.test.tsx`
- This report.

Existing uncommitted viewer collision responsiveness and multi-Gaussian picker changes were preserved.

## Verification

| Check | Actual result |
| --- | --- |
| Backend API, session, export, ownership, resource and scene queue suites | 267 passed |
| Worker runtime selection, prepared queue, registration and Isaac worker suites | 33 passed |
| Frontend scope, camera, client, auth, timeline, stage and replay suites | 74 passed, 9 files |
| `next typegen` and `tsc --noEmit --incremental false` | Passed |
| Scoped ESLint, 13 changed frontend files | Passed |
| Scoped Ruff check and format check | Passed, 22 files formatted |
| Production `next build` | Passed; new `/demo-workspace/[sessionId]` route included |
| `git diff --check` | Passed |
| `graphify update .` | Passed, 28045 nodes / 87824 edges; semantic community names not refreshed |

Commands for the Python suites:

```bash
.venv/bin/pytest tests/test_api/test_demo_sessions.py tests/test_api/test_scene_routes.py tests/test_api/test_demo_routes.py tests/test_api/test_sample_routes.py tests/test_api/test_guest_ownership.py tests/test_orchestration/test_resource_admission.py tests/test_orchestration/test_scene_objectify_queue.py tests/test_orchestration/test_sample_export.py -q --tb=short
.venv/bin/pytest tests/test_orchestration/test_worker_runtime_selection.py tests/test_orchestration/test_prepared_queue.py tests/test_orchestration/test_registration_worker.py tests/test_orchestration/test_isaac_validation_worker.py -q --tb=short
```

Frontend suite, from `frontend/`:

```bash
npx vitest run tests/demo-session-scope.test.ts tests/preview-scene-camera.test.tsx tests/api-client.test.ts tests/auth-ui.test.ts tests/auth-provider.test.tsx tests/pipeline-timeline.test.tsx tests/stage-workspace.test.tsx tests/studio-sample-pipeline.test.tsx tests/studio-demo-showcase.test.tsx
```

Real artifact checks through ASGI:

- All three samples: progress, stage views, scene, demo state, object geometry state and review state returned 200.
- DrJohnson private edits created rev-199, reset created rev-200, restore-root created rev-201. These revisions existed only in the private workspace.
- Closed workspaces were removed. All four source scene head checksums remained unchanged.

Live HTTP through `http://localhost:3010`:

- All three sample pages, workspace pages, progress, stage views and scenes returned 200.
- Heartbeat returned 204. Close returned 202. Subsequent scene reads returned 410, with each private directory removed.
- An idle native private scene worker launched and exited in 2.34 seconds with no queued GPU command. Its workspace was removed.

Evidence: `/tmp/p087-demo-migration.json`, `/tmp/p087-demo-sessions/{smoke.json,live-http.json,restart.json,local-stack.log,idle-worker-result.log}`, `/tmp/p087-demo-{backend,worker,frontend,static}-checks.log` and `/tmp/p087-demo-graphify.log`.

## Gate report

- **codegraph:** traced sample export/publication callers, scene revision lineage and head records, job journal persistence, native dispatch/admission and validation contracts. Used graphify query before navigation and updated the graph after source edits.
- **impact:** changes the sample scene entry, shared API dependency access under a request-local context, artifact URL builders, and the idle branch of the native worker loop. Requests outside a demo retain normal dependency selection.
- **understand:** source artifacts are immutable, SceneIR writes require revision/CAS, queue workers retain their native leases, and the demo baseline is independent of the live source head.
- **minimal-code:** reused real ScenePage, stage inspectors, auth/ownership, queue consumers, artifact resolver, resource admission and SceneIR lifecycle; no alternate simulation or fake completion state.
- **checks:** results above; early fixture signature failures were corrected and the final related suites passed.
- **DevTools:** UNVERIFIED; user explicitly requested source-based work without DevTools. Browser rendering, WebGL/GPU interaction and a real mesh/region/Isaac computation were not exercised. CPU tests and HTTP checks do not prove these or a deployed cloud environment.
