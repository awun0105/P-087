# Studio collision preview and authored floor/wall surfaces

Date: 2026-10-14. Branch: codex/pr04-browser-physics. All follow-up changes remain uncommitted and unpushed.

## Delivered behavior

Studio requests revision-bound collision with `preview=true`. Pending candidates participate as static preview colliders without changing `state`, `active`, or authored mass. Confirmed active objects retain their authored physics. Ignore/Merge/Delete/Restore follow existing review disposition and immutable source ownership. Individual viewport hiding and layer switches do not mutate physics admission.

The preview compositor removes immutable source regions for eligible Pending objects as well as Confirmed/Deleted regions. Current edited poses never define carve regions. Gizmo move callbacks update the camera query immediately; release persists pose through the existing revision command. Gaussian, selection shape, and independent collision visualization remain synchronized.

The object frame preserves its original GLB shape and selected-object edge highlight. Collision mesh independently renders the effective environment and all preview collider shapes. Triangle edges are a separate display option.

## Floor/wall workflow

1. Enable Collision mesh. Click Đánh dấu sàn or Đánh dấu tường.
2. Click one rendered environment triangle. The ray is converted explicitly from display to canonical world meters. The geometry URL must match the currently requested revision.
3. The server validates finite non-collinear points, floor/wall orientation, confirmed metric frame, selected source checksum, authorization, and expected revision. The source-bound plane is stored as user_authored provenance in a new immutable revision.
4. The selected triangle receives a colored wire marker; the toolbar lists the plane.
5. Lấp theo mặt phẳng explicitly enables authored infill. Xóa mặt phẳng removes annotation and infill. Existing scene Undo restores the prior configuration.

Existing source floor surfaces are protected using checksum-bound FloorFitEvidence; uncertain floor evidence never creates a guessed floor. User-marked planes also protect existing coplanar surfaces. Automatic repair triangulates simple closed planar holes bounded by source object footprints. Exact positional welding handles GLB vertex seams. Outer scene boundaries, nonplanar/branched loops, and loops over 512 vertices are not automatically capped. No source vertices are moved: noisy boundaries are joined to projected caps with small seam triangles.

Explicit authored infill creates planar collision rectangles inside immutable source footprints. It skips already supported footprints and distant walls; multiple marked floor levels choose the nearest eligible floor below the source footprint. This is user-requested geometry, not measured reconstruction. It may overlap surviving coplanar boundary geometry. It does not recover hidden texture/Gaussians.

Authored annotations are consumed by shared effective_environment for confirmed/export composition as well as Studio preview. Jobs without annotations retain the original official carving path and identity. Studio additionally includes Pending regions and safe evidence-based preview repair. No USD producer or Isaac runtime source was changed.

## Missing support safety

The pinned viewer patch checks a five-ray capsule footprint before accepting a Walk step, using existing surfaces within a 25cm up/down step. Unsupported movement restores the prior pose instead of allowing the camera to fall through a gap. This also covers empty object lists via the host environment-only collision provider. It intentionally blocks ledges or steps deeper than 25cm; Fly remains available.

## Verification evidence

- Frontend: npm test -- --maxWorkers=2 — 629 passed, 73 files, 72.17 s.
- First full frontend run: 628 passed / 1 failed. The palette gate found two new hardcoded colors. Both were changed to existing theme tokens; the final full run passed.
- Backend: focused Scene/Simulation/Scene API/ownership/package suites — 404 passed, 43.33 s.
- Final focused backend rerun after compatibility changes — 52 passed, 3.10 s.
- TypeScript and scoped ESLint: PASS.
- Ruff check: PASS. Ruff format --check: 622 files PASS.
- git diff --check: PASS.
- Viewer patch: pristine cached 1.35.2 tarball application, second idempotent application, and node --check PASS.
- Tests cover Pending preview/export separation, source-pose invariance, Ignore/Restore, plane mark/fill/remove and stale revision, source checksum, floor evidence corruption, floor/wall holes, GLB seams, outer-boundary exclusion, nonplanar rejection, planar projection/seams, explicit open-boundary infill, and the installed WalkController support guard.
- graphify AST graph refreshed. Community-label warnings do not indicate a source-check failure.

## Live browser/runtime

The existing stack used run_stack.sh with API 8010 and web 3010, with all five jobs SUCCEEDED. It was restarted with the same env file and dev mode to load the new API and dependency patch. The first detached launch exited with its command session; the supervised exec session 69966 loaded the feature for browser verification. The stack was subsequently reloaded once more after the final official-mode compatibility guard. Final supervised exec session: 46394; API PID 850398 and Next PID 850448 at verification. Both ports listened and application startup completed. Logs: /tmp/p087-studio-preview-stack.log.

Authenticated Room rev-092 rendered the new controls with a clean console. Actual browser preparation contained 60 bodies and 60 camera collision shapes, including 59 Pending candidates. Its preview endpoint returned HTTP 200, X-Collision-Mode studio-preview, and matching X-Scene-Revision rev-092. No SceneIR edits were written during this browser audit.

Read-only composition of the actual Room artifacts: 3365 carved source triangles, 28520 output vertices, 55996 faces, 0 protected surfaces and 0 automatically repaired triangles; CPU time 0.372 s. This is not evidence that Room holes were filled automatically. User annotations/infill are required where floor evidence and closed boundaries do not identify a repair.

Screenshot: /tmp/p087-studio-preview.png. Audit aliases and display toggles were restored after the probe. A second geometry-only screenshot did not finish promptly and was cancelled. No live end-to-end plane-save or physical mouse drag/Walk contact test was claimed.

## Limits and review

UNVERIFIED: complete mouse drag -> release -> save -> Walk contact workflow, live plane mark/fill/remove on the user's real Room data, dense marker/infill GPU stress, and Isaac Sim E2E. The unit/HTTP/native probes do not qualify those gates. Browser display toggles were exercised; source data was preserved.

Planar infill is intentionally authored approximation. Curved surfaces, doorway intent, stair geometry, and exact polygonal reconstruction behind occluders are not inferred. Automatic caps are conservative; explicit fill operates on bounded source footprints. Infill has no synthesized visual texture.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: viewer, overlay, object review, camera queries, shared compositor, ownership, floor evidence, API and revision publisher sources/callers inspected.
- impact: Studio and browser Walk; shared composition changes only for authored surface configuration. Original official jobs without labels remain compatible.
- understand: source-region removal separated from current object pose and review confirmation; surface geometry is explicit authored configuration.
- minimal-code: reused existing source ownership, revision publisher, palette, PlayCanvas wireframe, collision queries and FloorFitEvidence. No segmentation/CoACD/lifecycle producer edits.
- checks: tsc clean; scoped ESLint clean; 629 frontend, 404 backend plus 52 focused final tests passed; Ruff clean.
- DevTools: authenticated Room controls/rendering/preparation inspected; preview request 200 and console clean. Full gesture/contact/infill acceptance remains UNVERIFIED.
