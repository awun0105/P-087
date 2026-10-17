# Fix — editor Gaussian/collider coupling regression

Date: 2026-10-14. This corrects the Studio preview description in the original PR-02 handoff and its follow-up; immutable SOURCE conservation is an export rule, not the pose of an editable Pending preview.

## Root cause and responsibility

The regression was introduced by the PR-02 Studio projection (`73fbf639`): a Pending Candidate got an empty entity with its object ID at current pose B, while the actual PLY was loaded into `source:<id>` at immutable extraction pose A. SceneOverlay attaches the gizmo and its collider outline by the object ID. Dragging therefore moved an entity with no Gaussian component; the Gaussian stayed at A. The previous frontend test explicitly expected that detached preview and consequently did not catch the wrong editor behavior.

The author of that change incorrectly applied export/source-preservation semantics to the interactive editor. The user expects the Gaussian, geometry/outline and gizmo to represent one edited object. The fix is at that projection layer; the renderer, producer, ownership, source artifacts and simulation admission rules are unchanged.

## Corrected behavior

- Pending Candidate: one entity with the object ID, its ObjectGaussians URL and current object translation/quaternion. The gizmo manipulates this entity; its collider outline follows it, including during drag.
- Hide/Show: toggles that same entity's visibility and the outline together, without an API revision.
- Delete/Restore: lifecycle visibility applies to that same object; restoring the Pending preview uses its saved current pose.
- Confirmed: continues using current pose and existing physics admission.
- Ignored: retains one source observation at extraction pose, without an editable outline/gizmo, per the prior lifecycle policy. Restore switches that same ID back to editable pose.
- Pending/Ignore USD export still conserves source observation at immutable A. The UI preview does not create a Pending rigid body or rewrite source ownership.

## Current scene evidence (read-only)

Committed scene `job-a14981f78f85`, rev-080, has 61 objects and 61 ObjectGaussians refs. Its environment is the published background SOG/PLY, not a full-source visual accidentally reused as background. For candidate-006:

- Current edited translation B: `[6.335328443460088, 0.3122050807307073, -0.08602623350556315]`.
- Immutable source translation A: `[5.785641670227051, 1.0842213332653046, 0.32811496406793594]`.
- Policy: SOURCE; its PLY contains 2,550 owned Gaussian rows.
- `representation_issues(scene, resolver)` returned an empty list for the actual scene: source/membership/artifact conservation checks passed.

There are 362 original background rows inside that object's Gaussian AABB and zero appended inpaint rows there. Spatial overlap alone does not prove those background rows are wrongly labeled. The fix does not erase background by a bounding box or change segmentation/membership. Any residual background content must be distinguished from the owned editable Gaussian before a separate data correction.

No SceneIR revision or source artifact was edited for this fix. The existing dirty `presentation/pitch_deck.pptx` was not staged; SHA-256 matches the snapshot taken during this task.

## Implementation and regression evidence

Implementation: `frontend/src/features/studio/ObjectReviewView.tsx`, reducing the two-entity Pending projection to a single bound overlay entity.

Tests:

- `frontend/tests/object-review.test.tsx`: correct Pending B preview expectation; complete Move/Rotate → Hide/Show → Delete/Restore sequence with exact Gaussian and collider poses, stable ID, no source clone and no Pending physics body; Ignore A → Restore B.
- `frontend/tests/scene-overlay-gizmo.test.ts`: loaded Gaussian asset belongs to the entity actually attached to Translate/Rotate gizmo; transform events update its outline; hide/show retains the loaded entity, and removal releases it. Uses real PlayCanvas Entity/Quat hierarchy with graphics systems mocked; not pixel/render acceptance.

```bash
cd frontend
./node_modules/.bin/vitest run
# 590 passed across 67 files; focused editor/overlay suites: 49 passed
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/eslint src/features/studio/ObjectReviewView.tsx tests/object-review.test.tsx tests/scene-overlay-gizmo.test.ts
# exit 0

cd ..
.venv/bin/pytest tests/test_scene/test_representation_composition.py tests/test_simulation/test_representation_conservation.py tests/test_simulation/test_usd_capabilities.py -q
# 47 passed; export conservation unchanged, real local USD runner fixture included

git diff --check
# clean for the fix

graphify update .
# AST-only update completed: 23282 nodes, 72401 edges, 750 communities
```

Commit: `0a6c135b` — Bind editable Candidate Gaussians to their collider and gizmo entity. Documentation is committed separately. Local changes are not pushed by this task.

## Pre-flight and acceptance limits

- **codegraph / impact:** ObjectReviewView projection → MetricSceneView setObjects → SceneOverlay setObjects/attachGizmo/setObjectPose; representation resolver and current source/export consumers explored. No backend function changed.
- **understand:** edit preview B and immutable export source A have different purposes. Dedicated understand-anything tool unavailable; flow verified from current code and artifacts.
- **minimal-code:** existing object overlay and renderer behavior reused; no additional entity, renderer abstraction, lifecycle migration or producer change.
- **checks:** exact results above. Temporary fixture hierarchy/type errors were fixed before the implementation commit.
- **DevTools:** UNVERIFIED actual authenticated Studio/WebGL/Isaac acceptance. The connected browser had no authenticated Studio session; a later attempt to open the actual scene returned ERR_CONNECTION_REFUSED. CUA inventory also exposed no logged-in user browser. Final checks found no listeners on configured API 8010 / web 3010 and no matching uvicorn/Next dev processes. The agent did not stop or restart services in this task.

This is a frontend-only fix. Reload the Studio page after the existing stack is running; no backend restart is required to load this particular fix. Passing Node/jsdom/entity or USD fixture tests is not full browser/Isaac acceptance.
