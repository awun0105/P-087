# Planar cut repair: partial implementation, Room NOT accepted

## Requested behavior

Automatically cap the mesh opening created by an object-source cut using the plane of that boundary.
No floor/wall semantic classification is required. Do not cap pre-existing source openings.

## Changes in this follow-up

- `src/services/scene/collision_surfaces.py`: source-bound automatic plane inference using SVD;
  exact position welding; reject collinear/nonplanar boundaries (maximum residual 1 cm),
  original openings, branching boundaries, and unsupported polygon triangulation.
- Automatic repair retains the existing immutable source-region bounds. No current object pose is
  used to position environment caps. Original vertices are not moved.
- `require_closed_cuts` compares boundary edges before/after the cut and repair. Any newly exposed
  unresolved edge raises `UNREPAIRED_COLLISION_CUT`; it does not return a damaged mesh as success.
  This is an edge-closure check, not complete manifold/contact certification.
- `src/services/scene/effective_collision.py`: Studio preview always enables repair, even for direct
  compositor callers. Plane inference runs without floor/wall labels. Existing explicit surface
  labels and floor protection remain available. Default unlabelled non-preview export is unchanged.
- `tests/test_scene/test_collision_surfaces.py`: arbitrary rotated planes, preservation of original
  openings, unrepairable nonplanar cut rejection, automatic preview integration, pose independence.
  Two older tests now reject a partially removed solid instead of accepting an open leftover surface.
  Floor evidence checksum/protection is independently asserted, rather than implying closed repair.

## Actual Room evidence (read-only, rev-100)

Source: 59,361 triangles, 277 boundary edges after exact-position welding.
Existing source openings are not automatically repaired by this feature.

Preview composition removes 3,361 triangles and produces 20 repair triangles. It still has 954 NEW
unresolved boundary edges, so the revised compositor REJECTS it. Room is not fixed or accepted.
A diagnostic process temporarily replaced only its in-process closure assertion to inspect these
unresolved boundaries; production source/state/artifacts were not modified by that diagnostic.

Remaining new boundaries: 22 closed components, including 10 whose best-fit plane residual exceeds
1 cm (maximum about 0.3079 m), plus 7 branched/open components. Thus a single planar cap per boundary
cannot repair this actual Room geometry under the current validated path. Some other planar loops
also remain ineligible under the source-region/perimeter guards.

The API currently maps SourceCollisionOwnershipError to HTTP 409. Runtime browser handling has
NOT been validated in this follow-up. Do not claim the new guard is deployed to the running server.
No stack restart, SceneIR mutation, pipeline rerun, source artifact rewrite, commit or push occurred.

## Verification

- Ruff check src/ tests/: PASS; Ruff format --check src/ tests/: PASS (622 files).
- Frontend npx tsc --noEmit: PASS.
- Focused frontend regression: 3 files, 13 tests PASS.
- Focused backend: 58 PASS, including new integration test.
- Broad backend final run: 410 PASS in 39.89 s; /tmp/p087-cut-repair-backend-final.log.
- graphify update .: completed AST extraction; warns community labels need refresh.
- git diff --check: PASS at verification.
- Chrome DevTools list_pages: only about:blank. No authenticated Studio session was available.
  Browser drag, loaded repair triangles, Walk contacts and Isaac Sim remain UNVERIFIED.

## Pre-flight (GUIDE.md Rule 13)

- codegraph: composer, patch_planar_holes, API, MetricSceneView; callers of composer,
  effective_environment and browser collision service inspected.
- impact: Studio canonical/display collision uses shared composer; explicit labels can also enable
  repair in package callers. Non-preview unlabelled composition preserves prior behavior.
- understand: source ownership -> source mask -> cap -> closure validation -> API response.
  understand-anything tool unavailable; flow traced through CodeGraph/current source instead.
- minimal-code: reused existing cap triangulation and ownership errors; one source-bound inference
  path and one boundary validator, no new dependency or semantic classification.
- checks: results above. Full browser acceptance is not inferred from local tests.
- DevTools: UNVERIFIED — only blank browser tab; server not restarted with incomplete Room fix.
